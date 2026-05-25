#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="MilkChan"
APP_ID="milkchan"
SENTIENTMILK_REPO="https://github.com/obezbolen67/SentientMilk.git"
SENTIENTMILK_BRANCH="${SENTIENTMILK_BRANCH:-master}"
FFMPEG_URL_AMD64="${FFMPEG_URL_AMD64:-https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
USER_DATA_DIR="$XDG_DATA_HOME/$APP_ID"
USER_CONFIG_DIR="$XDG_CONFIG_HOME/$APP_ID"
FRAMEWORK_DIR="$USER_DATA_DIR/sentientmilk_framework"
FRAMEWORK_REPO_DIR="$USER_DATA_DIR/SentientMilk"
FFMPEG_BIN="$USER_DATA_DIR/ffmpeg"
INSTALL_DIR="$XDG_DATA_HOME/opt/$APP_ID"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$XDG_DATA_HOME/applications"

APT_PACKAGES=(
  ca-certificates
  curl
  git
  tar
  xz-utils
  build-essential
  python3
  python3-dev
  python3-pip
  python3-venv
  ffmpeg
  mpv
  xterm
  alsa-utils
  "libasound2t64|libasound2"
  libdbus-1-3
  libegl1
  libfontconfig1
  libgl1
  libglib2.0-0
  libgstreamer-plugins-base1.0-0
  libgstreamer1.0-0
  gstreamer1.0-plugins-base
  gstreamer1.0-plugins-good
  gstreamer1.0-pulseaudio
  gstreamer1.0-libav
  gstreamer1.0-tools
  libpulse0
  libpulse-mainloop-glib0
  pulseaudio-utils
  libsm6
  libx11-6
  libxcomposite1
  libxcb1
  libxcb-cursor0
  libxcb-icccm4
  libxcb-image0
  libxcb-keysyms1
  libxcb-randr0
  libxcb-render-util0
  libxcb-shape0
  libxcb-xfixes0
  libxcb-xinerama0
  libxext6
  libxkbcommon-x11-0
  libxrender1
  libxtst6
)

log() {
  printf '[%s] %s\n' "$APP_NAME" "$*"
}

die() {
  printf '[%s] ERROR: %s\n' "$APP_NAME" "$*" >&2
  exit 1
}

run_as_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    die "System packages are missing and sudo is not available."
  fi
}

require_debian_amd64() {
  [ -f /etc/debian_version ] || die "install.sh supports Debian/Ubuntu systems only."
  case "$(dpkg --print-architecture 2>/dev/null || uname -m)" in
    amd64|x86_64) ;;
    *) die "Only amd64/x86_64 Linux is supported." ;;
  esac
}

install_system_packages() {
  if [ "${MILKCHAN_SKIP_APT:-0}" = "1" ]; then
    log "Skipping Debian package installation because MILKCHAN_SKIP_APT=1."
    return
  fi

  local entries=()
  local entry
  for entry in "${APT_PACKAGES[@]}"; do
    if ! package_entry_is_installed "$entry"; then
      entries+=("$entry")
    fi
  done

  if [ "${#entries[@]}" -eq 0 ]; then
    log "System packages are already installed."
    return
  fi

  run_as_root apt-get update

  local missing=()
  for entry in "${entries[@]}"; do
    missing+=("$(resolve_package_entry "$entry")")
  done

  log "Installing Debian packages: ${missing[*]}"
  run_as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${missing[@]}"
}

package_entry_is_installed() {
  local entry="$1"
  local candidate
  IFS='|' read -ra candidates <<< "$entry"
  for candidate in "${candidates[@]}"; do
    if dpkg-query -W -f='${Status}' "$candidate" 2>/dev/null | grep -q "install ok installed"; then
      return 0
    fi
  done
  return 1
}

resolve_package_entry() {
  local entry="$1"
  local candidate
  IFS='|' read -ra candidates <<< "$entry"
  for candidate in "${candidates[@]}"; do
    if apt-cache show "$candidate" >/dev/null 2>&1; then
      printf '%s\n' "$candidate"
      return
    fi
  done
  printf '%s\n' "${candidates[0]}"
}

