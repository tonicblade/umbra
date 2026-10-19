import discord

from bot.utils.embeds import base_embed


class ProfileView(discord.ui.View):
    def __init__(
        self,
        owner_id: int,
        user: discord.User | discord.Member,
    ) -> None:
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.user = user

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Only the person who opened this profile can use these buttons.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Refresh",
        style=discord.ButtonStyle.primary,
        emoji="🔄",
        custom_id="profile:refresh",
    )
    async def refresh_button(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        embed = make_profile_embed(self.user)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(
        label="Account details",
        style=discord.ButtonStyle.secondary,
        emoji="🔎",
        custom_id="profile:details",
    )
    async def details_button(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_message(
            embed=make_account_details_embed(self.user, interaction.guild),
            ephemeral=False,
        )


def make_profile_embed(user: discord.User | discord.Member) -> discord.Embed:
    embed = base_embed(
        f"{user.display_name}'s profile",
        "To view more details about this user, click the Account Details button below.",
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="Username", value=f"{user.name}", inline=True)
    embed.add_field(name="Display name", value=user.display_name, inline=True)
    embed.add_field(name="Account", value="Bot" if user.bot else "User", inline=True)
    embed.add_field(
        name="Account created",
        value=discord.utils.format_dt(user.created_at, style="R"),
        inline=True,
    )
    embed.add_field(name="Mention", value=user.mention, inline=True)
    return embed


def make_account_details_embed(
    user: discord.User | discord.Member,
    guild: discord.Guild | None = None,
) -> discord.Embed:
    embed = base_embed(f"{user.display_name}'s account details")
    embed.add_field(name="Username", value=f"{user.name}", inline=True)
    embed.add_field(name="Display name", value=user.display_name, inline=True)
    embed.add_field(
        name="Global name",
        value=user.global_name or "Not set",
        inline=True,
    )
    embed.add_field(name="User ID", value=f"`{user.id}`", inline=True)
    embed.add_field(name="Mention", value=user.mention, inline=True)
    account_type = "System" if user.system else "Bot" if user.bot else "User"
    embed.add_field(name="Account type", value=account_type, inline=True)
    embed.add_field(
        name="Account created",
        value=discord.utils.format_dt(user.created_at, style="F"),
        inline=True,
    )
    embed.add_field(
        name="Account age",
        value=discord.utils.format_dt(user.created_at, style="R"),
        inline=True,
    )
    embed.add_field(
        name="Avatar",
        value=f"[Open avatar]({user.display_avatar.url})",
        inline=True,
    )

    if user.discriminator != "0":
        embed.add_field(name="Discriminator", value=user.discriminator, inline=True)

    if user.banner:
        embed.add_field(
            name="Banner",
            value=f"[Open banner]({user.banner.url})",
            inline=True,
        )

    if user.accent_color:
        embed.add_field(
            name="Profile accent",
            value=str(user.accent_color),
            inline=True,
        )

    badges = [
        badge.name.replace("_", " ").title()
        for badge in user.public_flags.all()
    ]
    embed.add_field(
        name="Public badges",
        value=", ".join(badges) if badges else "None",
        inline=True,
    )

    member_guild = guild or (user.guild if isinstance(user, discord.Member) else None)
    if member_guild:
        member = (
            member_guild.get_member(user.id)
            if not isinstance(user, discord.Member)
            else user
        )
        embed.add_field(
            name="Server nickname",
            value=member.nick or "Not set" if member else "Member data unavailable",
            inline=True,
        )
        if member and member.joined_at:
            embed.add_field(
                name="Joined this server",
                value=discord.utils.format_dt(member.joined_at, style="F"),
                inline=True,
            )
        roles = [role.name for role in reversed(member.roles)] if member else []
        roles_text = ", ".join(roles) if roles else "Member data unavailable"
        if len(roles_text) > 1024:
            roles_text = f"{roles_text[:1021]}..."
        embed.add_field(
            name=f"Roles ({len(roles)})",
            value=roles_text,
            inline=False,
        )
        embed.add_field(
            name="Server",
            value=member_guild.name or f"Server {member_guild.id}",
            inline=True,
        )
        embed.add_field(
            name="Server ID",
            value=f"`{member_guild.id}`",
            inline=True,
        )

    return embed
