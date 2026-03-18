#!/bin/bash
# =========================================================================
# MilkChan - Build Single Binary (PyInstaller) for Linux
# =========================================================================
# Creates a portable single binary with all dependencies bundled
#
# Output: dist/MilkChan (single file)
#
# User data stored in: ~/.milkchan/
# =========================================================================

set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
DIST_DIR="$ROOT/dist"
BUILD_DIR="$ROOT/build"
SPEC_FILE="$ROOT/MilkChan.spec"

echo "========================================================================"
echo "MilkChan Build Script (Linux)"
echo "========================================================================"
echo

echo "[1/6] Setting up environment..."
if [ -z "$VIRTUAL_ENV" ]; then
    if [ -f "$ROOT/.venv/bin/activate" ]; then
        source "$ROOT/.venv/bin/activate"
    elif [ -f "$ROOT/venv/bin/activate" ]; then
        source "$ROOT/venv/bin/activate"
    else
        echo "[!] No virtual environment found"
        echo "[*] Creating virtual environment..."
        python3 -m venv "$ROOT/.venv"
        source "$ROOT/.venv/bin/activate"
    fi
fi

echo "[*] Upgrading pip..."
pip install --upgrade pip wheel setuptools --quiet

echo "[2/6] Installing dependencies..."
pip install pyinstaller --quiet
pip install -e . --quiet

echo "[3/6] Cleaning previous builds..."
rm -rf "$DIST_DIR"
rm -rf "$BUILD_DIR"
echo "[*] Cleaned dist and build directories"

echo "[4/6] Verifying assets exist..."
if [ ! -f "$ROOT/milkchan/desktop/assets/icon.png" ]; then
    echo "[!] icon.png not found"
    exit 1
fi

echo "[5/6] Building single-file binary with PyInstaller..."
echo "This may take 2-5 minutes..."
echo

pyinstaller --noconfirm --clean "$SPEC_FILE"

echo
echo "[6/6] Build complete!"
echo

echo "========================================================================"
echo "Build Successful!"
echo "========================================================================"
echo
echo "Output: dist/MilkChan"
echo
echo "User data will be stored in: ~/.milkchan/"
echo
echo "To distribute:"
echo "1. Copy dist/MilkChan to target computer"
echo "2. Run: chmod +x MilkChan && ./MilkChan"
echo
echo "First run will:"
echo "- Show setup progress dialog"
echo "- Create ~/.milkchan folder with assets"
echo "- Pre-cache sprites for fast startup"
echo "- Auto-download FFmpeg (if not in system PATH)"
echo "- Create config.json and database"
echo
echo "NOTE: FFmpeg is auto-downloaded on first run if not found."
echo "No need to bundle ffmpeg manually."
echo
echo "========================================================================"
