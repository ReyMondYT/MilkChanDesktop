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
import concurrent.futures
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Optional, Dict, Any, List

# Add project root to path for imports when running standalone
# This file is at milkchan/terminal_chat.py, so go up 1 level to project root
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

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
    """Re-render the prompt label if it was active before we suspended it."""
    if previously_active:
        _render_inline_prompt_label()
        console.file.flush()


def _flag_prompt_label_active():
    """Mark that Prompt.ask has drawn its label so guards can restore it."""
    global _prompt_label_active, _prompt_waiting_for_input
    _prompt_waiting_for_input = True
    _prompt_label_active = True


def _mark_prompt_consumed():
    """Reset prompt label state once Prompt.ask has collected input."""
    global _prompt_label_active, _prompt_waiting_for_input
    _prompt_label_active = False
    _prompt_waiting_for_input = False


@contextmanager
def _prompt_guard():
    """Suspend inline prompt label while emitting console output."""
    was_active = _suspend_inline_prompt_label()
    try:
        yield
    finally:
        _restore_inline_prompt_label(was_active)


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
    'completed': {
        'title': 'Tool',
        'icon': '✓',
        'border_style': Style(color='#50fa7b'),
        'title_style': Style(color='#50fa7b', bold=True),
        'bg_color': '#153020',
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
        
        # Use a simple title without markup
        title = f"{style['icon']} {style['title']}"
        
        return Panel(
            content,
            title=title,
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


def display_history(history: list, *, use_guard: bool = True):
    context = _prompt_guard() if use_guard else nullcontext()
    with context:
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
    with _prompt_guard():
        console.print()
        console.print(InfoBlock.render_error(error))
        console.print()


def display_thinking_spinner(duration: float = 0.5):
    """Display a simple thinking indicator with dots animation."""
    spinner = ["   ", ".  ", ".. ", "..."]
    start_time = time.time()
    
    # Clear current line
    console.file.write('\r')
    
    while time.time() - start_time < duration:
        for frame in spinner:
            console.file.write(f'\r[dim]Thinking{frame}[/dim]')
            console.file.flush()
            time.sleep(0.15)
    
    # Clear the line
    console.file.write('\r\x1b[2K')
    console.file.flush()


def format_tool_result(result: Any) -> str:
    """Format tool result for display."""
    if result is None:
        return ""
    
    if isinstance(result, dict):
        # For web_search results, show count of results
        if 'results' in result:
            count = len(result['results'])
            return f"Found {count} results"
        elif 'web' in result:
            count = len(result.get('web', {}).get('results', []))
            return f"Found {count} web results"
        else:
            # Show first key or summary
            keys = list(result.keys())[:3]
            return f"Data: {', '.join(keys)}..." if len(result) > 3 else f"Data: {', '.join(keys)}"
    elif isinstance(result, list):
        return f"[{len(result)} items]"
    elif isinstance(result, str):
        if len(result) > 100:
            return result[:100] + "..."
        return result
    else:
        return str(result)[:100]


def display_tools(tools: List[Dict]):
    """Display tool blocks with nice formatting."""
    if not tools:
        return
    with _prompt_guard():    
        for tool in tools:
            tool_name = tool.get('tool_name', 'unknown')
            status = tool.get('status', 'completed')
            
            # Skip internal tools
            if tool_name in ('update_sprite', 'reset_sprite_state'):
                continue
                
            # Format status with icon
            status_icons = {
                'running': '⏳',
                'completed': '✓',
                'error': '✗'
            }
            status_icon = status_icons.get(status, '•')
            
            # Build details
            details_parts = []
            
            # Show arguments if available
            args = tool.get('arguments', {})
            if args and tool_name == 'web_search':
                query = args.get('query', '')
                if query:
                    details_parts.append(f"Query: [cyan]{query}[/cyan]")
            
            # Show formatted result
            result = tool.get('result')
            if result:
                formatted = format_tool_result(result)
                if formatted:
                    details_parts.append(formatted)
            
            # Show error if any
            error = tool.get('error')
            if error:
                details_parts.append(f"[red]Error: {error}[/red]")
            
            details = "\n".join(details_parts) if details_parts else f"Status: {status_icon} {status}"
            
            console.print(InfoBlock.render('tool', f"[bold]{tool_name}[/bold]", details))
            console.print()


_active_tool_blocks: Dict[str, int] = {}


def display_tool_event(event: Dict[str, Any]):
    """Display a single tool event in real-time with overwrite support."""
    global _active_tool_blocks

    event_type = event.get('type', 'tool_end')
    data = event.get('data', {})

    tool_name = data.get('tool_name', 'unknown')

    # Skip internal tools
    if tool_name in ('update_sprite', 'reset_sprite_state'):
        return

    # Create unique identifier for this tool call
    args_str = str(sorted(data.get('arguments', {}).items()))
    tool_hash = f"{tool_name}:{args_str}"

    # Determine status and style
    if event_type == 'tool_start':
        status_icon = '⏳'
        status_text = 'running'
        block_type = 'tool'
    elif event_type == 'tool_error':
        status_icon = '✗'
        status_text = 'error'
        block_type = 'error'
    else:
        status_icon = '✓'
        status_text = 'completed'
        block_type = 'completed'

    # Build details
    details_parts = [f"Status: {status_icon} {status_text}"]

    # Show arguments
    args = data.get('arguments', {})
    if args and tool_name == 'web_search':
        query = args.get('query', '')
        if query:
            details_parts.append(f"Query: [cyan]{query}[/cyan]")

    # Show result
    result = data.get('result')
    if result:
        formatted = format_tool_result(result)
        if formatted:
            details_parts.append(formatted)

    # Show error
    error = data.get('error')
    if error:
        details_parts.append(f"[red]Error: {error}[/red]")

    details = "\n".join(details_parts)

    # For tool_end, overwrite the running block if we tracked it
    if event_type == 'tool_end' and tool_hash in _active_tool_blocks:
        lines_to_clear = _active_tool_blocks[tool_hash]
        # Move cursor up and clear lines
        for _ in range(lines_to_clear):
            sys.stdout.write('\x1b[1A')  # Cursor up
            sys.stdout.write('\x1b[2K')  # Clear line
        sys.stdout.write('\x1b[0J')  # Clear to end
        sys.stdout.flush()
        del _active_tool_blocks[tool_hash]

    # Render the block
    panel = InfoBlock.render(block_type, f"[bold]{tool_name}[/bold]", details)
    console.print(panel)
    console.print()

    # Track lines for running tools (to overwrite later)
    if event_type == 'tool_start':
        # Estimate lines: panel height + 1 for blank line
        # Panel height depends on content, estimate generously
        estimated_lines = 6 + details.count('\n')
        _active_tool_blocks[tool_hash] = estimated_lines
    _render_inline_prompt_label()


def handle_sync_event(event: Dict[str, Any], history: list, history_file: str) -> bool:
    """Handle sync events from chatbox. Returns True if handled."""
    event_type = event.get('type', '')
    data = event.get('data', {})

    # Check if this is a chat_response sync event
    if event_type == 'chat_response':
        msg_type = data.get('type', '')
        
        if msg_type == 'sync_message':
            role = data.get('role', 'user')
            content = data.get('content', '')
            emotion = data.get('emotion')
            
            # Add to history
            history.append({'role': role, 'content': content})
            save_history(history_file, history)
            
            # Display the message
            if role == 'user':
                with _prompt_guard():
                    console.print(f"[bold cyan]You:[/bold cyan] {content}")
                    console.print()
            elif role == 'assistant':
                display_assistant_response(content, emotion)
            
            return True
        
        elif msg_type == 'system' and data.get('action') == 'clear_history':
            # History cleared from chatbox – rebuild UI so prompt is restored
            history.clear()
            save_history(history_file, history)

            was_active = _suspend_inline_prompt_label()
            try:
                # Re-render the empty history header for consistency
                display_history(history, use_guard=False)
                console.print("[yellow]History cleared from main app[/yellow]")
                console.print()
                console.print("[dim]Type your message and press Enter. Type 'exit' or 'quit' to close.[/dim]")
                console.print()
            finally:
                _restore_inline_prompt_label(was_active)
            return True
    
    return False


def display_assistant_response(response: str, emotion: dict):
    """Display assistant response with typing animation and mouth sync."""
    with _prompt_guard():
        console.print("[bold magenta]Milk Chan:[/bold magenta]")
        
        if response and response.strip():
            # Start speech animation via IPC
            send_to_milkchan('start_speech')
            
            # Send emotion if available
            if emotion:
                send_to_milkchan('stream_start', {'emotion': emotion})
            
            # Use Rich Live for smooth markdown streaming
            words = response.split(' ')
            displayed = ""
            
            with Live(console=console, refresh_per_second=30, transient=True) as live:
                for i, word in enumerate(words):
                    if i == 0:
                        displayed = word
                    else:
                        displayed = f"{displayed} {word}"
                    
                    # Update the live display with markdown rendering
                    live.update(Markdown(displayed))
                    time.sleep(0.02)
            
            # Final render (persistent)
            console.print(Markdown(response))
            
            # End speech animation
            send_to_milkchan('stream_end')
        else:
            console.print("[dim italic](No response)[/dim italic]")
        
        console.print()
        
        if emotion:
            console.print(f"[dim]Emotion: {emotion.get('emotion', [])}[/dim]")
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

    # Get stream port and connect
    tui_result = send_to_milkchan('tui_start')
    stream_port = tui_result.get('stream_port', 19528)
    
    # Import stream client
    from milkchan.desktop.services.stream_client import StreamClient, StreamConfig, ConnectionState
    
# Track displayed tools to avoid duplicates
    displayed_tools = set()

    def on_stream_event(event: Dict[str, Any]):
        """Handle stream events with deduplication."""
        # Check for sync events first (from chatbox)
        if handle_sync_event(event, history, history_file):
            return

        event_type = event.get('type', '')
        data = event.get('data', {})
        tool_name = data.get('tool_name', 'unknown')

        # Skip internal tools
        if tool_name in ('update_sprite', 'reset_sprite_state'):
            return

        # Create unique identifier for this tool call (name + args only)
        # Don't include event_type so start+end are tracked together
        args_str = str(sorted(data.get('arguments', {}).items()))
        tool_hash = f"{tool_name}:{args_str}"

        # For tool_end events, check if we already showed this tool completing
        if event_type == 'tool_end':
            completion_hash = f"{tool_hash}:completed"
            if completion_hash in displayed_tools:
                return  # Already showed completion
            displayed_tools.add(completion_hash)

        # For tool_start, just mark that we showed it starting
        if event_type == 'tool_start':
            displayed_tools.add(f"{tool_hash}:started")

        display_tool_event(event)
    
    # Create stream client for real-time tool events
    stream_config = StreamConfig(port=stream_port)
    stream_client = StreamClient(
        config=stream_config,
        on_event=on_stream_event
    )
    
    # Connect to stream
    stream_connected = stream_client.connect(filters=['tool_start', 'tool_end', 'tool_error', 'chat_response'])
    if stream_connected:
        console.print("[dim]Connected to event stream[/dim]")
    
    # Display initial history
    display_history(history)
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
                stream_client.disconnect()
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
            _flag_prompt_label_active()
            user_input = Prompt.ask("[bold cyan]You[/bold cyan]")
            _mark_prompt_consumed()

            if shutdown_event.is_set():
                break

            if user_input.lower() in ('exit', 'quit', 'q'):
                console.print("\n[bold red]Closing terminal chat...[/bold red]")
                save_history(history_file, history)
                break

            if not user_input.strip():
                continue

            # Add user message to history
            history.append({'role': 'user', 'content': user_input})
            
            # Clear displayed tools for this turn
            displayed_tools.clear()
            
            # Show thinking indicator
            console.print("[dim]Thinking...[/dim]")
            
            # Send chat request
            api_messages = [{'role': m['role'], 'content': m['content']} for m in history if m.get('role') in ('user', 'assistant')]
            
            # Make the chat request in a separate thread
            import concurrent.futures
            
            result = None
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(send_to_milkchan, 'chat', {
                    'message': user_input,
                    'history': api_messages[:-1]
                })
                
                # Wait for response (tools will be displayed in real-time via stream)
                while not future.done():
                    if shutdown_event.is_set():
                        break
                    time.sleep(0.05)
                
                try:
                    result = future.result(timeout=120)
                except concurrent.futures.TimeoutError:
                    result = {'status': 'error', 'error': {'type': 'timeout', 'message': 'Request timed out'}}
            
            # Clear the "Thinking..." line
            console.file.write('\x1b[1A\x1b[2K')
            console.file.flush()

            if shutdown_event.is_set():
                break

            if result.get('status') == 'error' or 'error' in result:
                error = result.get('error', {'type': 'unknown', 'message': result.get('error', 'Unknown error')})
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
            tools = result.get('tools', [])

            # Display any tools that weren't shown via stream
            for tool in tools:
                tool_name = tool.get('tool_name', 'unknown')
                if tool_name in ('update_sprite',):
                    continue
                # Create unique identifier for this tool call (name + arguments)
                args_str = str(sorted(tool.get('arguments', {}).items()))
                tool_hash = f"{tool_name}:{args_str}"
                completion_hash = f"{tool_hash}:completed"
                if completion_hash not in displayed_tools:
                    display_tool_event({'type': 'tool_end', 'data': tool})
                    displayed_tools.add(completion_hash)
            
            # Display assistant response with typing animation
            display_assistant_response(response, emotion)

            # Add assistant response to history
            history.append({'role': 'assistant', 'content': response})
            
            # Save tools to history for persistence
            if tools:
                for tool in tools:
                    if tool.get('tool_name') not in ('update_sprite',):
                        history.append({
                            'entry_type': 'tool',
                            'tool_name': tool.get('tool_name', 'unknown'),
                            'content': tool.get('result', ''),
                            'status': tool.get('status', 'completed'),
                            'role': 'system'
                        })

        except KeyboardInterrupt:
            console.print("\n[bold red]Interrupted. Saving history...[/bold red]")
            save_history(history_file, history)
            send_to_milkchan('stream_end')
            stream_client.disconnect()
            break
        except EOFError:
            save_history(history_file, history)
            send_to_milkchan('stream_end')
            stream_client.disconnect()
            break

    shutdown_event.set()
    stream_client.disconnect()
    send_to_milkchan('tui_end')
    send_to_milkchan('stop_speech')
    console.print("[green]History saved. You can close this terminal.[/green]")
    try:
        _flag_prompt_label_active()
        Prompt.ask("[dim]Press Enter to exit[/dim]")
        _mark_prompt_consumed()
    except Exception:
        pass


if __name__ == '__main__':
    main()
