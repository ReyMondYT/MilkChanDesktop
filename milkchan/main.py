#!/usr/bin/env python3
"""MilkChan entry point: the desktop app, plus a few maintenance commands.

    python -m milkchan.main                    run the desktop app
    python -m milkchan.main --print-paths      show where data and config live
    MilkChan --serve-brain                     run the SentientMilk brain (how packaged builds start it)
"""

import logging
import os
import sys

from milkchan.runtime_env import configure_qt_environment


def _print_paths():
    from milkchan import paths

    print(f"data={paths.get_user_data_dir()}")
    print(f"config={paths.get_config_path()}")
    print(f"assets={paths.get_assets_dir()}")
    from milkchan.desktop.services.brain import framework

    print(f"brain={framework.client.default_home()}")


def _migrate_legacy_data():
    from milkchan import paths

    migrated = paths.migrate_legacy_user_data()
    print(f"{'Migrated' if migrated else 'No'} legacy data from {paths.LEGACY_USER_DATA_DIR}")
    print(f"Canonical data: {paths.get_user_data_dir()}")
    print(f"Canonical config: {paths.get_config_path()}")


def _self_test_runtime():
    """Smoke test for packaged builds: the bundled character loads and the brain starts the way the app
    starts it (packaged: MilkChan --serve-brain), in a throwaway home."""
    import json
    import signal
    import tempfile
    from pathlib import Path

    from milkchan.desktop.services.brain import brain_command, framework
    from milkchan.desktop.sprites.library import BUILT_IN, load_character

    character = load_character(BUILT_IN)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as home:
        os.environ['SENTIENTMILK_HOME'] = home  # the started brain inherits it: the user's brain is not touched
        client = framework.connect(Path(home), command=brain_command())
        try:
            api = client.health()['api']
        finally:
            os.kill(json.loads((Path(home) / 'server.json').read_text(encoding='utf-8'))['pid'], signal.SIGTERM)
    print(f"runtime ok: character={character.name} frame={character.validate()} brain_api={api}")


def _self_test_restart():
    import subprocess

    from milkchan.process import restart_command, restart_environment

    result = subprocess.run(restart_command() + ["--self-test-runtime"], env=restart_environment(),
                            check=False, text=True)
    if result.returncode != 0:
        raise SystemExit(result.returncode)
    print("restart ok")


def _self_test_audio():
    from milkchan.desktop.utils.audio_player import NarrationPlayer
    from milkchan.paths import get_assets_dir

    audio_path = get_assets_dir() / "narr.mp3"
    player = NarrationPlayer(str(audio_path))
    print(f"audio={audio_path}")
    print(f"exists={audio_path.exists()}")
    print(f"backend={player.backend_name()}")
    print(f"available={player.is_available()}")
    if "--play" in sys.argv[2:]:
        print(f"played={player.play_test(1.0)}")


def _install_user():
    if sys.platform.startswith("linux"):
        from milkchan.system_deps import ensure_runtime_system_dependencies

        if not ensure_runtime_system_dependencies():
            raise SystemExit(1)
    from milkchan.self_install import install_current_binary

    print(f"MilkChan installed to {install_current_binary()}")


def _uninstall_user():
    from milkchan.self_install import uninstall_current_binary

    uninstall_current_binary()
    print("MilkChan user installation removed")


def _serve_brain():
    from milkchan.desktop.services.brain import serve_brain

    serve_brain()


def _terminal_chat():
    from milkchan.terminal_chat import main as terminal_main

    terminal_main()


COMMANDS = {
    "--serve-brain": _serve_brain,
    "--terminal-chat": _terminal_chat,
    "--install-user": _install_user,
    "--uninstall-user": _uninstall_user,
    "--print-paths": _print_paths,
    "--migrate-legacy-data": _migrate_legacy_data,
    "--self-test-runtime": _self_test_runtime,
    "--self-test-restart": _self_test_restart,
    "--self-test-audio": _self_test_audio,
}


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [MilkChan] %(name)s: %(message)s")
    configure_qt_environment()  # before anything starts Qt
    if len(sys.argv) >= 2 and sys.argv[1] in COMMANDS:
        COMMANDS[sys.argv[1]]()
        return
    from milkchan.desktop.app import main as desktop_main

    desktop_main()


if __name__ == "__main__":
    main()
