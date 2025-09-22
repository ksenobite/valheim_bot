#### 📄 `CHANGELOG.md`
```markdown

## v8.1.0 — 2025-09-22
### Added
- 🌐 **Fully event-aware architecture**: Bot now fully supports multiple events across all features.
- 🎯 **Event-aware ratings and roles**: Ratings and role assignments now track per event.
- 📋 **Event names in stat headers**: Stats output (e.g., `/top`, `/topmmr`) includes event names in headers.
- 🔒 **Data validation**: Added protection against invalid input data.
- 🐍 **Python 3.12+ compatibility**: Fixed deprecation warnings for Python 3.12 and higher.
- 📝 **Improved logging**: Enhanced logging for better debugging and tracking.
### Fixed
- 🐛 **Minor bug fixes**: Resolved small issues for improved stability.
### Migration Notes
- ⚠️ Users upgrading from v8.0.0+ should ensure their database reflects the new event-aware structure.
- 📌 If issues arise, back up your `frags.db`, delete it, and let the bot recreate a fresh database on startup.

## v8.0.0 — 2025-09-18
### Added
- 🏟️ **Events support**:
  - The bot can now be linked to multiple PvP events (e.g., different arenas or tournaments).
  - Each event is associated with its own text channel and webhook.
  - Stats commands (`/top`, `/topmmr`, `/mystats`, `/stats`) now include an `event` parameter to filter results per event.
  - If the parameter is not specified, the **default event** (`arena`) is used.
  - 👑 **Roles** are still assigned **only for the default event**.

- 🆕 New admin commands:
  - `/createevent` — create a new event.
  - `/setchannel` — bind a channel to an event (both track+announce).
  - `/clearchannel` — unbind a channel from an event.
  - `/listevents` — list all events with their assigned channels.

### Changed
- 🔄 Announcement logic refactored: `track` and `announce` have been merged into the `/setchannel` command.
- ✏️ Removed deprecated commands:
  - `/style`
  - `/announce` (replaced by `/setchannel`)
  - `/track` (replaced by `/setchannel`)

### Fixed
- 🐛 Fixed desynchronization between **online MMR calculation** (real-time) and deep analysis (`/mmrsync`).
  - Now `/mmrsync` is only required after a reset (`/mmrclear`) or when restoring the database from a backup.

### Migration Notes
- ⚠️ Users with **legacy databases** are strongly advised to:
  - Make a backup,
  - Delete the old database,
  - Let the bot create a fresh one on startup.
- 📌 Reason: migrating from the old schema to the new event model is complex and may cause errors.

## v7.0.0 — 2025-06-20
### Added
- 📈 Advanced **matchmaking rating system** (Glicko-2): rating, deviation (RD), and volatility
- 🧮 New rating commands:
  - `/topmmr`, `/mmr`, `/mmrlog`, `/mmrsync`, `/mmrclear`
- 👑 Role assignment based on MMR:
  - `/mmrroles`, `/mmrroleset`, `/mmrroleupdate`, `/mmrroleclear`
- 🧾 MMR history logging via `glicko_history` table
- 📊 Rating info integrated into `/top`, `/stats`, `/mystats`
- 💀 New streak-break announcements:
  - Dynamic embed and `obezhiren.wav` sound when a streak ends

### Changed
- ✏️ Default rating display now shows MMR (instead of legacy Elo)
- 🧹 Removed legacy logic:
  - `ratings` table, `update_mmr`, `apply_decay`, and related functions
- 📉 Deprecated the old point-based auto-role system
- 🧼 Removed commands:
  - `/autoroles`, `/autorolestatus`, `/autoroletimeout`
- 🧱 Updated build pipeline:
  - Python 3.13.5 + virtual environment
  - Nuitka 2.7 compatibility with standalone assets

### Fixed
- 🐛 Resolved all `Pylance` and typing warnings (`guild_permissions`, `send`, etc.)
- 🔒 Improved guild/context checks and error handling across commands

## v6.5.0 — 2025-05–27
- ➕ New command: `/points`
  - Allows admins to manually add or subtract points (wins) from characters or users.
  - Supports flexible adjustments with reason logging for transparency.
  - Accepts both character names and user mentions.

- ➕ New command: `/pointlog`
  - Shows history of manual adjustments for a user or character.
  - Displays reason, timestamp, and point delta.
  - Supports both character names and @user mentions.

- 📊 Stats & Rankings:
  - `/top`, `/stats`, and `/mystats` now display total points: frags + extrapoints.
  - `/top` is now sorted by **total points**, not just raw frags.
  - `/stats` and `/mystats` now show detailed stats vs opponents:
    - Wins, losses, winrate %, and new **win/loss ratio** (`winlos`).
    - Emoji-based rating indicators based on winrate.
  - Added protection against division by zero (e.g. when losses = 0).
  - Now shows summary totals including total wins/losses, winrate %, and extra points.

- 👑 Role system:
  - `/roleupdate` now assigns roles based on **total points**, including manual adjustments.
  - Users with negative point totals now receive the 0-point role (e.g. “Покончил с PvP”).

- 🔧 UX Improvements:
  - `/mystats` and `/stats` now handle pagination and edge cases more gracefully.
  - Improved error handling for characters without Discord owners.

- 🛠️ Internal refactoring:
  - Introduced `get_total_wins()` and `get_win_sources()` for consistent point calculations.
  - `generate_stats_embeds()` updated with proper pagination guards and async UI logic.

## v6.4.0 — 2025-05-22
- 📌 Improved `/whois` command:
  - Now supports both character names and user mentions (@user).
  - Shows who owns a character, or which characters are linked to a user.
  - Includes avatars and beautiful embed formatting.

- 🐛 Bugfixes:
  - Fixed error when fetching character owners with invalid Discord IDs.
  - Resolved edge case where empty or unlinked inputs caused silent failures.

- 🎨 Design Enhancements:
  - Embed output now includes avatars and structured layout for better readability.
  - Emoji icons for linked characters and owners add visual clarity.

## v6.3.0 — 2025-05-16
- 🖼️ Redesigned `/stats` and `/mystats`:
  - Avatars, role-colored usernames, and emojis are now shown in embeds.
  - Pagination added for long lists via interactive buttons.
  - Displayed stats are now more readable and informative.
- 🐛 Fixed interaction issues (`InteractionResponded`) during pagination.
- 🔁 Updated `PaginatedStatsView` to support user-friendly navigation and footer page numbering.

## v6.2.0 — 2025-05-15
- 🛠 Fixed a bug where "deathless streaks" were not reset on solo deaths.
- ➕ Added support for parsing death messages like `X is dead`, which now correctly resets the deathless streak.
- 💬 Logging improved for solo deaths and edge cases.

## v6.1.0 — 2025-05-15
- ✨ **New Feature: Deathless Streaks**
  - The bot now tracks “clean” killstreaks (until first death).
  - Stylish text and embed announcements with customizable styles.
  - Planned: sound support for deathless streaks.

- 🔊 **Sound System Improvements**
  - Sound playback is now queued to prevent overlapping killstreak and deathless sounds.

- 📣 **Killstreak Announcements Improved**
  - Embed format with Discord user name, avatar, color, and role.
  - Now works even if character is not linked to a Discord user.

- ⚙️ **New Auto-Role Features**
  - New commands added:
    - `/autoroles` — Enable or disable automatic role updates
    - `/autorolestatus` — Show current auto-role status
    - `/autoroletimeout` — Configure win window (in days) for roles

- 🧼 General fixes and logging improvements


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
