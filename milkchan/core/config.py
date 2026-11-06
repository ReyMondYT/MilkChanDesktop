"""MilkChan settings, stored as JSON at the XDG config path."""

import copy
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from milkchan.paths import get_config_path

logger = logging.getLogger(__name__)

DEFAULTS: Dict[str, Any] = {
    "position": {"x_offset": 0, "y_offset": 0},
    "scale_factor": 100,
    "font_size": 24,
    "char_delay_ms": 50,
    "username": os.getenv("USERNAME") or os.getenv("USER") or "User",
    "character": "",
    # The provider, model and tool keys belong to the brain (SentientMilk's settings).
    "processing": {"support_images": True, "screenshot_scale": 0.35},
    "proactive": {"enabled": True},
    "updates": {
        "auto_check": True,
        "auto_update": True,
        "check_interval_hours": 24,
        "github_token": "",
    },
}

_OBSOLETE_KEYS = ("sprite_resolution_scale", "sprite_pack", "ai_service_url", "memory_service_url")
_OBSOLETE_PROCESSING = (
    "vision_mode", "vision_enabled", "audio_enabled", "buffer_seconds",
    "screenshot_on_disabled_vision", "total_first_reply_budget_sec",
    "force_wait_for_emotion", "emotion_wait_timeout_sec", "emotion_min_wait_sec",
)


def _migrate(loaded: Dict[str, Any]) -> None:
    """Translate settings written by earlier versions, in place."""
    for key in _OBSOLETE_KEYS:
        loaded.pop(key, None)
    processing = loaded.get("processing")
    if isinstance(processing, dict):
        if "support_images" not in processing:
            mode = processing.get("vision_mode")
            if mode in ("text", "image", "video"):
                processing["support_images"] = mode != "text"
            elif "vision_enabled" in processing or "screenshot_on_disabled_vision" in processing:
                processing["support_images"] = bool(
                    processing.get("vision_enabled", True)
                    or processing.get("screenshot_on_disabled_vision", False)
                )
        if "video_resize_factor" in processing:
            processing.setdefault("screenshot_scale", processing.pop("video_resize_factor"))
        for key in _OBSOLETE_PROCESSING:
            processing.pop(key, None)
    if isinstance(loaded.get("proactive"), dict):
        loaded["proactive"] = {k: v for k, v in loaded["proactive"].items() if k == "enabled"}
    if isinstance(loaded.get("updates"), dict):
        for key in ("github_repo", "branch"):
            loaded["updates"].pop(key, None)


class Config:
    def __init__(self, config_path: Optional[str] = None):
        self.path = Path(config_path or get_config_path())
        self._config = self._load()

    def _load(self) -> Dict[str, Any]:
        config = copy.deepcopy(DEFAULTS)
        if not self.path.exists():
            return config
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("top level is not an object")
        except (OSError, ValueError) as exc:
            # Keep the unreadable file so a later save cannot destroy its contents.
            kept = self.path.with_name(self.path.name + ".invalid")
            logger.error("Config %s is unreadable (%s); kept as %s, using defaults", self.path, exc, kept)
            try:
                os.replace(self.path, kept)
            except OSError:
                pass
            return config
        _migrate(loaded)
        self._merge(config, loaded)
        return config

    @staticmethod
    def _merge(config: Dict[str, Any], data: Dict[str, Any]) -> None:
        for key, value in data.items():
            if isinstance(value, dict) and isinstance(config.get(key), dict):
                config[key].update(copy.deepcopy(value))
            else:
                config[key] = copy.deepcopy(value)

    def save(self) -> None:
        """Write atomically: a crash leaves either the old or the new file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".config-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(self._config, output, indent=4)
            os.replace(temporary, self.path)
        except BaseException:
            os.unlink(temporary)
            raise

    def get(self, key: str, default: Any = None) -> Any:
        """Read a value by dot-notation key, e.g. ``processing.support_images``."""
        value: Any = self._config
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value

    def set(self, key: str, value: Any) -> None:
        parts = key.split(".")
        current = self._config
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        current[parts[-1]] = value
        self.save()

    def update(self, data: Dict[str, Any]) -> None:
        self._merge(self._config, data)
        self.save()

    def remove(self, *keys: str) -> None:
        """Delete dot-notation keys; saves only if something was there."""
        removed = False
        for key in keys:
            *parents, last = key.split(".")
            container = self._config
            for part in parents:
                container = container.get(part) if isinstance(container, dict) else None
            if isinstance(container, dict) and last in container:
                del container[last]
                removed = True
        if removed:
            self.save()

    def as_dict(self) -> Dict[str, Any]:
        return copy.deepcopy(self._config)


_config: Optional[Config] = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config


def reload_config() -> Config:
    global _config
    _config = Config()
    return _config


def load_config() -> Dict[str, Any]:
    """An independent copy of the current settings."""
    return get_config().as_dict()
