# -*- coding: utf-8 -*-
# utils.py

import discord
import logging
import sqlite3

from discord import app_commands, Interaction, Member
from typing import Optional, cast
from operator import itemgetter
from datetime import datetime, timedelta

from db import *
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
    """
    Returns the readable name of the participant.
    """
    return member.nick or member.display_name or member.name

async def require_admin(interaction: discord.Interaction) -> bool:
    user = cast(Member, interaction.user)
    if not user.guild_permissions.administrator:
        await interaction.response.send_message("⚠️ Admin only", ephemeral=True)
        return False
    return True

async def check_positive(interaction: discord.Interaction, **kwargs):
    for name, value in kwargs.items():
        if value < 1:
            await interaction.response.send_message(f"❗ The parameter '{name}' must be greater than 0.", ephemeral=True)
            return False
    return True

async def resolve_display_data(character_name: str, guild: Optional[discord.Guild]) -> dict:
    """
    Returns display data for the character.
    If guild is None, returns fallback data (no member lookup).
    """
    discord_id = get_discord_id_by_character(character_name)
    if not discord_id or guild is None:
        # no linked discord id OR no guild provided -> fallback
        return {
            "display_name": character_name,
            "avatar_url": None,
            "role": None,
            "color": discord.Color.default()
        }

    # guild is provided and we have a discord_id
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
        except Exception as e:
            logging.exception(f"Failed to fetch member {discord_id}: {e}")
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
        "avatar_url": member.display_avatar.url if hasattr(member, "display_avatar") else None,
        "role": role.name if role else None,
        "color": role.color if role else discord.Color.default()
    }

async def generate_stats_embeds(
    interaction: discord.Interaction,
    characters: list[str],
    days: int,
    event_id: Optional[int] = None,
    avatar_url=None,
    target_user_id: Optional[int] = None
):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command must be used in a server (guild).", ephemeral=True)
        return
    guild = interaction.guild

    since = datetime.utcnow() - timedelta(days=days)
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        victories = {}
        defeats = {}
        characters = [name.lower() for name in characters]
        for character in characters:
            # победы
            c.execute("""
                SELECT victim, COUNT(*) FROM frags
                WHERE killer = ? AND timestamp >= ? AND (? IS NULL OR event_id = ?)
                GROUP BY victim
            """, (character, since, event_id, event_id))
            for victim, count in c.fetchall():
                victories[victim] = victories.get(victim, 0) + count

            # поражения
            c.execute("""
                SELECT killer, COUNT(*) FROM frags
                WHERE victim = ? AND timestamp >= ? AND (? IS NULL OR event_id = ?)
                GROUP BY killer
            """, (character, since, event_id, event_id))
            for killer, count in c.fetchall():
                defeats[killer] = defeats.get(killer, 0) + count

    # 📊 Stats computation
    all_opponents = set(victories) | set(defeats)
    stats = []
    for opponent in all_opponents:
        wins = victories.get(opponent, 0)
        losses = defeats.get(opponent, 0)
        total = wins + losses
        winlos = wins / losses if losses > 0 else wins
        winrate = (wins / total) * 100 if total else 0
        stats.append((opponent, wins, losses, winlos, winrate))

    stats.sort(key=itemgetter(4))  # by winrate

    total_wins = sum(victories.values())
    total_losses = sum(defeats.values())
    total_matches = total_wins + total_losses
    overall_winlos = total_wins / total_losses if total_losses > 0 else total_wins
    overall_winrate = (total_wins / total_matches) * 100 if total_matches else 0
    emoji_summary = get_winrate_emoji(overall_winrate)

    page_size = 10
    embeds = []
    for start in range(0, len(stats), page_size):
        embed = discord.Embed(color=discord.Color.blue())
        embed.set_author(
            name=f"📊 Stats for {len(characters)} character(s) in {days} day(s)",
            icon_url=avatar_url if avatar_url else None
        )

        for opponent, wins, losses, winlos, winrate in sorted(stats[start:start + page_size], key=itemgetter(4), reverse=False):
            display_data = await resolve_display_data(opponent, guild)
            emoji = get_winrate_emoji(winrate)
            embed.add_field(
                name=f"{emoji} **{display_data['display_name'].upper()}**",
                value=f"Wins: `{wins}`\tLosses: `{losses}`\nWinlos: `{winlos:.1f}`\tWinrate: `{winrate:.1f}%`",
                inline=False
            )

        chars = get_user_characters(target_user_id) if target_user_id else characters

        mmrs = []
        for c in chars:
            glicko_data = get_glicko_rating_extended(c, event_id)
            if glicko_data:
                mmrs.append(glicko_data[0])

        avg_mmr = round(sum(mmrs) / len(mmrs)) if mmrs else None
        mmr_line = f"`{avg_mmr}`\n" if avg_mmr is not None else ""

        summary = (
            f"Total Wins: `{total_wins}`\n"
            f"Total Losses: `{total_losses}`\n"
            f"Overall Winlos: `{overall_winlos:.1f}`\n"
            f"Overall Winrate: {emoji_summary} `{overall_winrate:.1f}%`\n"
            f"MMR: {mmr_line}"
        )

        embed.add_field(name="**🔍 SUMMARY: **", value=summary, inline=False)

        # 🧮 Aggregate manual points
        manual = 0
        natural = 0
        for char in characters:
            m, n = get_win_sources(char, event_id=event_id)
            manual += m
            natural += n

        # 🏁 Add final points summary
        embed.add_field(
            name=f"\n**🏅 TOTAL POINTS: **`{total_wins + manual}`",
            value=f"Frags: `{total_wins}`\nExtra: `{manual}`",
            inline=False
        )

        embeds.append(embed)

    return embeds

async def generate_topmmr_embeds(interaction: Interaction, leaderboard_data: list, public: bool = False, details: bool = False):
    """
    leaderboard_data: list of tuples
    [(display_name, avatar_url, characters, mmr, fights, wins, losses, winrate, recent_days),...]
    """
    embeds = []
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}

    author_text = f"🏆 Top MMR"
    color = discord.Color.gold()

    page_size = 10
    for start in range(0, len(leaderboard_data), page_size):
        embed = discord.Embed(color=color)
        embed.set_author(name=author_text)

        if leaderboard_data[start][1]:
            embed.set_thumbnail(url=leaderboard_data[start][1])

        for j, (name, avatar_url, chars, mmr, fights, wins, losses, winrate, recent_days) in enumerate(
            leaderboard_data[start:start+page_size]
        ):
            i = start + j + 1
            char_text = ", ".join(chars)
            medal = medals.get(i, "")
            winlos = f"{wins}/{losses}"
            winrate_str = f"{winrate:.1f}%"

            if recent_days <= 3:
                activity = f"🟢 `{recent_days}d ago`"
            elif recent_days <= 7:
                activity = f"🟡 `{recent_days}d ago`"
            else:
                activity = f"🔴 `{recent_days}d ago`"

            if details:
                value = (
                    f"`{char_text}`\n"
                    f"⚔️ `MMR: {round(mmr)}`\n"
                    f"Fights: `{fights}`\n"
                    f"Win/Los: `{winlos}`\n"
                    f"Winrate: `{winrate_str}`\n"
                    f"{activity}"
                )
            else:
                value = (
                    f"`{char_text}`\n"
                    f"⚔️ **`{round(mmr)}`**\t{activity}"
                )

            embed.add_field(
                name=f"**{i}. {medal} {name.upper()}**",
                value=value,
                inline=False
            )

        embeds.append(embed)

    return embeds
