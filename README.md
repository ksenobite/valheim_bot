## 🤖 Valheim PvP Bot

![Python](https://img.shields.io/badge/Python-3.13-blue)
![License](https://img.shields.io/github/license/ksenobite/valheim_bot)
![Repo Size](https://img.shields.io/github/repo-size/ksenobite/valheim_bot)

A feature-rich Discord bot for Valheim PvP communities. Tracks kills, announces streaks with sound effects, manages roles, and provides rich player statistics.

> ⚠️ **Requires integration with KillFeed messages** from the Valheim PvP Tweaks mod (e.g. "Player A is killed by Player B"). Killfeed must be forwarded to a dedicated text channel via webhook.

---

## 🎨 Features

- ✅ Automatic kill tracking and multi-kill recognition
- 🔥 Killstreaks + deathless streaks with voice + embed alerts
- 💀 Streak break detection (embed + dynamic `obezhiren.wav` sound)
- 🔊 Voice announcements with dynamic sound queueing
- 🖼️ Rich embeds with avatars, role-colored names, emojis
- 📊 Player stats: `/top`, `/mystats`, `/stats`, `/topmmr`
- 📈 Matchmaking rating (MMR) system with rating deviation (RD) and volatility
- 🧮 Manual and historical rating adjustment via `/mmr`, `/mmrsync`, `/mmrlog`
- 👑 Role assignment based on MMR or kill count
- ✍️ Fully configurable role thresholds via `/roleset`, `/mmrroleset`
- 🛠 Admin commands for linking, resetting, adjusting
- 💾 Lightweight SQLite backend
- 🧱 Self-contained build via Nuitka (`main.exe`)

---

## 📈 Rating System (MMR)

This bot uses an advanced **matchmaking rating system** based on [Glicko-2 principles](https://www.glicko.net/glicko.html), including:

- Automatic updates after each frag
- Rating deviation and volatility per player
- Manual rating adjustments: `/mmr`
- Full history replay and resync: `/mmrsync`
- Role assignment based on rating: `/mmrroles`, `/mmrroleupdate`
- Transparent rating history: `/mmrlog`

---

## 👑 Role System

Two parallel systems are supported:

### 1. MMR-based roles
- Assign roles based on rating thresholds
- Commands: `/mmrroleset`, `/mmrroleupdate`, `/mmrroles`, `/mmrroleclear`

### 2. Points-based roles
- Based on total frags + manual bonus points
- Manual control: `/roleset`, `/roleupdate`, `/roles`, `/roleclear`

---

## 🧰 Setup Instructions

1. **Create your bot on [Discord Developers](https://discord.com/developers/applications)**
   - Save the token in a `.env` file:  
     ```
     DISCORD_TOKEN=your_token_here
     ```

2. **Prepare database**
   - A new `frags.db` will be created automatically if missing
   - Or place your own copy in the project root

3. **Add sound effects**
   - WAV files (`48kHz PCM stereo`) go in the `/sounds` folder
   - Required filenames:
     ```
     doublekill.wav, triplekill.wav, ultrakill.wav, rampage.wav, silent.wav, obezhiren.wav
     ```

4. **Run the bot**
   - Execute: `main.exe` (after build)

---

## 🧱 Requirements

- Python **3.13.5**
- Nuitka **2.7+**
- `opus.dll` (already included)
- Microsoft Visual Studio Build Tools (C/C++ compiler)
- PyNaCl (for voice playback)

---

## 🔨 Build Instructions

Use `build.bat` to create a standalone executable (`main.exe`):

- Compiles all source files
- Includes `/sounds/` and `opus.dll`
- Excludes sensitive files (`.env`, `frags.db`)

After build:
- Manually copy:
  - `.env`
  - `frags.db` (optional — will be auto-created)
- Launch: `main.exe`

---

## 🎭 Authors

- Core Development: **@ksn**
- Coordination: **@Gurney**, **@Gloom**
- Engineering Support: **ChatGPT** 🤖
