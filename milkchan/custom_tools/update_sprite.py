"""
update_sprite - Custom tool for MilkChan to control the sprite emotion.

This tool is called by the LLM to set the sprite's emotion state.
"""

DESCRIPTION = """
Set Milk Chan's sprite emotion to match your reply.
The sprite will display the specified pose and mood.
Use it for your every message for immersion
"""

ARGS_DESCRIPTION = {
    "pose": "Body pose: 'arms_down' (relaxed), 'arms_crossed' (defensive), or 'one_arm' (casual)",
    "mood": "Facial expression: 'smile' (happy), 'neutral' (calm), 'sad' (downcast), 'mad' (angry), 'conf' (confident), 'nerv' (anxious), 'zout' (zoned out - only with arms_crossed)",
    "variation": "Sprite variation number (1-4, use 1 as default)",
    "expressions": "Optional comma-separated list: eyes_closed, eyes_half, mouth_closed, mouth_half, mouth_full"
}

_sprite_callback = None
_last_sprite_state = None  # Track last state to prevent duplicate calls


def reset_sprite_state():
    """Reset the sprite state tracker. Call this when starting a new conversation turn."""
    global _last_sprite_state
    _last_sprite_state = None


def set_sprite_callback(callback):
    """Set the callback function to be called when sprite should update.
    
    The callback should accept: (pose, mood, variation, expressions_list)
    """
    global _sprite_callback
    _sprite_callback = callback


def run(pose: str, mood: str, variation: str = "1", expressions: str = ""):
    """Update the sprite emotion.
    
    Args:
        pose: Body pose (arms_down, arms_crossed, one_arm)
        mood: Facial expression
        variation: Variation number as string (will be converted to int)
        expressions: Comma-separated expression modifiers
    """
    global _sprite_callback, _last_sprite_state
    
    valid_poses = ["arms_down", "arms_crossed", "one_arm"]
    valid_moods = ["smile", "neutral", "sad", "mad", "conf", "nerv", "zout"]
    
    pose = pose.lower().strip()
    mood = mood.lower().strip()
    
    if pose not in valid_poses:
        return {"error": f"Invalid pose '{pose}'. Valid: {valid_poses}"}
    
    if mood not in valid_moods:
        return {"error": f"Invalid mood '{mood}'. Valid: {valid_moods}"}
    
    if mood == "zout" and pose != "arms_crossed":
        return {"error": "'zout' mood is only available with 'arms_crossed' pose"}
    
    try:
        var_int = int(variation)
        if var_int < 1 or var_int > 4:
            var_int = 1
    except ValueError:
        var_int = 1
    
    expressions_list = []
    if expressions:
        valid_expressions = ["eyes_closed", "eyes_half", "mouth_closed", "mouth_half", "mouth_full"]
        for exp in expressions.split(","):
            exp = exp.strip().lower()
            if exp in valid_expressions:
                expressions_list.append(exp)
    
    # Check if this is a duplicate call
    current_state = (pose, mood, var_int, tuple(expressions_list))
    if _last_sprite_state == current_state:
        return {
            "success": True,
            "pose": pose,
            "mood": mood,
            "variation": var_int,
            "expressions": expressions_list,
            "message": "Sprite already set to this state. Proceed with your text response."
        }
    
    _last_sprite_state = current_state
    
    if _sprite_callback:
        try:
            _sprite_callback(pose, mood, var_int, expressions_list)
        except Exception as e:
            return {"error": f"Callback error: {e}"}
    
    return {
        "success": True,
        "pose": pose,
        "mood": mood,
        "variation": var_int,
        "expressions": expressions_list,
        "message": f"Sprite emotion set to {pose} with {mood} expression. Now respond to the user."
    }