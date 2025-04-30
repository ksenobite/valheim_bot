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

1. Create `.env` and set your `DISCORD_TOKEN=your_token`.
2. Place your sound files in `sounds/` (WAV PCM, 48000 Hz, stereo).
3. Install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run with:
    ```bash
    python main.py
    ```

Or build with build.bat via Nuitka.

## Build Requirements

- Python 3.9+
- Nuitka
- opus.dll in project root

## 📁 Project structure

- `bot/` — sources:
  - `main.py ` — main file of the bot
  - `db.py ` — working with the database
  - `killstreaks.py ` — sound effects ans messages
- `sounds/` — WAV files of frags sounds
- `.env` — token and environment variables (in .gitignore)
- `frags.db` — SQLite database (in .gitignore)
- `opus.dll ` — Opus library for playback
- `build.bat` — build script via Nuitka
- `README.md ` — project description
- `CHANGELOG.md ` — change log

## 🎭 The authors

Development: @ksn
Architecture & assembly: ChatGPT
Mastermind: @Gurney