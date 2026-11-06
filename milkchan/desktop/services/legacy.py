"""Hand what MilkChan kept itself, before SentientMilk was its brain, over to the brain once.

Older versions kept the provider settings in MilkChan's config, and the
conversation, transcript, persona and memories in milkchan.db. After the hand-over
the settings leave the config and the database is renamed milkchan.db.imported:
kept on disk, never read again.
"""

import json
import logging
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from milkchan.desktop.services.brain import BrainError
from milkchan.paths import get_db_path

logger = logging.getLogger(__name__)

# MilkChan setting -> brain setting
SETTINGS = {
    'openai_api_key': 'api_key',
    'openai_base_url': 'base_url',
    'openai_chat_model': 'model',
    'openai_thinking_mode': 'thinking_mode',
    'openai_thinking_tokens': 'thinking_tokens',
    'tools.web_search_token': 'web_search_key',
    'processing.max_request_bytes': 'request_budget',
}
RETIRED = ('ai', 'tools', 'openai_vision_model')
IDLE_PROMPT = '[no input...]'  # what idle turns used to send as the user's message
_CONTEXT_LINE = re.compile(r'^\[Context:[^\n]*\]\n?')


def _decode(value):
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _signals_header(message: dict) -> dict:
    """Replies used to be {"reply", "sprite"} JSON; the brain now starts replies with a signals line."""
    if message.get('role') != 'assistant' or not isinstance(message.get('content'), str):
        return message
    try:
        envelope = json.loads(message['content'])
    except ValueError:
        return message
    if not isinstance(envelope, dict) or not isinstance(envelope.get('reply'), str):
        return message
    sprite = envelope.get('sprite') or envelope.get('expression')
    header = json.dumps({'expression': f"{sprite['pose']}/{sprite['mood']}"}) + '\n' \
        if isinstance(sprite, dict) and sprite.get('pose') and sprite.get('mood') else ''
    return {**message, 'content': header + envelope['reply']}


def read_database(path: Path) -> dict:
    with closing(sqlite3.connect(path)) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

        def rows(table, query):
            return db.execute(query).fetchall() if table in tables else []

        shown = rows('history', "SELECT role, content FROM history ORDER BY id")
        messages = [json.loads(payload) for payload, in rows(
            'conversation_messages', "SELECT payload FROM conversation_messages ORDER BY id")]
        stored = rows('memory', "SELECT doc, item, value FROM memory")
    memory = {}
    for doc, item, value in stored:
        memory.setdefault(doc, {})[item] = _decode(value)
    persona = memory.pop('persona', {}).get('personality')
    return {
        # An empty model history used to be seeded from the shown one.
        'messages': [_signals_header(m) for m in messages] or [{'role': r, 'content': c} for r, c in shown],
        'transcript': [{'role': r, 'text': _CONTEXT_LINE.sub('', c)} for r, c in shown
                       if r in ('user', 'assistant') and c != IDLE_PROMPT],
        'memory': memory,
        'persona': persona if isinstance(persona, str) and persona.strip() else None,
    }


def hand_over(client, app: str, session: str, config) -> None:
    """Safe on every start: does nothing once everything has moved."""
    changes = {new: config.get(old) for old, new in SETTINGS.items() if config.get(old) not in (None, '')}
    if changes and config.get('processing.support_images') is False:
        changes['vision'] = False  # images used to be off for text-only models
    if changes and not client.config()['api_key_set']:  # a configured brain keeps its own settings
        for key, value in changes.items():
            try:
                client.update_config(**{key: value})
            except BrainError as exc:
                logger.warning("The brain refused the old %s setting: %s", key, exc.message)
    config.remove(*SETTINGS, *RETIRED)

    path = get_db_path()
    if not path.exists():
        return
    legacy = read_database(path)
    try:
        client.import_history(app, session, legacy['messages'], legacy['memory'], legacy['transcript'])
    except BrainError as exc:
        if exc.type != 'bad_request':
            raise  # the brain is unreachable: try again next start
        logger.warning("The brain kept its own history (%s); the old one stays in %s.imported",
                       exc.message, path.name)
    if legacy['persona'] and not client.app(app)['persona_custom']:
        client.update_app(app, persona=legacy['persona'])
    path.rename(path.with_name(path.name + '.imported'))
    logger.info("Handed %d messages and %d memory categories over to the brain",
                len(legacy['messages']), len(legacy['memory']))
