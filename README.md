#### 📄 `README.md`
## 🤖 Valheim PvP Bot

![Python](https://img.shields.io/badge/Python-3.9-blue)
![License](https://img.shields.io/github/license/ksenobite/valheim_bot)
![Repo Size](https://img.shields.io/github/repo-size/ksenobite/valheim_bot)

A feature-rich Discord bot for Valheim PvP communities. Tracks killstreaks, announces frags with sound effects, manages roles based on weekly performance, and provides in-depth statistics.

⚠️ **Requires integration with KillFeed messages** from the Valheim PvP Tweaks mod by Tristan (for example, lines such as `Player A is killed by Player B` in a special Discord channel are configured via a webhook; see the documentation for the Valheim PvP Tweaks mod).

## 🎨 Features
- ✅ Automatic kill tracking & killstreak recognition
- 🔥 **Killstreaks + Deathless streaks** (Dota2-style multi-level system)
- 🔊 Sound announcements with **dynamic queue playback**
- 🖼️ Stylish embeds with **avatars**, **role-colored names**, **emojis**
- 📊 Player stats: `/stats`, `/top`, `/mystats`, `/whois`
- 👑 PvP role assignment by weekly win count (**fully configurable**)
- ♻️ Auto-role system with toggle and rolling window setting
- 🛠 Full set of admin slash commands
- 💾 Lightweight SQLite backend
- 🧱 Works standalone (`main.exe`) via Nuitka + `opus.dll`

## 🧰 Setup Instructions
1. **Create `.env`** 
- Create file manually in the project root
- Place your token in the file in the format: `DISCORD_TOKEN=your_discord_token`
2. **Add database file**
- If you don't have a database yet, it will be created automatically.
- If you already have a database frags.db you can add it to the root of the project.
3. **Add sound files** 
- If you want to change the preset settings copy files to /sounds directory in `WAV (PCM, 48 kHz stereo)` format.
- The files must keep the original names:
        ```doublekill.wav```, ```triplekill.wav```, ```ultrakill.wav```, ```rampage.wav```, ```silent.wav``` (mute file to keep the bot in the voice channel) etc.
4. **Install Python dependencies**:
```bash
pip install -r requirements.txt
```
5. **Run the bot**
- ⚙️ `main.exe` (Standalone Executable)

## 🧱 **Requirements**
- Python 3.9+ (requires installation)
- Nuitka (requires installation)
- opus.dll in the project root (it is already present in the source code of the project)
- repear.ico for custom  (it is already present in the source code of the project)

## 🔨 **Build**
Run build.bat. It will:
- assemble the project in main.exe
- include /sounds/ directory and opus.dll
- exclude .env and frags.db for safety (user adds them after build)
- for Windows OS, you can use `build.bat` for building in the root of the project

**After building**, manually copy
- .env
- frags.db (if there is no database, it will be created automatically.)
Into the output directory next to `main.exe`

## 👑 **Role System**
Roles are assigned automatically based on player performance:
Update roles with /forceroleupdate or schedule it programmatically.
💡 The victory role system has been updated and can now work with any existing roles on your discord server.

## 🎭 **Authors**
- Development: @ksn
- Masterminds: @Gurney, @Gloom
- Structure & Optimization: ChatGPT 😍