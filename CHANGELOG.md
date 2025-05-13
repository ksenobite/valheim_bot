#### 📄 `CHANGELOG.md`
```markdown

## v6.0.0 — 2025-05-13
- 🔄 **Complete redesign of the system of ranked roles**
- The old hard-coded list of `ROLE_THRESHOLES` has been deleted.
  - Roles are now configured via the commands `/roleset`, `/roleclear`, `/roles`.
  - The configuration is stored in the database and does not depend on the language or names on the server.

- ⚙️ **A system for auto-updating roles has been introduced**
- New commands: `/autoroles`, `/autorolestatus`, `/autoroletimeout'.
  - The bot can automatically assign PvP roles for each update based on the number of wins in the last N days.

- ✨ **Updated team names to improve UX**
  - Short and easy-to-remember commands: `/link`, `/unlink`, `/roleset`, `/roleupdate`, `/roles`, etc.
  - '/helpme` now displays commands in an improved readable form.

- 🧠 **Updated the logic of determining the role by wins**
- Roles are selected dynamically, taking into account the current configuration.

- Outdated code and dependencies have been removed:
- The old binding functions to `ROLE_THRESHOLES` are no longer used.
  - Cleaning `roles.py `, `utils.py `, removed unnecessary imports and logic.

- Improved stability and convenience of project expansion in the future.

## v5.0.1 — 2025-05-10
- Complete refactoring of the project: the code is divided into modules (`main.py `, `commands.py `, `roles.py `, `announcer.py `, `utils.py `, `settings.py `)
- 🛠 Fixed critical errors in updating roles — the bot handles guild members correctly
- 🔔 The trigger for KillFeed messages has been restored (`on_message`)
- 🔊 The voiceover of murder sequences has been fixed (support for `.wav`, interaction with voice channels)
- Improved statistics output: color, roles, avatars
- 🧱 The build system has been updated (`.env` and `frags.db` are excluded, new structure)
- 📁 README.md and `build.bat` adapted to the new architecture
- Outdated deleted `killstreaks.py`

## v5.0.0 — 2025-05-05
- 🥳 😍 🤖 Added Discord user role management by bot!

## v4.4.0 — 2025-05-04
- Discord user names and avatars are now displayed in the statistics
- User role definition and coloring support

## v4.3.0 — 2025-05-03
- Added the bot version to the `/helpme` embed footer.
- The database structure has been changed.
- Improved logging
- Improved output of user statistics
- Additional error handling

## v4.2.0 — 2025-05-02
- New admin commands (`/linkcharacter`, `/unlinkcharacter`) so that you can establish a match between the game character and the Discord user.
- Updated user commands (`/stats`, `/mystats`) for viewing statistics.
- /stats command now accepts both the character_name and the @discord_user.

## v4.1.0 — 2025-05-01
- The project structure has been simplified.
- The code was refactored.
- The heartbeat feature has been added so that the bot does not disconnect from the voice channel without a command.

## v4.0.0 — 2025-04-30
- 🎧 Switched to native PCM WAV playback with opus.dll
- 🧹 Cleaned up killstreak system
- 🛠 Refactored sound engine for stability post-Nuitka
- 🐞 Fixed playback issues in compiled .exe builds

## v3.9.0
- Added multi-style killstreak announcements
- Initial slash command support
