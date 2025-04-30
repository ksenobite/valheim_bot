# -*- coding: utf-8 -*-

import subprocess

import os
import sys
import logging
from dotenv import load_dotenv
import sqlite3

import discord
from discord.ext import commands
from discord import app_commands, Interaction

from datetime import datetime, timedelta
from operator import itemgetter

try:
    import nacl
except ImportError:
    logging.error("❌ PyNaCl is not installed. Voice will NOT be supported.")

from db import *
from killstreaks import *

#  --- Consts ---

BOT_VERSION = "4.0.0"
BACKUP_DIR = 'db_backups'
killstreaks = {}

# --- Additional ---

async def check_positive(interaction: discord.Interaction, **kwargs):
    for name, value in kwargs.items():
        if value < 1:
            await interaction.response.send_message(f"The parameter '{name}' must be greater than 0.", ephemeral=True)
            return False
    return True

async def require_admin(interaction: discord.Interaction) -> bool:
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Admin only", ephemeral=True)
        return False
    return True

def get_current_killstreak_timeout():
    val = get_setting("killstreak_timeout")
    return int(val) if val else 15

def get_base_dir():
    return os.path.dirname(os.path.abspath(sys.argv[0]))

#  --- Logging --- 

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname).1s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logging.info(f"🤖 Bot started. Version: {BOT_VERSION}")

#  --- Settings --- 

BASE_DIR = get_base_dir()

opus_path = os.path.join(BASE_DIR, "opus.dll")
if not discord.opus.is_loaded():
    discord.opus.load_opus(opus_path)

env_path = os.path.join(BASE_DIR, '.env')
sounds_path  = os.path.join(BASE_DIR, 'sounds')
db_path = os.path.join(BASE_DIR, 'frags.db')

set_sounds_path(sounds_path)
set_db_path(db_path)

init_db()

# Load .env
if not os.path.exists(env_path):
    logging.error(f"❌ .env file not found at {env_path}")
else:
    load_dotenv(dotenv_path=env_path)

# Load token
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    logging.error("❌ DISCORD_TOKEN is missing from .env.")
    sys.exit(1)

# Check sounds
if not os.path.isdir(sounds_path ):
    logging.error(f"❌ Sounds folder not found at {sounds_path }")

#  --- Bot class --- 

class FragBot(commands.Bot):
    async def setup_hook(self):
        await self.tree.sync()
        logging.info("Slash commands synced.")

intents = discord.Intents.default()
intents.message_content = True
bot = FragBot(command_prefix=">", intents=intents)

CURRENT_STYLE = get_announce_style()
KILLSTREAK_TIMEOUT = get_current_killstreak_timeout()

# --- Events ---

@bot.event
async def on_ready():
    user = bot.user
    logging.info(f"🤖 Bot is ready! Logged in as {user} (ID: {user.id})")

    if get_tracking_channel_id() is None:
        logging.warning("⚠️ Tracking channel is not set.")
    if get_announce_channel_id() is None:
        logging.warning("⚠️ Announce channel is not set.")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    channel_id = get_tracking_channel_id()
    if channel_id and message.channel.id == channel_id:
        parts = message.content.split(" killed by ")
        if len(parts) == 2:
            victim = parts[0].strip()
            killer = parts[1].strip()
            now = datetime.utcnow()

            if killer not in killstreaks:
                killstreaks[killer] = {"count": 1, "last_kill_time": now}
            else:
                delta = (now - killstreaks[killer]["last_kill_time"]).total_seconds()
                if delta <= KILLSTREAK_TIMEOUT:
                    killstreaks[killer]["count"] += 1
                else:
                    killstreaks[killer]["count"] = 1
                killstreaks[killer]["last_kill_time"] = now
            if killstreaks[killer]["count"] >= 2:
                await send_killstreak_announcement(bot, killer, killstreaks[killer]["count"])
                await play_killstreak_sound(bot, killstreaks[killer]["count"], message.guild)

            if victim in killstreaks:
                del killstreaks[victim]
            add_frag(killer, victim)

@bot.event
async def on_app_command_completion(interaction: discord.Interaction, command: app_commands.Command):
    user = interaction.user
    logging.info(f"📥 Slash command used: /{command.name} by {user} (ID: {user.id})")

# --- Slash commands ---

