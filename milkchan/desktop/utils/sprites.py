import os
import re
import json
from typing import Dict, List, Optional, Any
import numpy as np
from PIL import Image
from milkchan.bootstrap import get_assets_dir, load_sprite_cache, is_cache_valid, rebuild_sprite_cache

ASSETS_DIR = get_assets_dir()
SPRITES_DIR = ASSETS_DIR / 'sprites'
MAPPINGS_FILE = ASSETS_DIR / 'mappings.json'

# Base display size
BASE_WIDTH = 685
BASE_HEIGHT = 450
# Original sprite dimensions
ORIG_WIDTH = 1920
ORIG_HEIGHT = 1080
# Uniform scale factor to fit original into base
UNIFORM_SCALE = min(BASE_WIDTH / ORIG_WIDTH, BASE_HEIGHT / ORIG_HEIGHT)


def scan_sprites_folder() -> Dict:
    if not SPRITES_DIR.exists():
        return {}
    expressions = {}
    for pose in os.listdir(SPRITES_DIR):
        pose_path = SPRITES_DIR / pose
        if not pose_path.is_dir() or pose.startswith('.'):
            continue
        expressions[pose] = {}
        for mood in os.listdir(pose_path):
            mood_path = SPRITES_DIR / mood
            if not mood_path.is_dir() or mood.startswith('.'):
                continue
            expressions[pose][mood] = []
            for file in os.listdir(mood_path):
                if file.endswith('.png'):
                    expressions[pose][mood].append(file[:-4])
    with open(MAPPINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(expressions, f, indent=4)
    return expressions


def load_sprite_mappings() -> Dict:
    if MAPPINGS_FILE.exists():
        with open(MAPPINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return scan_sprites_folder()


def load_cached_sprites() -> Optional[Dict[str, Any]]:
    """Load pre-cached sprites from bootstrap cache"""
    return load_sprite_cache()


def load_sprites_with_scale(resolution_scale: float) -> Dict[str, Any]:
    """Load sprites, rebuilding cache if scale doesn't match"""
    from milkchan.bootstrap import get_cache_resolution_scale
    
    cached_scale = get_cache_resolution_scale()
    
    # Rebuild if scale doesn't match
    if cached_scale is None or abs(cached_scale - resolution_scale) > 0.01:
        print(f"[Sprites] Cache scale {cached_scale} != requested {resolution_scale}, rebuilding...")
        return rebuild_sprite_cache(resolution_scale)
    
    # Load from cache
    cache = load_sprite_cache()
    if cache:
        return cache
    
    # Fallback: rebuild
    return rebuild_sprite_cache(resolution_scale)


def build_sprite_tree_string(expressions_dict: Dict) -> str:
    tree_lines = ["--- AVAILABLE SPRITES ---"]
    for pose, moods in sorted(expressions_dict.items()):
        tree_lines.append(f"Pose: {pose}")
        for mood, filenames in sorted(moods.items()):
            tree_lines.append(f"  Mood: {mood}")
            variations = {
                int(f[len(mood) + 1:])
                for f in filenames
                if f.startswith(mood + '_') and f[len(mood) + 1:].isdigit()
            }
            expressions = {
                f[len(mood) + 1:]
                for f in filenames
                if f.startswith(mood + '_') and not f[len(mood) + 1:].isdigit()
            }
            if variations:
                tree_lines.append("    - Variations: " + ', '.join(map(str, sorted(variations))))
            if expressions:
                tree_lines.append("    - Expressions: " + ', '.join(sorted(expressions)))
    return "\n".join(tree_lines)


def add_expressions(base_mood: np.ndarray, exps: List[np.ndarray]) -> np.ndarray:
    blended_img = base_mood.copy()
    for exp in exps:
        alpha = exp[:, :, 3] / 255.0
        alpha_mask = np.stack([alpha] * 4, axis=2)
        blended_img = (blended_img * (1.0 - alpha_mask) + exp * alpha_mask).astype(np.uint8)
    return blended_img


def normalize_img(image: np.ndarray, scale_factor: float = 1.0, resolution_scale: float = 1.0) -> np.ndarray:
    """Crop sprite to character region.
    
    Sprites are pre-cached with uniform scaling from 1920x1080.
    Character is roughly at x=76-825, y=44-1079 in original.
    
    Args:
        image: Sprite image (uniformly scaled from original)
        scale_factor: UI display scale (from config)
        resolution_scale: Scale sprites were cached at
    """
    # Original character bounds (from sprite analysis)
    ORIG_LEFT = 76
    ORIG_TOP = 44
    ORIG_RIGHT = 825
    ORIG_BOTTOM = 1079
    
    # Add some padding
    PADDING = 10
    ORIG_LEFT -= PADDING
    ORIG_TOP -= PADDING
    ORIG_RIGHT += PADDING
    ORIG_BOTTOM += PADDING
    
    # Calculate the scale that was applied to get current image size
    current_scale = UNIFORM_SCALE * resolution_scale
    
    # Crop region in current image coordinates
    crop_left = int(ORIG_LEFT * current_scale)
    crop_top = int(ORIG_TOP * current_scale)
    crop_right = int(ORIG_RIGHT * current_scale)
    crop_bottom = int(ORIG_BOTTOM * current_scale)
    
    # Clamp to image bounds
    h, w = image.shape[:2]
    crop_left = max(0, min(crop_left, w))
    crop_right = max(0, min(crop_right, w))
    crop_top = max(0, min(crop_top, h))
    crop_bottom = max(0, min(crop_bottom, h))
    
    # Crop the character region
    cropped = image[crop_top:crop_bottom, crop_left:crop_right]
    
    # If display scale differs from resolution scale, resize to final size
    final_scale = scale_factor / resolution_scale
    if abs(final_scale - 1.0) > 0.01:
        target_w = int(cropped.shape[1] * final_scale)
        target_h = int(cropped.shape[0] * final_scale)
        pil_img = Image.fromarray(cropped).resize((target_w, target_h), Image.Resampling.NEAREST)
        return np.array(pil_img)
    
    return cropped


def get_sprite_path(pose: str, mood: str, variation: int = None, exp: str = None) -> str:
    filename = f"{mood}"
    if variation:
        filename += f"_{variation}"
    if exp:
        filename += f"_{exp}"
    filename += ".png"
    return str(SPRITES_DIR / pose / mood / filename)