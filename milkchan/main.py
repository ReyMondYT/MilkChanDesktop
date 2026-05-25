#!/usr/bin/env python3
"""
MilkChan v1.0 - Desktop Application

Pure module-based desktop app - NO web servers!

Usage:
python -m milkchan.main # Run desktop GUI
"""

import sys
import os
from pathlib import Path
from milkchan.runtime_env import configure_qt_environment

# Fix Qt plugin conflict on Linux (must be before any Qt imports)
if sys.platform.startswith('linux'):
    configure_qt_environment()
    # Force xcb platform for X11/VNC
    # Disable OpenCV's Qt integration - use headless
    os.environ['OPENCV_VIDEOIO_PRIORITY_MSMF'] = '0'
    os.environ['OPENCV_VIDEOIO_PRIORITY_V4L2'] = '0'
    
    # Ensure PyQt5 plugins are preferred over OpenCV-bundled Qt plugins
    try:
        import PyQt5

        pyqt5_path = os.path.dirname(PyQt5.__file__)
        qt_plugin_path = os.path.join(pyqt5_path, 'Qt5', 'plugins')
        os.environ['QT_PLUGIN_PATH'] = qt_plugin_path

        qpa_plugin_path = os.path.join(qt_plugin_path, 'platforms')
        os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = qpa_plugin_path
    except Exception:
        pass

    # If OpenCV set a conflicting QPA plugin path, remove it
    qpa_path = os.environ.get('QT_QPA_PLATFORM_PLUGIN_PATH', '')
    if 'cv2' in qpa_path or 'opencv' in qpa_path:
        del os.environ['QT_QPA_PLATFORM_PLUGIN_PATH']

# Ensure project root is in path
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))


def main():
    """Run the desktop GUI application"""
    import logging
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [MilkChan] %(message)s"
    )
    logger = logging.getLogger(__name__)
    
    if len(sys.argv) >= 2 and sys.argv[1] == "--terminal-chat":
        from milkchan.terminal_chat import main as terminal_main
        sys.argv = [sys.argv[0], *sys.argv[2:]]
        terminal_main()
        return

    if len(sys.argv) >= 2 and sys.argv[1] == "--install-user":
        if sys.platform.startswith("linux"):
            from milkchan.system_deps import ensure_runtime_system_dependencies
            if not ensure_runtime_system_dependencies():
                raise SystemExit(1)
        from milkchan.self_install import install_current_binary
        target = install_current_binary()
        print(f"MilkChan installed to {target}")
        return

    if len(sys.argv) >= 2 and sys.argv[1] == "--uninstall-user":
        from milkchan.self_install import uninstall_current_binary
        uninstall_current_binary()
        print("MilkChan user installation removed")
        return

    if len(sys.argv) >= 2 and sys.argv[1] == "--print-paths":
        from milkchan.bootstrap import get_user_data_dir, get_config_path, get_assets_dir, get_db_path, get_cache_file, get_ffmpeg_path
        print(f"data={get_user_data_dir()}")
        print(f"config={get_config_path()}")
        print(f"assets={get_assets_dir()}")
        print(f"database={get_db_path()}")
        print(f"sprite_cache={get_cache_file()}")
        print(f"ffmpeg={get_ffmpeg_path()}")
        return

    if len(sys.argv) >= 2 and sys.argv[1] == "--migrate-legacy-data":
        from milkchan.bootstrap import LEGACY_USER_DATA_DIR, get_user_data_dir, get_config_path, migrate_legacy_user_data
        migrated = migrate_legacy_user_data()
        if migrated:
            print(f"Migrated legacy data from {LEGACY_USER_DATA_DIR}")
        else:
            print(f"No legacy data migrated from {LEGACY_USER_DATA_DIR}")
        print(f"Canonical data: {get_user_data_dir()}")
        print(f"Canonical config: {get_config_path()}")
        return

    if len(sys.argv) >= 2 and sys.argv[1] == "--self-test-runtime":
        import numpy
        import scipy
        from scipy.io import wavfile
        print(f"runtime ok: numpy={numpy.__version__} scipy={scipy.__version__}")
        return

    if len(sys.argv) >= 2 and sys.argv[1] == "--self-test-restart":
        import subprocess
        from milkchan.process import restart_command, restart_environment
        cmd = restart_command() + ["--self-test-runtime"]
        result = subprocess.run(cmd, env=restart_environment(), check=False, text=True)
        if result.returncode != 0:
            raise SystemExit(result.returncode)
        print("restart ok")
        return

    if len(sys.argv) >= 2 and sys.argv[1] == "--self-test-audio":
        from milkchan.bootstrap import get_assets_dir
        from milkchan.desktop.utils.audio_player import NarrationPlayer
        audio_path = get_assets_dir() / "narr.mp3"
        player = NarrationPlayer(str(audio_path))
        print(f"audio={audio_path}")
        print(f"exists={audio_path.exists()}")
        print(f"backend={player.backend_name()}")
        print(f"available={player.is_available()}")
        if "--play" in sys.argv[2:]:
            print(f"played={player.play_test(1.0)}")
        return

    logger.info("MilkChan v1.0 starting...")
    
    # Run desktop GUI directly - no API server!
    from milkchan.desktop.app import main as desktop_main
    desktop_main()


if __name__ == "__main__":
    main()
