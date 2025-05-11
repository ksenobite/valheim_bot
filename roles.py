# -*- coding: utf-8 -*-

import discord
import logging
import sqlite3
from datetime import datetime, timedelta
from db import get_db_path, get_user_characters


# 🏆  Threshold roles and colors — Discord roles must be created on the server with exactly the same names
ROLE_THRESHOLDS = [
    (400, "Смертельно опасен", discord.Color.purple()),
    (300, "Убить лишь завидев", discord.Color.magenta()),
    (200, "Опасен", discord.Color.orange()),
    (100, "Мужчина", discord.Color.gold()),
    (25, "Подает надежды", discord.Color.green()),
    (5, "Не опасен", discord.Color.light_grey()),
    (0, "Покончил с PvP", discord.Color.dark_grey())
]

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


def find_role_by_win_count(wins: int) -> str:
    """Finds the role name based on the number of wins."""
    for threshold, role_name, _ in ROLE_THRESHOLDS:
        if wins >= threshold:
            return role_name
    return ROLE_THRESHOLDS[-1][1]  # fallback


async def assign_role_based_on_wins(member: discord.Member):
    """Assigns a suitable role to the participant."""
    guild = member.guild
    wins = get_wins_for_user(member.id)
    role_name = find_role_by_win_count(wins)
    target_role = discord.utils.get(guild.roles, name=role_name)
    if not target_role:
        logging.warning(f"⚠️ Role '{role_name}' not found in guild.")
        return
    # Removing other PvP roles
    existing_roles = [r for r in member.roles if r.name in [name for _, name, _ in ROLE_THRESHOLDS]]
    if target_role not in existing_roles:
        try:
            await member.remove_roles(*existing_roles, reason="PvP role update")
            await member.add_roles(target_role, reason="PvP role update")
            logging.info(f"✅ Assigned role '{target_role.name}' to {member.display_name}")
        except Exception as e:
            logging.warning(f"❌ Failed to assign role for {member.display_name}: {e}")


async def update_roles_for_all_members(bot: discord.Client):
    """Updates the roles of all users in the guilds where the bot is running."""
    for guild in bot.guilds:
        logging.info(f"🔁 Updating roles in guild: {guild.name}")
        for member in guild.members:
            logging.info(f"🔍 Проверка участника: {member.display_name} ({member.id})")
            characters = get_user_characters(member.id)
            if not characters:
                logging.info(f"⛔ Нет привязанных персонажей — пропуск.")
                continue
            logging.info(f" Найдено персонажей: {characters}")
            if member.bot:
                continue
            await assign_role_based_on_wins(member)
