@echo off
title ⚙️ Building Discord Bot with Nuitka (Standalone - WAV Support)

set ENTRY=bot/main.py

if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

nuitka ^
  --standalone ^
  --follow-imports ^
  --enable-plugin=multiprocessing ^
  --output-dir=dist ^
  --remove-output ^
  --include-data-dir=sounds=sounds ^
  --include-data-file=.env=.env ^
  --include-data-file=frags.db=frags.db ^
  --include-data-file=opus.dll=opus.dll ^
  --windows-icon-from-ico=repear.ico ^
  %ENTRY%

echo.
echo ✅ Build complete!
echo Output: dist\main.dist\main.exe
pause
