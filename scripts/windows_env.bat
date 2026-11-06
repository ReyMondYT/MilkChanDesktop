@echo off
rem Called by build.bat and run.bat, which already set the working directory.
rem Do not setlocal: return the resolved paths to the caller's local environment.
if not defined SENTIENTMILK_ROOT set "SENTIENTMILK_ROOT=%~dp0..\..\SentientMilk"
for %%I in ("%SENTIENTMILK_ROOT%") do set "SENTIENTMILK_ROOT=%%~fI"
if not exist "%SENTIENTMILK_ROOT%\sentientmilk_framework\__init__.py" (
    echo [MilkChan] SentientMilk checkout not found: "%SENTIENTMILK_ROOT%" 1>&2
    echo [MilkChan] Place SentientMilk beside MilkChan or set SENTIENTMILK_ROOT. 1>&2
    exit /b 1
)

set "MILKCHAN_PYTHON=%~dp0..\.venv-win\Scripts\python.exe"
if exist "%MILKCHAN_PYTHON%" goto check_python
echo [MilkChan] Creating .venv-win with Python 3.12...
py -3.12 -m venv "%~dp0..\.venv-win"
if errorlevel 1 (
    echo [MilkChan] Install Python 3.12 with the Windows Python launcher, then retry. 1>&2
    exit /b 1
)

:check_python
"%MILKCHAN_PYTHON%" -c "import sys; sys.exit(0 if sys.platform == 'win32' and sys.version_info[:2] == (3, 12) else 1)"
if errorlevel 1 (
    echo [MilkChan] .venv-win must be a working Windows Python 3.12 environment. 1>&2
    exit /b 1
)

rem Reinstall on first use, when the framework path changes, or when requested.
if "%MILKCHAN_SETUP%"=="1" goto setup
"%MILKCHAN_PYTHON%" -c "import os, sys; from pathlib import Path; p=Path('.venv-win/.milkchan-setup'); sys.exit(0 if p.exists() and p.read_text(encoding='utf-8') == os.environ['SENTIENTMILK_ROOT'] else 1)"
if errorlevel 1 goto setup
"%MILKCHAN_PYTHON%" -m pip check >nul 2>&1
if errorlevel 1 goto setup
"%MILKCHAN_PYTHON%" -c "import PyInstaller, PyQt5, PIL, requests, mss, markdown2, rich, sentientmilk_framework" >nul 2>&1
if errorlevel 1 goto setup
exit /b 0

:setup
echo [MilkChan] Installing development and build dependencies...
"%MILKCHAN_PYTHON%" scripts\project.py --sentient-root "%SENTIENTMILK_ROOT%" setup
if errorlevel 1 exit /b 1
"%MILKCHAN_PYTHON%" -c "import os; from pathlib import Path; Path('.venv-win/.milkchan-setup').write_text(os.environ['SENTIENTMILK_ROOT'], encoding='utf-8')"
exit /b %ERRORLEVEL%
