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

IPC_PORT = 19527

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.prompt import Prompt
    from rich.text import Text
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
    from rich import print as rprint

console = Console()

ACCENT = "#ac3232"


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
    if os.path.exists(history_file):
        with open(history_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def save_history(history_file: str, history: list):
    with open(history_file, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2)


def display_history(history: list):
    console.clear()
    console.print(Panel("[bold red]Milk Chan Terminal Chat[/bold red]", style=ACCENT))
    console.print("[dim](Connected to MilkChan - sprites and audio will respond)[/dim]")
    console.print()

    for msg in history:
        role = msg.get('role', '')
        content = msg.get('content', '')

        if role == 'user':
            console.print(f"[bold cyan]You:[/bold cyan] {content}")
        elif role == 'assistant':
            console.print()
            console.print("[bold magenta]Milk Chan:[/bold magenta]")
            md = Markdown(content)
            console.print(md)
            console.print()


def stream_response(response: str, emotion: dict, char_delay: float = 0.03):
    """Stream response character by character, synced with MilkChan speech"""
    
    # Send emotion update and start speech
    if emotion:
        send_to_milkchan('stream_start', {'emotion': emotion})
    
    # Start speech animation
    send_to_milkchan('start_speech')
    
    # Stream text with typewriter effect
    displayed = ""
    console.print()
    console.print("[bold magenta]Milk Chan:[/bold magenta] ", end="")
    
    for char in response:
        displayed += char
        console.print(char, end="", soft_wrap=True)
        time.sleep(char_delay)
    
    console.print()  # New line at end
    
    # End streaming
    send_to_milkchan('stream_end')


def main():
    if len(sys.argv) < 2:
        console.print("[red]Error: No history file provided[/red]")
        sys.exit(1)

    history_file = sys.argv[1]
    history = load_history(history_file)

    # Check connection to MilkChan
    result = send_to_milkchan('ping')
    if 'error' in result:
        console.print(f"[red]Cannot connect to MilkChan: {result['error']}[/red]")
        console.print("[yellow]Make sure MilkChan is running.[/yellow]")
        sys.exit(1)

    display_history(history)

    # Notify MilkChan that TUI is active
    send_to_milkchan('tui_start')

    console.print("[dim]Type your message and press Enter. Type 'exit' or 'quit' to close.[/dim]")
    console.print()

    # Start shutdown watcher thread
    import threading
    import os
    import signal
    shutdown_event = threading.Event()

    def watch_for_shutdown():
        import time
        import sys
        while not shutdown_event.is_set():
            result = send_to_milkchan('ping')
            if 'error' in result:
                shutdown_event.set()
                console.print("\n[red]MilkChan closed. Killing terminal...[/red]")
                # Kill the terminal process
                if os.name == 'nt':
                    # On Windows, kill the cmd process
                    os.system('taskkill /f /im cmd.exe')
                else:
                    # On Unix, kill the terminal
                    os.kill(os.getppid(), signal.SIGTERM)
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

            # Send chat request via IPC
            api_messages = [{'role': m['role'], 'content': m['content']} for m in history]
            result = send_to_milkchan('chat', {
                'message': user_input,
                'history': api_messages[:-1]
            })

            if shutdown_event.is_set():
                break

            if 'error' in result:
                console.print(f"[red]Error: {result['error']}[/red]")
                history.pop()
                continue

            response = result.get('response', '')
            emotion = result.get('emotion')

            # Clear "Thinking..." line by printing control sequences directly
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
