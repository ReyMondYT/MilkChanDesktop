"""Small looping narration player with Linux-safe backends."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

from PyQt5.QtCore import QUrl
from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer


_SYSTEM_BIN_DIRS = ("/usr/local/bin", "/usr/bin", "/bin")


def _find_executable(name: str) -> Optional[str]:
    """Find a Debian runtime executable even when desktop launchers provide a thin PATH."""
    resolved = shutil.which(name)
    if resolved:
        return resolved
    for directory in _SYSTEM_BIN_DIRS:
        candidate = Path(directory) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


class NarrationPlayer:
    """Play the short MilkChan narration loop while speech animation is active."""

    def __init__(self, audio_path: str):
        self.audio_path = Path(audio_path)
        self._process: Optional[subprocess.Popen] = None
        self._qt_player: Optional[QMediaPlayer] = None
        self._backend_cmd = self._select_external_backend()

        if self.audio_path.exists() and self._backend_cmd is None:
            self._qt_player = QMediaPlayer()
            self._qt_player.setVolume(100)
            self._qt_player.setMedia(QMediaContent(QUrl.fromLocalFile(str(self.audio_path.resolve()))))

    def is_available(self) -> bool:
        return self.audio_path.exists() and (self._backend_cmd is not None or self._qt_player is not None)

    def backend_name(self) -> str:
        if self._backend_cmd:
            return Path(self._backend_cmd[0]).name
        if self._qt_player:
            return "qt"
        return "none"

    def play(self) -> None:
        if not self.audio_path.exists():
            return
        if self._is_external_running():
            return
        if self._backend_cmd:
            self._start_external()
            return
        if self._qt_player:
            self._qt_player.stop()
            self._qt_player.play()

    def play_test(self, seconds: float = 1.0) -> bool:
        """Play briefly and report whether a backend could be started."""
        self.play()
        time.sleep(max(0.1, seconds))
        external_ok = False
        if self._process is not None:
            rc = self._process.poll()
            external_ok = rc is None or rc == 0
        qt_ok = bool(self._qt_player and self._qt_player.state() == QMediaPlayer.PlayingState)
        self.stop()
        return external_ok or qt_ok

    def ensure_playing(self) -> None:
        if not self.audio_path.exists():
            return
        if self._backend_cmd:
            if not self._is_external_running():
                self._start_external()
            return
        if self._qt_player and self._qt_player.state() != QMediaPlayer.PlayingState:
            self._qt_player.play()

    def stop(self) -> None:
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None
        if self._qt_player:
            self._qt_player.stop()

    def _is_external_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _select_external_backend(self) -> Optional[List[str]]:
        if not sys.platform.startswith("linux"):
            return None
        mpv = _find_executable("mpv")
        if mpv:
            return [mpv, "--no-video", "--really-quiet", "--no-terminal"]
        ffplay = _find_executable("ffplay")
        if ffplay:
            return [ffplay, "-nodisp", "-autoexit", "-loglevel", "error", "-volume", "100"]
        gst_play = _find_executable("gst-play-1.0")
        if gst_play:
            return [gst_play, "--no-interactive", "--quiet"]
        pw_play = _find_executable("pw-play")
        if pw_play:
            return [pw_play]
        paplay = _find_executable("paplay")
        if paplay:
            return [paplay]
        aplay = _find_executable("aplay")
        if aplay:
            return [aplay, "-q"]
        return None

    def _start_external(self) -> None:
        if not self._backend_cmd:
            return
        from milkchan.runtime_env import external_process_environment

        env = external_process_environment()
        env.setdefault("PULSE_PROP_media.role", "music")
        try:
            self._process = subprocess.Popen(
                [*self._backend_cmd, str(self.audio_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                env=env,
                close_fds=True,
            )
        except Exception as exc:
            print(f"[Audio] failed to start {self.backend_name()}: {exc}")
            self._process = None
