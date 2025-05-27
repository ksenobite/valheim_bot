# -*- coding: utf-8 -*-

# roles.py

import discord
import logging
import sqlite3
from datetime import datetime, timedelta
from db import *
from typing import Optional


def get_wins_for_user(discord_id: int, days: int = 7) -> int:
    """
    Counts the number of wins of all tied characters in the last N days.
    """
    characters = get_user_characters(discord_id)
    if not characters:
        return 0
    since = datetime.utcnow() - timedelta(days=days)
    wins = 0
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        for character in characters:
            c.execute("""
                SELECT COUNT(*) FROM frags
                WHERE killer = ? AND timestamp >= ?
            """, (character.lower(), since))
            row = c.fetchone()
            if row:
                wins += row[0]
    return wins


def find_role_name_by_wins(wins: int) -> Optional[str]:
    roles = get_all_rank_roles()  # list of (threshold, role)
    if not roles:
        return None
    # От большего к меньшему
    for threshold, role_name in roles:
        if wins >= threshold:
            return role_name
    # Если ни один порог не подошел — вернуть самую низкую роль
    return roles[-1][1]  # Минимальная роль (последняя в списке)


async def assign_role_based_on_wins(member: discord.Member, days: int = 7):
    """
    Assigns a role to a player based on total points (frags + manual adjustments).
    """
    guild = member.guild

    total_wins = get_total_wins_for_user(member.id)  # 💥 new approach
    role_name = find_role_name_by_wins(total_wins)

    if not role_name:
        logging.info(f"ℹ️ No matching role for {total_wins} total points — skipping {member.display_name}.")
        return

    target_role = discord.utils.get(guild.roles, name=role_name)
    if not target_role:
        logging.warning(f"⚠️ Role '{role_name}' not found in guild.")
        return

    configured_roles = [rname for _, rname in get_all_rank_roles()]
    current_roles = [r for r in member.roles if r.name in configured_roles]

    if target_role not in current_roles:
        try:
            await member.remove_roles(*current_roles, reason="PvP role update")
            await member.add_roles(target_role, reason="PvP role update")
            logging.info(f"✅ Assigned role '{target_role.name}' to {member.display_name} ({total_wins} points)")
        except Exception as e:
            logging.warning(f"❌ Failed to assign role for {member.display_name}: {e}")


async def update_roles_for_all_members(bot: discord.Client, days: int = 7):
    """
    Updates PvP roles for all members across all guilds.
    """
    for guild in bot.guilds:
        logging.info(f"🔁 Updating roles in guild: {guild.name}")
        for member in guild.members:
            logging.info(f"🔍 Participant verification: {member.display_name} ({member.id})")
            if member.bot:
                continue
            characters = get_user_characters(member.id)
            if not characters:
                logging.info("⛔ There are no linked characters.")
                continue
            logging.info(f"✅ Characters found: {characters}")
            await assign_role_based_on_wins(member, days=days)
