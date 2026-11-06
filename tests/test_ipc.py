import json
import socket
import time

from milkchan.desktop.services.ipc_server import IPCServer
from milkchan.desktop.services.stream_broker import EventType, StreamEventBroker
from milkchan.desktop.services.stream_client import StreamClient, StreamConfig


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def request(port, message):
    with socket.create_connection(('127.0.0.1', port), timeout=5) as sock:
        sock.sendall((json.dumps(message) + '\n').encode())
        return json.loads(sock.makefile().readline())


def wait_until(condition, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


def test_commands_need_the_launch_token(brain):
    server = IPCServer()
    assert server.process_message({'command': 'get_history'}) == {'error': 'unauthorized'}
    assert server.process_message({'command': 'ping', 'token': 'guess'}) == {'error': 'unauthorized'}
    assert server.process_message({'command': 'get_history', 'token': server.token}) == {
        'status': 'ok', 'history': []}
    brain.server.close()
    answer = server.process_message({'command': 'get_history', 'token': server.token})
    assert answer['error']['type'] == 'brain_unreachable'
    assert IPCServer().token != server.token


def test_server_answers_over_the_socket():
    server = IPCServer(port=free_port(), stream_port=free_port())
    server.start()
    try:
        assert wait_until(lambda: server.server_socket is not None)
        assert request(server.port, {'command': 'ping', 'token': server.token})['message'] == 'pong'
        assert request(server.port, {'command': 'ping'}) == {'error': 'unauthorized'}
        started = request(server.port, {'command': 'tui_start', 'token': server.token})
        assert started['stream_port'] == server.stream_port and server.is_tui_active()
    finally:
        server.stop()


def test_chat_goes_through_the_desktop_pipeline(monkeypatch):
    import milkchan.desktop.agents.agent_workers as agent_workers

    calls = []

    def fake_send_message(message):
        calls.append(message)
        return {'response': 'hi', 'sprite': {'pose': 'arms_down', 'mood': 'smile'}, 'error': None, 'tools': []}

    monkeypatch.setattr(agent_workers, 'send_message', fake_send_message)
    server = IPCServer()
    result = server.process_message({'command': 'chat', 'token': server.token, 'params': {'message': 'hello'}})
    assert calls == ['hello']
    assert result == {'status': 'ok', 'response': 'hi', 'sprite': {'pose': 'arms_down', 'mood': 'smile'},
                      'tools': []}


def test_set_sprite_is_queued_to_the_window(monkeypatch):
    server = IPCServer()
    invoked = []
    monkeypatch.setattr(server, '_invoke', lambda slot, *args: invoked.append((slot, args)))
    params = {'sprite': {'pose': 'arms_down', 'mood': 'sad'}}
    assert server.process_message({'command': 'set_sprite', 'token': server.token, 'params': params})['status'] == 'ok'
    assert server.process_message({'command': 'stop_speech', 'token': server.token})['status'] == 'ok'
    assert invoked == [('set_expression', ('arms_down', 'sad')), ('stop_speech_animation', ())]


def test_event_stream_needs_the_token_and_starts_at_now():
    broker = StreamEventBroker('secret', port=free_port(), heartbeat_interval=0.2)
    broker.start()
    try:
        broker.publish(EventType.TOOL_END, {'tool_name': 'old'})
        received = []
        client = StreamClient(StreamConfig(port=broker.port, heartbeat_interval=0.1), token='secret',
                              on_event=received.append)
        assert client.connect()
        broker.publish(EventType.TOOL_END, {'tool_name': 'new'})
        assert wait_until(lambda: any(e['data'].get('tool_name') == 'new' for e in received))
        assert not any(e['data'].get('tool_name') == 'old' for e in received)
        client.disconnect()

        rejected = []
        intruder = StreamClient(StreamConfig(port=broker.port, max_reconnect_attempts=0), token='wrong',
                                on_event=rejected.append)
        intruder.connect()
        broker.publish(EventType.TOOL_END, {'tool_name': 'private'})
        time.sleep(0.3)
        intruder.disconnect()
        assert rejected == []
    finally:
        broker.stop()


def test_resume_sequence_never_goes_backwards():
    client = StreamClient()
    client._last_sequence = 42
    for sequence in (0, 45, 0):
        client._handle_event({'type': 'heartbeat', 'sequence': sequence})
    assert client._last_sequence == 45


def test_terminal_client_sends_the_token(monkeypatch):
    from milkchan import terminal_chat

    server = IPCServer(port=free_port(), stream_port=free_port())
    server.start()
    try:
        assert wait_until(lambda: server.server_socket is not None)
        monkeypatch.setattr(terminal_chat, 'IPC_PORT', server.port)
        monkeypatch.setattr(terminal_chat, 'TOKEN', server.token)
        assert terminal_chat.send_to_milkchan('ping')['message'] == 'pong'
        monkeypatch.setattr(terminal_chat, 'TOKEN', 'wrong')
        assert terminal_chat.send_to_milkchan('ping') == {'error': 'unauthorized'}
    finally:
        server.stop()


def test_synced_chat_box_replies_do_not_animate_the_sprite_again(monkeypatch):
    from milkchan import terminal_chat

    commands = []
    monkeypatch.setattr(terminal_chat, 'send_to_milkchan', lambda command, *a, **kw: commands.append(command) or {})
    monkeypatch.setattr(terminal_chat.time, 'sleep', lambda _: None)
    event = {'type': 'chat_response', 'data': {'type': 'sync_message', 'role': 'assistant', 'content': 'hi there'}}
    terminal_chat.handle_stream_event(event, set())
    assert commands == []
    terminal_chat.display_assistant_response('hi there', animate_sprite=True)
    assert commands == ['start_speech', 'stop_speech']
