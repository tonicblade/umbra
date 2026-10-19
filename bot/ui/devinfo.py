from __future__ import annotations

import logging
import sqlite3

import discord

from bot.database import Database, DevProfile
from bot.utils.embeds import base_embed

logger = logging.getLogger(__name__)


def make_devinfo_embed(
    user: discord.User | discord.Member,
    profile: DevProfile | None,
) -> discord.Embed:
    about = profile.about if profile else ""
    embed = base_embed(
        f"About {user.display_name}",
        about or "Use **Edit my info** to add a short introduction.",
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    if profile:
        for label, value in (
            ("Age", profile.age),
            ("Favorite song", profile.favorite_song),
            ("Favorite game", profile.favorite_game),
            ("Favorite movie or show", profile.favorite_movie),
        ):
            if value:
                embed.add_field(name=label, value=value, inline=True)
    return embed


class DevInfoModal(discord.ui.Modal, title="Customize your developer info"):
    age = discord.ui.TextInput(
        label="Age (optional)",
        placeholder="Optional",
        max_length=20,
        required=False,
    )
    favorite_song = discord.ui.TextInput(
        label="Favorite song",
        placeholder="Optional",
        max_length=100,
        required=False,
    )
    favorite_game = discord.ui.TextInput(
        label="Favorite game",
        placeholder="Optional",
        max_length=100,
        required=False,
    )
    favorite_movie = discord.ui.TextInput(
        label="Favorite movie or show",
        placeholder="Optional",
        max_length=100,
        required=False,
    )
    about = discord.ui.TextInput(
        label="About me",
        placeholder="A short introduction",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=False,
    )

    def __init__(
        self,
        database: Database,
        profile: DevProfile | None,
        view: DevInfoView,
    ) -> None:
        super().__init__()
        self.database = database
        self.view = view
        if profile:
            self.age.default = profile.age or None
            self.favorite_song.default = profile.favorite_song or None
            self.favorite_game.default = profile.favorite_game or None
            self.favorite_movie.default = profile.favorite_movie or None
            self.about.default = profile.about or None

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            profile = await self.database.save_dev_profile(
                interaction.user.id,
                self.age.value.strip(),
                self.favorite_song.value.strip(),
                self.favorite_game.value.strip(),
                self.favorite_movie.value.strip(),
                self.about.value.strip(),
            )
        except sqlite3.Error:
            logger.exception(
                "Could not save developer info for user %s",
                interaction.user.id,
            )
            await interaction.response.send_message(
                "I couldn't save your info profile. Please try again.",
                ephemeral=True,
            )
            return

        self.view.profile = profile
        await interaction.response.send_message(
            embed=make_devinfo_embed(interaction.user, profile),
            view=self.view,
        )


class DevInfoView(discord.ui.View):
    def __init__(
        self,
        database: Database,
        owner_id: int,
        profile: DevProfile | None,
    ) -> None:
        super().__init__(timeout=300)
        self.database = database
        self.owner_id = owner_id
        self.profile = profile

    @discord.ui.button(
        label="Edit my info",
        style=discord.ButtonStyle.primary,
        custom_id="devinfo:edit",
    )
    async def edit_info(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Only the person who opened this profile can edit it.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(
            DevInfoModal(self.database, self.profile, self)
        )
