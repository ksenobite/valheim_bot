@REM @REM build.bat
@REM @echo off
@REM title ⚙️ Building Discord Bot with Nuitka (Standalone - WAV Support)
@REM echo ===============================
@REM echo     Building Project
@REM echo ===============================
@REM echo.

@REM where nuitka >nul 2>nul
@REM if errorlevel 1 (
@REM   echo ❌ Nuitka not found. Please install it first: pip install nuitka
@REM   pause
@REM   exit /b
@REM )

@REM REM Specify the main script
@REM set ENTRY=main.py

@REM REM Cleaning up the previous build
@REM if exist dist rmdir /s /q dist
@REM if exist build rmdir /s /q build

@REM REM Creating an assembly
@REM nuitka ^
@REM   --standalone ^
@REM   --follow-imports ^
@REM   --enable-plugin=multiprocessing ^
@REM   --output-dir=dist ^
@REM   --remove-output ^
@REM   --include-data-dir=sounds=sounds ^
@REM   --include-data-file=opus.dll=opus.dll ^
@REM   --windows-icon-from-ico=repear.ico ^
@REM   --noinclude-data-files=.*\.env$ ^
@REM   --noinclude-data-files=frags\.db$ ^
@REM   %ENTRY%

@REM echo.
@REM if exist dist\main.dist\main.exe (
@REM   echo ✅ Build successful!
@REM ) else (
@REM   echo ❌ Build failed. Check for errors above.
@REM )
@REM pause


@echo off
title ⚙️ Building Discord Bot with Nuitka (Standalone - WAV Support)

echo ===============================
echo     Building Project
echo ===============================
echo.

REM Activate virtual environment
call venv\Scripts\activate.bat

REM Check if Nuitka is available
where nuitka >nul 2>nul
if errorlevel 1 (
  echo ❌ Nuitka not found in virtual environment. Please activate venv and run: pip install nuitka
  pause
  exit /b
)

REM Main script
set ENTRY=main.py

REM Clean previous build
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

REM Start build
nuitka ^
  --standalone ^
  --follow-imports ^
  --enable-plugin=multiprocessing ^
  --enable-plugin=pylint-warnings ^
  --output-dir=dist ^
  --remove-output ^
  --include-data-dir=sounds=sounds ^
  --include-data-file=opus.dll=opus.dll ^
  --windows-icon-from-ico=repear.ico ^
  --noinclude-data-files=.*\.env$ ^
  --noinclude-data-files=frags\.db$ ^
  %ENTRY%

echo.
if exist dist\main.dist\main.exe (
  echo ✅ Build successful!
) else (
  echo ❌ Build failed. Check for errors above.
)
pause
