import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Config:
    token: str
    guild_id: int | None
    database_path: Path
    merriam_webster_dictionary_key: str


def load_config() -> Config:
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise RuntimeError("DISCORD_TOKEN is missing. Add it to your .env file.")

    guild_value = os.getenv("GUILD_ID", "").strip()
    guild_id = int(guild_value) if guild_value else None

    database_value = os.getenv("DATABASE_PATH", "data/umbra.sqlite3").strip()
    database_path = Path(database_value)
    if not database_path.is_absolute():
        database_path = PROJECT_ROOT / database_path

    return Config(
        token=token,
        guild_id=guild_id,
        database_path=database_path,
        merriam_webster_dictionary_key=os.getenv(
            "MERRIAM_WEBSTER_DICTIONARY_KEY",
            "",
        ).strip(),
    )
