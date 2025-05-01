# -*- coding: utf-8 -*-

import os
import asyncio
import wave
import discord
import logging
from db import get_announce_channel_id, get_announce_style


SOUNDS_DIR = None

# 🎶 Frags Styles
KILLSTREAK_STYLES = {
    "classic": {
        2: {"title": "⚡ DOUBLE KILL", "emojis": "⚔️⚔️"},
        3: {"title": "🔥 TRIPLE KILL", "emojis": "🔥☠️"},
        4: {"title": "💀 ULTRA KILL", "emojis": "💀💀"},
        5: {"title": "👑 RAMPAGE", "emojis": "🔥👑"},
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


# 📦 Custom PCM audio source from WAV

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

def set_sounds_path(path):
    global SOUNDS_DIR
    SOUNDS_DIR = path
    logging.info(f"🎵 Using sounds from: {SOUNDS_DIR}")


async def send_killstreak_announcement(bot, killer: str, count: int):
    announce_channel_id = get_announce_channel_id()
    if not announce_channel_id:
        logging.warning("Announce channel not set.")
        return

    channel = bot.get_channel(announce_channel_id)
    if not channel:
        logging.warning("Announce channel not found.")
        return

    style = KILLSTREAK_STYLES.get(get_announce_style(), {})
    data = style.get(count)
    if data:
        await channel.send(f"{data['title']} by {killer}! {data['emojis']}")


async def play_killstreak_sound(bot, count: int, guild: discord.Guild):
    if not SOUNDS_DIR:
        logging.error("SOUNDS_DIR not set.")
        return

    voice_client = discord.utils.get(bot.voice_clients, guild=guild)
    if not voice_client:
        logging.warning("🔇 Bot is not connected to a voice channel.")
        return

    sound_map = {
        2: os.path.join(SOUNDS_DIR, "doublekill.wav"),
        3: os.path.join(SOUNDS_DIR, "triplekill.wav"),
        4: os.path.join(SOUNDS_DIR, "ultrakill.wav"),
        5: os.path.join(SOUNDS_DIR, "rampage.wav"),
    }

    sound_file = sound_map.get(count)
    if not sound_file or not os.path.isfile(sound_file):
        logging.error(f"❌ Sound file not found: {sound_file}")
        return

    if voice_client.is_playing():
        voice_client.stop()
        logging.warning("⚠ Already playing sound.")
        return

    try:
        logging.info(f"🔊 Playing sound: {sound_file}")
        source = SimpleAudioSource(sound_file)
        voice_client.play(source, after=lambda e: logging.info(f"✅ Playback complete. Error: {e}" if e else "✅ Sound finished."))
    except Exception as e:
        logging.exception("💥 Playback failed")


async def start_heartbeat_loop(bot, guild):
    silent_path = os.path.join(SOUNDS_DIR, "silent.wav")
    while True:
        await asyncio.sleep(60)  # Every minute
        voice_client = discord.utils.get(bot.voice_clients, guild=guild)
        if voice_client and not voice_client.is_playing():
            try:
                source = SimpleAudioSource(silent_path)
                voice_client.play(source)
                logging.debug("💤 Heartbeat: silent.wav played.")
            except Exception as e:
                logging.warning(f"⚠️ Heartbeat failed: {e}")
                await asyncio.sleep(10)  # Prevent spamming in case of repeated failure
