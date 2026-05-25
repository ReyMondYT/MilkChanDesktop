"""Shared image-support configuration helpers."""

from __future__ import annotations

from typing import Any, Dict


def support_images_enabled(config: Dict[str, Any]) -> bool:
    """Return whether MilkChan may capture/send screenshots.

    `processing.support_images` is authoritative. Legacy vision keys are only
    used to keep old configs compatible until settings are saved again.
    """
    processing = (config.get("processing") or {}) if isinstance(config, dict) else {}
    if "support_images" in processing:
        return bool(processing.get("support_images"))

    legacy_mode = processing.get("vision_mode")
    if legacy_mode == "text":
        return False
    if legacy_mode in ("image", "video"):
        return True

    return bool(processing.get("vision_enabled", True)) or bool(
        processing.get("screenshot_on_disabled_vision", False)
    )


def normalize_image_support_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize config in-place and return it."""
    processing = config.setdefault("processing", {})
    support_images = support_images_enabled(config)
    processing["support_images"] = support_images
    processing["vision_mode"] = "image" if support_images else "text"
    processing["vision_enabled"] = support_images
    processing["audio_enabled"] = False
    processing["screenshot_on_disabled_vision"] = False
    return config
