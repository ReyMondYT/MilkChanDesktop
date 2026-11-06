"""MilkChan terminal chat: a Rich console client for the running app.

Opened from the chat box's expand button, which passes the IPC token in
``MILKCHAN_IPC_TOKEN``. The brain keeps the history: this client reads it
through the app at start and shows new messages as they arrive.
"""

import json
import os
import signal
import socket
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Optional

# Run as a script from a source checkout: make the package importable.
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from rich.box import ROUNDED  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.live import Live  # noqa: E402
from rich.markdown import Markdown  # noqa: E402
from rich.panel import Panel  # noqa: E402
from rich.prompt import Prompt  # noqa: E402
from rich.style import Style  # noqa: E402

IPC_PORT = 19527
TOKEN = os.environ.get('MILKCHAN_IPC_TOKEN', '')

console = Console(force_terminal=True, soft_wrap=True)
ACCENT = "#ac3232"
assistant_name = "Milk Chan"

_prompt_label_active = False
_prompt_waiting_for_input = False


def _render_inline_prompt_label():
    """Render the "You:" prompt label manually when Prompt.ask can't redraw."""
    global _prompt_label_active
    if not _prompt_waiting_for_input or _prompt_label_active:
        return
    console.print("[bold cyan]You:[/bold cyan] ", end="")
    console.file.flush()
    _prompt_label_active = True


def _suspend_inline_prompt_label() -> bool:
    """Ensure subsequent console output starts on a new line."""
    global _prompt_label_active
    if _prompt_label_active:
        console.file.write('\r\x1b[2K')
        console.file.flush()
        _prompt_label_active = False
        return True
    return False


def _restore_inline_prompt_label(previously_active: bool):
    if previously_active:
        _render_inline_prompt_label()
        console.file.flush()


def _ask(label: str) -> str:
    """Prompt.ask that lets background output keep the label visible."""
    global _prompt_label_active, _prompt_waiting_for_input
    _prompt_waiting_for_input = _prompt_label_active = True
    try:
        return Prompt.ask(label)
    finally:
        _prompt_waiting_for_input = _prompt_label_active = False


@contextmanager
def _prompt_guard():
    """Suspend the inline prompt label while emitting console output."""
    was_active = _suspend_inline_prompt_label()
    try:
        yield
    finally:
        _restore_inline_prompt_label(was_active)


def _style(title: str, icon: str, color: str) -> Dict[str, Any]:
    return {'title': title, 'icon': icon, 'border_style': Style(color=color)}


class InfoBlock:
    """Panels for errors, tool calls and system messages."""

    STYLES = {
        'error': _style('Error', '✕', '#ff6b6b'),
        'warning': _style('Warning', '⚠', '#ffb86c'),
        'tool': _style('Tool', '⚙', '#8be9fd'),
        'info': _style('Info', 'ℹ', '#50fa7b'),
        'rate_limit': _style('Rate Limited', '⏳', '#ffb86c'),
        'completed': _style('Tool', '✓', '#50fa7b'),
        'network': _style('Connection Error', '📡', '#ff79c6'),
        'timeout': _style('Timeout', '⏱', '#f1fa8c'),
    }

    @classmethod
    def render(cls, block_type: str, message: str, details: Optional[str] = None) -> Panel:
        style = cls.STYLES.get(block_type, cls.STYLES['info'])
        content = message + (f"\n[dim]{details}[/dim]" if details else '')
        return Panel(content, title=f"{style['icon']} {style['title']}", border_style=style['border_style'],
                     box=ROUNDED, padding=(0, 1), expand=False)

    @classmethod
    def render_error(cls, error: Dict[str, Any]) -> Panel:
        error_type = error.get('type', 'error')
        return cls.render(error_type if error_type in cls.STYLES else 'error',
                          error.get('message', 'An error occurred'), error.get('details'))


def send_to_milkchan(command: str, params: Optional[dict] = None, timeout: Optional[float] = 30.0) -> dict:
    """Send one command to the app; failures come back as {'error': ...}."""
    try:
        with socket.create_connection(('127.0.0.1', IPC_PORT), timeout=timeout) as sock:
            sock.settimeout(timeout)
            message = {'command': command, 'params': params or {}, 'token': TOKEN}
            sock.sendall((json.dumps(message) + '\n').encode('utf-8'))
            response = b''
            while b'\n' not in response:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                response += chunk
        return json.loads(response.decode('utf-8').strip())
    except (OSError, ValueError) as exc:
        return {'error': str(exc)}


