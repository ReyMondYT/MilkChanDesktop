"""
AI Client - SentientMilk Framework Integration

Uses SentientMilk framework for AI interactions with tool support.
Maintains backward compatibility with existing MilkChan code.
"""

import os
import sys
import time
import json
import logging
from typing import List, Optional, Tuple, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)

_config = None
_llm = None
_persona_cache = None
_last_emotion: Dict[str, Any] = {}

def _get_config():
    """Get cached config instance"""
    global _config
    if _config is None:
        from milkchan.core.config import get_config
        _config = get_config()
    return _config

def _get_persona():
    """Get cached persona description"""
    global _persona_cache
    
    if _persona_cache is None:
        try:
            from milkchan.desktop.services import memory_client
            result = memory_client.get_item('persona', 'personality')
            _persona_cache = result or ''
            
            if not _persona_cache:
                from milkchan.bootstrap import get_assets_dir
                persona_file = get_assets_dir() / 'MILKCHAN.md'
                if persona_file.exists():
                    _persona_cache = persona_file.read_text(encoding='utf-8')
                else:
                    _persona_cache = "Milk Chan is a cheerful anime-style assistant."
        except Exception as e:
            logger.warning(f"Failed to load persona: {e}")
            _persona_cache = "Milk Chan is an anime-style assistant."
    return _persona_cache

def set_persona(persona: str):
    """Update cached persona"""
    global _persona_cache
    _persona_cache = persona

def reload_config():
    """Force reload config and LLM instance"""
    global _config, _llm, _persona_cache
    from milkchan.core.config import reload_config as core_reload
    _config = core_reload()
    _llm = None
    _persona_cache = None
    return _config

def _get_llm():
    """Get or create SentientMilk LLM instance"""
    global _llm
    
    if _llm is None:
        config = _get_config()
        
        api_key = config.openai_api_key
        base_url = config.openai_base_url
        model = config.openai_chat_model
        
        if not api_key or not base_url or not model:
            raise ValueError("API credentials not configured")
        
        # Check for updated framework in user data (for bundled EXE updates)
        if getattr(sys, 'frozen', False):
            from milkchan.bootstrap import get_user_data_dir
            user_framework = get_user_data_dir() / "sentientmilk_framework"
            if user_framework.exists() and (user_framework / "ai.py").exists():
                # Add to sys.path so imports use the updated version
                user_framework_str = str(user_framework.parent)
                if user_framework_str not in sys.path:
                    sys.path.insert(0, user_framework_str)
                    logger.info(f"Using updated framework from: {user_framework}")
        
        from milkchan.sentientmilk_framework import LLM, Settings
        
        # Find custom_tools path (works in both dev and bundled mode)
        if getattr(sys, 'frozen', False):
            # PyInstaller bundled - check user data first for updates
            from milkchan.bootstrap import get_user_data_dir
            user_tools = get_user_data_dir() / "custom_tools"
            if user_tools.exists():
                custom_tools_path = user_tools
            else:
                meipass = getattr(sys, '_MEIPASS', '.')
                custom_tools_path = Path(meipass) / "milkchan" / "custom_tools"
        else:
            # Development
            custom_tools_path = Path(__file__).parent.parent.parent / "custom_tools"
        
        persona = _get_persona()
        
        milkchan_persona = f"""
Name: Milk Chan
{persona}

## STRICT RESPONSE FORMAT
1. No Roleplaying actions: Do not simulate actions or emotions through asterisks. (e.g., *smiles*).
2. Avoid Generic AI Phrases: Do not say 'As an AI...'.
3. Do not use emojis or emoticons in your response.
4. Match your sprite emotion to your reply CONTENT using the update_sprite.
5. Don't write long messages, 2-3 sentences is maximum.
6. You have access to tools like memory, take_screenshot, read, write, edit, delete, and exec.
7. Use tools autonomously to help the user without asking for permission.
"""
        
        settings = Settings(
            persona=milkchan_persona,
            custom_tools_path=str(custom_tools_path)
        )
        
        _llm = LLM(
            api_key=api_key,
            base_url=base_url,
            model=model,
            settings=settings,
            request_timeout=(15.0, 180.0),
            tool_event_handler=_tool_event_handler
        )
        
        # Set the callback on the dynamically loaded module instance
        if 'update_sprite' in _llm._loaded_tools:
            _llm._loaded_tools['update_sprite']._sprite_callback = _sprite_update_callback
    
    return _llm

_last_sprite_update = None

