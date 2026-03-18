"""
AI Client - Direct OpenAI calls (NO HTTP!)

Uses OpenAI SDK directly instead of HTTP API calls.
Uses cached config for performance - reloaded on settings save.
Optimized: Single API call using function calling for both response + sprite update.
"""

import os
import time
import json
import logging
from typing import List, Optional, Tuple, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)

# Cached config - loaded once on first use, reloaded when settings change
_config = None
_sprites_tool_cache = None
_persona_cache = None  # Cached persona description

def _get_config():
    """Get cached config instance"""
    global _config
    if _config is None:
        from milkchan.core.config import get_config
        _config = get_config()
    return _config

def _get_persona():
    """Get cached persona description, load from memory or MILKCHAN.md on first use"""
    global _persona_cache
    print(f"[_get_persona] called, cache={repr(_persona_cache)[:50] if _persona_cache else 'None/empty'}")
    
    if _persona_cache is None:
        try:
            from milkchan.desktop.services import memory_client
            result = memory_client.get_item('persona', 'personality')
            print(f"[_get_persona] memory_client returned: {repr(result)[:50] if result else result}")
            _persona_cache = result or ''
            
            if not _persona_cache:
                # Try loading from MILKCHAN.md in user data dir
                from milkchan.bootstrap import get_assets_dir
                persona_file = get_assets_dir() / 'MILKCHAN.md'
                print(f"[_get_persona] Looking for persona at: {persona_file}")
                if persona_file.exists():
                    _persona_cache = persona_file.read_text(encoding='utf-8')
                    print(f"[_get_persona] Loaded persona from MILKCHAN.md: {len(_persona_cache)} chars")
                else:
                    # Fallback default
                    _persona_cache = "Milk Chan is a cheerful anime-style assistant."
                    print(f"[_get_persona] No persona file found, using default")
            else:
                print(f"[_get_persona] Loaded persona from memory: {len(_persona_cache)} chars")
        except Exception as e:
            print(f"[_get_persona] EXCEPTION: {e}")
            import traceback
            traceback.print_exc()
            _persona_cache = "Milk Chan is an anime-style assistant."
    return _persona_cache

def set_persona(persona: str):
    """Update cached persona (call when persona settings change)"""
    global _persona_cache
    _persona_cache = persona

def reload_config():
    """Force reload config from file (call when settings change)"""
    global _config, _sprites_tool_cache, _persona_cache
    from milkchan.core.config import reload_config as core_reload
    _config = core_reload()
    _sprites_tool_cache = None
    _persona_cache = None  # Reset to None so _get_persona will reload properly
    return _config


def _get_client():
    """Get OpenAI client with current config"""
    from openai import OpenAI
    config = _get_config()
    return OpenAI(
        api_key=config.openai_api_key,
        base_url=config.openai_base_url if config.openai_base_url else None
    )


def _build_sprite_tool() -> dict:
    """
    Build the update_sprite function tool definition with visual descriptions.
    
    The tool specifies which moods are available for each pose, so the LLM
    only selects valid pose-mood combinations.
    """
    global _sprites_tool_cache
    if _sprites_tool_cache is not None:
        return _sprites_tool_cache

    # Define available moods per pose (based on actual sprite folders)
    # zout is only available for arms_crossed
    pose_moods = {
        "arms_down": ["smile", "neutral", "sad", "mad", "conf", "nerv"],
        "arms_crossed": ["smile", "neutral", "sad", "mad", "conf", "nerv", "zout"],
        "one_arm": ["smile", "neutral", "sad", "mad", "conf", "nerv"],
    }

    # Visual descriptions for each mood - edit these to tweak how LLM understands emotions
    mood_descriptions = {
        "smile": "happy, cheerful, pleased expression",
        "neutral": "calm, default, unreadable expression",
        "sad": "downcast, melancholic, disappointed expression",
        "mad": "angry, frustrated, annoyed expression",
        "conf": "confident, assured, proud expression",
        "nerv": "nervous, anxious, worried expression",
        "zout": "zoned out, confused, spaced, dreamy, distracted expression",
    }

    # Visual descriptions for poses
    pose_descriptions = {
        "arms_down": "relaxed, natural stance with arms at sides",
        "arms_crossed": "defensive, stubborn, arms crossed over chest",
        "one_arm": "casual, one arm raised or gesturing",
    }

    # Build available moods list (union of all)
    all_moods = ["smile", "neutral", "sad", "mad", "conf", "nerv", "zout"]

    # Build pose-mood availability description
    pose_mood_info = []
    for pose, moods in pose_moods.items():
        mood_list = ", ".join(moods)
        pose_mood_info.append(f"{pose}: {mood_list}")

    _sprites_tool_cache = {
        "type": "function",
        "function": {
            "name": "update_sprite",
            "description": (
                "Set Milk Chan's sprite emotion to match your reply. "
                "IMPORTANT: You MUST provide a text response AND call this function together. "
                "Do not call this function alone - always include your reply in the message content.\n\n"
                "MOOD AVAILABILITY BY POSE:\n" + "\n".join(pose_mood_info) + "\n\n"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pose": {
                        "type": "string",
                        "enum": list(pose_moods.keys()),
                        "description": "Body pose. " + "; ".join([f"{p}: {pose_descriptions.get(p, '')}" for p in pose_moods.keys()])
                    },
                    "mood": {
                        "type": "string",
                        "enum": all_moods,
                        "description": "Facial expression. " + "; ".join([f"{m}: {mood_descriptions.get(m, '')}" for m in all_moods])
                    },
                    "variation": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 4,
                        "description": "Variation number (1-4), use 1 as default"
                    },
                    "expressions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional: eyes_closed, eyes_half, mouth_closed, mouth_half, mouth_full"
                    }
                },
                "required": ["pose", "mood", "variation"]
            }
        }
    }
    return _sprites_tool_cache


