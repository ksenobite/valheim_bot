# -*- coding: utf-8 -*-
# announcer.py

import os
import logging
import discord
import asyncio
import wave

from collections import defaultdict, deque
from typing import Optional
from discord import VoiceClient

from db import get_announce_channel_id, get_announce_style
from utils import resolve_display_data 

SOUNDS_DIR = None
audio_queues = defaultdict(deque)  # guild.id -> deque of file paths

# --- 📦 Simple WAV audio source ---

class SimpleAudioSource(discord.AudioSource):
    def __init__(self, file_path):
        self.wave = wave.open(file_path, 'rb')
        self.frame_bytes = int(self.wave.getframerate() / 50) * self.wave.getnchannels() * self.wave.getsampwidth()

    def read(self):
        return self.wave.readframes(self.frame_bytes // (self.wave.getnchannels() * self.wave.getsampwidth()))

    def is_opus(self):
        return False

    def cleanup(self):
        self.wave.close()

# --- 🎶 Frags Styles ---

KILLSTREAK_STYLES = {
    "classic": {
        2: {"title": "🔥 DOUBLE KILL 🔥", "emojis": "🔥"},
        3: {"title": "⚡️ TRIPLE KILL ⚡️", "emojis": "⚡️"},
        4: {"title": "💥 ULTRA KILL 💥", "emojis": "💥"},
        5: {"title": "💀 RAMPAGE 💀", "emojis": "💀"},
    },
    "epic": {
        2: {"title": "🌟 DOUBLE SLASH", "emojis": "⚡⚡"},
        3: {"title": "🌪️ WHIRLWIND TRIPLE", "emojis": "🌪️🌪️🌪️"},
        4: {"title": "🔥 BLAZING ULTRA", "emojis": "🔥🔥🔥"},
        5: {"title": "👑 LEGENDARY RAMPAGE", "emojis": "👑🔥👑"},
    },
    "tournament": {
        2: {"title": "⚡ 2 FRAGS", "emojis": "⚡"},
        3: {"title": "⚡ 3 FRAGS", "emojis": "⚡⚡"},
        4: {"title": "⚡ 4 FRAGS", "emojis": "⚡⚡⚡"},
        5: {"title": "⚡ 5 FRAGS", "emojis": "⚡⚡⚡⚡"},
    }
}

DEATHLESS_STYLES = {
    "classic": {
        3: {"title": "⚔️KILLING SPREE⚔️ ", "emojis": "⚔️"},
        4: {"title": "🔥 DOMINATING! 🔥", "emojis": "🔥"},
        5: {"title": "⚡️ MEGA KILL! ⚡️", "emojis": "⚡️"},
        6: {"title": "💥UNSTOPPABLE💥", "emojis": "💥"},
        7: {"title": "💀 WICKED SICK! 💀", "emojis": "💀"},
        8: {"title": "😈MONSTER KILL😈", "emojis": "😈"},
        9: {"title": "👑 GODLIKE!!! 👑", "emojis": "👑"},
    },
    "epic": {
        3: {"title": "⚔️ THEY’RE FALLING!", "emojis": "⚔️⚔️"},
        4: {"title": "⚡ GAINING MOMENTUM!", "emojis": "⚡⚡"},
        5: {"title": "🔥 ABSOLUTE DOMINANCE!", "emojis": "🔥🔥"},
        6: {"title": "🌪️ CAN’T BE STOPPED!", "emojis": "🌪️🌪️"},
        7: {"title": "😈 PURE CARNAGE!", "emojis": "😈🔥"},
        8: {"title": "💀 MONSTER OF THE ARENA!", "emojis": "💀👑"},
        9: {"title": "👑 THE GOD OF WAR!", "emojis": "👑✨"},
    }
}

def set_sounds_path(path):
    global SOUNDS_DIR
    SOUNDS_DIR = path
    if not os.path.isdir(SOUNDS_DIR):
        logging.warning(f"❗ Sounds directory does not exist: {SOUNDS_DIR}")
    else:
        logging.info(f"🎵 Using sounds from: {SOUNDS_DIR}")

async def send_killstreak_announcement(bot, killer: str, count: int):
    channel_id = get_announce_channel_id()
    if not channel_id:
        logging.warning("❗ Announce channel ID not set.")
        return

    channel = bot.get_channel(channel_id)
    if not channel:
        logging.warning(f"❗ Announce channel not found (ID: {channel_id}).")
        return

    style_name = get_announce_style()
    style = KILLSTREAK_STYLES.get(style_name)
    if not style:
        logging.warning(f"❗ Unknown announce style: {style_name}")
        return

    data = style.get(count)
    if not data:
        return  # Not announcing for this kill count

    # Getting information about the killer
    try:
        guild = channel.guild
        display = await resolve_display_data(killer, guild)
        name = display.get("display_name", killer)
        avatar_url = display.get("avatar_url")
        color = display.get("color", discord.Color.default())
    except Exception as e:
        logging.warning(f"⚠️ Could not resolve display data for {killer}: {e}")
        name = killer
        avatar_url = None
        color = discord.Color.default()

    # Creating an embed announcement
    try:
        embed = discord.Embed(
            title=data["title"],
            description=f"**{name.upper()}** is on a killstreak!",
            color=color
        )
        if avatar_url:
            embed.set_thumbnail(url=avatar_url)

        await channel.send(embed=embed)
        logging.info(f"📣 Killstreak embed announcement sent: {data['title']} by {name}")
    except Exception as e:
        logging.exception(f"❌ Failed to send killstreak embed announcement: {e}")

async def send_deathless_announcement(bot, killer: str, count: int):
    channel_id = get_announce_channel_id()
    if not channel_id:
        logging.warning("❗ Announce channel ID not set.")
        return

    channel = bot.get_channel(channel_id)
    if not channel:
        logging.warning(f"❗ Announce channel not found (ID: {channel_id}).")
        return

    style_name = get_announce_style()
    style = DEATHLESS_STYLES.get(style_name)
    if not style:
        logging.warning(f"❗ Unknown announce style for deathless streak: {style_name}")
        return

    data = style.get(count)
    if not data:
        return  # No announcement for this streak count

    # Getting information about the player
    try:
        guild = channel.guild
        display = await resolve_display_data(killer, guild)
        name = display.get("display_name", killer)
        avatar_url = display.get("avatar_url")
        color = display.get("color", discord.Color.default())
    except Exception as e:
        logging.warning(f"⚠️ Could not resolve display data for {killer}: {e}")
        name = killer
        avatar_url = None
        color = discord.Color.default()

    # Embed Create
    try:
        embed = discord.Embed(
            title=data["title"],
            description=f"**{name.upper()}** is on a deathless streak!",
            color=color
        )
        if avatar_url:
            embed.set_thumbnail(url=avatar_url)

        await channel.send(embed=embed)
        logging.info(f"📣 Deathless streak embed announcement sent: {data['title']} by {name}")
    except Exception as e:
        logging.exception(f"❌ Failed to send embed deathless streak announcement: {e}")

async def play_killstreak_sound(bot, count: int, guild: Optional[discord.Guild] = None, event_id: Optional[int] = None):
    if not SOUNDS_DIR:
        logging.error("❗ SOUNDS_DIR is not set.")
        return

    if guild is None:
        logging.warning("🔇 play_killstreak_sound: guild is None — cannot play sound.")
        return

    sound_map = {
        2: os.path.join(SOUNDS_DIR, "doublekill.wav"),
        3: os.path.join(SOUNDS_DIR, "triplekill.wav"),
        4: os.path.join(SOUNDS_DIR, "ultrakill.wav"),
        5: os.path.join(SOUNDS_DIR, "rampage.wav"),
    }
    sound_file = sound_map.get(count)
    if not sound_file or not os.path.isfile(sound_file):
        logging.warning(f"⚠️ Sound file not found: {sound_file}")
        return

    voice_client = discord.utils.get(bot.voice_clients, guild=guild)
    if not voice_client:
        logging.warning("🔇 Bot is not connected to a voice channel.")
        return
    # voice_client may be VoiceClient/VoiceProtocol — keep existing usage
    try:
        if voice_client.is_playing():
            voice_client.stop()
            logging.warning("⚠️ Stopped previous sound playback.")
    except Exception:
        # some voice backends may not expose is_playing; ignore
        pass

    try:
        enqueue_sound(guild, sound_file)
        logging.info(f"🔊 Playing sound: {sound_file}")
    except Exception as e:
        logging.exception("💥 Failed to play killstreak sound")

async def play_deathless_sound(bot, count: int, guild: Optional[discord.Guild] = None, event_id: Optional[int] = None):
    if not SOUNDS_DIR:
        logging.error("❗ SOUNDS_DIR is not set.")
        return

    if guild is None:
        logging.warning("🔇 play_deathless_sound: guild is None — cannot play sound.")
        return

    deathless_sound_map = {
        3: os.path.join(SOUNDS_DIR, "killing_spree.wav"),
        4: os.path.join(SOUNDS_DIR, "dominating.wav"),
        5: os.path.join(SOUNDS_DIR, "megakill.wav"),
        6: os.path.join(SOUNDS_DIR, "unstoppable.wav"),
        7: os.path.join(SOUNDS_DIR, "wickedsick.wav"),
        8: os.path.join(SOUNDS_DIR, "monsterkill.wav"),
        9: os.path.join(SOUNDS_DIR, "godlike.wav"),
    }

    sound_file = deathless_sound_map.get(count)
    if not sound_file or not os.path.isfile(sound_file):
        logging.warning(f"⚠️ Deathless sound file not found: {sound_file}")
        return

    voice_client = discord.utils.get(bot.voice_clients, guild=guild)
    if not voice_client:
        logging.warning("🔇 Bot is not connected to a voice channel.")
        return

    try:
        if voice_client.is_playing():
            voice_client.stop()
            logging.warning("⚠️ Stopped previous sound playback.")
    except Exception:
        pass

    try:
        enqueue_sound(guild, sound_file)
        logging.info(f"🔊 Playing deathless sound: {sound_file}")
    except Exception as e:
        logging.exception("💥 Failed to play deathless streak sound")

async def start_heartbeat_loop(bot, guild):
    if not SOUNDS_DIR:
        logging.error("❗ SOUNDS_DIR is not set.")
        return
    silent_path = os.path.join(SOUNDS_DIR, "silent.wav")
    if not os.path.isfile(silent_path):
        logging.warning("⚠️ Heartbeat sound (silent.wav) is missing.")
        return
    while True:
        await asyncio.sleep(60)
        voice_client = discord.utils.get(bot.voice_clients, guild=guild)
        if voice_client and not voice_client.is_playing():
            try:
                enqueue_sound(guild, silent_path)
                
                logging.debug("💤 Heartbeat: silent.wav played.")
            except Exception as e:
                logging.warning(f"⚠️ Heartbeat failed: {e}")
                await asyncio.sleep(10)
                
async def audio_queue_worker(bot: discord.Client, guild: discord.Guild):
    while True:
        queue = audio_queues[guild.id]
        voice_client = discord.utils.get(bot.voice_clients, guild=guild)

        if queue and isinstance(voice_client, VoiceClient) and not voice_client.is_playing():
            filepath = queue.popleft()
            try:
                source = SimpleAudioSource(filepath)
                voice_client.play(
                    source,
                    after=lambda e: logging.info(f"✅ Finished playing {filepath}") if not e else logging.error(f"🎧 Error: {e}")
                )
                logging.info(f"🔊 Playing from queue: {filepath}")
            except Exception:
                logging.exception(f"💥 Failed to play {filepath}")
        await asyncio.sleep(1)

def enqueue_sound(guild: discord.Guild, file_path: str):
    if os.path.isfile(file_path):
        audio_queues[guild.id].append(file_path)
        logging.info(f"🎶 Queued sound: {file_path}")

async def announce_streak_break(bot: discord.Client, character: str, guild: Optional[discord.Guild] = None, event_id: Optional[int] = None):
    """📣 Announcement of the interruption of the series of victories."""
    # Try to resolve announce channel for event if function supports it
    channel_id = None
    try:
        # If db has get_announce_channel_id(event_id) signature — use it
        channel_id = get_announce_channel_id(event_id)  # type: ignore
    except TypeError:
        # fallback to old signature
        try:
            channel_id = get_announce_channel_id()
        except Exception:
            channel_id = None
    except Exception:
        # any other error, try fallback
        try:
            channel_id = get_announce_channel_id()
        except Exception:
            channel_id = None

    if not channel_id:
        logging.warning("❗ Announce channel ID not set for streak break.")
        return

    channel = bot.get_channel(channel_id)
    if not channel or not isinstance(channel, discord.TextChannel):
        logging.warning(f"❗ Announce channel not found or not a TextChannel (ID: {channel_id}).")
        return

    # prefer guild from channel if none provided
    resolved_guild = guild or getattr(channel, "guild", None)

    try:
        # resolve_display_data now accepts Optional[Guild]
        display = await resolve_display_data(character, resolved_guild)
        name = display.get("display_name", character)
        avatar_url = display.get("avatar_url")
        color = display.get("color", discord.Color.red())
    except Exception as e:
        logging.warning(f"⚠️ Could not resolve display data for {character}: {e}")
        name = character
        avatar_url = None
        color = discord.Color.red()

    embed = discord.Embed(
        title="💀 STREAK BROKEN!",
        description=f"**{name.upper()}**'s killstreak has ended.",
        color=color
    )
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)

    try:
        await channel.send(embed=embed)
        logging.info(f"📣 Streak break embed sent for {name}")
    except Exception as e:
        logging.exception(f"❌ Failed to send streak break embed for {name}: {e}")

    # 🎵 Sound: try to enqueue in the channel's guild
    try:
        if SOUNDS_DIR and isinstance(SOUNDS_DIR, str):
            sound_file = os.path.join(SOUNDS_DIR, "obezhiren.wav")
            if os.path.isfile(sound_file):
                enqueue_sound(channel.guild, sound_file)
                logging.info(f"🔊 Queued sound for streak break: {sound_file}")
            else:
                logging.warning(f"⚠️ Streak break sound not found: {sound_file}")
        else:
            logging.warning("❗ SOUNDS_DIR not configured.")
    except Exception as e:
        logging.exception("❌ Failed to queue streak break sound")
