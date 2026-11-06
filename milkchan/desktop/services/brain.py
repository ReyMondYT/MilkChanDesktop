"""MilkChan's link to its brain, SentientMilk.

MilkChan is the body: it shows the character, looks at the screen and acts out the
expression the brain picks. Persona, provider, tools, memory and history live in the
brain, which runs as its own process; MilkChan starts it when it is not running.
Proactive messages and how reminders and finished tasks are shown are MilkChan's own
features: the brain only tells MilkChan that they happened. Only this module imports
the framework, so packaged builds use one copy of it: an update in user data, if installed.
"""

import base64
import importlib.util
import logging
import mimetypes
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypedDict

from milkchan.core.updater import REQUIRED_FILES
from milkchan.paths import get_assets_dir, get_user_data_dir

logger = logging.getLogger(__name__)

APP = 'milkchan'
SESSION = 'main'
ENVIRONMENT = """You live on the user's desktop as an animated character in a corner of the screen.
Messages may come with a screenshot of the user's screen: that is what you see.
Your replies appear in a small speech bubble, so:
1. Keep replies to 2-3 sentences.
2. No roleplay actions in asterisks (e.g. *smiles*), no emojis or emoticons.
3. Show how you feel through your expression."""
TOOLKITS = ['memory', 'web', 'todo', 'journal', 'schedule', 'tasks']
# MilkChan cannot show approval prompts; reminders are one of its features, so they need none.
RULES = {'allow': ['schedule_create']}
IDLE = {'type': 'event', 'name': 'idle',
        'text': "The user has not said anything for a while. Speak up if you have something to say about "
                "what you see or think; otherwise stay silent."}
SHOWN_NOTIFICATIONS = ('schedule.fired', 'task.completed', 'task.failed')