@bot.tree.command(name="joinvoice", description="Join or leave a voice channel")
@app_commands.describe(leave="Set True to leave the voice channel")
async def joinvoice(interaction: discord.Interaction, leave: bool = False):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Admin only", ephemeral=True)
        return
    if leave:
        if interaction.guild.voice_client:
            await interaction.guild.voice_client.disconnect()
            await interaction.response.send_message("Disconnected from voice channel.", ephemeral=True)
        else:
            await interaction.response.send_message("I'm not connected to a voice channel.", ephemeral=True)
    else:
        if interaction.user.voice is None:
            await interaction.response.send_message("You must be in a voice channel.", ephemeral=True)
            return
        channel = interaction.user.voice.channel
        await channel.connect()
        await interaction.response.send_message(f"Connected to {channel.name}", ephemeral=True)

@bot.tree.command(name="stats", description="Show player stats")
@app_commands.describe(player="Player", days="Days", public="Show publicly?")
async def stats(interaction: discord.Interaction, player: str, days: int = 1, public: bool = False):
    if public and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Admin only", ephemeral=True)
        return
    if not await check_positive(interaction, days=days):
        return
    since = datetime.utcnow() - timedelta(days=days)
    with sqlite3.connect(get_db_path()) as conn:
        c = conn.cursor()
        c.execute("SELECT victim, COUNT(*) FROM frags WHERE killer = ? AND timestamp >= ? GROUP BY victim", (player, since))
        victories = dict(c.fetchall())
        c.execute("SELECT killer, COUNT(*) FROM frags WHERE victim = ? AND timestamp >= ? GROUP BY killer", (player, since))
        defeats = dict(c.fetchall())
    all_opponents = set(victories.keys()) | set(defeats.keys())
    stats = []
    for opponent in all_opponents:
        wins = victories.get(opponent, 0)
        losses = defeats.get(opponent, 0)
        total = wins + losses
        winrate = (wins / total) * 100 if total > 0 else 0
        stats.append((opponent, wins, losses, winrate))
    total_wins = sum(victories.values())
    total_losses = sum(defeats.values())
    total_matches = total_wins + total_losses
    overall_winrate = (total_wins / total_matches) * 100 if total_matches > 0 else 0
    embed = discord.Embed(title=f"📊 Player stats: {player} from {days} day(s)")
    stats = sorted(stats, key=itemgetter(3), reverse=True)
    for opponent, wins, losses, winrate in stats:
        embed.add_field(
            name=f"{opponent}",
            value=f"Wins: {wins} | Losses: {losses} | Winrate: {winrate:.1f}%",
            inline=False
        )
    summary = f"Total wins: {total_wins}\nTotal losses: {total_losses}\nOverall Winrate: {overall_winrate:.1f}%"
    await interaction.response.send_message(embed=embed, ephemeral=not public)
    await interaction.followup.send(content=f"```{summary}```", ephemeral=not public)

@bot.tree.command(name="top", description="Top players by frags")
@app_commands.describe(count="Number of top players", days="Days", public="Show publicly?")
async def top(interaction: Interaction, count: int = 5, days: int = 1, public: bool = False):
    if not await check_positive(interaction, count=count, days=days):
        return
    if public and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Admin only", ephemeral=True)
        return
    top_stats = get_top_players(count, days)
    if not top_stats:
        await interaction.response.send_message(f"No data for last {days} day(s).", ephemeral=not public)
        return
    embed = discord.Embed(title=f"Top {count} players in the last {days} day(s)")
    for i, (player, score) in enumerate(top_stats, 1):
        embed.add_field(name="\u200b", value=f"{i}. {player}:   {score}", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=not public)

@bot.tree.command(name="announcestyle", description="Show or set the killstreak announce style")
@app_commands.describe(style="Style name (classic, epic, tournament)")
async def announcestyle(interaction: Interaction, style: str = None):
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
        await interaction.response.send_message(f"Announce style set to **{style}**.", ephemeral=True)
    else:
        current_style = get_announce_style()
        await interaction.response.send_message(f"Current announce style is **{current_style}**.", ephemeral=True)

