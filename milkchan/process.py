"""Process helpers for frozen and source execution."""

import os
import sys
import subprocess
from typing import List


def restart_command() -> List[str]:
    """Return the correct command for restarting the current app."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "milkchan.main"]


def restart_environment() -> dict:
    """Build an environment for a clean app restart.

    PyInstaller one-file apps must not inherit the parent extraction state.
    Without the reset flag, a restarted child can reference the parent's temp
    directory and lose bundled shared libraries when the parent exits.
    """
    env = os.environ.copy()
    if getattr(sys, "frozen", False):
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def restart_app() -> None:
    """Start a fresh instance of MilkChan."""
    subprocess.Popen(restart_command(), env=restart_environment(), close_fds=True)
