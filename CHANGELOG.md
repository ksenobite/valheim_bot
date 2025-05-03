#### 📄 `CHANGELOG.md`
```markdown


## v4.3.0 — 2025-05-03
- Added the bot version to the `/helpme` embed footer.

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
