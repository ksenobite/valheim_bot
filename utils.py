# -*- coding: utf-8 -*-

# utils.py

import discord
import logging
import sqlite3

from discord import app_commands, Interaction
from typing import Optional
from operator import itemgetter
from datetime import datetime, timedelta

from db import get_db_path, get_discord_id_by_character, get_all_rank_roles
from settings import get_db_file_path


class PaginatedStatsView(discord.ui.View):
    def __init__(self, embeds, ephemeral: bool):
        super().__init__(timeout=120)
        self.embeds = embeds
        self.index = 0
        self.ephemeral = ephemeral

    async def send_initial(self, interaction: Interaction):
        await interaction.followup.send(embed=self.embeds[0], view=self, ephemeral=self.ephemeral)

    @discord.ui.button(label="⏪ Prev", style=discord.ButtonStyle.grey)
    async def prev(self, interaction: Interaction, button: discord.ui.Button):
        if self.index > 0:
            self.index -= 1
            await interaction.response.edit_message(embed=self.embeds[self.index], view=self)

    @discord.ui.button(label="Next ⏩", style=discord.ButtonStyle.grey)
    async def next(self, interaction: Interaction, button: discord.ui.Button):
        if self.index < len(self.embeds) - 1:
            self.index += 1
            await interaction.response.edit_message(embed=self.embeds[self.index], view=self)


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
    Returns display data for the character:
    - If character is linked to a Discord user and found in guild:
        -> return their name, avatar, color and PvP role.
    - Else: show character name only.
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
    # Use role color from PvP roles configured in DB
    configured_roles = [name for _, name in get_all_rank_roles()]
    role = next((r for r in member.roles if r.name in configured_roles), None)
    return {
        "display_name": safe_display_name(member),
        "avatar_url": member.display_avatar.url,
        "role": role.name if role else None,
        "color": role.color if role else discord.Color.default()
    }


async def generate_stats_embeds(interaction: Interaction, characters: list[str], days: int, avatar_url: Optional[str] = None) -> list[discord.Embed]:

    since = datetime.utcnow() - timedelta(days=days)
    with sqlite3.connect(get_db_file_path()) as conn:
        c = conn.cursor()
        victories = {}
        defeats = {}
        characters = [name.lower() for name in characters]
        for character in characters:
            c.execute("""
                SELECT victim, COUNT(*) FROM frags
                WHERE killer = ? AND timestamp >= ?
                GROUP BY victim
            """, (character, since))
            for victim, count in c.fetchall():
                victories[victim] = victories.get(victim, 0) + count

            c.execute("""
                SELECT killer, COUNT(*) FROM frags
                WHERE victim = ? AND timestamp >= ?
                GROUP BY killer
            """, (character, since))
            for killer, count in c.fetchall():
                defeats[killer] = defeats.get(killer, 0) + count

    all_opponents = set(victories) | set(defeats)
    stats = []
    for opponent in all_opponents:
        wins = victories.get(opponent, 0)
        losses = defeats.get(opponent, 0)
        total = wins + losses
        winrate = (wins / total) * 100 if total else 0
        stats.append((opponent, wins, losses, winrate))

    total_wins = sum(victories.values())
    total_losses = sum(defeats.values())
    total_matches = total_wins + total_losses
    overall_winrate = (total_wins / total_matches) * 100 if total_matches else 0

    emoji_summary = get_winrate_emoji(overall_winrate)

    stats = sorted(stats, key=itemgetter(3), reverse=False)
    author_text=f"📊 Stats for {len(characters)} character(s) in {days} day(s)"
    # Pagination — 10 opponents per page
    PAGE_SIZE = 10
    pages = [stats[i:i + PAGE_SIZE] for i in range(0, len(stats), PAGE_SIZE)] or [[]]

    embeds = []
    for page in pages:
        embed = discord.Embed(
            color=discord.Color.blue()
        )
        embed.set_author(name=author_text)
        for opponent, wins, losses, winrate in sorted(page, key=itemgetter(3), reverse=False):
            display_data = await resolve_display_data(opponent, interaction.guild)
            emoji = get_winrate_emoji(winrate)
            embed.add_field(
                name=f"{emoji} {display_data['display_name']}",
                value=f"Wins: {wins} | Losses: {losses} | Winrate: {winrate:.1f}%",
                inline=False
            )

        embed.add_field(
            name="**__Overall Performance Summary__**",
            value=(
                f"**Total Wins:** {total_wins}\n"
                f"**Total Losses:** {total_losses}\n"
                f"**Overall Winrate:** {emoji_summary} **{overall_winrate:.1f}%**"
            ),
            inline=False
        )

        if avatar_url:
            embed.set_thumbnail(url=avatar_url)

        embeds.append(embed)

    return embeds
