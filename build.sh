#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="MilkChan"
SENTIENTMILK_REPO="https://github.com/obezbolen67/SentientMilk.git"
SENTIENTMILK_BRANCH="${SENTIENTMILK_BRANCH:-master}"
FFMPEG_URL_AMD64="${FFMPEG_URL_AMD64:-https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz}"
NATIVE_BUILD=0

if [ "${1:-}" = "--native" ]; then
  NATIVE_BUILD=1
  shift
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT_DIR/build/.venv-build"
BUILD_VENDOR_DIR="$ROOT_DIR/build/vendor"
FRAMEWORK_PARENT="$BUILD_VENDOR_DIR/SentientMilk"
FRAMEWORK_DIR="$FRAMEWORK_PARENT/sentientmilk_framework"
FFMPEG_BIN="$BUILD_VENDOR_DIR/bin/ffmpeg"
SPEC_FILE="$ROOT_DIR/MilkChan.spec"
DIST_BIN="$ROOT_DIR/dist/$APP_NAME"

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
  mpv
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
  printf '[%s build] %s\n' "$APP_NAME" "$*"
}

die() {
  printf '[%s build] ERROR: %s\n' "$APP_NAME" "$*" >&2
  exit 1
}

maybe_run_container_build() {
  if [ "$NATIVE_BUILD" = "1" ] || [ "${MILKCHAN_NO_DOCKER:-0}" = "1" ] || [ -f /.dockerenv ]; then
    return
  fi
  if ! command -v docker >/dev/null 2>&1; then
    log "Docker not found; falling back to native build."
    return
  fi

  log "Running distribution build inside debian:12-slim."
  docker run --rm \
    -e MILKCHAN_NO_DOCKER=1 \
    -e HOST_UID="$(id -u)" \
    -e HOST_GID="$(id -g)" \
    -v "$ROOT_DIR:/src" \
    -w /src \
    debian:12-slim \
    bash -lc './build.sh --native; status=$?; chown -R "$HOST_UID:$HOST_GID" dist build 2>/dev/null || true; exit "$status"'
  exit $?
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
  [ -f /etc/debian_version ] || die "build.sh supports Debian/Ubuntu systems only."
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
    log "System build packages are already installed."
    return
  fi

  run_as_root apt-get update

  local missing=()
  for entry in "${entries[@]}"; do
    missing+=("$(resolve_package_entry "$entry")")
  done

  log "Installing Debian build packages: ${missing[*]}"
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

sync_sentientmilk() {
  mkdir -p "$BUILD_VENDOR_DIR"
  if [ -d "$FRAMEWORK_PARENT/.git" ]; then
    log "Updating SentientMilk framework vendor."
    git config --global --add safe.directory "$FRAMEWORK_PARENT" || true
    git -C "$FRAMEWORK_PARENT" fetch --depth 1 origin "$SENTIENTMILK_BRANCH"
    git -C "$FRAMEWORK_PARENT" checkout -q "$SENTIENTMILK_BRANCH"
    git -C "$FRAMEWORK_PARENT" reset --hard "origin/$SENTIENTMILK_BRANCH"
  else
    log "Cloning SentientMilk framework vendor."
    rm -rf "$FRAMEWORK_PARENT"
    git clone --depth 1 --branch "$SENTIENTMILK_BRANCH" "$SENTIENTMILK_REPO" "$FRAMEWORK_PARENT"
  fi
  [ -f "$FRAMEWORK_DIR/__init__.py" ] || die "SentientMilk framework package was not found after clone."
}

download_ffmpeg() {
  if [ -x "$FFMPEG_BIN" ]; then
    log "Build FFmpeg already exists at $FFMPEG_BIN"
    return
  fi

  log "Downloading FFmpeg for release bundle."
  local tmp_dir archive extracted
  tmp_dir="$(mktemp -d)"
  archive="$tmp_dir/ffmpeg.tar.xz"
  curl -L --fail --retry 3 -o "$archive" "$FFMPEG_URL_AMD64"
  tar -C "$tmp_dir" -xf "$archive"
  extracted="$(find "$tmp_dir" -type f -name ffmpeg -perm /111 | head -n 1)"
  [ -n "$extracted" ] || die "Downloaded FFmpeg archive did not contain an executable."
  mkdir -p "$(dirname "$FFMPEG_BIN")"
  cp "$extracted" "$FFMPEG_BIN"
  chmod 755 "$FFMPEG_BIN"
  rm -rf "$tmp_dir"
}

prepare_python_env() {
  if [ ! -x "$VENV_DIR/bin/python" ]; then
    log "Creating virtual environment at $VENV_DIR"
    python3 -m venv "$VENV_DIR"
  fi
  log "Installing Python build dependencies."
  "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
  "$VENV_DIR/bin/python" -m pip install -e "$ROOT_DIR"
  "$VENV_DIR/bin/python" -m pip install pyinstaller
}

build_binary() {
  log "Cleaning previous PyInstaller output."
  rm -rf "$ROOT_DIR/dist" "$ROOT_DIR/build/MilkChan"

  log "Building one-file release binary."
  SENTIENTMILK_FRAMEWORK_PARENT="$FRAMEWORK_PARENT" \
  MILKCHAN_FFMPEG_PATH="$FFMPEG_BIN" \
    "$VENV_DIR/bin/pyinstaller" --noconfirm --clean "$SPEC_FILE"

  [ -x "$DIST_BIN" ] || die "PyInstaller did not create $DIST_BIN"
  "$DIST_BIN" --install-user >/tmp/milkchan-self-install-check.log
  log "Self-install mode smoke check passed."
}

main() {
  maybe_run_container_build
  require_debian_amd64
  install_system_packages
  sync_sentientmilk
  download_ffmpeg
  prepare_python_env
  build_binary

  log "Release binary: $DIST_BIN"
  log "Users can run it directly or install it with: $DIST_BIN --install-user"
}

main "$@"