def _normalize_emotion(obj: Any) -> dict:
    """Normalize emotion payload to standard format"""
    try:
        if isinstance(obj, dict) and isinstance(obj.get("emotion"), list):
            emo = obj.get("emotion")
            if isinstance(emo, list) and len(emo) >= 3:
                return {"emotion": emo}
            return {"emotion": []}
        if isinstance(obj, list) and len(obj) >= 3:
            return {"emotion": obj}
        return {"emotion": []}
    except Exception:
        return {"emotion": []}


def _parse_tool_call_to_emotion(tool_call) -> dict:
    """Parse a update_sprite tool call into emotion dict format"""
    try:
        args = json.loads(tool_call.function.arguments)
        pose = args.get("pose", "arms_down")
        mood = args.get("mood", "neutral")
        variation = args.get("variation", 1)
        expressions = args.get("expressions", [])
        emotion_list = [pose, mood, variation] + expressions
        return {"emotion": emotion_list}
    except Exception as e:
        logger.warning(f"Failed to parse tool call: {e}")
        return {"emotion": []}


def chat_respond_with_tools(
    user_message: str,
    persona_description: Optional[str] = None,
    history: Optional[List[dict]] = None,
    username: Optional[str] = None,
    image_path: Optional[str] = None,
    timeout_sec: Optional[float] = None
) -> Tuple[str, Optional[dict]]:
    """
    Optimized: Uses function calling for sprite update.
    
    For APIs that return tool call without content, we make a second call
    to get the text response (standard OpenAI function calling flow).
    
    Args:
        user_message: User's message
        persona_description: Override persona (uses cached persona from memory if not provided)
        history: Conversation history
        username: User's name
        image_path: Optional image path
        timeout_sec: Optional timeout
    """
    t0 = time.perf_counter()
    config = _get_config()

    if history is None:
        history = []

    # Use cached persona if not provided
    if persona_description is None:
        persona_description = _get_persona()

    # Debug log persona length
    logger.info(f"[PERSONA] Using persona: {len(persona_description)} chars, preview: {persona_description[:100] if persona_description else '(empty)'}...")

    system_instruction = (
        f"""
## PRIMARY
You are Milk Chan. You must always respond in character.

## PERSONA DESCRIPTION
Name: Milk Chan ---\n
{persona_description}\n\n
## STRICT RESPONSE FORMAT
1. No Roleplaying actions: Do not simulate actions or emotions through asterisks. (e.g., *smiles*).
2. Avoid Generic AI Phrases: Do not say 'As an AI...'.
3. Do not use emojis or emoticons in your response.
4. Match your sprite emotion to your reply CONTENT:
- Happy/cheerful/pleased -> use 'smile'
- Apologizing/sympathetic/disappointed -> use 'sad'
- Confident/assured/proud -> use 'conf'
- Frustrated/annoyed/angry -> use 'mad'
- Nervous/anxious/worried -> use 'nerv'
- Zoned out/confused/dazed -> use 'zout' (only with 'arms_crossed' pose!)
5. Include your text response in the message content alongside the function call.
6. Don't write long messages, 2-3 sentences is maximum.
"""
    )

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    hidden_text = f"--Hidden context: Time: {timestamp} | PC Name: {username or 'User'}--\n{user_message}"

    messages: List[dict] = [{"role": "system", "content": system_instruction}]
    messages.extend(history)
    messages.append({"role": "user", "content": hidden_text})

    try:
        client = _get_client()
        sprite_tool = _build_sprite_tool()

        if image_path and os.path.exists(image_path):
            try:
                import base64
                with open(image_path, 'rb') as f:
                    image_data = base64.b64encode(f.read()).decode('utf-8')
                messages[-1] = {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": hidden_text},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_data}"}}
                    ]
                }
            except Exception as e:
                logger.warning(f"Failed to attach image: {e}")

        # First API call - request with tools, let model decide
        # Note: NVIDIA API may return tool call without content when tool_choice forces it
        # Using "auto" gives model flexibility to return both content + tool call
        logger.info(f"API REQUEST 1: chat/completions with tools (model={config.openai_chat_model})")
        resp = client.chat.completions.create(
            model=config.openai_chat_model,
            messages=messages,
            temperature=0.7,
            max_tokens=2048,
            tools=[sprite_tool],
            tool_choice="auto",
        )

        msg = resp.choices[0].message
        print(resp.choices)
        reply_text = (msg.content or "").strip()
        emotion_obj = None

        # Parse tool calls
        tool_calls_to_append = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                if tc.function.name == "update_sprite":
                    emotion_obj = _parse_tool_call_to_emotion(tc)
                    logger.info(f"Tool call received: update_sprite -> {emotion_obj}")
                    tool_calls_to_append.append({
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                    })