def display_history(history: list):
    console.clear()
    console.print(Panel(f"[bold red]{assistant_name} Terminal Chat[/bold red]", style=ACCENT, box=ROUNDED))
    console.print("[dim](Connected to MilkChan - sprites and audio will respond)[/dim]")
    console.print()
    for msg in history:
        if msg.get('role') == 'user':
            console.print(f"[bold cyan]You:[/bold cyan] {msg.get('content', '')}")
        elif msg.get('role') == 'assistant':
            console.print()
            console.print(f"[bold magenta]{assistant_name}:[/bold magenta]")
            console.print(Markdown(msg.get('content', '')))
            console.print()
    console.print("[dim]Type your message and press Enter. Type 'exit' or 'quit' to close.[/dim]")
    console.print()


def display_error_block(error: dict):
    with _prompt_guard():
        console.print()
        console.print(InfoBlock.render_error(error))
        console.print()


def _truncate_tool_text(text: str, limit: int = 2000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated {len(text) - limit} chars]"


def format_tool_result(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, dict):
        if {"returncode", "stdout", "stderr"}.issubset(result):
            parts = [f"returncode: {result.get('returncode')}"]
            stdout = (result.get('stdout') or '').strip()
            stderr = (result.get('stderr') or '').strip()
            if stdout:
                parts.append(f"stdout:\n{_truncate_tool_text(stdout)}")
            if stderr:
                parts.append(f"stderr:\n{_truncate_tool_text(stderr)}")
            return "\n".join(parts)
        if 'results' in result:
            return f"Found {len(result['results'])} results"
        if 'web' in result:
            return f"Found {len(result.get('web', {}).get('results', []))} web results"
        keys = list(result.keys())[:3]
        return f"Data: {', '.join(keys)}..." if len(result) > 3 else f"Data: {', '.join(keys)}"
    if isinstance(result, list):
        return f"[{len(result)} items]"
    return _truncate_tool_text(str(result))


def _arguments(data: Dict[str, Any]) -> dict:
    arguments = data.get('arguments')
    return arguments if isinstance(arguments, dict) else {}  # unparsable arguments arrive as text


def _tool_key(data: Dict[str, Any]) -> str:
    return f"{data.get('tool_name', 'unknown')}:{sorted(_arguments(data).items())}"


_active_tool_blocks: Dict[str, int] = {}


def display_tool_event(event: Dict[str, Any]):
    """Show a tool call; its completion replaces the "running" block."""
    event_type = event.get('type', 'tool_end')
    data = event.get('data', {})
    tool_name = data.get('tool_name', 'unknown')
    key = _tool_key(data)
    if event_type == 'tool_start':
        status, block_type = '⏳ running', 'tool'
    elif event_type == 'tool_error':
        status, block_type = '✗ error', 'error'
    else:
        status, block_type = '✓ completed', 'completed'
    details_parts = [f"Status: {status}"]
    query = _arguments(data).get('query') if tool_name == 'web_search' else None
    if query:
        details_parts.append(f"Query: [cyan]{query}[/cyan]")
    formatted = format_tool_result(data.get('result'))
    if formatted:
        details_parts.append(formatted)
    if data.get('error'):
        details_parts.append(f"[red]Error: {data['error']}[/red]")
    details = "\n".join(details_parts)

    with _prompt_guard():
        if event_type != 'tool_start' and key in _active_tool_blocks:
            for _ in range(_active_tool_blocks.pop(key)):
                sys.stdout.write('\x1b[1A\x1b[2K')
            sys.stdout.write('\x1b[0J')
            sys.stdout.flush()
        console.print(InfoBlock.render(block_type, f"[bold]{tool_name}[/bold]", details))
        console.print()
        if event_type == 'tool_start':
            _active_tool_blocks[key] = 6 + details.count('\n')  # panel height plus the blank line


def display_assistant_response(response: str, animate_sprite: bool):
    """Type out a reply; ``animate_sprite`` also moves the character's mouth."""
    with _prompt_guard():
        console.print(f"[bold magenta]{assistant_name}:[/bold magenta]")
        if response.strip():
            if animate_sprite:
                send_to_milkchan('start_speech')
            displayed = ""
            with Live(console=console, refresh_per_second=30, transient=True) as live:
                for word in response.split(' '):
                    displayed = f"{displayed} {word}" if displayed else word
                    live.update(Markdown(displayed))
                    time.sleep(0.02)
            console.print(Markdown(response))
            if animate_sprite:
                send_to_milkchan('stop_speech')
        else:
            console.print("[dim italic](No response)[/dim italic]")
        console.print()


