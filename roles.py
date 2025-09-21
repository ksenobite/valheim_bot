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
    # From more to less
    for threshold, role_name in roles:
        if wins >= threshold:
            return role_name
    # If none of the thresholds are met, return the lowest role.
    return roles[-1][1]  # Minimum role (last in the list)


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
    Only processes users with activity in the main event (arena).
    """
    # Check if rank roles are configured
    roles_config = get_all_rank_roles()
    if not roles_config:
        logging.info("⚠️ No rank roles configured - skipping role update")
        return
    
    # Get main event (arena, id=1)
    main_event_id = get_default_event_id()
    main_event_name = get_setting("default_event") or "arena"
    
    for guild in bot.guilds:
        logging.info(f"🔁 Updating roles in guild: {guild.name}")
        updated = 0
        skipped = 0
        no_activity = 0
        
        for member in guild.members:
            if member.bot:
                continue
                
            characters = get_user_characters(member.id)
            if not characters:
                skipped += 1
                continue
            
            # Filter characters that have activity in main event
            active_characters = []
            for char in characters:
                # Check if character has any activity (frags) in main event
                wins, losses, total_fights = get_fight_stats(char, datetime.min, main_event_id)
                if total_fights > 0:  # Character has activity in main event
                    active_characters.append(char)
            
            if not active_characters:
                no_activity += 1
                continue
            
            # Calculate total wins only for characters active in main event
            total_wins = 0
            for char in active_characters:
                total_wins += get_total_wins(char, days=days, event_id=main_event_id)
            
            role_name = find_role_name_by_wins(total_wins)
            if not role_name:
                skipped += 1
                continue
            
            target_role = discord.utils.get(guild.roles, name=role_name)
            if not target_role:
                skipped += 1
                continue
            
            # Remove old rank roles and assign new one
            configured_roles = [rname for _, rname in roles_config]
            current_roles = [r for r in member.roles if r.name in configured_roles]
            
            try:
                await member.remove_roles(*current_roles, reason="PvP role update")
                if target_role not in member.roles:
                    await member.add_roles(target_role, reason="PvP role update")
                updated += 1
                logging.info(f"✅ Updated role for {member.display_name}: {role_name} ({total_wins} points)")
            except discord.Forbidden:
                logging.warning(f"❌ Can't update roles for {member.display_name} (missing permissions)")
            except Exception as e:
                logging.exception(f"⚠️ Unexpected error for {member.display_name}: {e}")
        
        logging.info(f"✅ Role update complete for {guild.name}: {updated} updated, {skipped} skipped, {no_activity} no activity")


async def update_mmr_roles(bot: discord.Client):
    """
    🔁 Assigns Glicko-2 based roles to users according to their average rating.
    """
    roles = get_all_mmr_roles()
    if not roles:
        logging.info("📭 No MMR roles configured.")
        return

    guild = discord.utils.get(bot.guilds)
    if not guild:
        logging.warning("❗ Bot is not in a guild.")
        return

    for member in guild.members:
        if member.bot:
            continue

        characters = get_user_characters(member.id)
        if not characters:
            continue

        # 🔎 Collect Glicko ratings for each character
        mmrs = []
        for char in characters:
            rating, _, _ = get_glicko_rating(char)
            mmrs.append(rating)

        if not mmrs:
            continue

        avg_mmr = sum(mmrs) / len(mmrs)

        # 🧱 Find matching role
        matched_role = None
        for threshold, role_name in sorted(roles, key=lambda x: x[0], reverse=True):
            if avg_mmr >= threshold:
                matched_role = discord.utils.get(guild.roles, name=role_name)
                break

        if not matched_role:
            continue

        # 🧹 Remove outdated roles
        mmr_role_names = [rname for _, rname in roles]
        current_roles = [r for r in member.roles if r.name in mmr_role_names]

        try:
            if matched_role not in current_roles:
                await member.remove_roles(*current_roles, reason="Glicko MMR role update")
                await member.add_roles(matched_role, reason="Glicko MMR role update")
                logging.info(f"✅ Assigned '{matched_role.name}' to {member.display_name} ({avg_mmr:.1f})")
        except Exception as e:
            logging.warning(f"❌ Failed to assign role to {member.display_name}: {e}")

