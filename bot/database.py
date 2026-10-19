import asyncio
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Honeypot:
    guild_id: int
    channel_id: int
    message_id: int
    kicks: int


@dataclass(frozen=True)
class Reminder:
    reminder_id: int
    user_id: int
    channel_id: int
    message: str


@dataclass(frozen=True)
class DevProfile:
    user_id: int
    age: str
    favorite_song: str
    favorite_game: str
    favorite_movie: str
    about: str


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize)

    async def sync_guilds(self, guilds: Iterable[tuple[int, str]]) -> None:
        await asyncio.to_thread(self._sync_guilds, list(guilds))

    async def add_guild(self, guild_id: int, name: str) -> None:
        await asyncio.to_thread(self._sync_guilds, [(guild_id, name)])

    async def remove_guild(self, guild_id: int) -> None:
        await asyncio.to_thread(self._remove_guild, guild_id)

    async def load_honeypots(self) -> list[Honeypot]:
        return await asyncio.to_thread(self._load_honeypots)

    async def get_honeypot(self, guild_id: int) -> Honeypot | None:
        return await asyncio.to_thread(self._get_honeypot, guild_id)

    async def save_honeypot(
        self,
        guild_id: int,
        channel_id: int,
        message_id: int,
    ) -> Honeypot:
        return await asyncio.to_thread(
            self._save_honeypot,
            guild_id,
            channel_id,
            message_id,
        )

    async def delete_honeypot(self, guild_id: int) -> None:
        await asyncio.to_thread(self._delete_honeypot, guild_id)

    async def increment_honeypot_kicks(self, guild_id: int) -> int:
        return await asyncio.to_thread(self._increment_honeypot_kicks, guild_id)

    async def create_reminder(
        self,
        user_id: int,
        channel_id: int,
        message: str,
        due_at: float,
    ) -> int:
        return await asyncio.to_thread(
            self._create_reminder,
            user_id,
            channel_id,
            message,
            due_at,
        )

    async def get_due_reminders(self, now: float) -> list[Reminder]:
        return await asyncio.to_thread(self._get_due_reminders, now)

    async def delete_reminder(self, reminder_id: int) -> None:
        await asyncio.to_thread(self._delete_reminder, reminder_id)

    async def get_dev_profile(self, user_id: int) -> DevProfile | None:
        return await asyncio.to_thread(self._get_dev_profile, user_id)

    async def save_dev_profile(
        self,
        user_id: int,
        age: str,
        favorite_song: str,
        favorite_game: str,
        favorite_movie: str,
        about: str,
    ) -> DevProfile:
        return await asyncio.to_thread(
            self._save_dev_profile,
            user_id,
            age,
            favorite_song,
            favorite_game,
            favorite_movie,
            about,
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS guilds (
                    guild_id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS honeypots (
                    guild_id INTEGER PRIMARY KEY,
                    channel_id INTEGER NOT NULL UNIQUE,
                    message_id INTEGER NOT NULL,
                    kicks INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reminders (
                    reminder_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    due_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS reminders_due_at_idx ON reminders (due_at)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS dev_profiles (
                    user_id INTEGER PRIMARY KEY,
                    age TEXT NOT NULL DEFAULT '',
                    favorite_song TEXT NOT NULL DEFAULT '',
                    favorite_game TEXT NOT NULL DEFAULT '',
                    favorite_movie TEXT NOT NULL DEFAULT '',
                    about TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def _sync_guilds(self, guilds: list[tuple[int, str]]) -> None:
        if not guilds:
            return
        with closing(self._connect()) as connection, connection:
            connection.executemany(
                """
                INSERT INTO guilds (guild_id, name)
                VALUES (?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    name = excluded.name,
                    last_seen_at = CURRENT_TIMESTAMP
                """,
                guilds,
            )

    def _remove_guild(self, guild_id: int) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "DELETE FROM guilds WHERE guild_id = ?",
                (guild_id,),
            )
            connection.execute(
                "DELETE FROM honeypots WHERE guild_id = ?",
                (guild_id,),
            )

    def _load_honeypots(self) -> list[Honeypot]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT guild_id, channel_id, message_id, kicks FROM honeypots"
            ).fetchall()
        return [Honeypot(*row) for row in rows]

    def _get_honeypot(self, guild_id: int) -> Honeypot | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT guild_id, channel_id, message_id, kicks
                FROM honeypots
                WHERE guild_id = ?
                """,
                (guild_id,),
            ).fetchone()
        return Honeypot(*row) if row else None

    def _save_honeypot(
        self,
        guild_id: int,
        channel_id: int,
        message_id: int,
    ) -> Honeypot:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO honeypots (guild_id, channel_id, message_id)
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    channel_id = excluded.channel_id,
                    message_id = excluded.message_id
                """,
                (guild_id, channel_id, message_id),
            )
            row = connection.execute(
                """
                SELECT guild_id, channel_id, message_id, kicks
                FROM honeypots
                WHERE guild_id = ?
                """,
                (guild_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("The honeypot record could not be read after saving.")
        return Honeypot(*row)

    def _delete_honeypot(self, guild_id: int) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "DELETE FROM honeypots WHERE guild_id = ?",
                (guild_id,),
            )

    def _increment_honeypot_kicks(self, guild_id: int) -> int:
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "UPDATE honeypots SET kicks = kicks + 1 WHERE guild_id = ?",
                (guild_id,),
            )
            if cursor.rowcount != 1:
                raise LookupError(f"No honeypot is configured for guild {guild_id}.")
            row = connection.execute(
                "SELECT kicks FROM honeypots WHERE guild_id = ?",
                (guild_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("The honeypot kick counter could not be read.")
        return int(row[0])

    def _create_reminder(
        self,
        user_id: int,
        channel_id: int,
        message: str,
        due_at: float,
    ) -> int:
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                INSERT INTO reminders (user_id, channel_id, message, due_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, channel_id, message, due_at),
            )
            return int(cursor.lastrowid)

    def _get_due_reminders(self, now: float) -> list[Reminder]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT reminder_id, user_id, channel_id, message
                FROM reminders
                WHERE due_at <= ?
                ORDER BY due_at, reminder_id
                LIMIT 100
                """,
                (now,),
            ).fetchall()
        return [Reminder(*row) for row in rows]

    def _delete_reminder(self, reminder_id: int) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "DELETE FROM reminders WHERE reminder_id = ?",
                (reminder_id,),
            )

    def _get_dev_profile(self, user_id: int) -> DevProfile | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT user_id, age, favorite_song, favorite_game, favorite_movie, about
                FROM dev_profiles
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        return DevProfile(*row) if row else None

    def _save_dev_profile(
        self,
        user_id: int,
        age: str,
        favorite_song: str,
        favorite_game: str,
        favorite_movie: str,
        about: str,
    ) -> DevProfile:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO dev_profiles (
                    user_id, age, favorite_song, favorite_game, favorite_movie, about
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    age = excluded.age,
                    favorite_song = excluded.favorite_song,
                    favorite_game = excluded.favorite_game,
                    favorite_movie = excluded.favorite_movie,
                    about = excluded.about,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, age, favorite_song, favorite_game, favorite_movie, about),
            )
            row = connection.execute(
                """
                SELECT user_id, age, favorite_song, favorite_game, favorite_movie, about
                FROM dev_profiles
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("The developer profile could not be read after saving.")
        return DevProfile(*row)