@bot.tree.command(name="killstreaktimeout", description="Show or set the killstreak timeout (in seconds)")
@app_commands.describe(seconds="New timeout value in seconds")
async def killstreaktimeout(interaction: Interaction, seconds: int = None):
    if not await require_admin(interaction):
        return
    global KILLSTREAK_TIMEOUT
    if seconds is not None:
        if seconds < 1:
            await interaction.response.send_message("Timeout must be greater than 0.", ephemeral=True)
            return
        KILLSTREAK_TIMEOUT = seconds
        set_setting("killstreak_timeout", str(seconds))
        await interaction.response.send_message(f"Killstreak timeout set to {seconds} seconds.", ephemeral=True)
    else:
        current = get_setting("killstreak_timeout")
        if current:
            await interaction.response.send_message(f"Current killstreak timeout: {current} seconds.", ephemeral=True)
        else:
            await interaction.response.send_message("Killstreak timeout is not set. Default: 15 seconds.", ephemeral=True)

@bot.tree.command(name="announce", description="Show or set the announce channel")
@app_commands.describe(channel="Channel")
async def announce(interaction: Interaction, channel: discord.TextChannel = None):
    if not await require_admin(interaction):
        return
    if channel:
        set_setting("announce_channel_id", str(channel.id))
        await interaction.response.send_message(f"Announce channel set to {channel.mention}.", ephemeral=True)
    else:
        cid = get_announce_channel_id()
        if cid:
            chan = interaction.guild.get_channel(cid)
            if chan:
                await interaction.response.send_message(f"Current announce channel: {chan.mention}", ephemeral=True)
            else:
                await interaction.response.send_message("Announce channel not found.", ephemeral=True)
        else:
            await interaction.response.send_message("Announce channel is not set.", ephemeral=True)

@bot.tree.command(name="tracking", description="Show or set the tracking channel")
@app_commands.describe(channel="Channel")
async def tracking(interaction: Interaction, channel: discord.TextChannel = None):
    if not await require_admin(interaction):
        return
    if channel:
        set_setting("tracking_channel_id", str(channel.id))
        await interaction.response.send_message(f"Tracking channel set to {channel.mention}.", ephemeral=True)
    else:
        cid = get_tracking_channel_id()
        if cid:
            chan = interaction.guild.get_channel(cid)
            if chan:
                await interaction.response.send_message(f"Current tracking channel: {chan.mention}", ephemeral=True)
            else:
                await interaction.response.send_message("Tracking channel not found.", ephemeral=True)
        else:
            await interaction.response.send_message("Tracking channel is not set.", ephemeral=True)

@bot.tree.command(name="reset", description="Reset the database or restore from backup")
@app_commands.describe(backup="Name of the backup file to restore (optional)")
async def reset(interaction: Interaction, backup: str = None):
    if not await require_admin(interaction):
        return
    os.makedirs(BACKUP_DIR, exist_ok=True)
    if backup is None:
        # Normal reset
        db_path = get_db_path()
        backup_file = os.path.join(BACKUP_DIR, f"frags_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.db")
        if os.path.exists(db_path):
            os.rename(db_path, backup_file)
        init_db()
        await interaction.response.send_message(
            "✅ Database has been reset.\n\n"
            "Please **set tracking channel** and **announce channel** again!",
            ephemeral=True
        )
        logging.info(f"Database reset complete. Backup saved as {backup_file}.")
    else:
        # Restore from backup
        backup_path = os.path.join(BACKUP_DIR, backup)
        if not os.path.exists(backup_path):
            await interaction.response.send_message(
                f"❌ Backup file `{backup}` not found.",
                ephemeral=True
            )
            return
        if os.path.exists(get_db_path()):
            os.remove(get_db_path())
        os.replace(backup_path, get_db_path())
        init_db()
        await interaction.response.send_message(
            "✅ Database restored from backup.\n\n"
            "**Please restart the bot manually!**",
            ephemeral=True
        )
        logging.info(f"Database restored from backup {backup}.")

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
            name="🔧 Admin Commands",
            value=(
                "⚙️ `/tracking [channel]` — Show or set the tracking channel\n"
                "📢 `/announce [channel]` — Show or set the announce channel\n"
                "⏳ `/killstreaktimeout [seconds]` — Show or set the killstreak timeout\n"
                "🔊 `/joinvoice [leave]` — Adds or removes a bot from the voice channel\n"
                "🎨 `/announcestyle [style]` — Show or set the announce style\n"
                "🔁 `/reset [filename]` — Reset or restore database with backup\n"
            ),
            inline=False
        )

    embed.add_field(
        name="👥 User Commands",
        value=(
            "🏆 `/top <players> <days>` — Show top players\n"
            "📊 `/stats <name> <days>` — Show player stats\n"
            "❓ `/helpme` — Show this help message\n"
        ),
        inline=False
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# --- Run ---

bot.run(TOKEN)