create_venv() {
  if [ ! -x "$VENV_DIR/bin/python" ]; then
    log "Creating virtual environment at $VENV_DIR"
    python3 -m venv "$VENV_DIR"
  fi
  log "Installing Python dependencies."
  "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
  "$VENV_DIR/bin/python" -m pip install -e "$ROOT_DIR"
}

sync_sentientmilk() {
  mkdir -p "$USER_DATA_DIR"
  if [ -d "$FRAMEWORK_REPO_DIR/.git" ]; then
    log "Updating SentientMilk framework."
    git config --global --add safe.directory "$FRAMEWORK_REPO_DIR" || true
    git -C "$FRAMEWORK_REPO_DIR" fetch --depth 1 origin "$SENTIENTMILK_BRANCH"
    git -C "$FRAMEWORK_REPO_DIR" checkout -q "$SENTIENTMILK_BRANCH"
    git -C "$FRAMEWORK_REPO_DIR" reset --hard "origin/$SENTIENTMILK_BRANCH"
  else
    log "Installing SentientMilk framework."
    rm -rf "$FRAMEWORK_REPO_DIR"
    git clone --depth 1 --branch "$SENTIENTMILK_BRANCH" "$SENTIENTMILK_REPO" "$FRAMEWORK_REPO_DIR"
  fi
  [ -d "$FRAMEWORK_REPO_DIR/sentientmilk_framework" ] || die "SentientMilk framework package was not found after clone."
  if [ ! -L "$FRAMEWORK_DIR" ]; then
    rm -rf "$FRAMEWORK_DIR"
  fi
  ln -sfn "$FRAMEWORK_REPO_DIR/sentientmilk_framework" "$FRAMEWORK_DIR"
}

install_ffmpeg() {
  if [ -x "$FFMPEG_BIN" ]; then
    log "Local FFmpeg already exists at $FFMPEG_BIN"
    return
  fi

  log "Installing local FFmpeg runtime."
  local tmp_dir archive extracted
  tmp_dir="$(mktemp -d)"
  archive="$tmp_dir/ffmpeg.tar.xz"
  curl -L --fail --retry 3 -o "$archive" "$FFMPEG_URL_AMD64"
  tar -C "$tmp_dir" -xf "$archive"
  extracted="$(find "$tmp_dir" -type f -name ffmpeg -perm /111 | head -n 1)"
  [ -n "$extracted" ] || die "Downloaded FFmpeg archive did not contain an executable."
  mkdir -p "$USER_DATA_DIR"
  cp "$extracted" "$FFMPEG_BIN"
  chmod 755 "$FFMPEG_BIN"
  rm -rf "$tmp_dir"
}

install_launchers() {
  mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$DESKTOP_DIR" "$USER_CONFIG_DIR"

  local launcher="$INSTALL_DIR/$APP_ID.sh"
  cat > "$launcher" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export QT_QPA_PLATFORM="\${QT_QPA_PLATFORM:-xcb}"
export QT_XCB_GL_INTEGRATION="\${QT_XCB_GL_INTEGRATION:-none}"
export QT_OPENGL="\${QT_OPENGL:-software}"
export LIBGL_ALWAYS_SOFTWARE="\${LIBGL_ALWAYS_SOFTWARE:-1}"
export PATH="$USER_DATA_DIR:\$PATH"
exec "$ROOT_DIR/run.sh" "\$@"
EOF
  chmod 755 "$launcher"

  ln -sfn "$launcher" "$BIN_DIR/$APP_ID"

  local icon="$ROOT_DIR/milkchan/desktop/assets/icon.png"
  cat > "$DESKTOP_DIR/$APP_ID.desktop" <<EOF
[Desktop Entry]
Version=1.0
Name=$APP_NAME
Comment=AI desktop companion
Exec=$launcher
TryExec=$launcher
Icon=$icon
Terminal=false
Type=Application
Categories=Utility;
StartupNotify=true
EOF
  update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
}

main() {
  require_debian_amd64
  install_system_packages
  create_venv
  sync_sentientmilk
  install_ffmpeg
  install_launchers

  log "Source install complete."
  log "Run with: ./run.sh"
  log "Desktop entry: $DESKTOP_DIR/$APP_ID.desktop"
  log "User data: $USER_DATA_DIR"
  log "User config: $USER_CONFIG_DIR/config.json"
}

main "$@"
