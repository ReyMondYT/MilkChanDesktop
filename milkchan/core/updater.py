"""Keep the SentientMilk brain of packaged builds current with GitHub.

Updates are written to user data, where the brain link loads them from.
Development checkouts are never touched: update those with git.
"""

import base64
import json
import logging
import shutil
import sys
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from milkchan.paths import get_user_data_dir

logger = logging.getLogger(__name__)

GITHUB_REPO = "obezbolen67/SentientMilk"
BRANCH = "master"
FRAMEWORK_PATH = "sentientmilk_framework"
GITHUB_API = "https://api.github.com"
GITHUB_RAW = "https://raw.githubusercontent.com"
# A commit without these is not a brain this MilkChan can use (runs.py and toolkits/ came with v2).
REQUIRED_FILES = ("__init__.py", "brain.py", "client.py", "server.py", "runs.py", "toolkits/__init__.py")


def updates_supported() -> bool:
    return bool(getattr(sys, 'frozen', False))


@dataclass(frozen=True)
class UpdateInfo:
    current_sha: str
    latest_sha: str
    commit_message: str
    commit_date: str
    available: bool


class AutoUpdater:
    def __init__(self, data_dir: Optional[Path] = None):
        data_dir = data_dir or get_user_data_dir()
        self.state_file = data_dir / "updater_state.json"
        self.target_path = data_dir / FRAMEWORK_PATH
        self._update_info: Optional[UpdateInfo] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _load_state(self) -> Dict[str, Any]:
        try:
            return json.loads(self.state_file.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            logger.warning("Failed to load updater state: %s", exc)
            return {}

    def _save_state(self, **changes: Any) -> None:
        state = {**self._load_state(), **changes}
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(state, indent=2), encoding='utf-8')
        except OSError as exc:
            logger.warning("Failed to save updater state: %s", exc)

    @staticmethod
    def _headers() -> Dict[str, str]:
        from milkchan.core.config import get_config

        headers = {'Accept': 'application/vnd.github.v3+json', 'User-Agent': 'MilkChan-Updater/1.0'}
        token = get_config().get('updates.github_token', '')
        if token:
            headers['Authorization'] = f'token {token}'
        return headers

    def _api_get(self, endpoint: str) -> Optional[Dict]:
        try:
            response = requests.get(f"{GITHUB_API}/{endpoint}", headers=self._headers(), timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as exc:
            logger.error("GitHub API request failed: %s", exc)
            return None

    def _get_tree(self, sha: str) -> List[Dict]:
        data = self._api_get(f"repos/{GITHUB_REPO}/git/trees/{sha}?recursive=1")
        return data.get('tree', []) if data else []

    def _download_file(self, github_path: str, local_path: Path, revision: str) -> bool:
        try:
            response = requests.get(f"{GITHUB_RAW}/{GITHUB_REPO}/{revision}/{github_path}",
                                    headers=self._headers(), timeout=30)
            if response.status_code == 404 and 'Authorization' in self._headers():
                # Private repositories are served through the contents API only.
                data = self._api_get(f"repos/{GITHUB_REPO}/contents/{github_path}?ref={revision}")
                if not data or 'content' not in data:
                    return False
                content = base64.b64decode(data['content'])
            else:
                response.raise_for_status()
                content = response.content
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(content)
            return True
        except requests.exceptions.RequestException as exc:
            logger.warning("Failed to download %s: %s", github_path, exc)
            return False

    def check_for_updates(self) -> Optional[UpdateInfo]:
        """Compare the installed framework with GitHub; None when GitHub is unreachable."""
        data = self._api_get(f"repos/{GITHUB_REPO}/commits/{BRANCH}")
        if not data:
            return None
        commit = data.get('commit', {})
        current = self._load_state().get('last_applied_sha') or 'unknown'
        self._update_info = UpdateInfo(
            current_sha=current,
            latest_sha=data.get('sha', ''),
            commit_message=commit.get('message', ''),
            commit_date=commit.get('committer', {}).get('date', ''),
            available=current != data.get('sha', ''),
        )
        self._save_state(last_check=datetime.now(timezone.utc).isoformat(),
                         last_remote_sha=self._update_info.latest_sha)
        logger.info("Framework %s -> %s, update available: %s",
                    current[:7], self._update_info.latest_sha[:7], self._update_info.available)
        return self._update_info

    def apply_update(self) -> bool:
        """Download the checked commit completely, then swap it in."""
        info = self._update_info
        if not info or not info.available:
            return False
        try:
            files = [item for item in self._get_tree(info.latest_sha)
                     if item.get('type') == 'blob' and item.get('path', '').startswith(FRAMEWORK_PATH + '/')]
            if not files:
                logger.error("Commit contains no framework files")
                return False
            target = self.target_path
            staging = target.parent / f".{target.name}.update-{info.latest_sha[:12]}"
            rollback = target.parent / f".{target.name}.rollback-{info.latest_sha[:12]}"
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True)
            for item in files:
                if not self._download_file(item['path'], staging / item['path'][len(FRAMEWORK_PATH) + 1:],
                                           info.latest_sha):
                    logger.error("Update rejected: %s could not be downloaded", item['path'])
                    shutil.rmtree(staging, ignore_errors=True)
                    return False
            if not all((staging / name).exists() for name in REQUIRED_FILES):
                logger.error("Update rejected: staged framework is incomplete")
                shutil.rmtree(staging, ignore_errors=True)
                return False
            shutil.rmtree(rollback, ignore_errors=True)
            try:
                if target.exists():
                    target.rename(rollback)
                staging.rename(target)
            except OSError:
                if rollback.exists() and not target.exists():
                    rollback.rename(target)
                shutil.rmtree(staging, ignore_errors=True)
                raise
            shutil.rmtree(rollback, ignore_errors=True)
            self._save_state(last_applied_sha=info.latest_sha,
                             last_update_time=datetime.now(timezone.utc).isoformat())
            self._update_info = replace(info, current_sha=info.latest_sha, available=False)
            logger.info("Updated %d framework files to %s", len(files), info.latest_sha[:7])
            return True
        except Exception as exc:
            logger.error("Failed to apply update: %s", exc)
            return False

    def start_auto_check(self) -> None:
        from milkchan.core.config import get_config

        if not updates_supported() or not get_config().get('updates.auto_check', True):
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._auto_check_loop, daemon=True)
        self._thread.start()

    def stop_auto_check(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)

    def _auto_check_loop(self) -> None:
        from milkchan.core.config import get_config

        while not self._stop_event.is_set():
            try:
                info = self.check_for_updates()
                if info and info.available and get_config().get('updates.auto_update', True):
                    self.apply_update()
            except Exception as exc:
                logger.error("Error in auto-check: %s", exc)
            self._stop_event.wait(float(get_config().get('updates.check_interval_hours', 24)) * 3600)


_updater: Optional[AutoUpdater] = None


def get_updater() -> AutoUpdater:
    global _updater
    if _updater is None:
        _updater = AutoUpdater()
    return _updater


def format_update_message(info: UpdateInfo) -> str:
    message = info.commit_message[:100] + ('...' if len(info.commit_message) > 100 else '')
    return '\n'.join([
        "Framework Update Available!",
        "",
        f"Current: {info.current_sha[:7]}",
        f"Latest:  {info.latest_sha[:7]}",
        "",
        "Latest commit:",
        message,
        f"Date: {info.commit_date}",
    ])
