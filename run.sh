#!/usr/bin/env bash
set -Eeuo pipefail

APP_ID="milkchan"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
USER_DATA_DIR="$XDG_DATA_HOME/$APP_ID"

if [ ! -x "$VENV_DIR/bin/python" ]; then
  printf '[MilkChan] .venv is missing. Run ./install.sh first.\n' >&2
  exit 1
fi

export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
export QT_XCB_GL_INTEGRATION="${QT_XCB_GL_INTEGRATION:-none}"
export QT_OPENGL="${QT_OPENGL:-software}"
export LIBGL_ALWAYS_SOFTWARE="${LIBGL_ALWAYS_SOFTWARE:-1}"
export PATH="$USER_DATA_DIR:$PATH"

exec "$VENV_DIR/bin/python" -m milkchan.main "$@"
