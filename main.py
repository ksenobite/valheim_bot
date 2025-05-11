# -*- coding: utf-8 -*-

import os
import sys
import logging
import discord
import re

from dotenv import load_dotenv
from datetime import datetime
from discord.ext import commands

from commands import setup_commands
from db import get_setting, set_db_path, init_db, get_tracking_channel_id, add_frag
from announcer import set_sounds_path, send_killstreak_announcement, play_killstreak_sound
from settings import BOT_VERSION, get_env_path, get_db_file_path, get_sounds_path


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

# --- Bot Initialization ---

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # 👈 required for bot identification of users!
bot = commands.Bot(command_prefix=">", intents=intents)
setup_commands(bot)  # 👈 registering the commands

# --- Paths & Init ---

set_db_path(get_db_file_path())
set_sounds_path(get_sounds_path())
init_db()

# --- Load .env ---

env_path = get_env_path()
if not os.path.exists(env_path):
    logging.error(f"❌ .env file not found at {env_path}")
    sys.exit(1)
else:
    load_dotenv(dotenv_path=env_path)

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    logging.error("❌ DISCORD_TOKEN is missing from .env")
    sys.exit(1)

killstreaks = {}
KILLSTREAK_TIMEOUT = int(get_setting("killstreak_timeout") or 15)


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    channel_id = get_tracking_channel_id()
    if channel_id and message.channel.id == channel_id:
        match = re.match(r"^(.+?) killed by (.+)$", message.content.strip())
        if match:
            victim, killer = match.groups()
            killer = killer.strip().lower()
            victim = victim.strip().lower()
            now = datetime.utcnow()

            # Killstreaks
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
        else:
            logging.warning(f"⚠️  Message does not match kill format: {message.content}")


# --- Run bot ---
bot.run(TOKEN)
