import json
import sqlite3

import pytest

from milkchan.desktop.services import brain as link
from milkchan.desktop.services import legacy


@pytest.fixture
def old_database(tmp_path, monkeypatch):
    path = tmp_path / 'milkchan.db'
    old_reply = {'role': 'assistant', 'content': json.dumps({'reply': 'Hello', 'sprite': {'pose': 'a', 'mood': 'b'}})}
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE history (id INTEGER PRIMARY KEY, role TEXT, content TEXT);
            CREATE TABLE conversation_messages (id INTEGER PRIMARY KEY, payload TEXT);
            CREATE TABLE memory (doc TEXT, item TEXT, value TEXT);
        """)
        db.executemany("INSERT INTO history(role, content) VALUES (?, ?)",
                       [('user', 'hi'), ('assistant', 'Hello'), ('user', '[no input...]'), ('assistant', 'Bored')])
        db.executemany("INSERT INTO conversation_messages(payload) VALUES (?)",
                       [(json.dumps({'role': 'user', 'content': 'hi'}),), (json.dumps(old_reply),)])
        db.executemany("INSERT INTO memory(doc, item, value) VALUES (?, ?, ?)",
                       [('persona', 'personality', 'An old persona.'), ('user', 'colour', 'green'),
                        ('user', 'age', '23')])
    db.close()
    monkeypatch.setattr(legacy, 'get_db_path', lambda: path)
    return path


def test_old_settings_and_history_move_into_the_brain_once(brain, config, old_database):
    config.update({'openai_api_key': 'sk-old', 'openai_base_url': 'https://old.invalid/v1/',
                   'openai_chat_model': 'old-model', 'openai_thinking_mode': 'high',
                   'tools': {'web_search_token': 'brave'}, 'ai': {'combined_reply_sprite': True},
                   'processing': {'support_images': False, 'max_request_bytes': 512 * 1024}})
    brain.client.update_config(api_key='')

    legacy.hand_over(brain.client, link.APP, link.SESSION, config)

    settings = brain.client.config()
    assert settings['api_key_set'] and settings['web_search_key_set']
    assert (settings['base_url'], settings['model'], settings['thinking_mode']) == (
        'https://old.invalid/v1', 'old-model', 'high')
    assert settings['vision'] is False and settings['request_budget'] == 512 * 1024
    assert not any(key in config.as_dict() for key in ('openai_api_key', 'tools', 'ai'))
    assert 'max_request_bytes' not in config.get('processing')
    assert [(e['role'], e['text']) for e in brain.client.history(link.APP, link.SESSION)] == [
        ('user', 'hi'), ('assistant', 'Hello'), ('assistant', 'Bored')]
    stored = brain.server.brain.store
    model_reply = stored.events(link.APP, link.SESSION, types=('assistant',))[0]['message']['content']
    assert model_reply == '{"expression": "a/b"}\nHello'  # the signals header the brain now uses
    assert stored.memories(link.APP) == {'user': {'age': 23, 'colour': 'green'}}
    assert brain.client.app(link.APP)['persona'] == 'An old persona.'
    assert not old_database.exists() and old_database.with_name('milkchan.db.imported').exists()

    legacy.hand_over(brain.client, link.APP, link.SESSION, config)  # nothing left to move
    assert len(brain.client.history(link.APP, link.SESSION)) == 3


def test_a_brain_with_its_own_setup_keeps_it(brain, config, old_database):
    brain.client.update_app(link.APP, persona='Chosen in the brain.')
    brain.server.brain.store.add_event(link.APP, link.SESSION, None, 'input', {'content': 'newer', 'display': 'newer'})
    config.update({'openai_api_key': 'sk-old', 'openai_chat_model': 'old-model'})

    legacy.hand_over(brain.client, link.APP, link.SESSION, config)

    assert brain.client.config()['model'] == ''
    assert config.get('openai_api_key') is None
    assert [e['text'] for e in brain.client.history(link.APP, link.SESSION)] == ['newer']
    assert brain.client.app(link.APP)['persona'] == 'Chosen in the brain.'
    assert brain.server.brain.store.recall(link.APP, 'user', 'colour') == 'green'
    assert not old_database.exists()


def test_an_unreachable_brain_leaves_the_old_database_for_next_time(brain, config, old_database):
    brain.server.close()
    with pytest.raises(link.BrainError):
        legacy.hand_over(brain.client, link.APP, link.SESSION, config)
    assert old_database.exists()
