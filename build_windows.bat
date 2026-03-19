@echo off
setlocal

REM =========================================================================
REM MilkChan - Build Single EXE (PyInstaller)
REM =========================================================================
REM Creates a portable single EXE with all dependencies bundled
REM 
REM Output: dist\MilkChan.exe (single file)
REM 
REM User data stored in: ~/.milkchan/
REM =========================================================================

set ROOT=%~dp0
set DIST_DIR=%ROOT%dist
set BUILD_DIR=%ROOT%build
set SPEC_FILE=%ROOT%MilkChan.spec

echo =========================================================================
echo MilkChan Build Script
echo =========================================================================
echo.

echo [1/6] Setting up environment...

REM Check if venv exists but is broken (points to non-existent Python)
if exist "%ROOT%.venv\pyvenv.cfg" (
  findstr /C:"Python313" "%ROOT%.venv\pyvenv.cfg" >nul 2>&1
  if not errorlevel 1 (
    echo [!] Found broken venv (Python 3.13 removed)
    echo [*] Removing old venv...
    rmdir /s /q "%ROOT%.venv"
  )
)

if not defined VIRTUAL_ENV (
  if exist "%ROOT%.venv\Scripts\activate.bat" (
    call "%ROOT%.venv\Scripts\activate.bat"
  ) else if exist "%ROOT%venv\Scripts\activate.bat" (
    call "%ROOT%venv\Scripts\activate.bat"
  ) else (
    echo [!] No virtual environment found
    echo [*] Creating virtual environment...
    python -m venv "%ROOT%.venv" || goto :error
    call "%ROOT%.venv\Scripts\activate.bat"
  )
)

echo [*] Upgrading pip...
python -m pip install --upgrade pip wheel setuptools --quiet || goto :error

echo [2/6] Installing dependencies...
python -m pip install pyinstaller --quiet || goto :error
python -m pip install -e . --quiet || goto :error

echo [3/6] Cleaning previous builds...
if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
echo [*] Cleaned dist and build directories

echo [4/6] Verifying assets exist...
if not exist "%ROOT%milkchan\desktop\assets\icon.ico" (
  echo [!] icon.ico not found, checking for PNG...
  if exist "%ROOT%milkchan\desktop\assets\icon.png" (
    echo [*] Converting icon.png to icon.ico...
    python -c "from PIL import Image; im=Image.open(r'%ROOT%milkchan\desktop\assets\icon.png').convert('RGBA'); sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)]; im.save(r'%ROOT%milkchan\desktop\assets\icon.ico', format='ICO', sizes=sizes)"
  )
)

echo [5/6] Building single-file EXE with PyInstaller...
echo     This may take 2-5 minutes...
echo.

pyinstaller --noconfirm --clean "%SPEC_FILE%" || goto :error

echo.
echo [6/6] Build complete!
echo.

echo =========================================================================
echo Build Successful!
echo =========================================================================
echo.
echo Output: dist\MilkChan.exe
echo.
echo User data will be stored in: %%USERPROFILE%%\.milkchan\
echo.
echo To distribute:
echo 1. Copy dist\MilkChan.exe to target computer
echo 2. Run MilkChan.exe
echo.
echo First run will:
echo - Show setup progress dialog
echo - Create ~/.milkchan folder with assets
echo - Pre-cache sprites for fast startup
echo - Auto-download FFmpeg (if not in system PATH)
echo - Create config.json and database
echo.
echo NOTE: FFmpeg is auto-downloaded on first run if not found.
echo       No need to bundle ffmpeg.exe manually.
echo.
echo First run will:
echo   - Show setup progress dialog
echo   - Create ~/.milkchan folder with assets
echo   - Create config.json and database
echo.
echo =========================================================================
exit /b 0

:error
echo.
echo =========================================================================
echo Build FAILED
echo =========================================================================
echo Check the error messages above
echo Common issues:
echo   - Missing Python or virtual environment
echo   - PyInstaller not installed
echo   - Dependencies not installed
echo   - Antivirus blocking PyInstaller
echo =========================================================================
exit /b 1