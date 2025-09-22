# -*- coding: utf-8 -*-
# main.py

import os
import sys
import logging
import re
import discord
import discord.opus
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
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
intents.members = True  # required for member info
bot = commands.Bot(command_prefix=">", intents=intents)
setup_commands(bot)  # register slash commands

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
init_mmr_roles_table()
clear_deathless_streaks()
ensure_default_event() 

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

# --- Killstreaks: store per-event to avoid mixing series across events ---

# key: (event_id, character) -> {"count": int, "last_kill_time": datetime}
killstreaks: dict = {}
KILLSTREAK_TIMEOUT = int(get_setting("killstreak_timeout") or 15)

@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        logging.info(f"🌐 Synced {len(synced)} commands.")
    except Exception as e:
        logging.error(f"❌ Failed to sync commands: {e}")

def _call_announcer(func, *args, event_id=None, **kwargs):
    """
    Helper: call announcer function trying two signatures:
    1) func(..., event_id=event_id)
    2) func(...)  (fallback for backward compatibility)
    """
    if event_id is None:
        try:
            return func(*args, **kwargs)
        except TypeError:
            return func(*args)
    else:
        try:
            return func(*args, event_id=event_id, **kwargs)
        except TypeError:
            # announcer not yet migrated to accept event_id -> fallback
            return func(*args, **kwargs)

@bot.event
async def on_message(message: discord.Message):
    # Ignore bot messages
    if message.author and message.author.bot:
        return

    channel = message.channel
    if not channel:
        return

    # Determine event by channel (new helper in db.py)
    try:
        event_id = get_event_id_by_channel(message.channel.id)
        logging.debug(f"DEBUG on_message channel={message.channel.id} event_id={event_id}")

    except Exception as e:
        logging.exception(f"❌ Failed to resolve event for channel {channel.id}: {e}")
        event_id = None

    # If channel isn't linked to any event — ignore message
    if not event_id:
        # optionally: debug log
        logging.debug(f"Ignored message in unregistered channel {channel.id}")
        return

    content = message.content.strip()

        # --- [1] Standard Kill Check ---
    match = re.match(r"^(.+?) killed by (.+)$", content)
    if match:
        victim_raw, killer_raw = match.groups()
        killer = killer_raw.strip().lower()
        victim = victim_raw.strip().lower()
        now = datetime.now(timezone.utc)
        
        # Validate input data
        if not killer or not victim or len(killer) > 50 or len(victim) > 50:
            logging.warning(f"❌ Invalid kill data: killer='{killer}', victim='{victim}'")
            return

        ks_key_killer = (event_id, killer)
        ks_key_victim = (event_id, victim)

        # --- Killstreak (per-event) ---
        if ks_key_killer not in killstreaks:
            killstreaks[ks_key_killer] = {"count": 1, "last_kill_time": now}
        else:
            delta = (now - killstreaks[ks_key_killer]["last_kill_time"]).total_seconds()
            if delta <= KILLSTREAK_TIMEOUT:
                killstreaks[ks_key_killer]["count"] += 1
            else:
                killstreaks[ks_key_killer]["count"] = 1
            killstreaks[ks_key_killer]["last_kill_time"] = now

        # announce killstreaks
        if killstreaks[ks_key_killer]["count"] >= 2:
            try:
                await _call_announcer(send_killstreak_announcement, bot, killer, killstreaks[ks_key_killer]["count"], event_id=event_id)
            except Exception as e:
                    logging.exception(f"❌ Killstreak announcement failed: {e}")

            # sound is handled inside announcer.send_killstreak_announcement to avoid duplicates

        # clear victim's killstreak for this event (if any)
        if ks_key_victim in killstreaks:
            del killstreaks[ks_key_victim]

        # Add frag: pass channel id so add_frag can resolve event internally
        try:
            # prefer passing channel id (backward compatible: if add_frag signature changed to accept channel_id)
            add_frag(killer, victim, channel_id=channel.id)
        except TypeError:
            # fallback: old signature (no channel_id) — still call it (less preferred)
            try:
                add_frag(killer, victim)
            except Exception as e:
                logging.exception(f"❌ add_frag failed (fallback): {e}")
        except Exception as e:
            logging.exception(f"❌ add_frag failed: {e}")

        # 🔻 Announce streak break if the victim had a deathless streak (use DB helper)
        try:
            # get_deathless_streak may be event-aware; try passing event_id, fallback otherwise
            had_deathless = False
            try:
                val = get_deathless_streak(victim, event_id=event_id)
                had_deathless = (val >= 3)
            except TypeError:
                val = get_deathless_streak(victim)
                had_deathless = (val >= 3)

            if had_deathless:
                try:
                    await _call_announcer(announce_streak_break, bot, victim, message.guild, event_id=event_id)
                except Exception:
                    try:
                        await announce_streak_break(bot, victim, message.guild)
                    except Exception as e:
                        logging.exception(f"❌ announce_streak_break failed: {e}")
        except Exception:
            # don't let announcer errors break processing
            logging.exception("❌ Failed while handling deathless streak check/announce")

        # --- Deathless streak logic: update DB counters (try to pass event_id)
        try:
            try:
                new_count = update_deathless_streaks(killer, victim, event_id=event_id)
            except TypeError:
                new_count = update_deathless_streaks(killer, victim)
            if new_count:
                try:
                    await _call_announcer(send_deathless_announcement, bot, killer, new_count, event_id=event_id)
                except Exception:
                    try:
                        await send_deathless_announcement(bot, killer, new_count)
                    except Exception as e:
                        logging.exception(f"❌ send_deathless_announcement failed: {e}")

                try:
                    await _call_announcer(play_deathless_sound, bot, new_count, message.guild, event_id=event_id)
                except Exception:
                    try:
                        await play_deathless_sound(bot, new_count, message.guild)
                    except Exception as e:
                        logging.exception(f"❌ play_deathless_sound failed: {e}")

        except Exception:
            logging.exception("❌ Failed during deathless streak update")

        return  # processed this message

    # --- [2] Single death (no killer) ---
    elif (match := re.match(r"^(.+?) is dead$", content)):
        victim = match.group(1).strip().lower()
        if victim:
            logging.info(f"💀 '{victim}' died without a killer. Resetting deathless streak.")
            try:
                try:
                    had_streak = reset_deathless_streak(victim, event_id=event_id)
                except TypeError:
                    had_streak = reset_deathless_streak(victim)
            except Exception as e:
                logging.exception(f"❌ Failed to reset deathless streak for '{victim}': {e}")
                had_streak = False

            if had_streak:
                try:
                    await _call_announcer(announce_streak_break, bot, victim, message.guild, event_id=event_id)
                except Exception:
                    try:
                        await announce_streak_break(bot, victim, message.guild)
                    except Exception as e:
                        logging.exception(f"❌ Failed to announce streak break for '{victim}': {e}")

            # clear killstreak for this victim in this event
            ks_key_victim = (event_id, victim)
            if ks_key_victim in killstreaks:
                del killstreaks[ks_key_victim]
        else:
            logging.warning(f"⚠️ Death message matched, but victim name is empty: {content}")
        return

    # not a known pattern
    logging.debug(f"⚠️  Message does not match known kill format: {content}")

# --- Run bot ---

bot.run(TOKEN)
