import time

from PIL import Image
from sentientmilk_framework.testing import tool_call

from milkchan.desktop.agents import agent_workers
from milkchan.desktop.services import brain as link
from milkchan.desktop.sprites.library import active_character


def reply(text, expression='arms_down/smile'):
    return f'{{"expression": "{expression}"}}\n{text}'


def user_text(payload):
    content = payload['messages'][-1]['content']
    return content if isinstance(content, str) else '\n'.join(b.get('text', '') for b in content)


def test_a_turn_shows_the_brain_what_milkchan_sees_and_is(brain, config, tmp_path, monkeypatch):
    screenshot = tmp_path / 'screen.jpg'
    Image.new('RGB', (64, 36), 'red').save(screenshot)
    monkeypatch.setattr(agent_workers, 'take_screenshot', lambda scale: screenshot)
    config.set('username', 'Tester')
    link.declare(active_character())
    brain.replies.append(reply('Hello'))

    result = agent_workers.send_message('hi')

    assert result == {'response': 'Hello', 'sprite': {'pose': 'arms_down', 'mood': 'smile'},
                      'error': None, 'tools': []}
    request = brain.sent[0]
    system = request['messages'][0]['content']
    assert 'arms_down: neutral, confused' in system and link.ENVIRONMENT in system
    user = request['messages'][-1]['content']
    assert 'user: Tester' in user[0]['text'] and user[1]['type'] == 'image_url'
    assert not screenshot.exists()
    assert link.history() == [{'role': 'user', 'content': 'hi'}, {'role': 'assistant', 'content': 'Hello'}]


def test_idle_turns_let_the_brain_speak_or_stay_silent(brain, config):
    config.set('processing.support_images', False)
    link.declare(active_character())
    brain.replies += [reply('So quiet...'), reply('[silent]', 'arms_down/neutral')]
    assert agent_workers.send_message(None)['response'] == 'So quiet...'
    assert '[Event: idle]' in user_text(brain.sent[0])
    quiet = agent_workers.send_message(None)
    assert quiet['response'] == '' and quiet['sprite'] == {'pose': 'arms_down', 'mood': 'neutral'}
    assert [entry['role'] for entry in link.history()] == ['assistant']


def test_reminders_and_finished_tasks_become_turns_milkchan_speaks(brain, config):
    config.set('processing.support_images', False)
    link.declare(active_character())
    seen, cursors = [], []
    link.listen(seen.append, 0, cursors.append)
    try:
        brain.client.create_schedule(link.APP, 'every 1m', 'stretch your legs')
        schedule = brain.server.brain.store.schedules(link.APP)[0]
        brain.server.brain.scheduler._fire(schedule)
        deadline = time.time() + 10
        while not seen and time.time() < deadline:
            time.sleep(0.05)
    finally:
        link.stop()
    assert seen[0]['type'] == 'schedule.fired' and cursors[-1] == seen[0]['id']
    brain.replies.append(reply('Time to stretch your legs!'))
    result = agent_workers.send_message(None, link.event_for(seen[0]))
    assert result['response'] == 'Time to stretch your legs!'
    assert '[Event: reminder]' in user_text(brain.sent[0]) and 'stretch your legs' in user_text(brain.sent[0])


def test_tool_events_reach_the_terminal_live(brain, config):
    config.set('processing.support_images', False)
    link.declare(active_character())
    events = []
    link.set_tool_event_callback(events.append)
    try:
        brain.replies += [tool_call('memory_list', {}, 'c1'), reply('I remember nothing yet.')]
        result = agent_workers.send_message('what do you remember?')
    finally:
        link.set_tool_event_callback(None)
    assert [event['type'] for event in events] == ['tool_start', 'tool_end']
    assert events[0]['tool_name'] == 'memory_list' and events[0]['arguments'] == events[1]['arguments'] == {}
    assert result['tools'][0]['status'] == 'completed' and result['response'] == 'I remember nothing yet.'


def test_tools_milkchan_cannot_approve_are_declined(brain, config):
    config.set('processing.support_images', False)
    link.declare(active_character())
    brain.client.update_app(link.APP, rules={'ask': ['memory_save']})
    brain.replies += [tool_call('memory_save', {'category': 'a', 'key': 'b', 'value': 'c'}, 'm1'),
                      reply('Fine, I will not.')]
    assert agent_workers.send_message('remember this')['response'] == 'Fine, I will not.'
    tool = next(m for m in brain.sent[1]['messages'] if m['role'] == 'tool')
    assert 'cannot ask the user for approval' in tool['content']


def test_brain_problems_arrive_as_chat_errors(brain, config):
    config.set('processing.support_images', False)
    brain.client.update_config(api_key='')
    assert agent_workers.send_message('hi')['error']['type'] == 'config_missing'
    assert not link.is_configured()
    brain.server.close()
    assert agent_workers.send_message('hi')['error']['type'] == 'brain_unreachable'
    assert not link.is_configured()


def test_packaged_builds_skip_an_update_from_before_the_brain_server(tmp_path, monkeypatch):
    import sys

    old = tmp_path / 'sentientmilk_framework'
    old.mkdir()
    (old / '__init__.py').write_text("raise RuntimeError('the old framework must not load')")
    monkeypatch.setattr(link, 'get_user_data_dir', lambda: tmp_path)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    assert link._load_framework() is link.framework
    assert link.brain_command() == [sys.executable, '--serve-brain']
