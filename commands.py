# -*- coding: utf-8 -*-
# commands.py

import os
import re
import sqlite3
import asyncio
import discord
import logging

from operator import itemgetter
from datetime import datetime, timedelta
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
        character = character.lower()
        set_character_owner(character, user.id)
        await interaction.response.send_message(f"✅ The character **{character}** is linked to {user.mention}.", ephemeral=True)

    @bot.tree.command(name="unlink", description="Remove the connection between the character and the user")
    @app_commands.describe(character="Character's name")
    async def unlink(interaction: Interaction, character: str):
        if not await require_admin(interaction):
            return
        character = character.lower()
        removed = remove_character_owner(character)
        if removed:
            await interaction.response.send_message(f"🔗 Connection to the character **{character}** has been deleted.", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ The character **{character}** was not attached.", ephemeral=True)

    @bot.tree.command(name="roleset", description="Set a rank role for a win threshold")
    @describe(wins="Minimum number of wins for the role", role="Discord role to assign")
    async def roleset(interaction: Interaction, wins: int, role: discord.Role):
        if not await require_admin(interaction):
            return
        if wins < 0:
            await interaction.response.send_message("❗ Wins must be >= 0.", ephemeral=True)
            return
        set_rank_role(wins, role.name)
        await interaction.response.send_message(f"✅ Rank **{role.name}** set for `{wins}`+ wins.", ephemeral=True)

    @bot.tree.command(name="roleupdate", description="Force role update for all members")
    async def roleupdate(interaction: discord.Interaction):

        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⚠️ Admin only", ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=True)  # <- an important fix
        await update_roles_for_all_members(interaction.client)
        await interaction.followup.send("✅ Roles updated.")

    @bot.tree.command(name="roleclear", description="Clear all configured rank roles")
    async def roleclear(interaction: Interaction):
        if not await require_admin(interaction):
            return
        clear_rank_roles()
        await interaction.response.send_message("🗑️ All rank roles have been cleared.", ephemeral=True)

    @bot.tree.command(name="points", description="Admin: manual control of players' points")
    @app_commands.describe(
        target="Character or @user",
        amount="Number of points to add (or subtract)",
        reason="Optional reason",
        event="Event name (optional)"
    )
    async def points(interaction: Interaction, target: str, amount: int, reason: str = "Manual adjustment", event: Optional[str] = None):
        
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⚠️ Admin only", ephemeral=True)
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
        for character in characters:
            adjust_wins(character, amount, reason, event_id=event_id)

        # ✅ Response
        char_list = "\n".join(f"- `{char}`" for char in characters)
        
        embed = discord.Embed(
            title="✅ Manual Points Adjustment",
            color=discord.Color.orange(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Characters", value=char_list, inline=False)
        embed.add_field(name="Amount", value=f"`{amount:+}`", inline=True)
        embed.add_field(name="Reason", value=reason or "—", inline=True)
        embed.set_footer(text=f"Changed by {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)

        await interaction.followup.send(embed=embed, ephemeral=True)

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
            timestamp=datetime.utcnow()
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
            voice_client = interaction.guild.voice_client
            if isinstance(voice_client, discord.VoiceClient) and voice_client.is_connected():
                await voice_client.disconnect(force=True)
                await interaction.followup.send("🔌 Disconnected from voice channel.")
            else:
                await interaction.followup.send("ℹ️ I'm not connected to a voice channel.")
            return

        # 🔊 Connect
        voice_state = getattr(interaction.user, "voice", None)
        channel = getattr(voice_state, "channel", None)

        if not channel:
            await interaction.followup.send("⚠️ You must be in a voice channel.")
            return

        await channel.connect()
        await interaction.followup.send(f"🔈 Connected to **{channel.name}**")

        # 🎵 Start playback tasks
        asyncio.create_task(audio_queue_worker(bot, interaction.guild))
        asyncio.create_task(start_heartbeat_loop(bot, interaction.guild))

    # /style command removed (styles are fixed)

    @bot.tree.command(name="reset", description="Reset the database or restore from backup")
    @app_commands.describe(backup="Name of the backup file to restore (optional)")
    async def reset(interaction: Interaction, backup: Optional[str] = None):
        if not await require_admin(interaction):
            return
        os.makedirs(BACKUP_DIR, exist_ok=True)
        if backup is None:
            # Normal reset
            db_path = get_db_file_path()
            backup_file = os.path.join(BACKUP_DIR, f"frags_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.db")
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

# --- User Commands ---

    @bot.tree.command(name="top", description="Top players by total points (frags + adjustments)")
    @app_commands.describe(count="Number of top players", days="Days", event="Event name", public="Publish?")
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

        since = datetime.utcnow() - timedelta(days=days)
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

        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        author_text = f"🏆 Top-{count} in {days} day(s) ({event or 'default'})"
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
    @app_commands.describe(days="Days", event="Event name", public="Publish?")
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
        since = datetime.utcnow() - timedelta(days=days)
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
        event="Event name",
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
        since = datetime.utcnow() - timedelta(days=days)
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
            await interaction.response.send_message("ℹ️ No rank roles are currently configured.", ephemeral=not public)
            return

        embed = discord.Embed(
            title="🏆 Rank Role Configuration",
            description="Custom PvP roles by weekly win count:",
            color=discord.Color.green()
        )
        for wins, role_name in ranks:
            embed.add_field(name=role_name, value=f"{wins}+", inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=not public)
    
# --- MMR ---        
            
    @bot.tree.command(name="mmr", description="Admin: manually adjust Glicko-2 rating for character(s) or user")
    @app_commands.describe(
        target="Character name or @user",
        value="Rating value: +50, -30, or =1500",
        reason="Optional reason for the change",
        event="Event name (optional)"
    )
    async def mmr(interaction: Interaction, target: str, value: str, reason: str = "Manual Glicko adjustment", event: Optional[str] = None):
        
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⚠️ Admin only", ephemeral=True)
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
            rating, rd, vol = get_glicko_rating(character)

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

        # 📦 Embed
        embed = discord.Embed(
            title="🔧 Glicko-2 Adjustment",
            color=discord.Color.orange(),
            timestamp=datetime.utcnow()
        )
        for char, old, new, d in changed:
            embed.add_field(name=char, value=f"{old:.1f} → {new:.1f} ({d:+.1f})", inline=False)

        embed.add_field(name="Reason", value=reason or "—", inline=False)
        embed.set_footer(text=f"Changed by {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @bot.tree.command(name="mmrlog", description="Show Glicko-2 rating adjustment history for a character or user")
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
            await interaction.followup.send("ℹ️ No Glicko-2 rating adjustments found.", ephemeral=True)
            return

        embed = discord.Embed(
            title="📜 Glicko-2 Adjustment Log",
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow()
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

    @bot.tree.command(name="mmrroleset", description="Set a Glicko-2 role for a threshold")
    @app_commands.describe(threshold="Minimum Glicko rating", role="Discord role")
    async def mmrroleset(interaction: Interaction, threshold: int, role: discord.Role):
        if not await require_admin(interaction):
            return
        if threshold < 0:
            await interaction.response.send_message("❗ Rating must be >= 0.", ephemeral=True)
            return
        set_mmr_role(threshold, role.name)
        await interaction.response.send_message(f"✅ Role **{role.name}** set for `{threshold}+` Glicko rating.", ephemeral=True)

    @bot.tree.command(name="mmrroles", description="Show current Glicko-2 role configuration")
    async def mmrroles(interaction: Interaction):
        if not await require_admin(interaction):
            return
        roles = get_all_mmr_roles()
        if not roles:
            await interaction.response.send_message("ℹ️ No Glicko roles configured.", ephemeral=True)
            return
        embed = discord.Embed(
            title="🏅 Glicko-2 Roles",
            description="Roles based on current player rating:",
            color=discord.Color.dark_gold()
        )
        for threshold, role_name in roles:
            embed.add_field(name=f"{role_name}", value=f"Rating: `{threshold}+`", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(name="mmrroleclear", description="Clear all Glicko-2 role settings")
    async def mmrroleclear(interaction: Interaction):
        if not await require_admin(interaction):
            return
        clear_mmr_roles()
        await interaction.response.send_message("🧹 All Glicko role settings have been cleared.", ephemeral=True)

    @bot.tree.command(name="mmrsync", description="🔁 Rebuild all Glicko-2 MMR from frags table")
    @app_commands.describe(event="Optional event name to rebuild (otherwise rebuild all events)")
    async def mmrsync(interaction: Interaction, event: Optional[str] = None):

        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⚠️ Admin only", ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=True)

        try:
            # 🗂️ Defining the list of events to process
            if event:
                ev = get_event_by_name(event)
                if not ev:
                    await interaction.followup.send(f"❌ Event '{event}' not found.", ephemeral=True)
                    return
                events_to_process = [ev]  # [(id, name, ...)]
            else:
                events_to_process = list_events()  # [(id, name, ...)]

            if not events_to_process:
                await interaction.followup.send("❌ No events found.", ephemeral=True)
                return

            for ev in events_to_process:
                event_id, event_name, *_ = ev
                logging.info(f"🔄 Rebuilding MMR for event '{event_name}' (id={event_id})")

                # 🧹 Clearing old data only for this event
                with sqlite3.connect(get_db_path()) as conn:
                    conn.execute("DELETE FROM glicko_ratings WHERE event_id = ?", (event_id,))
                    conn.commit()

                # 📖 We read all the frags on the event
                with sqlite3.connect(get_db_path()) as conn:
                    c = conn.cursor()
                    c.execute("""
                        SELECT killer, victim, timestamp 
                        FROM frags 
                        WHERE event_id = ? 
                        ORDER BY timestamp ASC
                    """, (event_id,))
                    rows = c.fetchall()

                if not rows:
                    logging.info(f"ℹ️ No frags found for event '{event_name}'")
                    continue

                # 🎯 Grouping the fights by day
                battles_by_day = defaultdict(list)
                all_dates = []

                for killer, victim, ts in rows:
                    day = datetime.fromisoformat(ts).date()
                    battles_by_day[day].append((killer.lower(), victim.lower()))
                    all_dates.append(day)

                start_date = min(all_dates)
                end_date = max(all_dates)
                all_players = {}

                # 🚀 Recalculating day by day
                current_date = start_date
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

                logging.info(f"✅ Glicko-2 sync finished for event '{event_name}'")

            await interaction.followup.send("✅ Glicko-2 MMR sync complete!", ephemeral=True)

        except Exception as e:
            logging.exception("❌ Failed to run Glicko MMR sync")
            await interaction.followup.send("❌ Failed to run MMR sync.", ephemeral=True)

    @bot.tree.command(name="mmrclear", description="🧹 Reset Glicko-2 ratings to default values")
    @app_commands.describe(event="Optional event name (reset only for this event)")
    async def mmrclear(interaction: Interaction, event: Optional[str] = None):

        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⚠️ Admin only", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            # --- Resolve events to process ---
            events_to_process = []

            if event:
                ev = get_event_by_name(event)
                if not ev:
                    await interaction.followup.send(f"❌ Event `{event}` not found.", ephemeral=True)
                    return
                events_to_process = [ev]  # [(id, name, ...)]
            else:
                events_to_process = list_events()  # [(id, name, description), ...] or []

            # --- If there are no registered events at all, do a safe global fallback ---
            global_fallback = False
            if not events_to_process:
                # If no rows in events, but DB has ratings/history, do global reset
                with sqlite3.connect(get_db_path()) as conn:
                    c = conn.cursor()
                    c.execute("SELECT COUNT(*) FROM glicko_ratings")
                    total_ratings = c.fetchone()[0] or 0
                    c.execute("SELECT COUNT(*) FROM glicko_history")
                    total_history = c.fetchone()[0] or 0

                if total_ratings == 0 and total_history == 0:
                    await interaction.followup.send("❌ No events and no rating/history data found.", ephemeral=True)
                    return

                global_fallback = True

            results = []  # list of (event_name, event_id, players_reset, history_cleared)

            with sqlite3.connect(get_db_path()) as conn:
                c = conn.cursor()

                if global_fallback:
                    # Global: clear all history and reset all ratings
                    # count rows first for reporting
                    c.execute("SELECT COUNT(*) FROM glicko_history")
                    hist_count = c.fetchone()[0] or 0
                    c.execute("SELECT COUNT(*) FROM glicko_ratings")
                    ratings_count = c.fetchone()[0] or 0

                    c.execute("DELETE FROM glicko_history")
                    c.execute("UPDATE glicko_ratings SET rating = 1500, rd = 350")

                    conn.commit()
                    results.append(("ALL_EVENTS_GLOBAL", None, ratings_count, hist_count))

                else:
                    # Process each event separately
                    for ev in events_to_process:
                        # ev expected like (id, name, description) or (id, name, ...)
                        event_id = ev[0]
                        event_name = ev[1] if len(ev) > 1 else str(event_id)

                        # count how many history rows and rating rows we will touch
                        c.execute("SELECT COUNT(*) FROM glicko_history WHERE event_id = ?", (event_id,))
                        hist_count = c.fetchone()[0] or 0

                        c.execute("SELECT COUNT(*) FROM glicko_ratings WHERE event_id = ?", (event_id,))
                        ratings_count = c.fetchone()[0] or 0

                        # delete history for this event
                        c.execute("DELETE FROM glicko_history WHERE event_id = ?", (event_id,))

                        # reset ratings for this event (only rating and rd)
                        c.execute("UPDATE glicko_ratings SET rating = 1500, rd = 350 WHERE event_id = ?", (event_id,))

                        results.append((event_name, event_id, ratings_count, hist_count))

                    conn.commit()

            # --- Build response embed with details ---
            embed = discord.Embed(
                title="🧹 Glicko-2 Ratings Reset",
                color=discord.Color.orange()
            )

            if global_fallback:
                # single-line summary
                _, _, ratings_count, hist_count = results[0]
                embed.description = (
                    f"Global reset applied.\n\n"
                    f"Ratings reset: **{ratings_count}** records\n"
                    f"History cleared: **{hist_count}** records\n\n"
                    f"Default values → `1500 ± 350`"
                )
            else:
                total_players = sum(r for _, _, r, _ in results)
                total_hist = sum(h for _, _, _, h in results)
                embed.description = f"Reset complete for **{len(results)}** event(s).\nTotal players updated: **{total_players}**\nTotal history rows removed: **{total_hist}**\n\nDefault values → `1500 ± 350`"

                for name, eid, num_players, num_hist in results:
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

                    label = f"{name}"
                    if eid is not None and default_event_id is not None and eid == default_event_id:
                        label = f"{label} (default)"

                    players_text = f"{num_players} player(s) reset" if num_players else "no players"
                    hist_text = f"{num_hist} history row(s) cleared" if num_hist else "no history"

                    embed.add_field(name=f"✅ {label}", value=f"{players_text} — {hist_text}", inline=False)

            embed.set_footer(text="Glicko-2 Admin Tool")

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logging.exception("❌ Failed to reset and reinitialize Glicko-2 ratings")
            await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

    @bot.tree.command(name="topmmr", description="Top players by Glicko-2 rating")
    @app_commands.describe(
        count="Number of top players",
        days="Days to consider",
        event="Event name",
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

        since = datetime.utcnow() - timedelta(days=days)
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
                    days_ago = (datetime.utcnow().date() - last_active).days
                    recent_days.append(days_ago)

            # # ⚖️ Filtering
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

        # 🔹 Short output
        if not details:
            leaderboard_data = leaderboard_data[:count]
            embeds = await generate_topmmr_embeds(interaction, leaderboard_data, public=public, details=False)

            if not embeds:
                await interaction.followup.send("❌ No MMR data available.", ephemeral=not public)
                return

            if len(embeds) == 1:
                await interaction.followup.send(embed=embeds[0], ephemeral=not public)
            else:
                view = PaginatedStatsView(embeds, ephemeral=not public)
                await view.send_initial(interaction)
            return

        # 📊 Detailed output
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        embed = discord.Embed(
            title=f"Top-{count} MMR in {days} day(s) ({event or 'default'})",
            color=discord.Color.gold()
        )
        if leaderboard_data and leaderboard_data[0][1]:
            embed.set_thumbnail(url=leaderboard_data[0][1])

        for i, (name, avatar_url, chars, mmr, fights, wins, losses, winrate, recent_days) in enumerate(leaderboard_data, start=1):
            medal = medals.get(i, "")
            char_text = ", ".join(chars)
            winlos = f"{wins}/{losses}"
            winrate_str = f"{winrate:.1f}%"

            if recent_days <= 3:
                activity = f"🟢 `{recent_days}d ago`"
            elif recent_days <= 7:
                activity = f"🟡 `{recent_days}d ago`"
            else:
                activity = f"🔴 `{recent_days}d ago`"

            value = (
                f"Characters: `{char_text}`\n"
                f"MMR: `{mmr}`\n"
                f"Fights: `{fights}`\n"
                f"Win/Los: `{winlos}`\n"
                f"Winrate: `{winrate_str}`\n"
                f"{activity}"
            )

            embed.add_field(
                name=f"**{i}. {medal} {name.upper()}**",
                value=value,
                inline=False
            )

        await interaction.followup.send(embed=embed, ephemeral=not public)

    @bot.tree.command(name="mmrroleupdate", description="🔁 Update Glicko-based roles for all users")
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
        
        # 🧠 Ensure MMR is fresh
        recalculate_glicko_recent(30)

        roles_config = get_all_mmr_roles()
        if not roles_config:
            await interaction.followup.send("⚠️ No MMR role thresholds configured.", ephemeral=True)
            return

        updated = 0
        skipped = 0

        for member in guild.members:
            if member.bot:
                continue

            characters = get_user_characters(member.id)
            if not characters:
                skipped += 1
                continue

            mmrs = []
            for char in characters:
                glicko = get_glicko_rating(char)
                if glicko:
                    mmrs.append(glicko[0])

            if not mmrs:
                skipped += 1
                continue

            avg_mmr = sum(mmrs) / len(mmrs)

            # 🎯 We'll find a suitable role
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

            # 🧼 Delete the old MMR roles and assign a new one
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
            except discord.Forbidden:
                logging.warning(f"❌ Can't update roles for {member.display_name} (missing permissions)")
            except Exception as e:
                logging.exception(f"⚠️ Unexpected error for {member.display_name}: {e}")

        await interaction.followup.send(
            f"✅ MMR roles updated.\n🧍 Processed: {updated} users\n⏭️ Skipped: {skipped} (no characters or MMR)",
            ephemeral=True
        )

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

    @bot.tree.command(name="setchannel", description="Link a channel to an event (both track & announce)")
    @app_commands.describe(event="Event name", channel="Channel")
    async def setchannel(interaction: discord.Interaction, event: str, channel: discord.TextChannel):
        if not await require_admin(interaction):
            return
        try:
            set_event_channel(event, channel.id)
            await interaction.response.send_message(
                f"✅ The channel {channel.mention} is linked to the event **{event}** as `track+announcement`.",
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
            timestamp=datetime.utcnow()
        )

        # Show admin commands only if member and has permission
        if isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator:
            # ⚙️ Admin Commands (1/4: Events & Channels)
            embed.add_field(
                name="__⚙️ Admin Commands (1/4: Events & Channels)__",
                value=(
                    "🆕 `/createevent` `[name]` `[desc]` — Create new event\n"
                    "📌 `/setchannel` `[event]` `[channel]` — Bind channel to event\n"
                    "❌ `/clearchannel` `[event]` — Unbind channel from event\n"
                    "📅 `/listevents` — Show all events and their channels"
                ),
                inline=False
            )
            # 🧰 Admin Commands (2/4: Core Settings)
            embed.add_field(
                name="__🧰 Admin Commands (2/4: Core Settings)__",
                value=(
                    "⏳ `/killstreaktimeout` `[seconds]` — Set killstreak timeout\n"
                    "🔗 `/link` `[character]` `[@user]` — Link character to user\n"
                    "❌ `/unlink` `[character]` — Unlink character\n"
                    "🔊 `/voice` `[leave]` — Join or leave voice channel\n"
                    "🔁 `/reset` `[filename]` — Reset or restore database"
                ),
                inline=False
            )
            # 🧮 Admin Commands (3/4: Points & Roles)
            embed.add_field(
                name="__🧮 Admin Commands (3/4: Points & Roles)__",
                value=(
                    "🧮 `/points` `[char/@user]` `[±value]` `[reason]` — Adjust player points\n"
                    "📜 `/pointlog` `[char/@user]` `[event]` — Show adjustment history\n"
                    "👑 `/roleupdate` — Update all rank roles\n"
                    "🥇 `/roleset` `[wins]` `[role]` — Set rank role threshold\n"
                    "🧹 `/roleclear` — Clear all rank roles"
                ),
                inline=False
            )
            # 📊 Admin Commands (4/4: MMR)
            embed.add_field(
                name="__📊 Admin Commands (4/4: MMR)__",
                value=(
                    "🎯 `/mmr` `[char/@user]` `[+/-/=value]` `[reason]` `[event]` — Adjust rating\n"
                    "📃 `/mmrlog` `[char/@user]` `[event]` — Show rating history\n"
                    "🔁 `/mmrsync` `[event]` — Rebuild MMR from frags\n"
                    "🧹 `/mmrclear` `[event]` — Reset MMR to defaults\n"
                    "🏅 `/mmrroleset` `[rating]` `[role]` — Set MMR role threshold\n"
                    "🎭 `/mmrroles` — Show MMR role config\n"
                    "🧹 `/mmrroleclear` — Clear all MMR roles\n"
                    "🔄 `/mmrroleupdate` — Update all MMR-based roles"
                ),
                inline=False
            )

        # 👥 User Commands (always shown)
        embed.add_field(
            name="__👥 User Commands__",
            value=(
                "🏆 `/top` `[count]` `[days]` `[event]` `[public*]` — Show top by points\n"
                "📈 `/topmmr` `[count]` `[days]` `[event]` `[public*]` `[details]` — Show top by MMR\n"
                "🧍 `/mystats` `[days]` `[event]` `[public*]` — Show your stats\n"
                "📊 `/stats` `[char/@user]` `[days]` `[event]` `[public*]` — Show player stats\n"
                "🔍 `/whois` `[char/@user]` — Show who owns character\n"
                "🏅 `/roles` — Show current rank roles\n"
                "❓ `/helpme` — Show this help message\n\n"
                "`[public*]` → only available to admins"
            ),
            inline=False
        )

        embed.set_footer(text=f"Bot version {BOT_VERSION}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

