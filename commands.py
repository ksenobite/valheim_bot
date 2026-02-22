# -*- coding: utf-8 -*-
# commands.py

import os
import re
import sqlite3
import asyncio
import discord
import logging

from operator import itemgetter
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from typing import Optional

from discord import app_commands, Interaction
from discord.app_commands import describe
from discord.ext import commands

from settings import *
from db import *
from roles import *
from announcer import *
from utils import *
from glicko2 import Player

def setup_commands(bot: commands.Bot):
    
    # --- Admin commands ---

    @bot.tree.command(name="killstreaktimeout", description="Show or set the killstreak timeout (in seconds)")
    @app_commands.describe(seconds="New timeout value in seconds")
    async def killstreaktimeout(interaction: Interaction, seconds: Optional[int] = None):

        if not await require_admin(interaction):
            return
        global KILLSTREAK_TIMEOUT
        if seconds is not None:
            if seconds < 1:
                await interaction.response.send_message("❗ Timeout must be greater than 0.", ephemeral=True)
                return
            KILLSTREAK_TIMEOUT = seconds
            set_setting("killstreak_timeout", str(seconds))
            await interaction.response.send_message(f"✅ Killstreak timeout set to {seconds} seconds.", ephemeral=True)
        else:
            current = get_setting("killstreak_timeout")
            if current:
                await interaction.response.send_message(f"✅ Current killstreak timeout: {current} seconds.", ephemeral=True)
            else:
                await interaction.response.send_message("❗ Killstreak timeout is not set. Default: 15 seconds.", ephemeral=True)

    @bot.tree.command(name="link", description="Link a game character to a Discord user")
    @app_commands.describe(character="Character's name", user="Discord User")
    async def link(interaction: Interaction, character: str, user: discord.Member):
        if not await require_admin(interaction):
            return
        
        # Validate input
        if not character or len(character) > 50:
            await interaction.response.send_message("❌ Invalid character name.", ephemeral=True)
            return
            
        character = character.lower()
        try:
            set_character_owner(character, user.id)
            await interaction.response.send_message(f"✅ The character **{character}** is linked to {user.mention}.", ephemeral=True)
        except Exception as e:
            logging.exception(f"❌ Failed to link character {character} to user {user.id}: {e}")
            await interaction.response.send_message("❌ Failed to link character.", ephemeral=True)

    @bot.tree.command(name="unlink", description="Remove the connection between the character and the user")
    @app_commands.describe(character="Character's name")
    async def unlink(interaction: Interaction, character: str):
        if not await require_admin(interaction):
            return
        
        # Validate input
        if not character or len(character) > 50:
            await interaction.response.send_message("❌ Invalid character name.", ephemeral=True)
            return
            
        character = character.lower()
        try:
            removed = remove_character_owner(character)
            if removed:
                await interaction.response.send_message(f"🔗 Connection to the character **{character}** has been deleted.", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ The character **{character}** was not attached.", ephemeral=True)
        except Exception as e:
            logging.exception(f"❌ Failed to unlink character {character}: {e}")
            await interaction.response.send_message("❌ Failed to unlink character.", ephemeral=True)

    @bot.tree.command(name="roleset", description="Set a rank role for a win threshold")
    @describe(wins="Minimum number of wins for the role", role="Discord role to assign")
    async def roleset(interaction: Interaction, wins: int, role: discord.Role):
        if not await require_admin(interaction):
            return
        
        # Validate input data
        if wins < 0:
            await interaction.response.send_message("❗ Wins must be >= 0.", ephemeral=True)
            return
            
        if wins > 10000:
            await interaction.response.send_message("❗ Wins must be <= 10000.", ephemeral=True)
            return
            
        if not role.name or len(role.name) > 100:
            await interaction.response.send_message("❗ Invalid role name.", ephemeral=True)
            return
        
        try:
            set_rank_role(wins, role.name)
            await interaction.response.send_message(f"✅ Rank **{role.name}** set for `{wins}`+ wins.", ephemeral=True)
        except Exception as e:
            logging.exception(f"❌ Failed to set rank role: {e}")
            await interaction.response.send_message("❌ Failed to set rank role.", ephemeral=True)

    @bot.tree.command(name="roleupdate", description="Force role update for all members")
    async def roleupdate(interaction: discord.Interaction):

        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⚠️ Admin only", ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=True)

        # Check if rank roles are configured
        roles_config = get_all_rank_roles()
        if not roles_config:
            await interaction.followup.send("⚠️ No rank roles configured.", ephemeral=True)
            return

        # Get main event info
        main_event_id = get_default_event_id()
        main_event_name = get_setting("default_event") or "arena"
        
        await update_roles_for_all_members(interaction.client)
        
        # Build response embed
        embed = discord.Embed(
            title="🔁 Rank Roles Update Complete",
            color=discord.Color.green()
        )
        
        embed.description = (
            f"**Event:** {main_event_name} (id={main_event_id})\n\n"
            f"✅ **Updated:** Users with activity in main event\n"
            f"⏭️ **Skipped:** Users without linked characters or no activity\n\n"
            f"Only users with activity in main event received roles."
        )
        
        embed.set_footer(text="Rank Role Management")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @bot.tree.command(name="roleclear", description="Clear all configured rank roles")
    async def roleclear(interaction: Interaction):
        if not await require_admin(interaction):
            return
        clear_rank_roles()
        await interaction.response.send_message("🗑️ All rank roles have been cleared.", ephemeral=True)

    @bot.tree.command(name="points", description="Admin: manual control of players' points")
    @app_commands.describe(
        target="Character or @user",
        amount="Extra points: +50, -30",
        reason="Reason (optional)",
        event="Event name (optional)"
    )
    async def points(interaction: Interaction, target: str, amount: int, reason: str = "Manual adjustment", event: Optional[str] = None):
        
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⚠️ Admin only", ephemeral=True)
            return

        # Validate input data
        if not target or len(target) > 100:
            await interaction.response.send_message("❌ Invalid target. Character name too long or empty.", ephemeral=True)
            return
        
        if abs(amount) > 10000:
            await interaction.response.send_message("❌ Amount too large. Maximum ±10000 points.", ephemeral=True)
            return
            
        if reason and len(reason) > 200:
            await interaction.response.send_message("❌ Reason too long. Maximum 200 characters.", ephemeral=True)
            return
            
        if event and len(event) > 50:
            await interaction.response.send_message("❌ Event name too long. Maximum 50 characters.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        # Resolve event_id
        event_id = get_event_id_by_name(event) if event else get_default_event_id()

        # We determine who we are correcting
        if match := re.match(r"<@!?(\d+)>", target):  # if @user
            user_id = int(match.group(1))
            characters = get_user_characters(user_id)
            if not characters:
                await interaction.followup.send("❌ This user does not have any attached characters.", ephemeral=True)
                return
        else:
            characters = [target.lower()]

        # Making adjustments for each character
        try:
            for character in characters:
                adjust_wins(character, amount, reason, event_id=event_id)

            # ✅ Response
            char_list = "\n".join(f"- `{char}`" for char in characters)
            
            embed = discord.Embed(
                title="✅ Manual Points Adjustment",
                color=discord.Color.orange(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="Characters", value=char_list, inline=False)
            embed.add_field(name="Amount", value=f"`{amount:+}`", inline=True)
            embed.add_field(name="Reason", value=reason or "—", inline=True)
            embed.set_footer(text=f"Changed by {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)

            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logging.exception(f"❌ Failed to adjust points for {characters}: {e}")
            await interaction.followup.send("❌ Failed to adjust points.", ephemeral=True)

    @bot.tree.command(name="pointlog", description="Show manual adjustment history")
    @app_commands.describe(target="Character name or @user", event="Event name (optional)")
    async def pointlog(interaction: Interaction, target: str, event: Optional[str] = None):
        
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⚠️ Admin only", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        event_id = get_event_id_by_name(event) if event else get_default_event_id()

        # Get characters
        if match := re.match(r"<@!?(\d+)>", target):
            user_id = int(match.group(1))
            characters = get_user_characters(user_id)
            if not characters:
                await interaction.followup.send("❌ This user has no linked characters.", ephemeral=True)
                return
        else:
            characters = [target.lower()]

        # Collecting the history of adjustments
        with sqlite3.connect(get_db_path()) as conn:
            c = conn.cursor()
            placeholders = ",".join("?" for _ in characters)
            query = f"""
                SELECT character, adjustment, reason, timestamp
                FROM manual_adjustments
                WHERE character IN ({placeholders}) AND event_id = ?
                ORDER BY timestamp DESC
                LIMIT 20
            """
            c.execute(query, (*characters, event_id))
            rows = c.fetchall()

        if not rows:
            await interaction.followup.send("ℹ️ No points adjustments found.", ephemeral=True)
            return

        embed = discord.Embed(
            title="📜 Points History",
            color=discord.Color.teal(),
            timestamp=datetime.now(timezone.utc)
        )
        grouped = {}
        for char, delta, reason, ts in rows:
            ts_fmt = datetime.fromisoformat(ts).strftime("%Y-%m-%d %H:%M")
            line = f"`{delta:+}` | _{reason}_ ({ts_fmt})"
            grouped.setdefault(char, []).append(line)

        for char, changes in grouped.items():
            value = "\n".join(changes)
            embed.add_field(name=f"🧍 {char}", value=value, inline=False)

        embed.set_footer(text="Most recent 20 changes")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @bot.tree.command(name="voice", description="Join or leave a voice channel")
    @app_commands.describe(leave="Set True to leave the voice channel")
    async def voice(interaction: discord.Interaction, leave: bool = False):
        """🔊 Connect or disconnect the bot from a voice channel."""

        # 👮 Ensure user is an admin and a guild member
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⚠️ Admin only", ephemeral=True)
            return

        # ✅ Ensure command is run in a server (not in DMs)
        if not interaction.guild:
            await interaction.response.send_message("❌ This command must be used in a server.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=True)

        # 🔇 Disconnect
        if leave:
            try:
                voice_client = interaction.guild.voice_client
                if isinstance(voice_client, discord.VoiceClient) and voice_client.is_connected():
                    await voice_client.disconnect(force=True)
                    await interaction.followup.send("🔌 Disconnected from voice channel.")
                else:
                    await interaction.followup.send("ℹ️ I'm not connected to a voice channel.")
            except Exception as e:
                logging.exception(f"❌ Failed to disconnect from voice channel: {e}")
                await interaction.followup.send("❌ Failed to disconnect from voice channel.")
            return

        # 🔊 Connect
        try:
            voice_state = getattr(interaction.user, "voice", None)
            channel = getattr(voice_state, "channel", None)

            if not channel:
                await interaction.followup.send("⚠️ You must be in a voice channel.", ephemeral=True)
                return

            current_vc = interaction.guild.voice_client
            if current_vc:
                if isinstance(current_vc, discord.VoiceClient) and current_vc.is_connected():
                    await current_vc.disconnect(force=True)
                if current_vc in interaction.client.voice_clients:
                    interaction.client.voice_clients.remove(current_vc)
                await interaction.guild.change_voice_state(channel=None)
                await asyncio.sleep(2.0)

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    await channel.connect(timeout=30.0, reconnect=True)
                    await interaction.followup.send(f"🔈 Connected to **{channel.name}**")
                    
                    # 🎵 Start playback tasks
                    asyncio.create_task(audio_queue_worker(bot, interaction.guild))
                    asyncio.create_task(start_heartbeat_loop(bot, interaction.guild))
                    
                    break
                except discord.errors.ConnectionClosed as e:
                    if e.code == 4006 and attempt < max_retries - 1:
                        wait_time = (2 ** attempt) + 1  # 3s, 5s, 9s
                        logging.warning(f"Voice connect failed (4006) on attempt {attempt+1}. Retrying in {wait_time}s...")
                        await asyncio.sleep(wait_time)
                    else:
                        raise
                except Exception:
                    raise

        except discord.Forbidden:
            await interaction.followup.send("❌ I don't have permission to join this voice channel.", ephemeral=True)
        except discord.ClientException as e:
            logging.exception(f"❌ Voice connection error: {e}")
            await interaction.followup.send("❌ Voice connection error.", ephemeral=True)
        except Exception as e:
            logging.exception(f"❌ Unexpected error in voice command: {e}")
            await interaction.followup.send("❌ An unexpected error occurred. Try updating discord.py or resetting bot token.", ephemeral=True)

    # /style command removed (styles are fixed)

    @bot.tree.command(name="reset", description="Reset the database or restore from backup")
    @app_commands.describe(backup="Name of the backup file to restore (optional)")
    async def reset(interaction: Interaction, backup: Optional[str] = None):
        if not await require_admin(interaction):
            return
        
        try:
            os.makedirs(BACKUP_DIR, exist_ok=True)
            if backup is None:
                # Normal reset
                db_path = get_db_file_path()
                backup_file = os.path.join(BACKUP_DIR, f"frags_backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.db")
                if os.path.exists(db_path):
                    os.rename(db_path, backup_file)
                init_db()
                await interaction.response.send_message(
                    "✅ Database has been reset.\n\n"
                    f"✅ Backup saved:\n {backup_file}\n\n"
                    "❗ Please set **tracking channel** and **announce channel** again!",
                    ephemeral=True
                )
                logging.info(f"✅ Database reset complete. Backup saved: {backup_file}")
            else:
                # Restore from backup
                backup_path = os.path.join(BACKUP_DIR, backup)
                if not os.path.exists(backup_path):
                    await interaction.response.send_message(
                        f"❌ Backup file `{backup}` not found.",
                        ephemeral=True
                    )
                    return
                if os.path.exists(get_db_file_path()):
                    os.remove(get_db_file_path())
                os.replace(backup_path, get_db_file_path())
                init_db()
                await interaction.response.send_message(
                    "✅ Database restored from backup\n\n"
                    "**❗ Please restart the bot manually!**",
                    ephemeral=True
                )
                logging.info(f"✅ Database restored from backup {backup}")
        except FileNotFoundError as e:
            logging.exception(f"❌ File not found during reset: {e}")
            await interaction.response.send_message("❌ File not found during reset operation.", ephemeral=True)
        except PermissionError as e:
            logging.exception(f"❌ Permission denied during reset: {e}")
            await interaction.response.send_message("❌ Permission denied during reset operation.", ephemeral=True)
        except Exception as e:
            logging.exception(f"❌ Unexpected error during reset: {e}")
            await interaction.response.send_message("❌ An unexpected error occurred during reset.", ephemeral=True)

# --- User Commands ---

    @bot.tree.command(name="top", description="Top players by total points (frags + adjustments)")
    @app_commands.describe(count="Number of top players", days="Days", event="Event name (optional)", public="Publish?")
    async def top(interaction: Interaction, count: int = 10, days: int = 1, event: Optional[str] = None, public: bool = False):
        if not await check_positive(interaction, count=count, days=days):
            return

        if public and (not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator):
            await interaction.response.send_message("⚠️ Admin only", ephemeral=True)
            return

        if not interaction.guild:
            await interaction.response.send_message("❌ This command must be used in a server.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=not public)

        # 🎯 Определяем event_id
        event_id = get_event_id_by_name(event) if event else get_default_event_id()
        if not event_id:
            await interaction.followup.send(f"❌ Event `{event}` not found.", ephemeral=True)
            return

        since = datetime.now(timezone.utc) - timedelta(days=days)
        with sqlite3.connect(get_db_path()) as conn:
            c = conn.cursor()
            c.execute("""
                SELECT killer, COUNT(*) as count FROM frags
                WHERE timestamp >= ? AND event_id = ?
                GROUP BY killer
            """, (since, event_id))
            raw_stats = c.fetchall()

        # 📊 Aggregate frags and manual points (event-aware)
        user_points = {}
        for character, frags in raw_stats:
            manual, _ = get_win_sources(character, event_id=event_id)
            discord_id = get_character_owner(character)
            key = discord_id if discord_id else character

            if key not in user_points:
                user_points[key] = {"characters": set(), "frags": 0, "manual": 0}

            user_points[key]["characters"].add(character)
            user_points[key]["frags"] += frags
            user_points[key]["manual"] += manual

        aggregated_stats = [
            (key, data["characters"], data["frags"], data["manual"], data["frags"] + data["manual"])
            for key, data in user_points.items()
        ]
        sorted_stats = sorted(aggregated_stats, key=lambda x: x[4], reverse=True)[:count]

        if not sorted_stats:
            await interaction.followup.send(f"❌ No data for last {days} day(s).", ephemeral=not public)
            return

        # Get event name for display
        event_name = event if event else "arena"
        if not event:
            try:
                default_event_name = get_setting("default_event")
                if default_event_name:
                    event_name = default_event_name
            except Exception:
                pass
        
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        author_text = f"🏆 Top-{count} in {days} day(s) - Event: {event_name}"
        page_size = 10
        embeds = []

        # 🖼️ Top user info
        top_key = sorted_stats[0][0]
        if isinstance(top_key, int):
            member = interaction.guild.get_member(top_key)
            top_display = {
                "display_name": member.display_name if member else f"User {top_key}",
                "avatar_url": member.display_avatar.url if member else None,
                "color": member.top_role.color if member and member.top_role else discord.Color.default()
            }
        else:
            top_display = await resolve_display_data(top_key, interaction.guild)

        # 📄 Build paginated leaderboard
        for start in range(0, len(sorted_stats), page_size):
            embed = discord.Embed(color=top_display.get("color", discord.Color.dark_grey()))
            embed.set_author(name=author_text)
            if top_display.get("avatar_url"):
                embed.set_thumbnail(url=top_display["avatar_url"])

            for i, (key, characters, frags, manual, total) in enumerate(sorted_stats[start:start + page_size], start + 1):
                if isinstance(key, int):
                    member = interaction.guild.get_member(key)
                    display_data = {
                        "display_name": member.display_name if member else f"User {key}",
                        "avatar_url": member.display_avatar.url if member else None
                    }
                    mmr = get_user_glicko_mmr(key, event_id)
                else:
                    display_data = await resolve_display_data(key, interaction.guild)
                    rating_data = get_glicko_rating_extended(key, event_id)
                    mmr = rating_data[0] if rating_data else "—"

                medal = medals.get(i, "")
                char_list = ", ".join(characters)
                line = (
                    f"Characters: `{char_list}`\n"
                    f"Points: `{total}` (`{frags}` + `{manual}`)\n"
                    f"MMR: `{mmr}`"
                )

                embed.add_field(
                    name=f"**{i}. {medal} {display_data['display_name'].upper()}**",
                    value=line,
                    inline=False
                )

            embeds.append(embed)

        if len(embeds) == 1:
            await interaction.followup.send(embed=embeds[0], ephemeral=not public)
        else:
            view = PaginatedStatsView(embeds, ephemeral=not public)
            await view.send_initial(interaction)

    @bot.tree.command(name="mystats", description="Show your stats (all linked characters)")
    @app_commands.describe(days="Days", event="Event name (optional)", public="Publish?")
    async def mystats(interaction: Interaction, days: int = 1, event: Optional[str] = None, public: bool = False):
        if public and (not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator):
            await interaction.response.send_message("⚠️ Admin only", ephemeral=True)
            return

        if not await check_positive(interaction, days=days):
            return

        user_id = interaction.user.id
        characters = get_user_characters(user_id)
        if not characters:
            await interaction.response.send_message("❌ You don't have any linked characters.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=not public)

        event_id = get_event_id_by_name(event) if event else get_default_event_id()
        if not event_id:
            await interaction.followup.send(f"❌ Event `{event}` not found.", ephemeral=True)
            return

        avatar_url = interaction.user.display_avatar.url if hasattr(interaction.user, "display_avatar") else None
        # filter characters by activity in this event and time window
        since = datetime.now(timezone.utc) - timedelta(days=days)
        filtered_characters = []
        for ch in characters:
            w, l, t = get_fight_stats(ch, since, event_id)
            if t > 0:
                filtered_characters.append(ch)

        if not filtered_characters:
            await interaction.followup.send("❌ No stats available for this player.", ephemeral=not public)
            return

        embeds = await generate_stats_embeds(
            interaction,
            filtered_characters,
            days,
            event_id=event_id,
            avatar_url=avatar_url,
            target_user_id=user_id
        )

        if not embeds:
            await interaction.followup.send("❌ No stats available for this player.", ephemeral=not public)
            return

        if len(embeds) == 1:
            await interaction.followup.send(embed=embeds[0], ephemeral=not public)
        else:
            view = PaginatedStatsView(embeds, ephemeral=not public)
            await view.send_initial(interaction)

    @bot.tree.command(name="stats", description="Show player stats")
    @app_commands.describe(
        player="Character or @user",
        days="Days",
        event="Event name (optional)",
        public="Publish?"
    )
    async def stats(interaction: Interaction, player: str, days: int = 1, event: Optional[str] = None, public: bool = False):
        # 🛡️ Admin check
        if public and (not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator):
            await interaction.response.send_message("⚠️ Admin only", ephemeral=True)
            return

        if not await check_positive(interaction, days=days):
            return

        await interaction.response.defer(thinking=True, ephemeral=not public)

        event_id = get_event_id_by_name(event) if event else get_default_event_id()
        if not event_id:
            await interaction.followup.send(f"❌ Event `{event}` not found.", ephemeral=True)
            return

        avatar_url = None
        characters = []
        user_id = None

        if match := re.match(r"<@!?(\d+)>", player):
            user_id = int(match.group(1))
            characters = get_user_characters(user_id)
            if not characters:
                await interaction.followup.send("❌ No characters linked to this user.", ephemeral=True)
                return
            try:
                user = await bot.fetch_user(user_id)
                avatar_url = user.display_avatar.url if hasattr(user, "display_avatar") else None
            except Exception:
                avatar_url = None
        else:
            characters = [player.lower()]

        # filter characters by activity in this event and time window
        since = datetime.now(timezone.utc) - timedelta(days=days)
        filtered_characters = []
        for ch in characters:
            w, l, t = get_fight_stats(ch, since, event_id)
            if t > 0:
                filtered_characters.append(ch)

        if not filtered_characters:
            await interaction.followup.send("❌ No stats available for this player.", ephemeral=not public)
            return

        embeds = await generate_stats_embeds(
            interaction,
            filtered_characters,
            days,
            event_id=event_id,
            avatar_url=avatar_url,
            target_user_id=user_id
        )

        if not embeds:
            await interaction.followup.send("❌ No stats available for this player.", ephemeral=not public)
            return

        if len(embeds) == 1:
            await interaction.followup.send(embed=embeds[0], ephemeral=not public)
        else:
            view = PaginatedStatsView(embeds, ephemeral=not public)
            await view.send_initial(interaction)

    @bot.tree.command(name="whois", description="Show who owns the character or what characters belong to a user")
    @app_commands.describe(character="Character or @user")
    async def whois(interaction: Interaction, character: str):
        await interaction.response.defer(thinking=True, ephemeral=True)
        match = re.match(r"<@!?(\d+)>", character)  # check if @mention
        if match:
            user_id = int(match.group(1))
            linked_characters = get_user_characters(user_id)
            if not linked_characters:
                await interaction.followup.send("❌ This user has no linked characters.", ephemeral=True)
                return
            formatted = "\n".join(f"🔗 `{name}`" for name in linked_characters)
            user = await bot.fetch_user(user_id)
            embed = discord.Embed(
                title=f"🧍 Characters linked to {user.display_name}",
                description=formatted,
                color=discord.Color.blurple()
            )
            embed.set_thumbnail(url=user.display_avatar.url)
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            character_name = character.lower()
            discord_id = get_character_owner(character_name)
            if discord_id:
                try:
                    user = await bot.fetch_user(discord_id)
                    embed = discord.Embed(
                        title=f"🎮 Character Owner",
                        description=f"The character `{character_name}` is linked to {user.mention}.",
                        color=discord.Color.green()
                    )
                    embed.set_thumbnail(url=user.display_avatar.url)
                    await interaction.followup.send(embed=embed, ephemeral=True)
                except Exception:
                    await interaction.followup.send(
                        f"✅ Character `{character_name}` is linked to a user, but their profile couldn't be fetched.",
                        ephemeral=True
                    )
            else:
                await interaction.followup.send(
                    f"❌ The character `{character_name}` is not linked to any user.",
                    ephemeral=True
                )

    @bot.tree.command(name="roles", description="Show the current rank role configuration")
    @app_commands.describe(public="Publish result to channel?")
    async def roles(interaction: Interaction, public: bool = False):
        # 🛡️ Only allow public publishing by admins
        is_admin = isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator
        if public and not is_admin:
            await interaction.response.send_message("⚠️ Only admins can publish the result.", ephemeral=True)
            return

        ranks = get_all_rank_roles()
        if not ranks:
            await interaction.response.send_message("ℹ️ No rank roles are currently configured.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🏆 Rank Roles",
            description="Custom PvP roles by weekly win count:",
            color=discord.Color.dark_gold()
        )
        for wins, role_name in ranks:
            embed.add_field(name=role_name, value=f"{wins}+", inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=not public)
    
# --- MMR ---        
            
    @bot.tree.command(name="mmr", description="Admin: manually adjust MMR rating for character(s) or user")
    @app_commands.describe(
        target="Character name or @user",
        value="Rating value: +50, -30, or =1500",
        reason="Optional reason for the change",
        event="Event name (optional)"
    )
    async def mmr(interaction: Interaction, target: str, value: str, reason: str = "Manual MMR adjustment", event: Optional[str] = None):
        
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⚠️ Admin only", ephemeral=True)
            return

        # Validate input data
        if not target or len(target) > 100:
            await interaction.response.send_message("❌ Invalid target. Character name too long or empty.", ephemeral=True)
            return
            
        if not value or len(value) > 20:
            await interaction.response.send_message("❌ Invalid value format. Use +N, -N, or =N.", ephemeral=True)
            return
            
        if reason and len(reason) > 200:
            await interaction.response.send_message("❌ Reason too long. Maximum 200 characters.", ephemeral=True)
            return
            
        if event and len(event) > 50:
            await interaction.response.send_message("❌ Event name too long. Maximum 50 characters.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        event_id = get_event_id_by_name(event) if event else get_default_event_id()

        # 🔍 Define the characters
        if match := re.match(r"<@!?(\d+)>", target):
            user_id = int(match.group(1))
            characters = get_user_characters(user_id)
            if not characters:
                await interaction.followup.send("❌ No characters linked to this user.", ephemeral=True)
                return
        else:
            characters = [target.lower()]

        # 📐 Parse the value
        if value.startswith("+") or value.startswith("-"):
            try:
                delta = float(value)
            except ValueError:
                await interaction.followup.send("❌ Invalid value format. Use +N, -N, or =N.", ephemeral=True)
                return
        elif value.startswith("="):
            try:
                absolute = float(value[1:])
            except ValueError:
                await interaction.followup.send("❌ Invalid absolute value. Use =1500.", ephemeral=True)
                return
            delta = None
        else:
            await interaction.followup.send("❌ Use +N, -N, or =N format.", ephemeral=True)
            return

        changed = []

        for character in characters:
            rating, rd, vol, _ = get_glicko_rating_extended(character, event_id=event_id)

            if delta is not None:
                new_rating = rating + delta
                delta_applied = delta
            else:
                new_rating = absolute
                delta_applied = new_rating - rating

            set_glicko_rating(character, new_rating, rd, vol, event_id=event_id)

            with sqlite3.connect(get_db_path()) as conn:
                conn.execute("""
                    INSERT INTO glicko_history (character, delta, reason, event_id)
                    VALUES (?, ?, ?, ?)
                """, (character, delta_applied, reason, event_id))

            changed.append((character, rating, new_rating, delta_applied))

        # Get event name for display
        event_name = event if event else "arena"
        if not event:
            try:
                default_event_name = get_setting("default_event")
                if default_event_name:
                    event_name = default_event_name
            except Exception:
                pass

        # 📦 Embed
        embed = discord.Embed(
            title=f"🔧 MMR Adjustment - Event: {event_name}",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc)
        )
        for char, old, new, d in changed:
            embed.add_field(name=char, value=f"{old:.1f} → {new:.1f} ({d:+.1f})", inline=False)

        embed.add_field(name="Reason", value=reason or "—", inline=False)
        embed.set_footer(text=f"Changed by {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @bot.tree.command(name="mmrlog", description="Show MMR rating adjustment history for a character or user")
    @app_commands.describe(target="Character name or @user", event="Event name (optional)")
    async def mmrlog(interaction: Interaction, target: str, event: Optional[str] = None):
        
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⚠️ Admin only", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        event_id = get_event_id_by_name(event) if event else get_default_event_id()

        if match := re.match(r"<@!?(\d+)>", target):
            user_id = int(match.group(1))
            characters = get_user_characters(user_id)
            if not characters:
                await interaction.followup.send("❌ No characters linked to this user.", ephemeral=True)
                return
        else:
            characters = [target.lower()]

        with sqlite3.connect(get_db_path()) as conn:
            c = conn.cursor()
            placeholders = ",".join("?" for _ in characters)
            c.execute(f"""
                SELECT character, delta, reason, timestamp
                FROM glicko_history
                WHERE character IN ({placeholders}) AND event_id = ?
                ORDER BY timestamp DESC
                LIMIT 20
            """, (*characters, event_id))
            rows = c.fetchall()

        if not rows:
            await interaction.followup.send("ℹ️ No MMR rating adjustments found.", ephemeral=True)
            return

        # Get event name for display
        event_name = event if event else "arena"
        if not event:
            try:
                default_event_name = get_setting("default_event")
                if default_event_name:
                    event_name = default_event_name
            except Exception:
                pass

        embed = discord.Embed(
            title=f"📜 MMR Adjustment Log - Event: {event_name}",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc)
        )

        grouped = defaultdict(list)
        for character, delta, reason, ts in rows:
            ts_fmt = datetime.fromisoformat(ts).strftime("%Y-%m-%d %H:%M")
            line = f"`{delta:+.1f}` | _{reason}_ ({ts_fmt})"
            grouped[character].append(line)

        for char, lines in grouped.items():
            embed.add_field(name=f"🎮 {char}", value="\n".join(lines), inline=False)

        embed.set_footer(text="Most recent 20 changes")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @bot.tree.command(name="mmrroleset", description="Set a MMR role for a threshold")
    @app_commands.describe(threshold="Minimum MMR", role="Discord role")
    async def mmrroleset(interaction: Interaction, threshold: int, role: discord.Role):
        if not await require_admin(interaction):
            return
        
        # Validate input data
        if threshold < 0:
            await interaction.response.send_message("❗ Rating must be >= 0.", ephemeral=True)
            return
            
        if threshold > 10000:
            await interaction.response.send_message("❗ Rating must be <= 5000.", ephemeral=True)
            return
            
        if not role.name or len(role.name) > 100:
            await interaction.response.send_message("❗ Invalid role name.", ephemeral=True)
            return
        
        try:
            set_mmr_role(threshold, role.name)
            await interaction.response.send_message(f"✅ Role **{role.name}** set for `{threshold}+` MMR rating.", ephemeral=True)
        except Exception as e:
            logging.exception(f"❌ Failed to set MMR role: {e}")
            await interaction.response.send_message("❌ Failed to set MMR role.", ephemeral=True)

    @bot.tree.command(name="mmrroles", description="Show current MMR roles configuration")
    async def mmrroles(interaction: Interaction, public: bool = False):
        # 🛡️ Only allow public publishing by admins
        is_admin = isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator
        if public and not is_admin:
            await interaction.response.send_message("⚠️ Only admins can publish the result.", ephemeral=True)
            return
        
        roles = get_all_mmr_roles()
        if not roles:
            await interaction.response.send_message("ℹ️ No MMR roles configured.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="🏅 MMR Roles",
            description="Roles based on current player rating:",
            color=discord.Color.dark_gold()
        )
        for threshold, role_name in roles:
            embed.add_field(name=f"{role_name}", value=f"Rating: `{threshold}+`", inline=True)
            
        await interaction.response.send_message(embed=embed, ephemeral=not public)

    @bot.tree.command(name="mmrroleclear", description="Clear all MMR roles settings")
    async def mmrroleclear(interaction: Interaction):
        if not await require_admin(interaction):
            return
        clear_mmr_roles()
        await interaction.response.send_message("🧹 All MMR roles settings have been cleared.", ephemeral=True)

    @bot.tree.command(name="mmrsync", description="🔁 Rebuild MMR from frags table for specific event")
    @app_commands.describe(
        event="Event name to rebuild",
        start_date="Start date DD.MM.YYYY (optional)"
    )
    async def mmrsync(interaction: Interaction, event: str, start_date: Optional[str] = None):

        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⚠️ Admin only", ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=True)

        try:
            # 🗂️ Get the specific event
            ev = get_event_by_name(event)
            if not ev:
                await interaction.followup.send(f"❌ Event '{event}' not found.", ephemeral=True)
                return

            event_id, event_name, *_ = ev
            logging.info(f"🔄 Rebuilding MMR for event '{event_name}' (id={event_id})")

            # 🧹 Clearing old data only for this event
            with sqlite3.connect(get_db_path()) as conn:
                conn.execute("DELETE FROM glicko_ratings WHERE event_id = ?", (event_id,))
                conn.commit()

            # 📖 We read all the frags on the event
            with sqlite3.connect(get_db_path()) as conn:
                c = conn.cursor()
                start_dt = None
                if start_date:
                    parsed = None
                    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
                        try:
                            parsed = datetime.strptime(start_date, fmt)
                            break
                        except ValueError:
                            continue
                    if not parsed:
                        await interaction.followup.send(
                            "❌ Invalid start_date format. Use DD.MM.YYYY (e.g., 14.02.2026) or YYYY-MM-DD.",
                            ephemeral=True
                        )
                        return
                    start_dt = parsed.replace(tzinfo=timezone.utc)

                if start_dt:
                    c.execute("""
                        SELECT killer, victim, timestamp 
                        FROM frags 
                        WHERE event_id = ? AND timestamp >= ?
                        ORDER BY timestamp ASC
                    """, (event_id, start_dt.isoformat()))
                else:
                    c.execute("""
                        SELECT killer, victim, timestamp 
                        FROM frags 
                        WHERE event_id = ? 
                        ORDER BY timestamp ASC
                    """, (event_id,))
                rows = c.fetchall()

            if not rows:
                if start_date:
                    await interaction.followup.send(
                        f"❌ No frags found for event '{event_name}' from {start_date}.",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(f"❌ No frags found for event '{event_name}'.", ephemeral=True)
                return

            # 🎯 Grouping the fights by day
            battles_by_day = defaultdict(list)
            all_dates = []

            for killer, victim, ts in rows:
                day = datetime.fromisoformat(ts).date()
                battles_by_day[day].append((killer.lower(), victim.lower()))
                all_dates.append(day)

            first_date = min(all_dates)
            end_date = max(all_dates)
            all_players = {}

            # 🚀 Recalculating day by day
            current_date = first_date
            while current_date <= end_date:
                fights = battles_by_day.get(current_date, [])

                participated_today = set()

                for killer, victim in fights:
                    if killer not in all_players:
                        all_players[killer] = Player()
                    if victim not in all_players:
                        all_players[victim] = Player()

                    p1 = all_players[killer]
                    p2 = all_players[victim]

                    p1.update_player([p2.getRating()], [p2.getRd()], [1])
                    p2.update_player([p1.getRating()], [p1.getRd()], [0])

                    participated_today.update([killer, victim])

                # 📉 decay for those who didn't play that day
                for name, player in all_players.items():
                    if name not in participated_today:
                        player.pre_rating_period()

                current_date += timedelta(days=1)

            # ✅ Saving the results
            with sqlite3.connect(get_db_path()) as conn:
                for name, player in all_players.items():
                    last_act = get_last_active_iso(name, event_id=event_id)
                    set_glicko_rating(
                        name,
                        player.getRating(),
                        player.getRd(),
                        player._vol,
                        event_id=event_id,
                        last_activity=last_act,
                    )

            # --- Build response embed ---
            embed = discord.Embed(
                title="🔁 MMR Sync Complete",
                color=discord.Color.green()
            )

            # mark default event if it matches
            default_event_id = None
            try:
                default_name = get_setting("default_event")
                if default_name:
                    def_ev = get_event_by_name(default_name)
                    if def_ev:
                        default_event_id = def_ev[0]
            except Exception:
                default_event_id = None

            label = f"{event_name}"
            if default_event_id is not None and event_id == default_event_id:
                label = f"{label} (default)"

            if start_date:
                embed.description = (
                    f"Sync complete for event **{label}**.\n"
                    f"Players rebuilt: **{len(all_players)}**\n"
                    f"Period: from {start_date} to {end_date.isoformat()}\n\n"
                    "Ratings recalculated from frags data"
                )
            else:
                embed.description = (
                    f"Sync complete for event **{label}**.\n"
                    f"Players rebuilt: **{len(all_players)}**\n\n"
                    "All ratings recalculated from frags data"
                )
            embed.set_footer(text="MMR Admin Tool")

            await interaction.followup.send(embed=embed, ephemeral=True)
            logging.info(f"✅ MMR sync finished for event '{event_name}' ({len(all_players)} players)")

        except Exception as e:
            logging.exception("❌ Failed to run MMR sync")
            await interaction.followup.send("❌ Failed to run MMR sync.", ephemeral=True)

    @bot.tree.command(name="mmrclear", description="🧹 Reset MMR ratings to default values for specific event")
    @app_commands.describe(event="Event name to reset")
    async def mmrclear(interaction: Interaction, event: str):

        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⚠️ Admin only", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            # 🗂️ Get the specific event
            ev = get_event_by_name(event)
            if not ev:
                await interaction.followup.send(f"❌ Event '{event}' not found.", ephemeral=True)
                return

            event_id, event_name, *_ = ev
            logging.info(f"🧹 Resetting MMR for event '{event_name}' (id={event_id})")

            with sqlite3.connect(get_db_path()) as conn:
                c = conn.cursor()

                # count how many history rows and rating rows we will touch
                c.execute("SELECT COUNT(*) FROM glicko_history WHERE event_id = ?", (event_id,))
                hist_count = c.fetchone()[0] or 0

                c.execute("SELECT COUNT(*) FROM glicko_ratings WHERE event_id = ?", (event_id,))
                ratings_count = c.fetchone()[0] or 0

                # delete history for this event
                c.execute("DELETE FROM glicko_history WHERE event_id = ?", (event_id,))

                # reset ratings for this event (only rating and rd)
                c.execute("UPDATE glicko_ratings SET rating = 1500, rd = 350 WHERE event_id = ?", (event_id,))

                conn.commit()

            # --- Build response embed ---
            embed = discord.Embed(
                title="🧹 MMR Ratings Reset",
                color=discord.Color.orange()
            )

            # mark default event if it matches
            default_event_id = None
            try:
                default_name = get_setting("default_event")
                if default_name:
                    def_ev = get_event_by_name(default_name)
                    if def_ev:
                        default_event_id = def_ev[0]
            except Exception:
                default_event_id = None

            label = f"{event_name}"
            if default_event_id is not None and event_id == default_event_id:
                label = f"{label} (default)"

            players_text = f"{ratings_count} player(s) reset" if ratings_count else "no players"
            hist_text = f"{hist_count} history row(s) cleared" if hist_count else "no history"

            embed.description = f"Reset complete for event **{label}**.\n{players_text} — {hist_text}\n\nDefault values → `1500 ± 350`"
            embed.set_footer(text="MMR Admin Tool")

            await interaction.followup.send(embed=embed, ephemeral=True)
            logging.info(f"✅ MMR reset finished for event '{event_name}' ({ratings_count} players, {hist_count} history rows)")

        except Exception as e:
            logging.exception("❌ Failed to reset and reinitialize MMR ratings")
            await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

    @bot.tree.command(name="topmmr", description="Top players by MMR rating")
    @app_commands.describe(
        count="Number of top players",
        days="Days to consider",
        event="Event name (optional)",
        public="Publish to channel (admins only)?",
        details="Show detailed statistics?"
    )
    async def topmmr(
        interaction: Interaction,
        count: int = 10,
        days: int = 30,
        event: Optional[str] = None,
        public: bool = False,
        details: bool = False
    ):
        # 🛡️ Access check
        if public and not (isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator):
            await interaction.response.send_message("⚠️ Admin only.", ephemeral=True)
            return

        if not await check_positive(interaction, count=count, days=days):
            return

        await interaction.response.defer(thinking=True, ephemeral=not public)

        if not interaction.guild:
            await interaction.followup.send("❌ This command must be used in a server (guild).", ephemeral=True)
            return

        # 🎯 Resolve event_id
        event_id = get_event_id_by_name(event) if event else get_default_event_id()
        if not event_id:
            await interaction.followup.send(f"❌ Event `{event}` not found.", ephemeral=True)
            return

        since = datetime.now(timezone.utc) - timedelta(days=days)
        seen: set = set()
        leaderboard_data = []

        for key in get_all_players(event_id):
            if key in seen:
                continue
            seen.add(key)

            characters = get_user_characters(key) if isinstance(key, int) else [key]
            total_wins = total_losses = total_fights = 0
            glicko_values = []
            recent_days = []

            for char in characters:
                wins, losses, fights = get_fight_stats(char, since, event_id)
                total_wins += wins
                total_losses += losses
                total_fights += fights

                rating, rd, vol, _ = get_glicko_rating_extended(char, event_id)
                glicko_values.append(rating)

                last_active = get_last_active_day(char, event_id)
                if last_active:
                    days_ago = (datetime.now(timezone.utc).date() - last_active).days
                    recent_days.append(days_ago)

            # # # ⚖️ Filtering
            if total_fights < 10:
                continue
            if total_wins > 0 and total_losses == 0:
                continue

            avg_mmr = round(sum(glicko_values) / len(glicko_values)) if glicko_values else 1500
            avg_active = min(recent_days) if recent_days else 999
            winrate = (total_wins / total_fights * 100) if total_fights else 0

            if isinstance(key, int):
                member = interaction.guild.get_member(key)
                display_name = member.display_name if member else f"User {key}"
                avatar_url = member.display_avatar.url if member else None
            else:
                display_data = await resolve_display_data(key, interaction.guild)
                display_name = display_data["display_name"]
                avatar_url = display_data["avatar_url"]

            leaderboard_data.append((
                display_name, avatar_url, characters,
                avg_mmr, total_fights, total_wins, total_losses,
                winrate, avg_active
            ))

        leaderboard_data.sort(key=lambda x: (-x[3], -x[5], x[0]))

        # Get event name for display
        event_name = event if event else "arena"
        if not event:
            try:
                default_event_name = get_setting("default_event")
                if default_event_name:
                    event_name = default_event_name
            except Exception:
                pass

        # 🔹 Short output
        if not details:
            leaderboard_data = leaderboard_data[:count]
            embeds = await generate_topmmr_embeds(interaction, leaderboard_data, public=public, details=False, event_name=event_name)

            if not embeds:
                await interaction.followup.send("❌ No MMR data available.", ephemeral=not public)
                return

            if len(embeds) == 1:
                await interaction.followup.send(embed=embeds[0], ephemeral=not public)
            else:
                view = PaginatedStatsView(embeds, ephemeral=not public)
                await view.send_initial(interaction)
            return

        # 📊 Detailed output (paginate + honor count)
        leaderboard_data = leaderboard_data[:count]
        embeds = await generate_topmmr_embeds(interaction, leaderboard_data, public=public, details=True, event_name=event_name)

        if not embeds:
            await interaction.followup.send("❌ No MMR data available.", ephemeral=not public)
            return

        title = f"Top-{len(leaderboard_data)} MMR in {days} day(s) - Event: {event_name}"
        for embed in embeds:
            embed.title = title

        if len(embeds) == 1:
            await interaction.followup.send(embed=embeds[0], ephemeral=not public)
        else:
            view = PaginatedStatsView(embeds, ephemeral=not public)
            await view.send_initial(interaction)
        return

    @bot.tree.command(name="mmrroleupdate", description="🔁 Update MMR roles for users in main event (arena)")
    async def mmrroleupdate(interaction: discord.Interaction):
        # 🛡️ Checking administrator rights
        if not await require_admin(interaction):
            return

        await interaction.response.defer(thinking=True, ephemeral=True)

        # 🏰 Checking the availability of the server
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("❌ This command must be used in a server (guild).", ephemeral=True)
            return
        
        # 🎯 Get main event (arena, id=1)
        main_event_id = get_default_event_id()
        main_event_name = get_setting("default_event") or "arena"
        
        roles_config = get_all_mmr_roles()
        if not roles_config:
            await interaction.followup.send("⚠️ No MMR role thresholds configured.", ephemeral=True)
            return

        inactive_role_name = next(
            (role_name for threshold, role_name in roles_config if threshold == 0),
            "😴 Покончил с PvP"
        )
        inactive_days = 30
        inactive_cutoff = datetime.now(timezone.utc) - timedelta(days=inactive_days)

        updated = 0
        skipped = 0
        no_activity = 0
        inactive = 0

        for member in guild.members:
            if member.bot:
                continue

            characters = get_user_characters(member.id)
            if not characters:
                skipped += 1
                continue

            # 🔍 Filter characters that have activity in main event
            active_characters = []
            for char in characters:
                # Check if character has any activity (frags) in main event
                wins, losses, total_fights = get_fight_stats(char, datetime.min, main_event_id)
                if total_fights > 0:  # Character has activity in main event
                    active_characters.append(char)

            if not active_characters:
                no_activity += 1
                continue

            # 💤 Check last activity for inactivity
            last_activity_dt = None
            for char in active_characters:
                glicko_data = get_glicko_rating_extended(char, event_id=main_event_id)
                if glicko_data and glicko_data[3]:
                    try:
                        ts = datetime.fromisoformat(glicko_data[3])
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        if (last_activity_dt is None) or (ts > last_activity_dt):
                            last_activity_dt = ts
                    except Exception:
                        continue

            if (last_activity_dt is None) or (last_activity_dt < inactive_cutoff):
                # Remove all MMR roles and assign inactive role
                roles_to_remove = [
                    discord.utils.get(guild.roles, name=role_name)
                    for _, role_name in roles_config
                ]
                inactive_role = discord.utils.get(guild.roles, name=inactive_role_name)
                try:
                    await member.remove_roles(*filter(None, roles_to_remove))
                    if inactive_role and inactive_role not in member.roles:
                        await member.add_roles(inactive_role)
                    inactive += 1
                    logging.info(
                        f"💤 Marked inactive for {member.display_name}: {inactive_role_name} "
                        f"(last_activity={last_activity_dt})"
                    )
                except discord.Forbidden:
                    logging.warning(f"❌ Can't update roles for {member.display_name} (missing permissions)")
                except Exception as e:
                    logging.exception(f"⚠️ Unexpected error for {member.display_name}: {e}")
                continue

            # 📊 Get MMR ratings only for characters active in main event
            mmrs = []
            for char in active_characters:
                glicko_data = get_glicko_rating_extended(char, event_id=main_event_id)
                if glicko_data and glicko_data[0] is not None:
                    mmrs.append(glicko_data[0])

            if not mmrs:
                skipped += 1
                continue

            avg_mmr = sum(mmrs) / len(mmrs)

            # 🎯 Find suitable role
            roles_sorted = sorted(roles_config, key=lambda x: x[0], reverse=True)
            new_role_name = next(
                (role_name for threshold, role_name in roles_sorted if avg_mmr >= threshold),
                None
            )

            if not new_role_name:
                continue  # No matching role

            discord_role = discord.utils.get(guild.roles, name=new_role_name)
            if not discord_role:
                continue

            # 🧼 Remove old MMR roles and assign new one
            roles_to_remove = [
                discord.utils.get(guild.roles, name=role_name)
                for _, role_name in roles_config
                if role_name != new_role_name
            ]

            try:
                await member.remove_roles(*filter(None, roles_to_remove))
                if discord_role not in member.roles:
                    await member.add_roles(discord_role)
                updated += 1
                logging.info(f"✅ Updated MMR role for {member.display_name}: {new_role_name} (avg MMR: {avg_mmr:.1f})")
            except discord.Forbidden:
                logging.warning(f"❌ Can't update roles for {member.display_name} (missing permissions)")
            except Exception as e:
                logging.exception(f"⚠️ Unexpected error for {member.display_name}: {e}")

        # 📊 Build response
        embed = discord.Embed(
            title="🔁 MMR Roles Update Complete",
            color=discord.Color.green()
        )
        
        embed.description = (
            f"**Event:** {main_event_name} (id={main_event_id})\n\n"
            f"✅ **Updated:** {updated} users\n"
            f"💤 **Inactive:** {inactive} users (no activity {inactive_days}+ days)\n"
            f"⏭️ **Skipped:** {skipped} users (no MMR data)\n"
            f"🚫 **No activity:** {no_activity} users (not active in main event)\n\n"
            f"Only users with activity in main event received roles."
        )
        
        embed.set_footer(text="MMR Role Management")
        await interaction.followup.send(embed=embed, ephemeral=True)

# --- Events ---

    @bot.tree.command(name="createevent", description="Create a new event")
    @app_commands.describe(name="Event name", description="Event description (optional)")
    async def createevent(interaction: discord.Interaction, name: str, description: Optional[str] = None):
        if not await require_admin(interaction):
            return
        try:
            event_id = create_event(name, description or "")
            await interaction.response.send_message(
                f"✅ Event **{name}** created (ID: `{event_id}`)", ephemeral=True
            )
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
        except Exception as e:
            logging.exception("❌ Unexpected error in /createevent")
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

    @bot.tree.command(name="setchannel", description="Link a channel to an event")
    @app_commands.describe(event="Event name", channel="Channel")
    async def setchannel(interaction: discord.Interaction, event: str, channel: discord.TextChannel):
        if not await require_admin(interaction):
            return
        try:
            set_event_channel(event, channel.id)
            await interaction.response.send_message(
                f"✅ The channel {channel.mention} is linked to the event **{event}**.",
                ephemeral=True
            )
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
        except Exception as e:
            logging.exception("❌ Unexpected error in /setchannel")
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

    @bot.tree.command(name="clearchannel", description="Release the channel from the event")
    @app_commands.describe(event="Event name")
    async def clearchannel(interaction: discord.Interaction, event: str):
        if not await require_admin(interaction):
            return

        cleared = clear_event_channels(event)
        if cleared:
            await interaction.response.send_message(
                f"✅ All channels of the event **{event}** are released.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"⚠️ The event **{event}** had no fixed channels.", ephemeral=True
            )

    @bot.tree.command(name="listevents", description="List all events")
    async def listevents(interaction: discord.Interaction):
        if not await require_admin(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
            return

        events = list_events()
        if not events:
            await interaction.response.send_message("❌ No events found.", ephemeral=True)
            return

        embed = discord.Embed(title="📅 Events", color=discord.Color.blue())

        for name, desc, channel_id, is_default in events:
            if channel_id:
                channel = interaction.guild.get_channel(channel_id)
                if channel:
                    channel_display = f"✅ {name}{' (default)' if is_default else ''}: {channel.mention}"
                else:
                    channel_display = f"❌ {name}{' (default)' if is_default else ''}: channel not found!"
            else:
                channel_display = f"❌ {name}{' (default)' if is_default else ''}: channel is not set!"

            embed.add_field(
                name=channel_display,
                value=desc or "—",
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

# --- Help ---

    @bot.tree.command(name="helpme", description="Show list of available commands")
    async def helpme(interaction: discord.Interaction):
        embed = discord.Embed(
            title="📖 Bot Command Help",
            description="Use slash commands to manage PvP stats, MMR, killstreaks, events and roles.",
            color=discord.Color.purple(),
            timestamp=datetime.now(timezone.utc)
        )

        # Show admin commands only if member and has permission
        if isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator:
            # ⚙️ Admin Commands (1/4: Events & Channels)
            embed.add_field(
                name="__⚙️ Admin Commands (1/4: Events & Channels)__",
                value=(
                    "📅 `/listevents` — Show all events and their channels\n"
                    "🆕 `/createevent` `[name]` `[desc]` — Create new event\n"
                    "📌 `/setchannel` `[event]` `[channel]` — Bind channel to event\n"
                    "❌ `/clearchannel` `[event]` — Unbind channel from event"
                ),
                inline=False
            )
            # 🧰 Admin Commands (2/4: Core Settings)
            embed.add_field(
                name="__🧰 Admin Commands (2/4: Core Settings)__",
                value=(
                    "🔗 `/link` `[character]` `[@user]` — Link character to user\n"
                    "❌ `/unlink` `[character]` — Unlink character\n"
                    "🔊 `/voice` `[leave]` — Join or leave voice channel\n"
                    "⏳ `/killstreaktimeout` `[seconds]` — Set killstreak timeout\n"
                    "🔁 `/reset` `[filename]` — Reset or restore database"
                ),
                inline=False
            )
            # 📊 Admin Commands (3/4: MMR)
            embed.add_field(
                name="__📊 Admin Commands (3/4: MMR)__",
                value=(
                    "🏅 `/mmrroleset` `[rating]` `[role]` — Set MMR role threshold\n"
                    "🧹 `/mmrroleclear` — Clear all MMR roles\n"
                    "🔄 `/mmrroleupdate` — Update all MMR-based roles\n"
                    "🎯 `/mmr` `[char/@user]` `[+/-/=value]` `[reason]` `[event]` — Adjust rating\n"
                    "📃 `/mmrlog` `[char/@user]` `[event]` — Show rating history\n"
                    "🧹 `/mmrclear` `[event]` — Reset MMR to defaults\n"
                    "🔁 `/mmrsync` `[event]` `[start_date]` — Rebuild MMR from frags (start_date optional)"
                ),
                inline=False
            )
            # 🧮 Admin Commands (4/4: Points & Roles)
            embed.add_field(
                name="__🧮 Admin Commands (4/4: Points & Roles)__",
                value=(
                    "🥇 `/roleset` `[wins]` `[role]` — Set rank role threshold\n"
                    "🧹 `/roleclear` — Clear all rank roles\n"
                    "👑 `/roleupdate` — Update all rank roles\n"
                    "🧮 `/points` `[char/@user]` `[±value]` `[reason]` `[event]` — Adjust player points\n"
                    "📜 `/pointlog` `[char/@user]` `[event]` — Show adjustment history"
                ),
                inline=False
            )


        # 👥 User Commands (always shown)
        embed.add_field(
            name="__👥 User Commands__",
            value=(
                "📈 `/topmmr` `[count]` `[days]` `[event]` `[public*]` `[details]` — Show top by MMR\n"
                "🏆 `/top` `[count]` `[days]` `[event]` `[public*]` — Show top by points\n"
                "🧍 `/mystats` `[days]` `[event]` `[public*]` — Show your stats\n"
                "📊 `/stats` `[char/@user]` `[days]` `[event]` `[public*]` — Show player stats\n"
                "🔍 `/whois` `[char/@user]` — Show who owns character\n"
                "🎭 `/mmrroles` `[public*]` — Show MMR role configuration\n"
                "🏅 `/roles` `[public*]` — Show rank roles configuration\n"
                "❓ `/helpme` — Show this help message\n\n"
                "`[public*]` - only available to admins"
            ),
            inline=False
        )

        embed.set_footer(text=f"Bot version {BOT_VERSION}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