def handle_stream_event(event: Dict[str, Any], shown_tools: set):
    """Messages typed in the chat box, history clears and live tool calls."""
    data = event.get('data', {})
    if event.get('type') == 'chat_response':
        if data.get('type') == 'sync_message':
            if data.get('role') == 'user':
                with _prompt_guard():
                    console.print(f"[bold cyan]You:[/bold cyan] {data.get('content', '')}")
                    console.print()
            elif data.get('role') == 'assistant':
                # The chat box already animates the character for its own replies.
                display_assistant_response(data.get('content', ''), animate_sprite=False)
        elif data.get('action') == 'clear_history':
            was_active = _suspend_inline_prompt_label()
            try:
                display_history([])
                console.print("[yellow]History cleared from main app[/yellow]")
                console.print()
            finally:
                _restore_inline_prompt_label(was_active)
        return
    if event.get('type') not in ('tool_start', 'tool_end', 'tool_error'):
        return
    marker = f"{_tool_key(data)}:{event['type']}"
    if marker not in shown_tools:
        shown_tools.add(marker)
        display_tool_event(event)


def _watch_for_shutdown(stop: threading.Event):
    """Close this terminal when MilkChan exits."""
    terminal_pid = os.getppid()
    while not stop.is_set():
        if 'error' in send_to_milkchan('ping', timeout=5.0):
            console.print("\n[red]MilkChan closed. Closing terminal...[/red]")
            try:
                if os.name == 'nt':
                    os.system(f'taskkill /f /pid {terminal_pid}')
                else:
                    os.kill(terminal_pid, signal.SIGTERM)
            except OSError:
                pass
            os._exit(0)
        time.sleep(0.5)


def chat_turn(user_input: str, shown_tools: set):
    console.print("[dim]Thinking...[/dim]")
    result = send_to_milkchan('chat', {'message': user_input}, timeout=None)
    console.file.write('\x1b[1A\x1b[2K')  # remove "Thinking..."
    console.file.flush()
    if result.get('status') != 'ok':
        error = result.get('error')
        display_error_block(error if isinstance(error, dict) else {'type': 'error', 'message': str(error)})
        return
    for tool in result.get('tools', []):
        # Tool events normally arrive live; show any the stream missed.
        if f"{_tool_key(tool)}:tool_end" not in shown_tools:
            display_tool_event({'type': 'tool_end', 'data': tool})
    sprite = result.get('sprite')
    if sprite:
        send_to_milkchan('set_sprite', {'sprite': sprite})
    display_assistant_response(result.get('response', ''), animate_sprite=True)
    if sprite:
        console.print(f"[dim]{sprite['pose']} / {sprite['mood']}[/dim]")
        console.print()


def main():
    global assistant_name
    from milkchan.desktop.services.stream_client import StreamClient, StreamConfig

    if not TOKEN:
        console.print("[red]Open the terminal chat from MilkChan's chat box.[/red]")
        sys.exit(1)
    started = send_to_milkchan('tui_start')
    if started.get('status') != 'ok':
        console.print(f"[red]Cannot connect to MilkChan: {started.get('error')}[/red]")
        console.print("[yellow]Make sure MilkChan is running.[/yellow]")
        sys.exit(1)
    assistant_name = started.get('name') or assistant_name
    history = send_to_milkchan('get_history').get('history', [])

    shown_tools: set = set()
    stream_client = StreamClient(StreamConfig(port=started['stream_port']), token=TOKEN,
                                 on_event=lambda event: handle_stream_event(event, shown_tools))
    stream_client.connect(filters=['tool_start', 'tool_end', 'tool_error', 'chat_response'])
    display_history(history)

    stop = threading.Event()
    threading.Thread(target=_watch_for_shutdown, args=(stop,), daemon=True).start()
    try:
        while True:
            user_input = _ask("[bold cyan]You[/bold cyan]")
            if user_input.lower() in ('exit', 'quit', 'q'):
                console.print("\n[bold red]Closing terminal chat...[/bold red]")
                break
            if user_input.strip():
                shown_tools.clear()
                chat_turn(user_input, shown_tools)
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        stop.set()
        stream_client.disconnect()
        send_to_milkchan('tui_end')
        send_to_milkchan('stop_speech')
    console.print("[green]Your conversation is saved. You can close this terminal.[/green]")
    try:
        _ask("[dim]Press Enter to exit[/dim]")
    except (KeyboardInterrupt, EOFError):
        pass


if __name__ == '__main__':
    main()
