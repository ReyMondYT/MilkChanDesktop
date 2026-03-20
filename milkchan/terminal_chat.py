"""
MilkChan Terminal Chat - Rich Console Interface

A standalone terminal chat interface using Rich for formatting.
Launched from the overlay chatbox expand button.
Communicates with main MilkChan app via IPC socket.
"""

import sys
import json
import os
import socket
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

IPC_PORT = 19527

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.prompt import Prompt
    from rich.text import Text
    from rich.live import Live
    from rich.layout import Layout
    from rich.box import ROUNDED, MINIMAL
    from rich.style import Style
    from rich import print as rprint
except ImportError:
    print("Installing rich...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "rich", "-q"])
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.prompt import Prompt
    from rich.text import Text
    from rich.live import Live
    from rich.layout import Layout
    from rich.box import ROUNDED, MINIMAL
    from rich.style import Style
    from rich import print as rprint

console = Console(force_terminal=True, soft_wrap=True)

ACCENT = "#ac3232"
ACCENT_DIM = "#8a2828"


class InfoBlock:
    """Beautiful info block for displaying errors, tool calls, and system messages."""
    
    STYLES = {
        'error': {
            'title': 'Error',
            'icon': '✕',
            'border_style': Style(color='#ff6b6b'),
            'title_style': Style(color='#ff6b6b', bold=True),
            'bg_color': '#3a1515',
        },
        'warning': {
            'title': 'Warning',
            'icon': '⚠',
            'border_style': Style(color='#ffb86c'),
            'title_style': Style(color='#ffb86c', bold=True),
            'bg_color': '#3a2a15',
        },
        'tool': {
            'title': 'Tool',
            'icon': '⚙',
            'border_style': Style(color='#8be9fd'),
            'title_style': Style(color='#8be9fd', bold=True),
            'bg_color': '#152030',
        },
        'info': {
            'title': 'Info',
            'icon': 'ℹ',
            'border_style': Style(color='#50fa7b'),
            'title_style': Style(color='#50fa7b', bold=True),
            'bg_color': '#153020',
        },
        'rate_limit': {
            'title': 'Rate Limited',
            'icon': '⏳',
            'border_style': Style(color='#ffb86c'),
            'title_style': Style(color='#ffb86c', bold=True),
            'bg_color': '#3a2a15',
        },
        'network': {
            'title': 'Connection Error',
            'icon': '📡',
            'border_style': Style(color='#ff79c6'),
            'title_style': Style(color='#ff79c6', bold=True),
            'bg_color': '#301530',
        },
        'timeout': {
            'title': 'Timeout',
            'icon': '⏱',
            'border_style': Style(color='#f1fa8c'),
            'title_style': Style(color='#f1fa8c', bold=True),
            'bg_color': '#303015',
        },
    }
    
    @classmethod
    def render(cls, block_type: str, message: str, details: Optional[str] = None) -> Panel:
        style = cls.STYLES.get(block_type, cls.STYLES['info'])
        
        content_parts = [message]
        if details:
            content_parts.append(f"[dim]{details}[/dim]")
        
        content = '\n'.join(content_parts)
        
        title = f"{style['icon']} {style['title']}"
        
        return Panel(
            content,
            title=title,
            title_style=style['title_style'],
            border_style=style['border_style'],
            box=ROUNDED,
            padding=(0, 1),
            expand=False,
        )
    
    @classmethod
    def render_error(cls, error: Dict[str, Any]) -> Panel:
        error_type = error.get('type', 'error') if isinstance(error, dict) else 'error'
        message = error.get('message', 'An error occurred') if isinstance(error, dict) else str(error)
        details = error.get('details') if isinstance(error, dict) else None
        
        block_type = error_type if error_type in cls.STYLES else 'error'
        return cls.render(block_type, message, details)


class ChatEntry:
    """Represents a single entry in the chat history (message or info block)."""
    
    def __init__(self, entry_type: str, content: Any, metadata: Optional[Dict] = None):
        self.entry_type = entry_type
        self.content = content
        self.metadata = metadata or {}
        self.timestamp = time.strftime("%H:%M:%S")
    
    def render(self):
        if self.entry_type == 'user':
            return f"[bold cyan]You:[/bold cyan] {self.content}"
        elif self.entry_type == 'assistant':
            return None
        elif self.entry_type == 'error':
            return InfoBlock.render_error(self.content)
        elif self.entry_type == 'tool':
            tool_name = self.metadata.get('tool_name', 'unknown')
            return InfoBlock.render('tool', f"Called [bold]{tool_name}[/bold]", self.content)
        elif self.entry_type == 'info':
            return InfoBlock.render('info', self.content, self.metadata.get('details'))
        return None


def send_to_milkchan(command: str, params: dict = None) -> dict:
    """Send command to MilkChan IPC server"""
    if params is None:
        params = {}

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(120.0)
        sock.connect(('127.0.0.1', IPC_PORT))

        message = json.dumps({'command': command, 'params': params})
        sock.sendall((message + '\n').encode('utf-8'))

        response = b''
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk
            if b'\n' in response:
                break

        sock.close()
        return json.loads(response.decode('utf-8').strip())
    except Exception as e:
        return {'error': str(e)}


def load_history(history_file: str) -> list:
    # First try to load from MilkChan database via IPC
    result = send_to_milkchan('get_history')
    if result.get('status') == 'ok' and result.get('history'):
        history = result['history']
        if history:
            print(f"[TUI] Loaded {len(history)} messages from database")
            return history
    
    # Fallback to history file
    if os.path.exists(history_file):
        with open(history_file, 'r', encoding='utf-8') as f:
            history = json.load(f)
            if history:
                print(f"[TUI] Loaded {len(history)} messages from file")
            return history
    print("[TUI] No history found, starting fresh")
    return []


def save_history(history_file: str, history: list):
    # Save to history file
    with open(history_file, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2)
    # Also sync to MilkChan database
    send_to_milkchan('update_history', {'history': history})


def display_history(history: list):
    console.clear()
    console.print(Panel("[bold red]Milk Chan Terminal Chat[/bold red]", style=ACCENT, box=ROUNDED))
    console.print("[dim](Connected to MilkChan - sprites and audio will respond)[/dim]")
    console.print()

    for msg in history:
        role = msg.get('role', '')
        content = msg.get('content', '')
        entry_type = msg.get('entry_type', '')

        if entry_type == 'error':
            console.print(InfoBlock.render_error(content))
            console.print()
        elif entry_type == 'tool':
            tool_name = msg.get('tool_name', 'unknown')
            console.print(InfoBlock.render('tool', f"Called [bold]{tool_name}[/bold]", content))
            console.print()
        elif entry_type == 'info':
            console.print(InfoBlock.render('info', content, msg.get('details')))
            console.print()
        elif role == 'user':
            console.print(f"[bold cyan]You:[/bold cyan] {content}")
        elif role == 'assistant':
            console.print()
            console.print("[bold magenta]Milk Chan:[/bold magenta]")
            md = Markdown(content)
            console.print(md)
            console.print()


def stream_response(response: str, emotion: dict, char_delay: float = 0.03):
    """Stream response character by character with smooth markdown rendering"""

    if emotion:
        send_to_milkchan('stream_start', {'emotion': emotion})

    send_to_milkchan('start_speech')

    displayed = ""

    md = Markdown(displayed)

    with Live(md, refresh_per_second=30, transient=False) as live:
        for char in response:
            displayed += char
            md = Markdown(displayed)
            live.update(md)
            time.sleep(char_delay)

    console.print("\n[bold magenta]Milk Chan:[/bold magenta]")
    console.print(Markdown(displayed))

    send_to_milkchan('stream_end')


def display_error_block(error: dict):
    """Display a beautiful error block."""
    console.print()
    console.print(InfoBlock.render_error(error))
    console.print()


def main():
    if len(sys.argv) < 2:
        console.print("[red]Error: No history file provided[/red]")
        sys.exit(1)

    history_file = sys.argv[1]
    history = load_history(history_file)

    result = send_to_milkchan('ping')
    if 'error' in result:
        console.print(f"[red]Cannot connect to MilkChan: {result['error']}[/red]")
        console.print("[yellow]Make sure MilkChan is running.[/yellow]")
        sys.exit(1)

    display_history(history)

    send_to_milkchan('tui_start')

    console.print("[dim]Type your message and press Enter. Type 'exit' or 'quit' to close.[/dim]")
    console.print()

    import threading
    import signal
    shutdown_event = threading.Event()

    terminal_pid = os.getppid()

    def watch_for_shutdown():
        import time
        while not shutdown_event.is_set():
            result = send_to_milkchan('ping')
            if 'error' in result:
                shutdown_event.set()
                console.print("\n[red]MilkChan closed. Closing terminal...[/red]")
                try:
                    if os.name == 'nt':
                        os.system(f'taskkill /f /pid {terminal_pid}')
                    else:
                        os.kill(terminal_pid, signal.SIGTERM)
                except Exception:
                    pass
                os._exit(0)
            time.sleep(0.5)

    watcher_thread = threading.Thread(target=watch_for_shutdown, daemon=True)
    watcher_thread.start()

    while True:
        try:
            user_input = Prompt.ask("[bold cyan]You[/bold cyan]")

            if shutdown_event.is_set():
                break

            if user_input.lower() in ('exit', 'quit', 'q'):
                console.print("\n[bold red]Closing terminal chat...[/bold red]")
                save_history(history_file, history)
                break

            if not user_input.strip():
                continue

            history.append({'role': 'user', 'content': user_input})
            console.print()

            console.print("[bold magenta]Milk Chan:[/bold magenta] [dim]Thinking...[/dim]")

            api_messages = [{'role': m['role'], 'content': m['content']} for m in history if m.get('role') in ('user', 'assistant')]
            result = send_to_milkchan('chat', {
                'message': user_input,
                'history': api_messages[:-1]
            })

            if shutdown_event.is_set():
                break

            if result.get('status') == 'error' or 'error' in result:
                error = result.get('error', {'type': 'unknown', 'message': result.get('error', 'Unknown error')})
                console.file.write('\x1b[1A\x1b[2K')
                console.file.flush()
                display_error_block(error)
                history.pop()
                history.append({
                    'entry_type': 'error',
                    'content': error,
                    'role': 'system'
                })
                continue

            response = result.get('response', '')
            emotion = result.get('emotion')

            console.file.write('\x1b[1A\x1b[2K')
            console.file.flush()
            stream_response(response, emotion, char_delay=0.025)

            history.append({'role': 'assistant', 'content': response})

            if emotion:
                console.print(f"[dim]Emotion: {emotion.get('emotion', [])}[/dim]")
            console.print()

        except KeyboardInterrupt:
            console.print("\n[bold red]Interrupted. Saving history...[/bold red]")
            save_history(history_file, history)
            send_to_milkchan('stream_end')
            break
        except EOFError:
            save_history(history_file, history)
            send_to_milkchan('stream_end')
            break

    shutdown_event.set()
    send_to_milkchan('tui_end')
    send_to_milkchan('stop_speech')
    console.print("[green]History saved. You can close this terminal.[/green]")
    try:
        Prompt.ask("[dim]Press Enter to exit[/dim]")
    except Exception:
        pass


if __name__ == '__main__':
    main()
