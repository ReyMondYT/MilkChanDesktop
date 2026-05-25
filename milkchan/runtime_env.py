"""Runtime environment helpers for Linux desktop integration."""

from __future__ import annotations

import os
import sys
from typing import Dict


def configure_qt_environment() -> None:
    """Use conservative Qt settings that work on mixed GLX/Wayland systems."""
    if not sys.platform.startswith("linux"):
        return
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
    os.environ.setdefault("QT_XCB_GL_INTEGRATION", "none")
    os.environ.setdefault("QT_OPENGL", "software")
    os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")


def external_process_environment() -> Dict[str, str]:
    """Return an env safe for launching system programs from a frozen app."""
    env = os.environ.copy()
    if getattr(sys, "frozen", False):
        for key in (
            "LD_LIBRARY_PATH",
            "LD_PRELOAD",
            "PYTHONHOME",
            "PYTHONPATH",
            "PYINSTALLER_RESET_ENVIRONMENT",
            "_PYI_APPLICATION_HOME_DIR",
            "_PYI_ARCHIVE_FILE",
            "_PYI_PARENT_PROCESS_LEVEL",
            "_PYI_SPLASH_IPC",
            "QT_PLUGIN_PATH",
            "QT_QPA_PLATFORM_PLUGIN_PATH",
        ):
            env.pop(key, None)
    return env
