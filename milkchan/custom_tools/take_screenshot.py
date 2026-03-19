"""
take_screenshot - Custom tool for MilkChan to capture the screen.

Allows the LLM to see what's on screen for context-aware responses.
"""

DESCRIPTION = """
Take a screenshot of the current screen to see what the user is looking at.
Use this to understand the user's current context when they ask about something on screen.
"""

ARGS_DESCRIPTION = {
    "resize_factor": "Optional resize factor (0.0-1.0) to reduce image size. Default 0.35"
}

def run(resize_factor: str = "0.35"):
    """Take a screenshot and return the path.
    
    Args:
        resize_factor: Factor to resize image (as string, will be converted)
    """
    try:
        from milkchan.desktop.utils.screenshot import take_screenshot
        try:
            rf = float(resize_factor)
            rf = max(0.1, min(1.0, rf))
        except ValueError:
            rf = 0.35
        
        result = take_screenshot(rf)
        if result:
            path, width, height = result
            return {
                "success": True,
                "path": path,
                "width": width,
                "height": height,
                "message": f"Screenshot saved to {path}"
            }
        return {"error": "Failed to take screenshot"}
    except Exception as e:
        return {"error": str(e)}