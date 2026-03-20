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
import importlib
from typing import List, Optional, Tuple, Dict, Any, TypedDict, Union, Callable


# Global list to capture tool events during a chat request
_captured_tools: List[Dict[str, Any]] = []


def _clear_captured_tools():
    """Clear the captured tools list before a new chat request."""
    global _captured_tools
    _captured_tools = []


class ChatError(TypedDict):
    type: str
    message: str
    details: Optional[str]
    http_status: Optional[int]


class ChatResult(TypedDict):
    response: str
    emotion: Optional[dict]
    error: Optional[ChatError]
    tools: List[Dict[str, Any]]


def create_error(error_type: str, message: str, details: Optional[str] = None, http_status: Optional[int] = None) -> ChatError:
    return ChatError(
        type=error_type,
        message=message,
        details=details,
        http_status=http_status
    )


def classify_http_error(status_code: int, url: str = "") -> ChatError:
    if status_code == 429:
        return create_error(
            "rate_limit",
            "API rate limit exceeded",
            "The AI service is busy. Please wait a moment and try again.",
            http_status=429
        )
    elif status_code == 401:
        return create_error(
            "auth_error",
            "Authentication failed",
            "Please check your API key configuration.",
            http_status=401
        )
    elif status_code == 402:
        return create_error(
            "payment_required",
            "API quota exceeded",
            "The API account needs credits. Please add funds or wait for quota reset.",
            http_status=402
        )
    elif status_code == 408 or status_code == 504:
        return create_error(
            "timeout",
            "Request timed out",
            "The AI took too long to respond. Try again.",
            http_status=status_code
        )
    elif status_code >= 500:
        return create_error(
            "server_error",
            "AI service error",
            f"The AI service returned error {status_code}. Try again later.",
            http_status=status_code
        )
    else:
        return create_error(
            "http_error",
            f"Request failed ({status_code})",
            f"URL: {url}",
            http_status=status_code
        )
from pathlib import Path

logger = logging.getLogger(__name__)

_config = None
_llm = None
_persona_cache = None
_last_emotion: Dict[str, Any] = {}


def _clear_sentientmilk_modules():
    """Remove previously loaded sentientmilk_framework modules to force reload."""
    to_remove = [name for name in sys.modules if name == 'sentientmilk_framework' or name.startswith('sentientmilk_framework.')]
    for name in to_remove:
        sys.modules.pop(name, None)

