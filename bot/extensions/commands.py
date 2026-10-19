import asyncio
import json
import logging
import re
import sqlite3
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.client import Umbra
from bot.ui.devinfo import DevInfoView, make_devinfo_embed
from bot.ui.profile import ProfileView, make_profile_embed

logger = logging.getLogger(__name__)
DURATION_PATTERN = re.compile(r"^([1-9][0-9]*)([smhd])$", re.IGNORECASE)
DURATION_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
MAX_REMINDER_SECONDS = 30 * 86400


def parse_duration(value: str) -> int:
    match = DURATION_PATTERN.fullmatch(value.strip())
    if match is None:
        raise ValueError("Use a duration such as `10m`, `2h`, or `1d`.")

    amount = int(match.group(1))
    seconds = amount * DURATION_SECONDS[match.group(2).lower()]
    if seconds > MAX_REMINDER_SECONDS:
        raise ValueError("Reminders can be set for up to 30 days.")
    return seconds


def lookup_definition(word: str, api_key: str) -> list[tuple[str, str]]:
    request = Request(
        "https://www.dictionaryapi.com/api/v3/references/collegiate/"
        f"json/{quote(word, safe='')}?key={quote(api_key, safe='')}",
        headers={"User-Agent": "Umbra"},
    )
    with urlopen(request, timeout=8) as response:
        entries = json.load(response)

    definitions: list[tuple[str, str]] = []
    for entry in entries:
        if isinstance(entry, str):
            definitions.append(("Suggestion", entry))
        elif isinstance(entry, dict):
            part_of_speech = entry.get("fl", "Definition")
            for definition in entry.get("shortdef", []):
                if definition:
                    definitions.append((part_of_speech, definition))
                if len(definitions) == 4:
                    return definitions
        if len(definitions) == 4:
            return definitions
    return definitions


