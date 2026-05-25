"""Debian/Ubuntu runtime dependency checks for frozen MilkChan builds."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Iterable, List, Sequence, Tuple


PACKAGE_GROUPS: Sequence[Sequence[str]] = (
    ("ca-certificates",),
    ("curl",),
    ("git",),
    ("ffmpeg",),
    ("mpv",),
    ("xterm",),
    ("alsa-utils",),
    ("libasound2t64", "libasound2"),
    ("libdbus-1-3",),
    ("libegl1",),
    ("libfontconfig1",),
    ("libgl1",),
    ("libglib2.0-0",),
    ("libgstreamer1.0-0",),
    ("libgstreamer-plugins-base1.0-0",),
    ("gstreamer1.0-plugins-base",),
    ("gstreamer1.0-plugins-good",),
    ("gstreamer1.0-pulseaudio",),
    ("gstreamer1.0-libav",),
    ("gstreamer1.0-tools",),
    ("libpulse0",),
    ("libpulse-mainloop-glib0",),
    ("pulseaudio-utils",),
    ("libsm6",),
    ("libx11-6",),
    ("libxcomposite1",),
    ("libxcb1",),
    ("libxcb-cursor0",),
    ("libxcb-icccm4",),
    ("libxcb-image0",),
    ("libxcb-keysyms1",),
    ("libxcb-randr0",),
    ("libxcb-render-util0",),
    ("libxcb-shape0",),
    ("libxcb-xfixes0",),
    ("libxcb-xinerama0",),
    ("libxext6",),
    ("libxkbcommon-x11-0",),
    ("libxrender1",),
    ("libxtst6",),
)


def _is_linux_apt_system() -> bool:
    return sys.platform.startswith("linux") and shutil.which("apt-get") and shutil.which("dpkg-query")


def _package_installed(package: str) -> bool:
    result = subprocess.run(
        ["dpkg-query", "-W", "-f=${Status}", package],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    return result.returncode == 0 and "install ok installed" in result.stdout


def _package_available(package: str) -> bool:
    result = subprocess.run(
        ["apt-cache", "policy", package],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    return result.returncode == 0 and "Candidate: (none)" not in result.stdout and "Candidate:" in result.stdout


def _resolve_missing_groups(groups: Iterable[Sequence[str]]) -> List[Tuple[str, ...]]:
    missing: List[Tuple[str, ...]] = []
    for alternatives in groups:
        if any(_package_installed(package) for package in alternatives):
            continue
        missing.append(tuple(alternatives))
    return missing


def _resolve_install_packages(groups: Iterable[Sequence[str]]) -> List[str]:
    packages: List[str] = []
    for alternatives in groups:
        for package in alternatives:
            if _package_available(package):
                packages.append(package)
                break
        else:
            packages.append(alternatives[0])
    return packages


def _root_command() -> List[str] | None:
    if os.geteuid() == 0:
        return []
    if shutil.which("sudo"):
        return ["sudo"]
    return None


def ensure_runtime_system_dependencies() -> bool:
    """Install missing Debian/Ubuntu runtime packages when possible."""
    if os.environ.get("MILKCHAN_SKIP_SYSTEM_DEPS") == "1":
        return True
    if not _is_linux_apt_system():
        return True

    missing_groups = _resolve_missing_groups(PACKAGE_GROUPS)
    if not missing_groups:
        return True

    prefix = _root_command()
    if prefix is None:
        missing_names = [group[0] for group in missing_groups]
        print("[MilkChan] Missing system packages:", " ".join(missing_names), file=sys.stderr)
        print("[MilkChan] Install them with apt, then start MilkChan again.", file=sys.stderr)
        return False

    update = prefix + ["apt-get", "update"]
    if subprocess.run(update, check=False).returncode != 0:
        return False
    packages = _resolve_install_packages(missing_groups)
    print("[MilkChan] Installing missing system packages:", " ".join(packages))
    install = prefix + ["apt-get", "install", "-y", "--no-install-recommends", *packages]
    return subprocess.run(install, check=False).returncode == 0
