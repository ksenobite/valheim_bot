# 🤖 Valheim PvP Bot

A feature-rich Discord bot for Valheim PvP communities. Tracks killstreaks, announces frags with sound effects, manages roles based on weekly performance, and provides in-depth statistics.

⚠️ **Requires integration with KillFeed messages** from the Valheim PvP Tweaks mod by Tristan (for example, lines such as `Player A is killed by Player B` in a special Discord channel are configured via a webhook; see the documentation for the Valheim PvP Tweaks mod).

## 🎨 Features

- ✅ Automatic kill tracking & killstreak recognition
- 🔊 Dynamic sound announcements (doublekill, triplekill, etc.)
- 📊 Player stats: `/stats`, `/top`, `/mystats`, `/whois`
- 👑 Automatic role assignment by weekly win count
- 🎨 Custom killstreak styles: classic, epic, tournament
- 🛠 Full set of admin slash commands
- 💾 SQLite database backend

## 🧰 Setup Instructions

1. **Create `.env`** file manually in the project root:
    DISCORD_TOKEN=your_discord_token_here

2. **Add or generate your database file** as `frags.db` (will be created on first run if missing).

3. **Install Python dependencies**:
```bash
pip install -r requirements.txt
```

4. **Add sound files** (if you want to change the preset settings) to /sounds directory in WAV (PCM, 48 kHz stereo) format.
    The files must keep the original names:
        ```doublekill.wav```, ```triplekill.wav```, ```ultrakill.wav```, ```rampage.wav```, ```silent.wav``` (mute file to keep the bot in the voice channel).
    
5. **Run the bot:**
    ⚙️ Build (Standalone Executable)
    To create a standalone .exe:

🧱 **Requirements:**
- Python 3.9+ (requires installation)
- Nuitka (requires installation)
- opus.dll in the project root (it is already present in the source code of the project)
- repear.ico for custom  (it is already present in the source code of the project)

🔨 **Build**
Run build.bat. It will:
- compile main.py into a standalone .exe
- include /sounds/ directory and opus.dll
- exclude .env and frags.db for safety (user adds them after build)

**After building, manually copy:**
- .env
- frags.db (if there is no database, it will be created automatically.)
Into the output directory next to `main.exe`.

📁 **Project Structure**

valheim_bot/
│
├── main.py               # Entry point
├── commands.py           # Slash commands
├── announcer.py          # Killstreak sounds and messages
├── roles.py              # Role assignment logic
├── utils.py              # Shared utilities
├── db.py                 # SQLite interface
├── settings.py           # Path utils and constants
│
├── frags.db              # SQLite database (user-supplied)
├── .env                  # Discord bot token (user-supplied)
├── requirements.txt      # Python dependencies
├── build.bat             # Standalone builder via Nuitka
├── opus.dll              # Required for voice playback
├── repear.ico            # App icon
│
├── sounds/               # Killstreak sound files (WAV)
├── db_backups/           # Automatic backups via /reset
├── README.md             # This file
├── CHANGELOG.md          # Version log

👑 **Role System (Weekly Wins)**
Roles are assigned automatically based on player performance (roles can be changed on request.):

- `Смертельно опасен`:	400+	Violet
- `Убить лишь завидев`:	300+	Magenta
- `Опасен`:	200+	Orange
- `Мужчина`:	100+	Gold
- `Подает надежды`:	25+	Green
- `Не опасен`:	5+	Light grey
- `Покончил с PvP`:	0	Dark grey

Update roles with /forceroleupdate or schedule it programmatically.

🎭 **Authors**
- Development: @ksn
- Masterminds: @Gurney, @Gloom
- Structure & Optimization: ChatGPT 😍