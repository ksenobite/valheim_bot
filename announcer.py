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

from db import get_event_channel
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

# --- 🎶 Titles (fixed)

KILLSTREAK_TITLES = {
    2: "🔥 DOUBLE KILL 🔥",
    3: "⚡️ TRIPLE KILL ⚡️",
    4: "💥 ULTRA KILL 💥",
    5: "💀 RAMPAGE 💀",
}

DEATHLESS_TITLES = {
    3: "⚔️KILLING SPREE⚔️ ",
    4: "🔥 DOMINATING! 🔥",
    5: "⚡️ MEGA KILL! ⚡️",
    6: "💥UNSTOPPABLE💥",
    7: "💀 WICKED SICK! 💀",
    8: "😈MONSTER KILL😈",
    9: "👑 GODLIKE!!! 👑",
}

def set_sounds_path(path):
    global SOUNDS_DIR
    SOUNDS_DIR = path
    if not os.path.isdir(SOUNDS_DIR):
        logging.warning(f"❗ Sounds directory does not exist: {SOUNDS_DIR}")
    else:
        logging.info(f"🎵 Using sounds from: {SOUNDS_DIR}")

async def send_killstreak_announcement(
    bot: discord.Client,
    killer: str,
    streak_count: int,
    guild: Optional[discord.Guild] = None,
    event_id: Optional[int] = None
):
    """📣 Announcement about killstreaks (double kill, triple kill, etc.)"""

    logging.info(f"[KILLSTREAK] called for killer={killer}, streak={streak_count}, event_id={event_id}")

    channel_id = None
    try:
        channel_id = get_event_channel(int(event_id), "announce") if event_id else None
        logging.debug(f"[KILLSTREAK] get_event_channel(event_id={event_id}, 'announce') -> {channel_id}")
    except Exception as e:
        logging.exception(f"[KILLSTREAK] Failed to resolve announce channel for event_id={event_id}: {e}")

    if not channel_id:
        logging.warning(f"[KILLSTREAK] ❗ Announce channel ID not set (event_id={event_id})")
        return

    channel = bot.get_channel(channel_id)
    logging.debug(f"[KILLSTREAK] bot.get_channel({channel_id}) -> {channel}")

    if not channel or not isinstance(channel, discord.TextChannel):
        logging.warning(f"[KILLSTREAK] ❗ Announce channel not found or not a TextChannel (ID: {channel_id})")
        return

    resolved_guild = guild or getattr(channel, "guild", None)
    logging.debug(f"[KILLSTREAK] resolved guild -> {resolved_guild}")

    try:
        display = await resolve_display_data(killer, resolved_guild)
        logging.debug(f"[KILLSTREAK] resolve_display_data({killer}) -> {display}")
        name = display.get("display_name", killer)
        avatar_url = display.get("avatar_url")
        color = display.get("color", discord.Color.orange())
    except Exception as e:
        logging.warning(f"[KILLSTREAK] ⚠️ Could not resolve display data for {killer}: {e}")
        name = killer
        avatar_url = None
        color = discord.Color.orange()

    # Title by fixed map; fallback to generic if missing
    title = KILLSTREAK_TITLES.get(streak_count, f"🔥 {streak_count} KILL STREAK!")
    description = f"**{name.upper()}** is on a killstreak: `{streak_count}`"
    embed = discord.Embed(title=title, description=description, color=color)
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)

    try:
        await channel.send(embed=embed)
        logging.info(f"[KILLSTREAK] 📣 Killstreak embed sent for {name} to channel {channel.id}")
    except Exception as e:
        logging.exception(f"[KILLSTREAK] ❌ Failed to send killstreak embed for {name}: {e}")

    # 🎵 Sound (only if needed)
    try:
        if SOUNDS_DIR and isinstance(SOUNDS_DIR, str):
            logging.debug(f"[KILLSTREAK] Sound dir = {SOUNDS_DIR}, streak_count={streak_count}")
            await play_killstreak_sound(bot, streak_count, resolved_guild)
        else:
            logging.warning("[KILLSTREAK] ❗ SOUNDS_DIR not configured.")
    except Exception as e:
        logging.exception("[KILLSTREAK] ❌ Failed to play killstreak sound")

