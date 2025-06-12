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

from discord import app_commands, Interaction
from discord.app_commands import describe
from discord.ext import commands


from settings import *
from db import *
from roles import *
from announcer import *
from utils import *
from glicko2 import Player



# --- Admin commands ---

def setup_commands(bot: commands.Bot):

    @bot.tree.command(name="track", description="Show or set the tracking channel")
    @app_commands.describe(channel="Channel")
    async def track(interaction: Interaction, channel: discord.TextChannel = None):
        if not await require_admin(interaction):
            return
        if channel:
            set_setting("tracking_channel_id", str(channel.id))
            await interaction.response.send_message(f"✅ Tracking channel set to {channel.mention}.", ephemeral=True)
        else:
            cid = get_tracking_channel_id()
            if cid:
                chan = interaction.guild.get_channel(cid)
                if chan:
                    await interaction.response.send_message(f"✅ Current tracking channel: {chan.mention}", ephemeral=True)
                else:
                    await interaction.response.send_message("❗ Tracking channel not found.", ephemeral=True)
            else:
                await interaction.response.send_message("⚠️ Tracking channel is not set.", ephemeral=True)


    @bot.tree.command(name="announce", description="Show or set the announce channel")
    @app_commands.describe(channel="Channel")
    async def announce(interaction: Interaction, channel: discord.TextChannel = None):
        if not await require_admin(interaction):
            return
        if channel:
            set_setting("announce_channel_id", str(channel.id))
            await interaction.response.send_message(f"✅ Announce channel set to {channel.mention}.", ephemeral=True)
        else:
            cid = get_announce_channel_id()
            if cid:
                chan = interaction.guild.get_channel(cid)
                if chan:
                    await interaction.response.send_message(f"✅ Current announce channel: {chan.mention}", ephemeral=True)
                else:
                    await interaction.response.send_message("❗ Announce channel not found.", ephemeral=True)
            else:
                await interaction.response.send_message("⚠️ Announce channel is not set.", ephemeral=True)


    @bot.tree.command(name="killstreaktimeout", description="Show or set the killstreak timeout (in seconds)")
    @app_commands.describe(seconds="New timeout value in seconds")
    async def killstreaktimeout(interaction: Interaction, seconds: int = None):
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
    async def roleet(interaction: Interaction, wins: int, role: discord.Role):
        if not await require_admin(interaction):
            return
        if wins < 0:
            await interaction.response.send_message("❗ Wins must be >= 0.", ephemeral=True)
            return
        set_rank_role(wins, role.name)
        await interaction.response.send_message(f"✅ Rank **{role.name}** set for `{wins}`+ wins.", ephemeral=True)


    @bot.tree.command(name="roleupdate", description="Force role update for all members")
    async def roleupdate(interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⚠️ Admin only", ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)  # <- an important fix
        await update_roles_for_all_members(interaction.client)
        await interaction.followup.send("✅ Roles updated.")


    @bot.tree.command(name="roleclear", description="Clear all configured rank roles")
    async def rankclear(interaction: Interaction):
        if not await require_admin(interaction):
            return
        clear_rank_roles()
        await interaction.response.send_message("🗑️ All rank roles have been cleared.", ephemeral=True)


    @bot.tree.command(name="autoroles", description="Enable or disable automatic role assignment")
    @app_commands.describe(enabled="Enable or disable (true/false)")
    async def autoroles(interaction: Interaction, enabled: bool):
        if not await require_admin(interaction):
            return
        set_auto_role_update_enabled(enabled)
        status = "enabled" if enabled else "disabled"
        await interaction.response.send_message(f"✅ Auto-role assignment **{status}**.", ephemeral=True)


    @bot.tree.command(name="autorolestatus", description="Show the current auto-role update setting")
    async def autorolestatus(interaction: Interaction):
        if not await require_admin(interaction):
            return
        enabled = is_auto_role_update_enabled()
        days = get_auto_role_update_days()
        status = "✅ Enabled" if enabled else "❌ Disabled"
        await interaction.response.send_message(f"{status}\nInterval: `{days}` day(s)", ephemeral=True)


    @bot.tree.command(name="autoroletimeout", description="Set the time window for auto-role updates")
    @app_commands.describe(days="Number of days to consider")
    async def autoroletimeout(interaction: Interaction, days: int):
        if not await require_admin(interaction):
            return
        if days < 1:
            await interaction.response.send_message("❗ Days must be at least 1.", ephemeral=True)
            return
        set_auto_role_update_days(days)
        await interaction.response.send_message(f"✅ Auto-update interval set to `{days}` day(s).", ephemeral=True)


    @bot.tree.command(name="points", description="Admin: manual control of players' points")
    @app_commands.describe(
        target="Character or @user",
        amount="Number of points to add (or subtract)",
        reason="Optional reason"
    )
    async def points(interaction: Interaction, target: str, amount: int, reason: str = "Manual adjustment"):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⚠️ Admins only.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

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
            adjust_wins(character, amount, reason)

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
    @app_commands.describe(target="Character name or @user")
    async def pointlog(interaction: Interaction, target: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⚠️ Admins only.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

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
        with sqlite3.connect(get_db_file_path()) as conn:
            c = conn.cursor()
            placeholders = ",".join("?" for _ in characters)
            query = f"""
                SELECT character, adjustment, reason, timestamp
                FROM manual_adjustments
                WHERE character IN ({placeholders})
                ORDER BY timestamp DESC
                LIMIT 20
            """
            c.execute(query, characters)
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
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⚠️ Admin only", ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True) 
        if leave:
            if interaction.guild.voice_client:
                await interaction.guild.voice_client.disconnect()
                await interaction.followup.send("Disconnected from voice channel.")
            else:
                await interaction.followup.send("I'm not connected to a voice channel.")
        else:
            if interaction.user.voice is None:
                await interaction.followup.send("⚠️ You must be in a voice channel.")
                return
            channel = interaction.user.voice.channel
            await channel.connect()
            await interaction.followup.send(f"Connected to {channel.name}")
            asyncio.create_task(audio_queue_worker(bot, interaction.guild))
            asyncio.create_task(start_heartbeat_loop(bot, interaction.guild))


    @bot.tree.command(name="style", description="Show or set the killstreak announce style")
    @app_commands.describe(style="Style name (classic, epic, tournament)")
    async def style(interaction: Interaction, style: str = None):
        if not await require_admin(interaction):
            return
        available_styles = list(KILLSTREAK_STYLES.keys())
        if style:
            style = style.lower()
            if style not in available_styles:
                await interaction.response.send_message(
                    f"Invalid style. Available: {', '.join(available_styles)}",
                    ephemeral=True
                )
                return
            set_announce_style(style)
            await interaction.response.send_message(f"✅ Announce style set to **{style}**.", ephemeral=True)
        else:
            current_style = get_announce_style()
            await interaction.response.send_message(f"✅ Current announce style is **{current_style}**.", ephemeral=True)


    @bot.tree.command(name="reset", description="Reset the database or restore from backup")
    @app_commands.describe(backup="Name of the backup file to restore (optional)")
    async def reset(interaction: Interaction, backup: str = None):
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
    @app_commands.describe(count="Number of top players", days="Days", public="Publish?")
    async def top(interaction: Interaction, count: int = 10, days: int = 1, public: bool = False):
        if not await check_positive(interaction, count=count, days=days):
            return
        if public and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⚠️ Admin only", ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=not public)

        # Collect all the killers for the period
        since = datetime.utcnow() - timedelta(days=days)
        with sqlite3.connect(get_db_path()) as conn:
            c = conn.cursor()
            c.execute("""
                SELECT killer, COUNT(*) as count FROM frags
                WHERE timestamp >= ?
                GROUP BY killer
            """, (since,))
            raw_stats = c.fetchall()
                
        # Collecting frags and manual adjustments based on Discord ID or character name
        user_points = {}

        for character, frags in raw_stats:
            manual, _ = get_win_sources(character)
            total = frags + manual
            discord_id = get_character_owner(character)

            key = discord_id if discord_id else character  # Use the user_id if available, otherwise the character's name

            if key not in user_points:
                user_points[key] = {"characters": set(), "frags": 0, "manual": 0}

            user_points[key]["characters"].add(character)
            user_points[key]["frags"] += frags
            user_points[key]["manual"] += manual

        # Preparing the final sorting
        aggregated_stats = []
        for key, data in user_points.items():
            total = data["frags"] + data["manual"]
            aggregated_stats.append((key, data["characters"], data["frags"], data["manual"], total))

        # Sort by total
        sorted_stats = sorted(aggregated_stats, key=lambda x: x[4], reverse=True)[:count]

        if not sorted_stats:
            await interaction.followup.send(f"❌ No data for last {days} day(s).", ephemeral=not public)
            return

        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        embeds = []
        
        top_key = sorted_stats[0][0]
        if isinstance(top_key, int):  # Discord user ID
            member = interaction.guild.get_member(top_key)
            top_display = {
                "display_name": member.display_name if member else f"User {top_key}",
                "avatar_url": member.display_avatar.url if member else None,
                "color": member.top_role.color if member and member.top_role else discord.Color.default()
            }
        else:
            top_display = await resolve_display_data(top_key, interaction.guild)

        author_text = f"🏆 Top-{count} in {days} day(s)"
        page_size = 10

        for start in range(0, len(sorted_stats), page_size):
            embed = discord.Embed(color=top_display.get("color", discord.Color.dark_grey()))
            embed.set_author(name=author_text)
            if top_display.get("avatar_url"):
                embed.set_thumbnail(url=top_display["avatar_url"])

            for i, (key, characters, frags, manual, total) in enumerate(sorted_stats[start:start+page_size], start + 1):
                if isinstance(key, int):
                    member = interaction.guild.get_member(key)
                    display_data = {
                        "display_name": member.display_name if member else f"User {key}",
                        "avatar_url": member.display_avatar.url if member else None
                    }
                else:
                    # character with no linked user
                    display_data = await resolve_display_data(key, interaction.guild)

                medal = medals.get(i, "")
                char_list = ", ".join(characters)
                                    
                
                if isinstance(key, int):
                    mmr = get_user_glicko_mmr(key)
                else:
                    mmr = get_glicko_rating(key)[0] if get_glicko_rating(key) else "—"
                    
                    
                line = f"Characters: `{char_list}`\nPoints: `{total}` (`{frags}` + `{manual}`)\nMMR: `{mmr}`"
                
                embed.add_field(
                    name=f"**{i}. {medal} {display_data['display_name'].upper()}**",
                    value=line,
                    inline=False
                )

            embeds.append(embed)

        if not embeds:
            await interaction.followup.send("❌ No stats available for the selected timeframe.", ephemeral=not public)
            return
        
        if len(embeds) == 1:
            await interaction.followup.send(embed=embeds[0], ephemeral=not public)
        else:
            view = PaginatedStatsView(embeds, ephemeral=not public)
            await view.send_initial(interaction)


    @bot.tree.command(name="mystats", description="Show your stats (all linked characters)")
    @app_commands.describe(days="Days", public="Publish?")
    async def mystats(interaction: Interaction, days: int = 1, public: bool = False):
        if public and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⚠️ Admin only", ephemeral=True)
            return
        if not await check_positive(interaction, days=days):
            return
        user_id = interaction.user.id
        characters = get_user_characters(user_id)
        if not characters:
            await interaction.response.send_message("❌ You don't have any linked characters.", ephemeral=True)
            return
        # ✅  Protection from the Unknown Interaction error
        await interaction.response.defer(thinking=True, ephemeral=not public)
        avatar_url = interaction.user.display_avatar.url
        embeds = await generate_stats_embeds(interaction, characters, days, avatar_url=avatar_url, target_user_id=interaction.user.id)

        if not embeds:
            await interaction.followup.send("❌ No stats available for this player.", ephemeral=not public)
            return
        
        if len(embeds) == 1:
            await interaction.followup.send(embed=embeds[0], ephemeral=not public)
        else:
            view = PaginatedStatsView(embeds, ephemeral=not public)
            await view.send_initial(interaction)
    
    
    @bot.tree.command(name="stats", description="Show player stats")
    @app_commands.describe(player="character or @user", days="Days", public="Publish?")
    async def stats(interaction: Interaction, player: str, days: int = 1, public: bool = False):
        if public and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⚠️ Admin only", ephemeral=True)
            return
        if not await check_positive(interaction, days=days):
            return
        await interaction.response.defer(thinking=True, ephemeral=not public)

        avatar_url = None
        characters = []
        user_id = None  # ✅ fix

        if match := re.match(r"<@!?(\d+)>", player):
            user_id = int(match.group(1))
            characters = get_user_characters(user_id)
            if not characters:
                await interaction.followup.send("❌ No characters linked to this user.", ephemeral=True)
                return
            try:
                user = await bot.fetch_user(user_id)
                avatar_url = user.display_avatar.url
            except Exception:
                avatar_url = None
        else:
            characters = [player.lower()]

        embeds = await generate_stats_embeds(
            interaction, characters, days,
            avatar_url=avatar_url,
            target_user_id=user_id  # ✅ safe
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
        is_admin = interaction.user.guild_permissions.administrator
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
            embed.add_field(name=f"{role_name}", value=f"{wins}+", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=not public)
        
# --- MMR ---        
            

    @bot.tree.command(name="mmr", description="Admin: manually adjust Glicko-2 rating for character(s) or user")
    @app_commands.describe(
        target="Character name or @user",
        value="Rating value: +50, -30, or =1500",
        reason="Optional reason for the change"
    )
    async def mmr(interaction: Interaction, target: str, value: str, reason: str = "Manual Glicko adjustment"):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⚠️ Admins only.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        # 🔍 Определим персонажей
        if match := re.match(r"<@!?(\d+)>", target):
            user_id = int(match.group(1))
            characters = get_user_characters(user_id)
            if not characters:
                await interaction.followup.send("❌ No characters linked to this user.", ephemeral=True)
                return
        else:
            characters = [target.lower()]

        # 📐 Распарсим значение
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

            set_glicko_rating(character, new_rating, rd, vol)

            with sqlite3.connect(get_db_path()) as conn:
                conn.execute("""
                    INSERT INTO glicko_history (character, delta, reason)
                    VALUES (?, ?, ?)
                """, (character, delta_applied, reason))

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
    @app_commands.describe(target="Character name or @user")
    async def mmrlog(interaction: Interaction, target: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⚠️ Admins only.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

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
                WHERE character IN ({placeholders})
                ORDER BY timestamp DESC
                LIMIT 20
            """, characters)
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
    async def mmrsync(interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⚠️ Admin only", ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=True)

        try:
            # 🧠 Очистка всех текущих glicko_ratings
            with sqlite3.connect(get_db_path()) as conn:
                conn.execute("DELETE FROM glicko_ratings")
                conn.commit()

            # 🗂️ Чтение всех фрагов
            with sqlite3.connect(get_db_path()) as conn:
                c = conn.cursor()
                c.execute("SELECT killer, victim, timestamp FROM frags ORDER BY timestamp ASC")
                rows = c.fetchall()

            if not rows:
                await interaction.followup.send("❌ No frags found.")
                return

            # 🎯 Группируем бои по дню
            battles_by_day = defaultdict(list)
            all_dates = []

            for killer, victim, ts in rows:
                day = datetime.fromisoformat(ts).date()
                battles_by_day[day].append((killer.lower(), victim.lower()))
                all_dates.append(day)

            start_date = min(all_dates)
            end_date = max(all_dates)
            all_players = {}

            # 🚀 Начинаем пересчёт
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

                # 📉 Decay для не участвовавших в боях игроков
                for name, player in all_players.items():
                    if name not in participated_today:
                        player.pre_rating_period()

                current_date += timedelta(days=1)

            # ✅ Сохраняем результаты
            with sqlite3.connect(get_db_path()) as conn:
                for name, player in all_players.items():
                    set_glicko_rating(name, player.getRating(), player.getRd(), player._vol)

            await interaction.followup.send("✅ Glicko-2 MMR sync complete!", ephemeral=True)
            logging.info("✅ Glicko-2 MMR synced successfully.")

        except Exception as e:
            logging.exception("❌ Failed to run Glicko MMR sync")
            await interaction.followup.send("❌ Failed to run MMR sync.", ephemeral=True)


    @bot.tree.command(name="mmrclear", description="Admin: Reset and reinitialize all Glicko-2 ratings")
    async def mmrclear(interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⚠️ Admins only.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            with sqlite3.connect(get_db_path()) as conn:
                c = conn.cursor()

                # Очистка таблицы рейтингов
                c.execute("DELETE FROM glicko_ratings")

                # Получение всех уникальных персонажей из базы фрагов
                c.execute("SELECT DISTINCT killer FROM frags")
                killers = [row[0].lower() for row in c.fetchall()]
                c.execute("SELECT DISTINCT victim FROM frags")
                victims = [row[0].lower() for row in c.fetchall()]

                all_characters = set(killers + victims)

                # Повторная инициализация
                for character in all_characters:
                    c.execute("""
                        INSERT OR REPLACE INTO glicko_ratings (character, rating, rd, vol)
                        VALUES (?, ?, ?, ?)
                    """, (character, 1500, 350, 0.06))

                conn.commit()

            embed = discord.Embed(
                title="🧹 Glicko-2 Ratings Reset",
                description=(
                    f"Cleared and reinitialized Glicko-2 ratings for **{len(all_characters)}** characters.\n"
                    f"Default: `1500 ± 350`, vol=0.06"
                ),
                color=discord.Color.orange()
            )
            embed.set_footer(text="Glicko-2 Admin Tool")

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logging.exception("❌ Failed to reset and reinitialize Glicko-2 ratings")
            await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

# --- for gpt ---

    @bot.tree.command(name="topmmr", description="Top players by Glicko-2 rating")
    @app_commands.describe(
        count="Number of top players",
        days="Days to consider",
        public="Publish to channel (admins only)?",
        details="Show detailed statistics?"
    )
    async def topmmr(
        interaction: Interaction,
        count: int = 10,
        days: int = 30,
        public: bool = False,
        details: bool = False
    ):
        if not await check_positive(interaction, count=count, days=days):
            return
        if public and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⚠️ Admin only.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=not public)

        since = datetime.utcnow() - timedelta(days=days)
        seen = set()
        leaderboard_data = []

        for key in get_all_players():
            if key in seen:
                continue
            seen.add(key)

            characters = get_user_characters(key) if isinstance(key, int) else [key]
            total_wins = total_losses = total_fights = 0
            glicko_values = []
            recent_days = []

            for char in characters:
                wins, losses, fights = get_fight_stats(char, since)
                total_wins += wins
                total_losses += losses
                total_fights += fights

                rating, rd, vol = get_glicko_rating(char)
                glicko_values.append(rating)

                last_active = get_last_active_day(char)
                if last_active:
                    recent_days.append((datetime.utcnow().date() - last_active).days)

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
        leaderboard_data = leaderboard_data[:count]

        if not details:
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

        # 📊 Расширенный подробный вывод
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        embed = discord.Embed(
            title=f"Glicko-2 Top-{count} in {days} day(s)",
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
        if not await require_admin(interaction):
            return

        await interaction.response.defer(thinking=True, ephemeral=True)

        guild = interaction.guild
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

            # Найдем подходящую роль из конфигурации
            roles_sorted = sorted(roles_config, key=lambda x: x[0], reverse=True)
            new_role_name = None
            for threshold, role_name in roles_sorted:
                if avg_mmr >= threshold:
                    new_role_name = role_name
                    break

            if not new_role_name:
                continue  # нет подходящей роли

            discord_role = discord.utils.get(guild.roles, name=new_role_name)
            if not discord_role:
                continue

            # Удалим старые MMR-роли и добавим новую
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
            f"✅ MMR roles updated.\n🧍 Processed: {updated} users\n⏭️ Skipped: {skipped} (no characters or MMR)"
        )



# --- Help ---

    @bot.tree.command(name="helpme", description="Show list of available commands")
    async def helpme(interaction: discord.Interaction):
        embed = discord.Embed(
            title="📖 Bot Command Help",
            description="Use slash commands to control and monitor player frags and killstreaks.",
            color=discord.Color.purple(),
            timestamp=datetime.utcnow()
        )
        if interaction.user.guild_permissions.administrator:
            embed.add_field(
                name="__🔧 Admin Commands (1/2):__",
                value=(
                    "⚙️ `/track` `[channel]` — Show or set the tracking channel\n\n"
                    "📢 `/announce` `[channel]` — Show or set the announce channel\n\n"
                    "⏳ `/killstreaktimeout` `[seconds]` — Show or set the killstreak timeout (default 15)\n\n"
                    "🔊 `/voice` `[leave]` — Add or remove bot from voice channel\n\n"
                    "🎨 `/style` `[style]` — Show or set the announce style\n\n"
                    "🔁 `/reset` `[filename]` — Reset or restore database from backup\n\n"
                ),
                inline=False
            )
            embed.add_field(
                name="__🔧 Admin Commands (2/2):__",
                value=(
                    "🔗 `/link` `[character]` `[@user]` — Link a character to a user\n\n"
                    "❌ `/unlink` `[character]` — Unlink a character\n\n"
                    "🥇 `/roleset` `[wins]` `[role]` — Set rank role for win threshold\n\n"
                    "👑 `/roleupdate` — Forcibly updates roles for all linked users\n\n"
                    "🧹 `/roleclear` — Clear all configured rank roles\n\n"
                    "⚙️ `/autoroles` `[on/off]` — Enable or disable auto role updates\n\n"
                    "📊 `/autorolestatus` — Show the current auto-role update setting\n\n"
                    "📆 `/autoroletimeout` `[days]` — Set time window (in days) for role calculation\n\n"
                    "🧮 `/points` `[character/@user]` `[amount]` `[reason]` — Adjust players points manually\n\n"
                    "📜 `/pointlog` `[character/@user]` — Show manual adjustment history\n\n"
                ),
                inline=False
            )
        embed.add_field(
            name="\n__👥 User Commands:__",
            value=(
                "🏆 `/top` `[players]` `[days]` — Show top players\n\n"
                "🧍 `/mystats` `[days]` — Show your stats (linked characters)\n\n"
                "📊 `/stats` `[character/@user]` `[days]` — Show stats for character or user\n\n"
                "🔍 `/whois` `[character/@user]` — Show who owns this character\n\n"
                "🏅 `/roles` — Show current roles configuration\n\n"
                "❓ `/helpme` — Show this help message"
            ),
            inline=False
        )
        embed.set_footer(text=f"Bot version {BOT_VERSION}")
        await interaction.response.send_message(embed=embed, ephemeral=True)