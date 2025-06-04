# -*- coding: utf-8 -*-

# main.py

import os
import sys
import logging
import re
import ctypes
import discord
import discord.opus

from dotenv import load_dotenv
from datetime import datetime
from discord.ext import commands

from settings import *
from db import *
from commands import *
from announcer import *


# --- Logging ---

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname).1s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# --- Opus ---

if not discord.opus.is_loaded():
    dll_path = os.path.join(os.path.dirname(__file__), "opus.dll")
    discord.opus.load_opus(dll_path)
if discord.opus.is_loaded():
    logging.info("🎧 Opus successfully loaded.")
else:
    logging.error("❌ Opus failed to load.")

# --- Bot Init ---

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # 👈 required for bot identification of users!
bot = commands.Bot(command_prefix=">", intents=intents)
setup_commands(bot)  # 👈 registering the commands

# --- Paths & Init ---

set_db_path(get_db_file_path())

sounds_path = get_sounds_path()
set_sounds_path(sounds_path)
if not os.path.exists(sounds_path):
    os.makedirs(sounds_path)
    logging.warning(f"⚠️ Created missing 'sounds' directory at: {sounds_path}")
else:
    logging.info(f"✅ 'sounds' directory found: {sounds_path}")

init_db()
init_rank_roles_table()

clear_deathless_streaks()

# --- Token ---

env_path = get_env_path()
if not os.path.exists(env_path):
    logging.error(f"❌ .env file not found at {env_path}")
    sys.exit("❌ .env file not found")
else:
    load_dotenv(dotenv_path=env_path)
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    logging.error("❌ DISCORD_TOKEN is missing from .env")
    sys.exit("❌ Token missing.")
    
# --- Killstreaks ---

killstreaks = {}
KILLSTREAK_TIMEOUT = int(get_setting("killstreak_timeout") or 15)

# --- Events ---

@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        logging.info(f"🌐 Synced {len(synced)} commands.")
    except Exception as e:
        logging.error(f"❌ Failed to sync commands: {e}")


@bot.event
async def on_message(message):
    channel_id = get_tracking_channel_id()
    if channel_id and message.channel.id == channel_id:
        content = message.content.strip()

        # --- [1] Standard Kill Check ---
        match = re.match(r"^(.+?) killed by (.+)$", content)
        if match:
            victim, killer = match.groups()
            killer = killer.strip().lower()
            victim = victim.strip().lower()
            now = datetime.utcnow()

            # --- Killstreak ---
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

            # --- Deathless streak logic ---
            new_count = update_deathless_streaks(killer, victim)
            if new_count:
                await send_deathless_announcement(bot, killer, new_count)
                await play_deathless_sound(bot, new_count, message.guild)

        # --- [2] Checking for a single death (for example, by nature or suicide) ---
        elif (match := re.match(r"^(.+?) is dead$", content)):
            victim = match.group(1).strip().lower()
            if victim:
                logging.info(f"💀 '{victim}' died without a killer. Resetting deathless streak.")
                try:
                    reset_deathless_streak(victim)
                except Exception as e:
                    logging.exception(f"❌ Failed to reset deathless streak for '{victim}': {e}")
                if victim in killstreaks:
                    del killstreaks[victim]
            else:
                logging.warning(f"⚠️ Death message matched, but victim name is empty: {content}")
        else:
            logging.warning(f"⚠️  Message does not match known kill format: {content}")


# --- Run bot ---
bot.run(TOKEN)