def _load_framework():
    """SentientMilk; packaged builds prefer an update installed in user data.

    An update installed before SentientMilk was a server lacks the brain and is ignored.
    """
    override = get_user_data_dir() / 'sentientmilk_framework'
    if not getattr(sys, 'frozen', False) or not all((override / name).exists() for name in REQUIRED_FILES):
        import sentientmilk_framework
        return sentientmilk_framework
    for name in [n for n in sys.modules if n.split('.')[0] == 'sentientmilk_framework']:
        del sys.modules[name]  # submodules must come from the update too
    spec = importlib.util.spec_from_file_location(
        'sentientmilk_framework', override / '__init__.py', submodule_search_locations=[str(override)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules['sentientmilk_framework'] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules['sentientmilk_framework']
        raise
    logger.info("Using updated framework from %s", override)
    return module


framework = _load_framework()
BrainError = framework.BrainError
THINKING_MODES = importlib.import_module('sentientmilk_framework.thinking').THINKING_MODES

_client = None
_tool_event_callback: Optional[Callable[[Dict[str, Any]], None]] = None
_notification_callback: Optional[Callable[[Dict[str, Any]], None]] = None
_listening = threading.Event()


class ChatError(TypedDict):
    type: str
    message: str
    details: Optional[str]
    http_status: Optional[int]


class ChatResult(TypedDict):
    response: str  # empty when the brain chose to stay silent
    sprite: Optional[Dict[str, str]]  # {'pose': ..., 'mood': ...} the brain chose
    error: Optional[ChatError]
    tools: List[Dict[str, Any]]


def create_error(error_type: str, message: str, details: Optional[str] = None) -> ChatError:
    return ChatError(type=error_type, message=message, details=details, http_status=None)


def brain_command() -> Optional[List[str]]:
    """How to start the brain: packaged MilkChan runs itself in brain mode; Python uses the default."""
    return [sys.executable, '--serve-brain'] if getattr(sys, 'frozen', False) else None


def serve_brain() -> None:
    """Run the brain in this process until it is idle (packaged builds: MilkChan.exe --serve-brain)."""
    importlib.import_module('sentientmilk_framework.server').serve(log_file=True)


def start() -> None:
    """Find the running brain, starting it when none runs, and listen for its notifications."""
    global _client
    if _client is None:
        _client = framework.connect(command=brain_command())
        logger.info("Brain at %s", _client.url)


def stop() -> None:
    """MilkChan leaves; the brain keeps running while it has work, then exits on its own."""
    _listening.clear()


def client():
    start()
    return _client


def default_persona() -> str:
    return (get_assets_dir() / 'MILKCHAN.md').read_text(encoding='utf-8')


def declare(character) -> None:
    """Tell the brain who it is in MilkChan and which expressions the character can show."""
    client().declare_app(APP, name=character.name, environment=ENVIRONMENT, persona=default_persona(),
                         signals={'expression': {'description': 'the pose and mood that match what you say',
                                                 'options': character.moods()}},
                         toolkits=TOOLKITS, rules=RULES)


def is_configured() -> bool:
    try:
        return client().config()['api_key_set']
    except BrainError as exc:
        logger.warning("Brain unavailable: %s", exc)
        return False


def set_tool_event_callback(callback: Optional[Callable[[Dict[str, Any]], None]]) -> None:
    """Receive tool events as they happen (the IPC server streams them to the terminal)."""
    global _tool_event_callback
    _tool_event_callback = callback


def _old_tool(tool: Dict[str, Any]) -> Dict[str, Any]:
    """Tool entries in the shape MilkChan's terminal protocol uses."""
    failed = tool['status'] == 'error'
    return {'tool_name': tool['name'], 'call_id': tool['call_id'], 'arguments': tool.get('arguments', {}),
            'status': tool['status'], 'result': None if failed else tool.get('result'),
            'error': tool.get('result') if failed else None}


def _emit(event: Dict[str, Any]) -> None:
    if not _tool_event_callback or event['type'] not in ('tool.start', 'tool.end'):
        return
    # The terminal pairs a tool's start and end by name and arguments.
    shown = {'tool_name': event['name'], 'call_id': event['call_id'], 'arguments': event.get('arguments', {})}
    if event['type'] == 'tool.start':
        shown['type'] = 'tool_start'
    elif event['status'] == 'ok':
        shown.update(type='tool_end', result=event['result'])
    else:
        shown.update(type='tool_error', error=event['result'])
    try:
        _tool_event_callback(shown)
    except Exception as exc:
        logger.warning("Failed to forward a tool event: %s", exc)


def _data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or 'image/jpeg'
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _deny(event: Dict[str, Any]):
    return 'deny', "MilkChan cannot ask the user for approval; do without this tool here."


def turn(text: Optional[str], screenshot: Optional[Path], username: str,
         event: Optional[Dict[str, Any]] = None) -> ChatResult:
    """One turn. ``text`` None with no ``event`` is an idle turn: the brain may stay silent."""
    items = [event or IDLE] if text is None else []
    try:
        result = client().turn(APP, SESSION, text, items=items, image=_data_url(screenshot) if screenshot else None,
                               context={'user': username}, reply='optional' if text is None and not event else 'required',
                               on_event=_emit, on_approval=_deny)
    except BrainError as exc:
        return ChatResult(response='', sprite=None, error=exc.as_dict(), tools=[])
    expression = result['signals'].get('expression')
    pose, _, mood = (expression or '').partition('/')
    return ChatResult(response=result['reply'], sprite={'pose': pose, 'mood': mood} if expression else None,
                      error=None, tools=[_old_tool(tool) for tool in result['tools']])


def history() -> List[Dict[str, str]]:
    """The conversation as shown to the user."""
    return [{'role': entry['role'], 'content': entry['text']} for entry in client().history(APP, SESSION)]


def clear_history() -> None:
    client().clear_history(APP, SESSION)


def persona() -> str:
    return client().app(APP)['persona'].strip()


def set_persona(text: str) -> None:
    client().update_app(APP, persona=text)


def event_for(notification: Dict[str, Any]) -> Dict[str, Any]:
    """The turn input that lets MilkChan tell the user about a reminder or a finished task."""
    data = notification['data']
    if notification['type'] == 'schedule.fired':
        late = ' (it came due while MilkChan was closed)' if data.get('late') else ''
        return {'type': 'event', 'name': 'reminder',
                'text': f"A reminder you scheduled is due now{late}: {data['text']}. Remind the user."}
    status = 'finished' if notification['type'] == 'task.completed' else 'failed'
    return {'type': 'event', 'name': notification['type'],
            'text': f"Your background task {status}: {data.get('goal', '')}. Tell the user how it went."}


def listen(callback: Callable[[Dict[str, Any]], None], cursor: int, save_cursor: Callable[[int], None]) -> None:
    """Pass reminders and finished tasks to ``callback`` (from a background thread), from ``cursor`` on;
    -1 starts from now. Notifications that came while MilkChan was closed arrive first."""
    def run():
        after = cursor
        while _listening.is_set():
            try:
                for notification in client().events(APP, after):
                    after = notification['id']
                    save_cursor(after)
                    if notification['type'] in SHOWN_NOTIFICATIONS:
                        callback(notification)
                    if not _listening.is_set():
                        return
            except BrainError as exc:
                logger.info("Brain notifications paused: %s", exc.message)
                time.sleep(5)  # the client starts the brain again on the next try

    _listening.set()
    threading.Thread(target=run, name='brain-notifications', daemon=True).start()
