#!/bin/bash
# =========================================================================
# MilkChan - Linux Installation Script
# =========================================================================
# Installs MilkChan system-wide on Ubuntu/Debian
#
# Usage: sudo ./install_linux.sh
# =========================================================================

set -e

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo ./install_linux.sh"
    exit 1
fi

INSTALL_DIR="/opt/milkchan"
LAUNCHER_SCRIPT="$INSTALL_DIR/milkchan.sh"
DESKTOP_FILE="/usr/share/applications/milkchan.desktop"

echo "========================================================================"
echo "MilkChan Linux Installer"
echo "========================================================================"
echo

# Create installation directory
echo "[1/4] Creating installation directory..."
mkdir -p "$INSTALL_DIR"

# Copy binary
echo "[2/4] Copying MilkChan binary..."
if [ -f "dist/MilkChan" ]; then
    cp dist/MilkChan "$INSTALL_DIR/"
    chmod +x "$INSTALL_DIR/MilkChan"
else
    echo "[!] dist/MilkChan not found. Build first with: ./build_linux.sh"
    exit 1
fi

# Copy icon
echo "[3/4] Copying icon..."
if [ -f "milkchan/desktop/assets/icon.png" ]; then
    cp milkchan/desktop/assets/icon.png "$INSTALL_DIR/"
fi

# Create launcher script that ensures env + logging
cat > "$LAUNCHER_SCRIPT" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

# Ensure Qt runs on X11 when available
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"

# Make sure user data dir exists so logs/config land in $HOME
USER_DATA_DIR="$HOME/.milkchan"
mkdir -p "$USER_DATA_DIR"

LOG_FILE="$USER_DATA_DIR/milkchan.log"
exec "$INSTALL_DIR/MilkChan" "$@" >>"$LOG_FILE" 2>&1
EOF

chmod 755 "$LAUNCHER_SCRIPT"

# Create .desktop file
echo "[4/4] Creating desktop entry..."
cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Version=1.0
Name=MilkChan
Comment=Anime-style desktop assistant
Exec=$LAUNCHER_SCRIPT
TryExec=$LAUNCHER_SCRIPT
Icon=/opt/milkchan/icon.png
Terminal=false
Type=Application
Categories=Utility;Game;
StartupNotify=true
Path=$INSTALL_DIR
EOF

chmod 644 "$DESKTOP_FILE"

# Update desktop database
update-desktop-database /usr/share/applications/ 2>/dev/null || true

echo
echo "========================================================================"
echo "Installation Complete!"
echo "========================================================================"
echo
echo "MilkChan installed to: $INSTALL_DIR"
echo
echo "You can now:"
echo "  - Find MilkChan in your applications menu"
echo "  - Run from terminal: /opt/milkchan/MilkChan"
echo "  - Search 'MilkChan' in Ubuntu Dash"
echo
echo "To uninstall: sudo rm -rf /opt/milkchan /usr/share/applications/milkchan.desktop"
echo
echo "========================================================================"
