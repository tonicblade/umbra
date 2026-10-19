import logging

import discord
from discord.ext import commands

from bot.config import load_config
from bot.database import Database, Honeypot


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


class Umbra(commands.AutoShardedBot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            max_messages=None,
        )
        self.config = load_config()
        self.database = Database(self.config.database_path)
        self.honeypots_by_channel: dict[int, Honeypot] = {}

    async def setup_hook(self) -> None:
        await self.database.initialize()
        self.honeypots_by_channel = {
            honeypot.channel_id: honeypot
            for honeypot in await self.database.load_honeypots()
        }
        logging.info("Using SQLite database at %s", self.config.database_path)
        await self.load_extension("bot.extensions.commands")
        await self.load_extension("bot.extensions.honeypot")

        synced = await self.tree.sync()
        logging.info("Synced %s global application commands", len(synced))

        if self.config.guild_id:
            guild = discord.Object(id=self.config.guild_id)
            self.tree.copy_global_to(guild=guild)
            guild_synced = await self.tree.sync(guild=guild)
            logging.info(
                "Synced %s development commands to guild %s",
                len(guild_synced),
                self.config.guild_id,
            )

    async def on_ready(self) -> None:
        await self.database.sync_guilds(
            (guild.id, guild.name) for guild in self.guilds
        )
        if self.user:
            logging.info("Logged in as %s (%s)", self.user, self.user.id)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        await self.database.add_guild(guild.id, guild.name)
        logging.info("Joined guild %s (%s)", guild.name, guild.id)

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        await self.database.remove_guild(guild.id)
        for channel_id, honeypot in tuple(self.honeypots_by_channel.items()):
            if honeypot.guild_id == guild.id:
                del self.honeypots_by_channel[channel_id]
        logging.info("Removed from guild %s (%s)", guild.name, guild.id)


async def run() -> None:
    bot = Umbra()
    async with bot:
        await bot.start(bot.config.token)
