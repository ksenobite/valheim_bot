# Valheim Bot

A feature-rich Discord bot that tracks killstreaks in PvP messages and plays dynamic sound announcements.
Attention! The bot only works in conjunction with the Valheim PvP Tweaks by Tristan mod and the configured KillFeed channel in Discord (see Valheim PvP Tweaks settings).

## Features

- ✅ Killstreak detection with timeout
- 🔊 Sound playback using `opus.dll` and raw PCM `.wav` files
- 🗂️ Player statistics & `/top`, `/stats` commands
- 🎨 Custom killstreak announce styles
- 🛠 Slash commands for admins and users
- 💾 SQLite support

## Setup Instructions

1. Copy `.env.example` → `.env` and set your `DISCORD_TOKEN`.
2. Place your sound files in `sounds/` (WAV PCM, 48000 Hz, stereo).
3. Run with:

```bash
python main.py
```

Or build with build.bat via Nuitka.

## Build Requirements

- Python 3.9+
- Nuitka
- opus.dll in project root

## Project Structure

valheim_bot/
├── src/
│   ├── main.py
│   ├── db.py
│   └── killstreaks.py
├── sounds/
├── .env
├── frags.db
├── opus.dll
├── build.bat
├── README.md
└── CHANGELOG.md
