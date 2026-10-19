import discord

ACCENT = discord.Colour.from_rgb(124, 92, 255)


def base_embed(title: str, description: str | None = None) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        colour=ACCENT,
        timestamp=discord.utils.utcnow(),
    )
    embed.set_footer(text="Umbra")
    return embed