def _sprite_update_callback(pose: str, mood: str, variation: int, expressions: list):
    """Callback when update_sprite tool is called - records emotion for later sync with message"""
    global _last_sprite_update, _last_emotion
    _last_sprite_update = {
        'pose': pose,
        'mood': mood,
        'variation': variation,
        'expressions': expressions
    }
    _last_emotion = {'emotion': [pose, mood, variation] + expressions}
    # Note: Emotion is returned via _last_emotion and will be applied when message is displayed

def _tool_event_handler(event: Dict[str, Any]):
    """Handle tool events from SentientMilk framework"""
    event_type = event.get('type', '')
    tool_name = event.get('tool_name', 'unknown')
    
    if event_type == 'tool_start':
        logger.info(f"[TOOL] Starting: {tool_name} with args: {event.get('arguments', {})}")
    elif event_type == 'tool_end':
        logger.info(f"[TOOL] Completed: {tool_name}")
    elif event_type == 'tool_error':
        logger.error(f"[TOOL] Error in {tool_name}: {event.get('error', 'unknown')}")

def chat_respond(
    user_message: str,
    persona_description: Optional[str] = None,
    history: Optional[List[dict]] = None,
    username: Optional[str] = None,
    image_path: Optional[str] = None,
    video_path: Optional[str] = None,
    timeout_sec: Optional[float] = None
) -> Tuple[str, Optional[dict]]:
    """
    Send a message to the AI and get response with emotion.
    
    Uses SentientMilk framework for AI interaction with tool support.
    
    Args:
        user_message: User's message
        persona_description: Override persona (uses cached persona if not provided)
        history: Conversation history
        username: User's name
        image_path: Optional image path for vision
        video_path: Optional video path (not yet implemented)
        timeout_sec: Optional timeout
        
    Returns:
        Tuple of (response_text, emotion_dict)
    """
    global _last_emotion, _last_sprite_update
    
    t0 = time.perf_counter()
    config = _get_config()
    
    # Reset sprite state for new conversation turn
    from milkchan.custom_tools.update_sprite import reset_sprite_state
    reset_sprite_state()
    
    if history is None:
        history = []
    
    if persona_description:
        set_persona(persona_description)
    
    _last_sprite_update = None
    _last_emotion = {}
    
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    hidden_text = f"--Hidden context: Time: {timestamp} | PC Name: {username or 'User'}--\n{user_message}"
    
    messages: List[dict] = []
    
    for msg in history:
        messages.append(msg)
    
    user_content = hidden_text
    
    if image_path and os.path.exists(image_path):
        try:
            import base64
            with open(image_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')
            
            user_content = [
                {"type": "text", "text": hidden_text},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_data}"}}
            ]
        except Exception as e:
            logger.warning(f"Failed to attach image: {e}")
    
    messages.append({"role": "user", "content": user_content})
    
    try:
        llm = _get_llm()
        
        response = llm.completion(messages, stream=False)
        
        reply_text = ""
        emotion_obj = None
        
        if isinstance(response, dict):
            if 'error' in response:
                logger.error(f"LLM error: {response['error']}")
                return "", None
            
            choices = response.get('choices', [])
            if choices:
                reply_text = choices[0].get('message', {}).get('content', '')
        
        if _last_emotion:
            emotion_obj = _last_emotion
        
        total_time = time.perf_counter() - t0
        logger.info(f"✓ chat_respond: TOTAL={total_time:.2f}s reply_len={len(reply_text)} has_emotion={bool(emotion_obj)}")
        
        return reply_text.strip(), emotion_obj
        
    except Exception as e:
        logger.exception(f"chat_respond error: {e}")
        return "", None


def chat_respond_with_tools(
    user_message: str,
    persona_description: Optional[str] = None,
    history: Optional[List[dict]] = None,
    username: Optional[str] = None,
    image_path: Optional[str] = None,
    timeout_sec: Optional[float] = None
) -> Tuple[str, Optional[dict]]:
    """
    Same as chat_respond - uses SentientMilk framework with tools.
    
    Kept for backward compatibility.
    """
    return chat_respond(
        user_message=user_message,
        persona_description=persona_description,
        history=history,
        username=username,
        image_path=image_path,
        timeout_sec=timeout_sec
    )


def analyze_emotion(text: str, sprites_tree: str) -> dict:
    """
    Analyze emotion from text.
    
    With SentientMilk, emotions are handled via update_sprite tool,
    so this is kept for legacy compatibility.
    """
    global _last_emotion
    
    if _last_emotion:
        return _last_emotion
    
    return {"emotion": ["arms_down", "neutral", 1]}


def grounding_bbox(text: str) -> dict:
    """Stub - grounding not needed"""
    return {}


def describe_video_tail(video_path: str, seconds: int = 4) -> str:
    """Describe video - not yet implemented"""
    return "Video description not yet implemented"