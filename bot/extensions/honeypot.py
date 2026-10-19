import asyncio
import logging
import secrets
import sqlite3
import string

import discord
from discord import app_commands
from discord.ext import commands

from bot.client import Umbra

logger = logging.getLogger(__name__)
HONEYPOT_WARNING = (
    "WARNING! THIS IS A HONEYPOT CHANNEL MEANT TO DETER SPAM BOTS! "
    "DO NOT CHAT HERE! YOU WILL BE KICKED!"
)
CHANNEL_ALPHABET = string.ascii_lowercase + string.digits


def make_honeypot_embed(configured: bool) -> discord.Embed:
    embed = discord.Embed(
        title="Honeypot setup",
        description=(
            "Create a hard-to-guess channel that deters spam bots. Any human who "
            "posts there will have their messages from the last seven days deleted, "
            "be banned, and then immediately unbanned."
        ),
        colour=discord.Colour.orange(),
    )
    embed.add_field(
        name="Status",
        value="Already configured" if configured else "Not configured",
        inline=False,
    )
    embed.set_footer(text="Requires Manage Channels and Ban Members permissions.")
    return embed


class HoneypotSetupView(discord.ui.View):
    def __init__(self, bot: Umbra) -> None:
        super().__init__(timeout=300)
        self.bot = bot

    @discord.ui.button(
        label="Create honeypot channel",
        style=discord.ButtonStyle.danger,
        custom_id="honeypot:create",
    )
    async def create_honeypot(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Honeypots can only be configured in a server.",
                ephemeral=True,
            )
            return
        if not isinstance(interaction.user, discord.Member) or not (
            interaction.user.guild_permissions.manage_guild
        ):
            await interaction.response.send_message(
                "You need the Manage Server permission to configure the honeypot.",
                ephemeral=True,
            )
            return

        bot_member = guild.me
        if bot_member is None:
            await interaction.response.send_message(
                "I could not verify my server permissions. Please try again shortly.",
                ephemeral=True,
            )
            return
        permissions = bot_member.guild_permissions
        missing = [
            name
            for name, granted in (
                ("Manage Channels", permissions.manage_channels),
                ("Ban Members", permissions.ban_members),
                ("View Channels", permissions.view_channel),
                ("Send Messages", permissions.send_messages),
            )
            if not granted
        ]
        if missing:
            await interaction.response.send_message(
                f"I need these permissions first: {', '.join(missing)}.",
                ephemeral=True,
            )
            return

        existing = await self.bot.database.get_honeypot(guild.id)
        if existing is not None:
            active_channel = guild.get_channel(existing.channel_id)
            if active_channel is not None:
                await interaction.response.send_message(
                    f"The honeypot is already set up in {active_channel.mention}.",
                    ephemeral=True,
                )
                return
            await self.bot.database.delete_honeypot(guild.id)
            self.bot.honeypots_by_channel.pop(existing.channel_id, None)

        channel_name = "".join(
            secrets.choice(CHANNEL_ALPHABET) for _ in range(20)
        )
        channel: discord.TextChannel | None = None
        try:
            channel = await guild.create_text_channel(channel_name)
            warning = await channel.send(f"{HONEYPOT_WARNING}\nKicks: 0")
            honeypot = await self.bot.database.save_honeypot(
                guild.id,
                channel.id,
                warning.id,
            )
        except discord.HTTPException as error:
            logger.exception("Could not create the honeypot in guild %s", guild.id)
            await self._remove_incomplete_channel(channel)
            await interaction.response.send_message(
                f"I couldn't create the honeypot channel: {error}.",
                ephemeral=True,
            )
            return
        except sqlite3.Error:
            logger.exception("Could not save the honeypot in guild %s", guild.id)
            await self._remove_incomplete_channel(channel)
            await interaction.response.send_message(
                "The channel was created, but I couldn't save its configuration. "
                "Please try again.",
                ephemeral=True,
            )
            return

        self.bot.honeypots_by_channel[honeypot.channel_id] = honeypot
        await interaction.response.send_message(
            f"Honeypot created: {channel.mention}",
            ephemeral=True,
        )

    async def _remove_incomplete_channel(
        self,
        channel: discord.TextChannel | None,
    ) -> None:
        if channel is None:
            return
        try:
            await channel.delete(reason="Honeypot setup did not complete")
        except discord.HTTPException:
            logger.exception(
                "Could not remove incomplete honeypot channel %s",
                channel.id,
            )


class HoneypotCommands(commands.Cog):
    def __init__(self, bot: Umbra) -> None:
        self.bot = bot
        self._guild_locks: dict[int, asyncio.Lock] = {}

    @app_commands.command(
        name="setup",
        description="Configure Umbra's server honeypot",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_honeypot(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        configured = await self.bot.database.get_honeypot(interaction.guild.id)
        active = (
            configured is not None
            and interaction.guild.get_channel(configured.channel_id) is not None
        )
        embed = make_honeypot_embed(active)
        view = None if active else HoneypotSetupView(self.bot)
        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return

        honeypot = self.bot.honeypots_by_channel.get(message.channel.id)
        if honeypot is None or honeypot.guild_id != message.guild.id:
            return
        member = message.author
        if not isinstance(member, discord.Member):
            try:
                member = await message.guild.fetch_member(message.author.id)
            except discord.NotFound:
                logger.warning(
                    "Honeypot author %s is no longer in guild %s",
                    message.author.id,
                    message.guild.id,
                )
                return
            except discord.HTTPException:
                logger.exception(
                    "Could not fetch honeypot author %s in guild %s",
                    message.author.id,
                    message.guild.id,
                )
                return

        async with self._guild_locks.setdefault(message.guild.id, asyncio.Lock()):
            try:
                await message.guild.ban(
                    member,
                    reason="Posted in the server honeypot channel",
                    delete_message_seconds=7 * 24 * 60 * 60,
                )
            except discord.HTTPException:
                logger.exception(
                    "Could not ban honeypot offender %s in guild %s",
                    message.author.id,
                    message.guild.id,
                )
                try:
                    await message.delete()
                except discord.HTTPException:
                    logger.exception(
                        "Could not delete honeypot message %s",
                        message.id,
                    )
                return

            try:
                honeypot.kicks = await self.bot.database.increment_honeypot_kicks(
                    message.guild.id
                )
                channel = message.guild.get_channel(honeypot.channel_id)
                if isinstance(channel, discord.TextChannel):
                    warning = await channel.fetch_message(honeypot.message_id)
                    await warning.edit(content=f"{HONEYPOT_WARNING}\nKicks: {honeypot.kicks}")
            except (discord.HTTPException, LookupError, sqlite3.Error):
                logger.exception(
                    "Could not update honeypot counter for guild %s",
                    message.guild.id,
                )
            finally:
                try:
                    await message.guild.unban(
                    member,
                        reason="Honeypot action complete; permit rejoining",
                    )
                except discord.HTTPException:
                    logger.exception(
                        "Could not unban honeypot offender %s in guild %s",
                        member.id,
                        message.guild.id,
                    )


async def setup(bot: commands.Bot) -> None:
    if not isinstance(bot, Umbra):
        raise TypeError("The honeypot extension requires the Umbra bot client.")
    await bot.add_cog(HoneypotCommands(bot))