# If model returned only tool call without content, make second call
        if msg.tool_calls and not reply_text:
            logger.info("API REQUEST 2: chat/completions (follow-up after tool call with empty response)")

            # Build hidden context about selected emotion in natural language
            emotion_context = ""
            if emotion_obj and emotion_obj.get("emotion"):
                emo = emotion_obj["emotion"]
                pose = emo[0] if len(emo) > 0 else "arms_down"
                mood = emo[1] if len(emo) > 1 else "neutral"
                mood_descriptions = {
                    "smile": "happy and cheerful",
                    "neutral": "calm and neutral",
                    "sad": "sad or sympathetic",
                    "mad": "frustrated or annoyed",
                    "conf": "confident and assured",
                    "nerv": "nervous or anxious",
                    "zout": "zoned out or confused",
                }
                pose_descriptions = {
                    "arms_down": "relaxed stance",
                    "arms_crossed": "arms crossed defensively",
                    "one_arm": "casual gesture",
                }
                mood_desc = mood_descriptions.get(mood, mood)
                pose_desc = pose_descriptions.get(pose, pose)
                emotion_context = f"[You are currently displaying a {mood_desc} expression with {pose_desc}. Match your response tone to this emotion.]"

            # Append the assistant's tool call message
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": tool_calls_to_append
            })

            # Append tool response with hidden emotion context
            for tc in msg.tool_calls:
                if tc.function.name == "update_sprite":
                    tool_response = "ok"
                    if emotion_context:
                        tool_response = f"ok. {emotion_context}"
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_response
                    })

            # Second API call to get the text response
            resp2 = client.chat.completions.create(
                model=config.openai_chat_model,
                messages=messages,
                temperature=0.7,
                max_tokens=300,
            )
            reply_text = (resp2.choices[0].message.content or "").strip()

        total_time = time.perf_counter() - t0
        logger.info(f"✓ chat_respond_with_tools: TOTAL={total_time:.2f}s reply_len={len(reply_text)} has_tool_call={bool(msg.tool_calls)} has_content={bool(reply_text)}")

        return reply_text, emotion_obj

    except Exception as e:
        logger.exception("chat_respond_with_tools: error")
        return "", None


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
    Legacy wrapper - now uses tool-based single API call internally.
    """
    return chat_respond_with_tools(
        user_message=user_message,
        persona_description=persona_description,
        history=history,
        username=username,
        image_path=image_path,
        timeout_sec=timeout_sec
    )


def analyze_emotion(text: str, sprites_tree: str) -> dict:
    """Analyze emotion from text using direct OpenAI call (legacy - prefer chat_respond_with_tools)"""
    t0 = time.perf_counter()
    config = _get_config()

    system_prompt = (
        "You are an emotion analysis model. Analyze the assistant's message and determine its emotion. "
        "Your response MUST be a valid JSON object with a single key 'emotion', which is a list: "
        "[pose_string, mood_string, variation_integer, ...optional_expressions].\n\n"
        f"Choose from the sprites below.\n{sprites_tree}\n\n"
        "Example: {\"emotion\": [\"arms_down\", \"smile\", 1]}"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"ASSISTANT'S MESSAGE TO ANALYZE:\n'''{text}'''"},
    ]

    try:
        client = _get_client()
        resp = client.chat.completions.create(
            model=config.openai_chat_model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.5,
            max_tokens=100,
        )

        raw_content = (resp.choices[0].message.content or "").strip()
        try:
            parsed = json.loads(raw_content or "{}")
        except Exception:
            parsed = {}

        out = _normalize_emotion(parsed)
        total_time = time.perf_counter() - t0
        logger.info(f"✓ analyze_emotion: TOTAL={total_time:.2f}s")
        return out

    except Exception:
        logger.exception("analyze_emotion: error")
        return {"emotion": []}


# Legacy compatibility - stubs for functions we don't need
def grounding_bbox(text: str) -> dict:
    """Stub - grounding no longer needed"""
    return {}


def describe_video_tail(video_path: str, seconds: int = 4) -> str:
    """Describe video using OpenAI vision"""
    # TODO: Implement video frame extraction and description
    return "Video description not yet implemented"
