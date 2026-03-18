"""Unified configuration system for MilkChan

All settings stored in ~/.milkchan/config.json
"""

import os
import json
from pathlib import Path
from getpass import getuser
from typing import Optional, Any, Dict

from milkchan.bootstrap import get_config_path, get_user_data_dir


class Config:
    """Unified configuration manager - all settings in ~/.milkchan/config.json"""
    
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or str(get_config_path())
        self._config: Dict[str, Any] = {}
        self.load()
    
    def _find_config_file(self) -> str:
        """Find config.json - prefer user data dir"""
        user_config = get_config_path()
        if user_config.exists():
            return str(user_config)
        return str(user_config)  # Will be created
    
    def load(self) -> None:
        """Load configuration from file"""
        default_config = {
            "position": {"x_offset": 0, "y_offset": 0},
            "scale_factor": 100,
            "font_size": 6,
            "char_delay_ms": 50,
            "username": os.getenv("USERNAME") or getuser() or "User",
            "sprite_resolution_scale": 1.0,

            # API Configuration - stored in config.json!
            "openai_api_key": "",
            "openai_base_url": "https://api.openai.com/v1",
            "openai_chat_model": "gpt-4o-mini",
            "openai_vision_model": "gpt-4o-mini",

            "processing": {
                "vision_mode": "image",
                "vision_enabled": True,
                "audio_enabled": True,
                "video_resize_factor": 0.35,
                "buffer_seconds": 10,
                "screenshot_on_disabled_vision": True,
                "total_first_reply_budget_sec": 15.0,
                "force_wait_for_emotion": True,
                "emotion_wait_timeout_sec": 6.0,
                "emotion_min_wait_sec": 0.5,
            },
            "proactive": {
                "enabled": True,
                "sample_interval_ms": 1200,
                "change_threshold": 0.08,
                "pixel_delta": 0.08,
                "min_interval_sec": 15.0,
                "min_change_percent": 6.0,
                "highlight_score_threshold": 0.55,
            },
        }

        config_file = Path(self.config_path)
        if not config_file.exists():
            self._config = default_config
            if config_file.parent.exists():
                self.save()
            return
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            
            self._config = default_config.copy()
            
            for k, v in loaded.items():
                if isinstance(v, dict) and k in self._config and isinstance(self._config[k], dict):
                    self._config[k].update(v)
                else:
                    self._config[k] = v
                    
        except Exception:
            self._config = default_config
    
    def save(self) -> None:
        """Save configuration to file"""
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self._config, f, indent=4)
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value by dot-notation key"""
        parts = key.split('.')
        value = self._config
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return default
        return value
    
    def set(self, key: str, value: Any) -> None:
        """Set configuration value by dot-notation key"""
        parts = key.split('.')
        current = self._config
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value
        self.save()
    
    def update(self, data: dict) -> None:
        """Update config with dictionary of values"""
        for key, value in data.items():
            if isinstance(value, dict) and key in self._config and isinstance(self._config[key], dict):
                self._config[key].update(value)
            else:
                self._config[key] = value
        self.save()
    
    # API Configuration properties (read/write from config.json)
    @property
    def openai_api_key(self) -> str:
        return self._config.get("openai_api_key", "")
    
    @openai_api_key.setter
    def openai_api_key(self, value: str):
        self._config["openai_api_key"] = value
        self.save()
    
    @property
    def openai_base_url(self) -> str:
        return self._config.get("openai_base_url", "https://api.openai.com/v1")
    
    @openai_base_url.setter
    def openai_base_url(self, value: str):
        self._config["openai_base_url"] = value
        self.save()
    
    @property
    def openai_chat_model(self) -> str:
        return self._config.get("openai_chat_model", "gpt-4o-mini")
    
    @openai_chat_model.setter
    def openai_chat_model(self, value: str):
        self._config["openai_chat_model"] = value
        self.save()
    
    @property
    def openai_vision_model(self) -> str:
        return self._config.get("openai_vision_model", self.openai_chat_model)

    @openai_vision_model.setter
    def openai_vision_model(self, value: str):
        self._config["openai_vision_model"] = value
        self.save()

    # Service URLs
    @property
    def ai_service_url(self) -> str:
        return self._config.get("ai_service_url", "http://localhost:8001")
    
    @property
    def memory_service_url(self) -> str:
        return self._config.get("memory_service_url", "http://localhost:8002")


# Global config instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get global config instance"""
    global _config
    if _config is None:
        _config = Config()
    return _config


def reload_config() -> Config:
    """Reload global config"""
    global _config
    _config = Config()
    return _config


def load_config() -> Dict[str, Any]:
    """Load and return config as dict (for backward compatibility)"""
    return get_config()._config.copy()


def save_config(cfg: Dict[str, Any]) -> None:
    """Save config dict to file (for backward compatibility)"""
    config = get_config()
    config._config = cfg
    config.save()
