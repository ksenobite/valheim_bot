# -*- coding: utf-8 -*-

from datetime import datetime, timedelta

import os
import re
import sqlite3
import asyncio
import discord
import logging

from discord import app_commands, Interaction
from discord.app_commands import describe
from discord.ext import commands

from operator import itemgetter

from settings import BOT_VERSION, BACKUP_DIR, get_db_file_path
from db import *
from roles import update_roles_for_all_members
from announcer import start_heartbeat_loop, KILLSTREAK_STYLES, audio_queue_worker
from utils import require_admin, check_positive, get_winrate_emoji, resolve_display_data


async def show_stats_for_characters(interaction: Interaction, characters: list[str], days: int, public: bool):
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
    # 📊 Statistics processing
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
    # 🎨 Embed preparation
    emoji_summary = get_winrate_emoji(overall_winrate)
    embed = discord.Embed(
        title=f"📊 Stats for {len(characters)} character(s) in {days} day(s)",
        color=discord.Color.blue()
    )
    for opponent, wins, losses, winrate in sorted(stats, key=itemgetter(3), reverse=True):
        display_data = await resolve_display_data(opponent, interaction.guild)
        emoji = get_winrate_emoji(winrate)
        embed.add_field(
            name=f"{emoji} {display_data['display_name'].upper()}",
            value=f"Wins: {wins} | Losses: {losses} | Winrate: {winrate:.1f}%",
            inline=False
        )
    embed.add_field(
        name="**__Overall Performance Summary__**",
        value=(
            f"**Total Wins:** {total_wins}  \n"
            f"**Total Losses:** {total_losses}  \n"
            f"**Overall Winrate:** {emoji_summary} **{overall_winrate:.1f}%**"
        ),
        inline=False
    )
    await interaction.response.send_message(embed=embed, ephemeral=not public)

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

    @bot.tree.command(name="top", description="Top players by frags")
    @app_commands.describe(count="Number of top players", days="Days", public="Publish?")
    async def top(interaction: Interaction, count: int = 5, days: int = 1, public: bool = False):
        if not await check_positive(interaction, count=count, days=days):
            return
        if public and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⚠️ Admin only", ephemeral=True)
            return
        top_stats = get_top_players(count, days)
        if not top_stats:
            await interaction.response.send_message(f"❌ No data for last {days} day(s).", ephemeral=not public)
            return
        embed = discord.Embed(title=f"🏆 Top {count} players in the last {days} day(s)")
        # Let's define the embed color based on the role of the first participant
        top_name = top_stats[0][0]
        top_display = await resolve_display_data(top_name, interaction.guild)
        embed.color = top_display.get("color", discord.Color.dark_grey())
        for i, (character, kills) in enumerate(top_stats, 1):
            display_data = await resolve_display_data(character, interaction.guild)
            line = f"**{i}.** {display_data['display_name']} — `{kills}` kills"
            if i == 1 and display_data.get("avatar_url"):
                embed.set_thumbnail(url=display_data["avatar_url"])
            embed.add_field(name="\u200b", value=line, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=not public)

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
        # Use ready-made logic from /stats, but on all characters
        await show_stats_for_characters(interaction, characters, days, public)

    @bot.tree.command(name="stats", description="Show player stats")
    @app_commands.describe(player="character_name or @discord_user", days="Days", public="Publish?")
    async def stats(interaction: Interaction, player: str, days: int = 1, public: bool = False):
        if public and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⚠️ Admin only", ephemeral=True)
            return
        if not await check_positive(interaction, days=days):
            return
        if match := re.match(r"<@!?(\d+)>", player):  # Is this a user mention?
            user_id = int(match.group(1))
            characters = get_user_characters(user_id)
            if not characters:
                await interaction.response.send_message("❌ No characters linked to this user.", ephemeral=True)
                return
            await show_stats_for_characters(interaction, characters, days, public)
        else:
            await show_stats_for_characters(interaction, [player.lower()], days, public)

    @bot.tree.command(name="whois", description="Show the character's owner")
    @app_commands.describe(character="Character's name")
    async def whois(interaction: Interaction, character: str):
        character = character.lower()
        discord_id = get_character_owner(character)
        if discord_id:
            user = await bot.fetch_user(discord_id)
            await interaction.response.send_message(f"🎮 The character **{character}** belongs to {user.mention}.", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ The character **{character}** is not linked to any user.", ephemeral=True)

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
            embed.add_field(name=f"{role_name}", value=f"{wins}+ wins", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=not public)

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
                name="__🔧 Admin Commands:__",
                value=(
                    "⚙️ `/track` `[channel]` — Show or set the tracking channel\n\n"
                    "📢 `/announce` `[channel]` — Show or set the announce channel\n\n"
                    "⏳ `/killstreaktimeout` `[seconds]` — Show or set the killstreak timeout (default 15)\n\n"
                    "🔗 `/link` `[character]` `[@user]` — Link a character to a user\n\n"
                    "❌ `/unlink` `[character]` — Unlink a character\n\n"
                    "🥇 `/roleset` `[wins]` `[role]` — Set rank role for win threshold\n\n"
                    "👑 `/roleupdate` — Forcibly updates roles for all linked users\n\n"
                    "🧹 `/roleclear` — Clear all configured rank roles\n\n"
                    "⚙️ `/autoroles` `[on/off]` — Enable or disable auto role updates\n\n"
                    "📊 `/autorolestatus` — Show the current auto-role update setting\n\n"
                    "📆 `/autoroletimeout` `[days]` — Set time window (in days) for role calculation\n\n"
                    "🔊 `/voice` `[leave]` — Add or remove bot from voice channel\n\n"
                    "🎨 `/style` `[style]` — Show or set the announce style\n\n"
                    "🔁 `/reset` `[filename]` — Reset or restore database from backup\n\n"
                ),
                inline=False
            )
        embed.add_field(
            name="\n__👥 User Commands:__",
            value=(
                "🏆 `/top` `[players]` `[days]` — Show top players\n\n"
                "🧍 `/mystats` `[days]` — Show your stats (linked characters)\n\n"
                "📊 `/stats` `[character/@user]` `[days]` — Show stats for character or user\n\n"
                "🔍 `/whois` `[character]` — Show who owns this character\n\n"
                "🏅 `/roles` — Show current roles configuration\n\n"
                "❓ `/helpme` — Show this help message"
            ),
            inline=False
        )

        embed.set_footer(text=f"Bot version {BOT_VERSION}")
        await interaction.response.send_message(embed=embed, ephemeral=True)