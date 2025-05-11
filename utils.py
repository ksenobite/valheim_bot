# -*- coding: utf-8 -*-

import discord
import logging

from db import get_discord_id_by_character
from roles import ROLE_THRESHOLDS


def get_winrate_emoji(winrate: float) -> str:
    """Returns emoji based on win rate."""
    if winrate > 60:
        return "🟢"
    elif winrate >= 40:
        return "🟡"
    else:
        return "🔴"


def safe_display_name(member: discord.Member) -> str:
    """Returns the readable name of the participant."""
    return member.nick or member.display_name or member.name


async def require_admin(interaction: discord.Interaction) -> bool:
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("⚠️ Admin only", ephemeral=True)
        return False
    return True


async def check_positive(interaction: discord.Interaction, **kwargs):
    for name, value in kwargs.items():
        if value < 1:
            await interaction.response.send_message(f"❗ The parameter '{name}' must be greater than 0.", ephemeral=True)
            return False
    return True


async def resolve_display_data(character_name: str, guild: discord.Guild) -> dict:
    """
    Determines how to display the character beautifully:
    - if there is a connection, returns the username, role, avatar
        - otherwise, it displays the character's name
    """
    discord_id = get_discord_id_by_character(character_name)
    if not discord_id:
        return {
            "display_name": character_name,
            "avatar_url": None,
            "role": None,
            "color": discord.Color.default()
        }
    member = guild.get_member(discord_id)
    if not member:
        try:
            member = await guild.fetch_member(discord_id)
        except discord.NotFound:
            logging.warning(f"User {discord_id} not found in guild.")
            return {
                "display_name": character_name,
                "avatar_url": None,
                "role": None,
                "color": discord.Color.default()
            }
    # Let's define the role by color (priority: top of the list of known ones)
    known_role_names = [name for _, name, _ in ROLE_THRESHOLDS]
    role = next((r for r in member.roles if r.name in known_role_names), None)

    return {
        "display_name": safe_display_name(member),
        "avatar_url": member.display_avatar.url,
        "role": role.name if role else None,
        "color": role.color if role else discord.Color.default()
    }