def _load_framework_from_user_data() -> Tuple[Optional[Any], Optional[Any]]:
    """Attempt to load sentientmilk_framework from the writable user data folder."""
    try:
        from milkchan.bootstrap import get_user_data_dir
        user_framework = get_user_data_dir() / "sentientmilk_framework"
        init_path = user_framework / "__init__.py"
        if not init_path.exists():
            return None, None

        _clear_sentientmilk_modules()

        framework_parent = str(user_framework.parent)
        if framework_parent not in sys.path:
            sys.path.insert(0, framework_parent)

        framework_module = importlib.import_module("sentientmilk_framework")
        LLM = getattr(framework_module, "LLM", None)
        Settings = getattr(framework_module, "Settings", None)
        if LLM and Settings:
            logger.info(f"Using updated framework from: {user_framework}")
            return LLM, Settings
    except Exception as exc:
        logger.error(f"Failed loading user framework override: {exc}")
    return None, None


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

        # Always prefer user-data override so dev and bundled behave the same
        LLM, Settings = _load_framework_from_user_data()

        if LLM is None or Settings is None:
            # Use bundled framework
            from milkchan.sentientmilk_framework import LLM, Settings

        # Find custom_tools path (prefer user data in both modes)
        from milkchan.bootstrap import get_user_data_dir
        user_tools = get_user_data_dir() / "custom_tools"
        if user_tools.exists():
            custom_tools_path = user_tools
        else:
            if getattr(sys, 'frozen', False):
                meipass = getattr(sys, '_MEIPASS', '.')
                custom_tools_path = Path(meipass) / "milkchan" / "custom_tools"
            else:
                # Development fallback to repo tools
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
6. Use tools autonomously to help the user without asking for permission.
"""

        settings = Settings(
            persona=milkchan_persona,
            custom_tools_path=str(custom_tools_path)
        )

        web_search_token = config.get('tools.web_search_token', '')

        _llm = LLM(
            api_key=api_key,
            base_url=base_url,
            model=model,
            settings=settings,
            request_timeout=(15.0, 180.0),
            tool_event_handler=_tool_event_handler,
            web_search_token=web_search_token if web_search_token else None
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

# Callback for streaming tool events to IPC server
_tool_event_callback: Optional[Callable[[Dict[str, Any]], None]] = None


def set_tool_event_callback(callback: Optional[Callable[[Dict[str, Any]], None]]):
    """Set a callback function to receive real-time tool events.
    
    This enables streaming tool events to external clients (like TUI).
    """
    global _tool_event_callback
    _tool_event_callback = callback


def _emit_tool_event(event: Dict[str, Any]):
    """Emit tool event to callback if registered."""
    global _tool_event_callback
    if _tool_event_callback:
        try:
            _tool_event_callback(event)
        except Exception as e:
            logger.warning(f"Failed to emit tool event: {e}")


def _tool_event_handler(event: Dict[str, Any]):
    """Handle tool events from SentientMilk framework and capture them for display"""
    global _captured_tools
    event_type = event.get('type', '')
    tool_name = event.get('tool_name', 'unknown')
    
    if event_type == 'tool_start':
        logger.info(f"[TOOL] Starting: {tool_name} with args: {event.get('arguments', {})}")
        # Capture tool start event
        tool_data = {
            'tool_name': tool_name,
            'status': 'running',
            'arguments': event.get('arguments', {}),
            'result': None,
            'error': None
        }
        _captured_tools.append(tool_data)
        # Emit for real-time streaming
        _emit_tool_event({**tool_data, 'type': 'tool_start'})
        
    elif event_type == 'tool_end':
        logger.info(f"[TOOL] Completed: {tool_name}")
        # Update the last tool with the result
        for tool in reversed(_captured_tools):
            if tool['tool_name'] == tool_name and tool['status'] == 'running':
                tool['status'] = 'completed'
                tool['result'] = event.get('result', '')
                # Emit for real-time streaming
                _emit_tool_event({**tool, 'type': 'tool_end'})
                break
                
    elif event_type == 'tool_error':
        logger.error(f"[TOOL] Error in {tool_name}: {event.get('error', 'unknown')}")
        # Update the last tool with the error
        for tool in reversed(_captured_tools):
            if tool['tool_name'] == tool_name and tool['status'] == 'running':
                tool['status'] = 'error'
                tool['error'] = event.get('error', 'unknown')
                # Emit for real-time streaming
                _emit_tool_event({**tool, 'type': 'tool_error'})
                break

def chat_respond(
    user_message: str,
    persona_description: Optional[str] = None,
    history: Optional[List[dict]] = None,
    username: Optional[str] = None,
    image_path: Optional[str] = None,
    video_path: Optional[str] = None,
    timeout_sec: Optional[float] = None
) -> ChatResult:
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
    _clear_captured_tools()

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
                return ChatResult(
                    response="",
                    emotion=None,
                    error=create_error("api_error", "AI returned an error", str(response.get('error'))),
                    tools=_captured_tools.copy()
                )

            # Try multiple response formats
            choices = response.get('choices', [])
            if choices and isinstance(choices, list):
                first_choice = choices[0]
                if isinstance(first_choice, dict):
                    message = first_choice.get('message', {})
                    if isinstance(message, dict):
                        reply_text = message.get('content', '')
                    else:
                        reply_text = str(message)
                else:
                    reply_text = str(first_choice)
            
            # Also check for direct content field
            if not reply_text:
                reply_text = response.get('content', '')
            
            # Check for text field
            if not reply_text:
                reply_text = response.get('text', '')
            
            # Check for response field
            if not reply_text:
                reply_text = response.get('response', '')
            
            # Log raw response for debugging if empty
            if not reply_text:
                logger.warning(f"Empty response. Raw response keys: {list(response.keys())}")

            if _last_emotion:
                emotion_obj = _last_emotion

        total_time = time.perf_counter() - t0
        logger.info(f"✓ chat_respond: TOTAL={total_time:.2f}s reply_len={len(reply_text)} has_emotion={bool(emotion_obj)}")

        return ChatResult(response=reply_text.strip(), emotion=emotion_obj, error=None, tools=_captured_tools.copy())

    except Exception as e:
        logger.exception(f"chat_respond error: {e}")
        
        error = None
        
        # Check for HTTP errors with status code
        if hasattr(e, 'response') and hasattr(e.response, 'status_code'):
            error = classify_http_error(e.response.status_code, str(getattr(e, 'url', '')))
        elif '429' in str(e) or 'Too Many Requests' in str(e):
            error = classify_http_error(429)
        elif '401' in str(e) or 'Unauthorized' in str(e):
            error = classify_http_error(401)
        elif 'timeout' in str(e).lower() or 'timed out' in str(e).lower():
            error = create_error("timeout", "Request timed out", "The AI took too long to respond.")
        elif 'connection' in str(e).lower() or 'network' in str(e).lower():
            error = create_error("network", "Connection failed", "Could not reach the AI service. Check your network.")
        else:
            error = create_error("unknown", "An error occurred", str(e))
        
        return ChatResult(response="", emotion=None, error=error, tools=_captured_tools.copy())


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