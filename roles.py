# -*- coding: utf-8 -*-

# roles.py

import discord
import logging
import sqlite3
from datetime import datetime, timedelta
from db import get_db_path, get_user_characters, get_all_rank_roles
from typing import Optional


def get_wins_for_user(discord_id: int, days: int = 7) -> int:
    """Counts the number of wins of all tied characters in the last N days."""
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
    """
    Returns the role name based on number of wins.
    Uses the dynamic configuration stored in the database.
    """
    thresholds = sorted(get_all_rank_roles(), key=lambda x: x[0], reverse=True)
    for threshold, role_name in thresholds:
        if wins >= threshold:
            return role_name
    return None

async def assign_role_based_on_wins(member: discord.Member, days: int = 7):
    """Assigns the appropriate PvP role to the member based on recent wins."""
    guild = member.guild
    wins = get_wins_for_user(member.id, days)
    role_name = find_role_name_by_wins(wins)
    if not role_name:
        logging.info(f"ℹ️ No matching role for {wins} wins — skipping {member.display_name}.")
        return
    target_role = discord.utils.get(guild.roles, name=role_name)
    if not target_role:
        logging.warning(f"⚠️ Role '{role_name}' not found in guild.")
        return
    # Remove existing PvP roles before assigning new one
    configured_roles = [rname for _, rname in get_all_rank_roles()]
    current_roles = [r for r in member.roles if r.name in configured_roles]
    if target_role not in current_roles:
        try:
            await member.remove_roles(*current_roles, reason="PvP role update")
            await member.add_roles(target_role, reason="PvP role update")
            logging.info(f"✅ Assigned role '{target_role.name}' to {member.display_name} ({wins} wins)")
        except Exception as e:
            logging.warning(f"❌ Failed to assign role for {member.display_name}: {e}")

async def update_roles_for_all_members(bot: discord.Client, days: int = 7):
    """Updates PvP roles for all members across all guilds."""
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
