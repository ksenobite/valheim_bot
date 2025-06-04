@REM build.bat
@echo off
title ⚙️ Building Discord Bot with Nuitka (Standalone - WAV Support)
echo ===============================
echo     Building Project
echo ===============================
echo.

where nuitka >nul 2>nul
if errorlevel 1 (
  echo ❌ Nuitka not found. Please install it first: pip install nuitka
  pause
  exit /b
)

REM Specify the main script
set ENTRY=main.py

REM Cleaning up the previous build
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

REM Creating an assembly
nuitka ^
  --standalone ^
  --follow-imports ^
  --enable-plugin=multiprocessing ^
  --output-dir=dist ^
  --remove-output ^
  --include-data-dir=sounds=sounds ^
  --include-data-file=opus.dll=opus.dll ^
  --windows-icon-from-ico=repear.ico ^
  --noinclude-data-files=.*\.env$ ^
  --noinclude-data-files=frags\.db$
  %ENTRY%

echo.
if exist dist\main.dist\main.exe (
  echo ✅ Build successful!
) else (
  echo ❌ Build failed. Check for errors above.
)
pause