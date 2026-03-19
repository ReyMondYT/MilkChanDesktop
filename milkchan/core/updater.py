"""Auto-update mechanism for MilkChan

Checks for new commits from GitHub repository and updates local files.
Uses pure HTTP requests - no git or gh CLI required.
"""

import os
import sys
import json
import time
import logging
import shutil
import base64
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass
from datetime import datetime, timezone
import threading

import requests

logger = logging.getLogger(__name__)


@dataclass
class UpdateInfo:
    """Information about available update"""
    current_sha: str
    latest_sha: str
    commit_message: str
    commit_date: str
    available: bool
    repo_url: str
    branch: str


class AutoUpdater:
    """GitHub auto-updater for MilkChan
    
    Syncs the SentientMilk framework from the GitHub repository.
    Uses GitHub REST API - no git CLI required.
    """
    
    GITHUB_REPO = "obezbolen67/SentientMilk"
    BRANCH = "master"
    FRAMEWORK_PATH = "sentientmilk_framework"
    
    GITHUB_API = "https://api.github.com"
    GITHUB_RAW = "https://raw.githubusercontent.com"
    
    def __init__(self, 
                 auto_check: bool = True,
                 check_interval_hours: int = 24,
                 auto_update: bool = False,
                 github_token: Optional[str] = None,
                 on_update_available: Optional[Callable[[UpdateInfo], None]] = None):
        """Initialize the auto-updater
        
        Args:
            auto_check: Whether to automatically check for updates
            check_interval_hours: Hours between automatic checks
            auto_update: Whether to automatically apply updates
            github_token: Optional GitHub token for private repos
            on_update_available: Callback when update is available
        """
        self.auto_check = auto_check
        self.check_interval_hours = check_interval_hours
        self.auto_update = auto_update
        self.github_token = github_token
        self.on_update_available = on_update_available
        
        self._last_check_time: Optional[datetime] = None
        self._update_info: Optional[UpdateInfo] = None
        self._check_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # State file to track last known commit
        self.state_file = self._get_state_file_path()
        
        # Get framework path (works in both dev and bundled mode)
        self.framework_path = self._find_framework_path()
        
        logger.info(f"AutoUpdater initialized")
    
    def _find_framework_path(self) -> Optional[Path]:
        """Find the local sentientmilk_framework folder
        
        For bundled EXE: updates go to user data folder (writable)
        For development: updates go to source folder
        """
        current_file = Path(__file__).resolve()
        
        # Check if we're in bundled mode
        meipass = getattr(sys, '_MEIPASS', None)
        
        if meipass:
            # Bundled EXE mode
            # First check if there's an updated framework in user data
            from milkchan.bootstrap import get_user_data_dir
            user_framework = get_user_data_dir() / "sentientmilk_framework"
            if user_framework.exists() and (user_framework / "ai.py").exists():
                logger.info("Using updated framework from user data")
                return user_framework
            
            # No update in user data, use bundled version (read-only)
            bundled_path = Path(meipass) / "milkchan" / "sentientmilk_framework"
            if bundled_path.exists() and (bundled_path / "ai.py").exists():
                return bundled_path
            
            # Need to download to user data
            user_framework.mkdir(parents=True, exist_ok=True)
            return user_framework
        else:
            # Development mode - update source folder directly
            dev_path = current_file.parent.parent / "sentientmilk_framework"
            if dev_path.exists() and (dev_path / "ai.py").exists():
                return dev_path
            
            # Fallback to user data
            from milkchan.bootstrap import get_user_data_dir
            user_framework = get_user_data_dir() / "sentientmilk_framework"
            user_framework.mkdir(parents=True, exist_ok=True)
            return user_framework
    
    def _get_update_target_path(self) -> Optional[Path]:
        """Get the writable path where updates should be downloaded
        
        In bundled mode: always use user data folder (writable)
        In development: use source folder
        """
        meipass = getattr(sys, '_MEIPASS', None)
        
        if meipass:
            # Bundled EXE mode - always download to user data
            from milkchan.bootstrap import get_user_data_dir
            user_framework = get_user_data_dir() / "sentientmilk_framework"
            return user_framework
        else:
            # Development mode - update source folder directly
            return self.framework_path
    
    def _get_state_file_path(self) -> Path:
        """Get path to state file for tracking updates"""
        from milkchan.bootstrap import get_user_data_dir
        user_data = get_user_data_dir()
        return user_data / "updater_state.json"
    
    def _load_state(self) -> Dict[str, Any]:
        """Load updater state from file"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load updater state: {e}")
        return {}
    
    def _save_state(self, state: Dict[str, Any]) -> None:
        """Save updater state to file"""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save updater state: {e}")
    
    def _get_headers(self) -> Dict[str, str]:
        """Get headers for GitHub API requests"""
        headers = {
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'MilkChan-Updater/1.0'
        }
        if self.github_token:
            headers['Authorization'] = f'token {self.github_token}'
        return headers
    
    def _api_get(self, endpoint: str) -> Optional[Dict]:
        """Make a GET request to GitHub API"""
        url = f"{self.GITHUB_API}/{endpoint}"
        try:
            response = requests.get(url, headers=self._get_headers(), timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"GitHub API request failed: {e}")
            return None
    
    def _get_remote_commit_info(self) -> Optional[Dict[str, str]]:
        """Get the latest commit info from GitHub API"""
        data = self._api_get(f"repos/{self.GITHUB_REPO}/commits/{self.BRANCH}")
        
        if not data:
            return None
        
        return {
            'sha': data.get('sha', ''),
            'message': data.get('commit', {}).get('message', ''),
            'date': data.get('commit', {}).get('committer', {}).get('date', ''),
            'url': data.get('html_url', '')
        }
    
    def _get_tree(self, sha: str) -> List[Dict]:
        """Get the git tree for a commit"""
        data = self._api_get(f"repos/{self.GITHUB_REPO}/git/trees/{sha}?recursive=1")
        
        if not data:
            return []
        
        return data.get('tree', [])
    
    def _download_file(self, github_path: str, local_path: Path) -> bool:
        """Download a single file from GitHub"""
        # Try raw URL first (works for public repos)
        raw_url = f"{self.GITHUB_RAW}/{self.GITHUB_REPO}/{self.BRANCH}/{github_path}"
        
        try:
            response = requests.get(raw_url, headers=self._get_headers(), timeout=30)
            
            # If raw URL fails (private repo), try API
            if response.status_code == 404 and self.github_token:
                api_data = self._api_get(f"repos/{self.GITHUB_REPO}/contents/{github_path}?ref={self.BRANCH}")
                if api_data and 'content' in api_data:
                    content = base64.b64decode(api_data['content'])
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    local_path.write_bytes(content)
                    return True
            
            response.raise_for_status()
            
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(response.content)
            return True
            
        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to download {github_path}: {e}")
            return False
    
    def check_for_updates(self, force: bool = False) -> Optional[UpdateInfo]:
        """Check if updates are available
        
        Args:
            force: Force check even if recently checked
            
        Returns:
            UpdateInfo if check succeeded, None otherwise
        """
        # Rate limiting - don't check too frequently
        if not force and self._last_check_time:
            time_since_check = (datetime.now(timezone.utc) - self._last_check_time).total_seconds()
            min_interval = 300  # 5 minutes minimum between manual checks
            if time_since_check < min_interval:
                logger.debug("Skipping update check - too soon since last check")
                return self._update_info
        
        logger.info("Checking for updates...")
        
        # Get the last applied framework SHA from state
        state = self._load_state()
        local_sha = state.get('last_applied_sha', '')
        
        # If no previous SHA recorded
        if not local_sha:
            local_sha = "unknown"
        
        remote_info = self._get_remote_commit_info()
        
        if not remote_info:
            logger.error("Cannot fetch remote commit info")
            return None
        
        remote_sha = remote_info['sha']
        
        # Check if update is available
        update_available = local_sha != remote_sha
        
        self._update_info = UpdateInfo(
            current_sha=local_sha,
            latest_sha=remote_sha,
            commit_message=remote_info['message'],
            commit_date=remote_info['date'],
            available=update_available,
            repo_url=f"https://github.com/{self.GITHUB_REPO}",
            branch=self.BRANCH
        )
        
        self._last_check_time = datetime.now(timezone.utc)
        
        # Save state
        state['last_check'] = self._last_check_time.isoformat()
        state['last_remote_sha'] = remote_sha
        state['update_available'] = update_available
        self._save_state(state)
        
        if update_available:
            logger.info(f"Framework update available: {local_sha[:7] if len(local_sha) > 7 else local_sha} -> {remote_sha[:7]}")
            logger.info(f"Commit message: {remote_info['message']}")
            
            if self.on_update_available:
                try:
                    self.on_update_available(self._update_info)
                except Exception as e:
                    logger.error(f"Update callback error: {e}")
            
            if self.auto_update:
                logger.info("Auto-update enabled - applying update...")
                self.apply_update()
        else:
            logger.info("No updates available - already at latest commit")
        
        return self._update_info
    
    def apply_update(self, backup: bool = True) -> bool:
        """Apply the available update by downloading framework files from GitHub
        
        Args:
            backup: Whether to create a backup before updating
            
        Returns:
            True if update succeeded, False otherwise
        """
        if not self._update_info or not self._update_info.available:
            logger.info("No update to apply")
            return False
        
        try:
            logger.info("Applying update...")
            
            # Get the target path for downloading updates
            # In bundled mode, always use user data (writable)
            # In dev mode, use source folder
            download_path = self._get_update_target_path()
            if not download_path:
                logger.error("Cannot determine download path")
                return False
            
            logger.info(f"Downloading to: {download_path}")
            
            # Create backup if requested and target exists
            if backup and download_path.exists() and (download_path / "ai.py").exists():
                backup_path = self._create_backup()
                if backup_path:
                    logger.info(f"Created backup at: {backup_path}")
            
            # Ensure target directory exists
            download_path.mkdir(parents=True, exist_ok=True)
            
            # Get the tree of files for the latest commit
            tree = self._get_tree(self._update_info.latest_sha)
            
            if not tree:
                logger.error("Failed to get file tree from GitHub")
                return False
            
            # Download files in the framework folder
            downloaded = 0
            failed = 0
            
            for item in tree:
                path = item.get('path', '')
                if path.startswith(self.FRAMEWORK_PATH + '/') and item.get('type') == 'blob':
                    relative_path = path.replace(self.FRAMEWORK_PATH + '/', '')
                    local_path = download_path / relative_path
                    
                    if self._download_file(path, local_path):
                        downloaded += 1
                    else:
                        failed += 1
            
            if failed > 0:
                logger.warning(f"Failed to download {failed} files")
            
            if downloaded == 0:
                logger.error("No files were downloaded")
                return False
            
            logger.info(f"Successfully updated {downloaded} framework files to {self._update_info.latest_sha[:7]}")
            
            # Update state
            state = self._load_state()
            state['last_applied_sha'] = self._update_info.latest_sha
            state['last_update_time'] = datetime.now(timezone.utc).isoformat()
            state['update_available'] = False
            self._save_state(state)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to apply update: {e}")
            return False
    
    def _create_backup(self) -> Optional[Path]:
        """Create a backup of the current framework folder"""
        if not self.framework_path or not self.framework_path.exists():
            return None
        
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"sentientmilk_backup_{timestamp}"
            
            from milkchan.bootstrap import get_user_data_dir
            backup_dir = get_user_data_dir() / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            
            backup_path = backup_dir / backup_name
            
            shutil.copytree(
                self.framework_path,
                backup_path,
                ignore=shutil.ignore_patterns(
                    '__pycache__', '*.pyc', '*.pyo'
                )
            )
            
            return backup_path
            
        except Exception as e:
            logger.warning(f"Failed to create backup: {e}")
            return None
    
    def start_auto_check(self) -> None:
        """Start automatic update checking in background thread"""
        if not self.auto_check:
            return
        
        if self._check_thread and self._check_thread.is_alive():
            logger.debug("Auto-check thread already running")
            return
        
        self._stop_event.clear()
        self._check_thread = threading.Thread(target=self._auto_check_loop, daemon=True)
        self._check_thread.start()
        logger.info("Started automatic update checking")
    
    def stop_auto_check(self) -> None:
        """Stop automatic update checking"""
        self._stop_event.set()
        if self._check_thread:
            self._check_thread.join(timeout=1.0)
    
    def _auto_check_loop(self) -> None:
        """Background loop for automatic update checks"""
        check_interval_seconds = self.check_interval_hours * 3600
        
        while not self._stop_event.is_set():
            try:
                self.check_for_updates()
            except Exception as e:
                logger.error(f"Error in auto-check: {e}")
            
            # Wait for next check interval or until stopped
            self._stop_event.wait(check_interval_seconds)
    
    def get_update_status(self) -> Dict[str, Any]:
        """Get current update status"""
        state = self._load_state()
        
        return {
            'auto_check': self.auto_check,
            'auto_update': self.auto_update,
            'check_interval_hours': self.check_interval_hours,
            'last_check': state.get('last_check'),
            'update_available': state.get('update_available', False),
            'current_sha': state.get('last_applied_sha'),
            'remote_sha': state.get('last_remote_sha'),
        }


# Global updater instance
_updater: Optional[AutoUpdater] = None


def get_updater(**kwargs) -> AutoUpdater:
    """Get or create global updater instance"""
    global _updater
    if _updater is None:
        _updater = AutoUpdater(**kwargs)
    return _updater


def check_updates_sync(force: bool = False) -> Optional[UpdateInfo]:
    """Synchronous update check - convenient function"""
    updater = get_updater()
    return updater.check_for_updates(force=force)


def format_update_message(info: UpdateInfo) -> str:
    """Format update info into user-friendly message"""
    current = info.current_sha[:7] if len(info.current_sha) > 7 else info.current_sha
    lines = [
        f"Framework Update Available!",
        f"",
        f"Current: {current}",
        f"Latest:  {info.latest_sha[:7]}",
        f"",
        f"Latest commit:",
        f"{info.commit_message[:100]}{'...' if len(info.commit_message) > 100 else ''}",
        f"Date: {info.commit_date}",
    ]
    return '\n'.join(lines)