class UmbraCommands(commands.Cog):
    def __init__(self, bot: Umbra) -> None:
        self.bot = bot

    @app_commands.command(name="profile", description="Show a profile card")
    @app_commands.describe(user="The user whose profile you want to view")
    async def profile(
        self,
        interaction: discord.Interaction,
        user: discord.Member | None = None,
    ) -> None:
        target = user or interaction.user
        embed = make_profile_embed(target)
        view = ProfileView(interaction.user.id, target)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(
        name="devinfo",
        description="View and customize your about-me profile",
    )
    async def devinfo(self, interaction: discord.Interaction) -> None:
        try:
            profile = await self.bot.database.get_dev_profile(interaction.user.id)
        except sqlite3.Error:
            logger.exception(
                "Could not load developer info for user %s",
                interaction.user.id,
            )
            await interaction.response.send_message(
                "I couldn't load your info profile. Please try again."
            )
            return
        await interaction.response.send_message(
            embed=make_devinfo_embed(interaction.user, profile),
            view=DevInfoView(self.bot.database, interaction.user.id, profile),
        )

    @app_commands.command(name="timestamp", description="Format a Unix time as a Discord timestamp")
    @app_commands.describe(unix_time="Unix timestamp in seconds")
    @app_commands.choices(
        style=[
            app_commands.Choice(name="Short time", value="t"),
            app_commands.Choice(name="Long time", value="T"),
            app_commands.Choice(name="Short date", value="d"),
            app_commands.Choice(name="Long date", value="D"),
            app_commands.Choice(name="Short date and time", value="f"),
            app_commands.Choice(name="Long date and time", value="F"),
            app_commands.Choice(name="Relative", value="R"),
        ]
    )
    async def timestamp(
        self,
        interaction: discord.Interaction,
        unix_time: int,
        style: app_commands.Choice[str],
    ) -> None:
        try:
            datetime.fromtimestamp(unix_time, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            await interaction.response.send_message(
                "That Unix timestamp is outside the supported date range.",
            )
            return

        formatted = f"<t:{unix_time}:{style.value}>"
        await interaction.response.send_message(
            f"{formatted}\nCopy: `{formatted}`"
        )

    @app_commands.command(name="remind", description="Set a reminder in this channel")
    @app_commands.describe(
        duration="How long to wait, e.g. 10m, 2h, or 1d (up to 30 days)",
        message="What to remind you about",
    )
    async def remind(
        self,
        interaction: discord.Interaction,
        duration: str,
        message: str,
    ) -> None:
        try:
            seconds = parse_duration(duration)
        except ValueError as error:
            await interaction.response.send_message(str(error))
            return

        if interaction.channel_id is None:
            await interaction.response.send_message(
                "I couldn't determine where to deliver this reminder.",
            )
            return

        due_at = time.time() + seconds
        try:
            reminder_id = await self.bot.database.create_reminder(
                interaction.user.id,
                interaction.channel_id,
                message[:1000],
                due_at,
            )
        except sqlite3.Error:
            logger.exception("Could not save reminder for user %s", interaction.user.id)
            await interaction.response.send_message(
                "I couldn't save that reminder. Please try again."
            )
            return
        due = datetime.fromtimestamp(due_at, tz=timezone.utc)
        await interaction.response.send_message(
            f"Reminder #{reminder_id} set for {discord.utils.format_dt(due, style='R')}."
        )

    @app_commands.command(name="define", description="Look up an English word")
    @app_commands.describe(word="The word to look up")
    async def define(self, interaction: discord.Interaction, word: str) -> None:
        api_key = self.bot.config.merriam_webster_dictionary_key
        if not api_key:
            await interaction.response.send_message(
                "Dictionary lookup isn't configured yet. Add "
                "`MERRIAM_WEBSTER_DICTIONARY_KEY` to `.env` and restart the bot."
            )
            return

        await interaction.response.defer(thinking=True)
        try:
            definitions = await asyncio.to_thread(
                lookup_definition,
                word[:100],
                api_key,
            )
        except HTTPError as error:
            if error.code in (401, 403):
                logger.warning("Merriam-Webster rejected the configured dictionary key")
                await interaction.followup.send(
                    "The dictionary service rejected its configured API key. "
                    "Check `MERRIAM_WEBSTER_DICTIONARY_KEY` in `.env`."
                )
                return
            if error.code == 404:
                await interaction.followup.send(
                    f"No definition found for **{discord.utils.escape_markdown(word)}**."
                )
                return
            logger.warning("Merriam-Webster returned HTTP %s", error.code)
            await interaction.followup.send(
                "The dictionary service is temporarily unavailable."
            )
            return
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            logger.warning("Merriam-Webster lookup failed: %s", error)
            await interaction.followup.send(
                "The dictionary service is temporarily unavailable."
            )
            return

        if not definitions:
            await interaction.followup.send(
                f"No definition found for **{discord.utils.escape_markdown(word)}**."
            )
            return

        embed = discord.Embed(
            title=f"Definition: {discord.utils.escape_markdown(word[:100])}",
            colour=discord.Colour.blurple(),
        )
        for index, (part_of_speech, definition) in enumerate(definitions, start=1):
            embed.add_field(
                name=f"{index}. {part_of_speech}",
                value=definition[:1024],
                inline=False,
            )
        await interaction.followup.send(embed=embed)


class ReminderWorker(commands.Cog):
    def __init__(self, bot: Umbra) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.deliver_reminders.start()

    def cog_unload(self) -> None:
        self.deliver_reminders.cancel()

    @tasks.loop(seconds=15)
    async def deliver_reminders(self) -> None:
        try:
            reminders = await self.bot.database.get_due_reminders(time.time())
        except sqlite3.Error:
            logger.exception("Could not load due reminders from SQLite")
            return

        for reminder in reminders:
            destination = self.bot.get_channel(reminder.channel_id)
            try:
                if destination is None:
                    destination = await self.bot.fetch_channel(reminder.channel_id)
                await destination.send(
                    f"<@{reminder.user_id}> Reminder: {reminder.message}",
                    allowed_mentions=discord.AllowedMentions(
                        users=[discord.Object(id=reminder.user_id)]
                    ),
                )
            except (discord.Forbidden, discord.NotFound, discord.HTTPException) as error:
                logger.warning(
                    "Could not send reminder %s to its channel: %s",
                    reminder.reminder_id,
                    error,
                )
                try:
                    user = self.bot.get_user(reminder.user_id)
                    if user is None:
                        user = await self.bot.fetch_user(reminder.user_id)
                    await user.send(f"Reminder: {reminder.message}")
                except (discord.Forbidden, discord.NotFound, discord.HTTPException) as dm_error:
                    logger.warning(
                        "Could not deliver reminder %s by DM: %s",
                        reminder.reminder_id,
                        dm_error,
                    )
                    continue

            try:
                await self.bot.database.delete_reminder(reminder.reminder_id)
            except sqlite3.Error:
                logger.exception("Could not remove delivered reminder %s", reminder.reminder_id)

    @deliver_reminders.before_loop
    async def before_deliver_reminders(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    if not isinstance(bot, Umbra):
        raise TypeError("The command extension requires the Umbra bot client.")
    await bot.add_cog(UmbraCommands(bot))
    await bot.add_cog(ReminderWorker(bot))