async def send_deathless_announcement(
    bot: discord.Client,
    killer: str,
    count: int,
    guild: Optional[discord.Guild] = None,
    event_id: Optional[int] = None
):
    """📣 Announce when a player reaches a deathless streak."""

    logging.info(f"[DEATHLESS] called for killer={killer}, count={count}, event_id={event_id}")

    # --- Find channel ---
    channel_id = None
    try:
        if event_id is not None:
            channel_id = get_event_channel(event_id, "announce")
            logging.debug(f"[DEATHLESS] get_event_channel(event_id={event_id}, 'announce') -> {channel_id}")
        else:
            channel_id = None
    except Exception as e:
        logging.exception(f"[DEATHLESS] Failed to resolve announce channel (event_id={event_id}): {e}")

    if not channel_id:
        logging.warning(f"[DEATHLESS] ❗ Announce channel ID not set (event_id={event_id})")
        return

    channel = bot.get_channel(channel_id)
    logging.debug(f"[DEATHLESS] bot.get_channel({channel_id}) -> {channel}")

    if not channel or not isinstance(channel, discord.TextChannel):
        logging.warning(f"[DEATHLESS] ❗ Announce channel not found or not a TextChannel (ID={channel_id})")
        return

    # --- Fixed titles ---
    title = DEATHLESS_TITLES.get(count)
    if not title:
        logging.debug(f"[DEATHLESS] No announcement for streak count={count}")
        return

    # --- Player display ---
    resolved_guild = guild or channel.guild
    try:
        display = await resolve_display_data(killer, resolved_guild)
        logging.debug(f"[DEATHLESS] resolve_display_data({killer}) -> {display}")
        name = display.get("display_name", killer)
        avatar_url = display.get("avatar_url")
        color = display.get("color", discord.Color.default())
    except Exception as e:
        logging.warning(f"[DEATHLESS] ⚠️ Could not resolve display data for {killer}: {e}")
        name = killer
        avatar_url = None
        color = discord.Color.default()

    # --- Embed ---
    description = f"**{name.upper()}** is on a deathless streak: `{count}`"
    embed = discord.Embed(title=title, description=description, color=color)
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)

    try:
        await channel.send(embed=embed)
        logging.info(f"[DEATHLESS] 📣 Deathless streak embed sent: {title} by {name} to channel {channel.id}")
    except Exception as e:
        logging.exception(f"[DEATHLESS] ❌ Failed to send embed deathless streak announcement: {e}")

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

async def announce_streak_break(
    bot: discord.Client,
    character: str,
    guild: Optional[discord.Guild] = None,
    event_id: Optional[int] = None
):
    """📣 Announcement of the interruption of the series of victories."""

    logging.info(f"[STREAK_BREAK] called for char={character}, event_id={event_id}")

    channel_id = None
    try:
        channel_id = get_event_channel(int(event_id), "announce") if event_id else None
        logging.debug(f"[STREAK_BREAK] get_event_channel(event_id={event_id}, 'announce') -> {channel_id}")
    except Exception as e:
        logging.exception(f"[STREAK_BREAK] Failed to resolve announce channel for event_id={event_id}: {e}")

    if not channel_id:
        logging.warning(f"[STREAK_BREAK] ❗ Announce channel ID not set (event_id={event_id})")
        return

    channel = bot.get_channel(channel_id)
    logging.debug(f"[STREAK_BREAK] bot.get_channel({channel_id}) -> {channel}")

    if not channel or not isinstance(channel, discord.TextChannel):
        logging.warning(f"[STREAK_BREAK] ❗ Announce channel not found or not a TextChannel (ID: {channel_id})")
        return

    # prefer guild from channel if none provided
    resolved_guild = guild or getattr(channel, "guild", None)
    logging.debug(f"[STREAK_BREAK] resolved guild -> {resolved_guild}")

    try:
        display = await resolve_display_data(character, resolved_guild)
        logging.debug(f"[STREAK_BREAK] resolve_display_data({character}) -> {display}")
        name = display.get("display_name", character)
        avatar_url = display.get("avatar_url")
        color = display.get("color", discord.Color.red())
    except Exception as e:
        logging.warning(f"[STREAK_BREAK] ⚠️ Could not resolve display data for {character}: {e}")
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
        logging.info(f"[STREAK_BREAK] 📣 Embed sent for {name} to channel {channel.id}")
    except Exception as e:
        logging.exception(f"[STREAK_BREAK] ❌ Failed to send streak break embed for {name}: {e}")

    # 🎵 Sound
    try:
        if SOUNDS_DIR and isinstance(SOUNDS_DIR, str):
            sound_file = os.path.join(SOUNDS_DIR, "obezhiren.wav")
            logging.debug(f"[STREAK_BREAK] Checking sound file: {sound_file}")
            if os.path.isfile(sound_file):
                enqueue_sound(channel.guild, sound_file)
                logging.info(f"[STREAK_BREAK] 🔊 Queued sound for streak break: {sound_file}")
            else:
                logging.warning(f"[STREAK_BREAK] ⚠️ Streak break sound not found: {sound_file}")
        else:
            logging.warning("[STREAK_BREAK] ❗ SOUNDS_DIR not configured.")
    except Exception as e:
        logging.exception("[STREAK_BREAK] ❌ Failed to queue streak break sound")
