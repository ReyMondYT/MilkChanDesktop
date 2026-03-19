import os
import shutil
import sys
import time
import logging
from PyQt5.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon, QMenu, QStyle
from PyQt5.QtGui import QIcon
from milkchan.desktop.ui.sprite_window import SpriteWindow


def _init_database():
    """Initialize SQLite database"""
    try:
        from milkchan.desktop.services import memory_client
        memory_client.init()
    except Exception as e:
        logging.warning(f"Database initialization warning: {e}")


def _run_bootstrap() -> bool:
    """Run bootstrap setup if needed, returns True if successful"""
    from milkchan.bootstrap import is_first_run, ensure_setup

    if is_first_run():
        print("[Bootstrap] First run detected, setting up user data...")
        return ensure_setup()
    
    print("[Bootstrap] User data exists, skipping setup")
    return True


def check_ffmpeg() -> bool:
    if shutil.which('ffmpeg'):
        return True
    
    from milkchan.bootstrap import get_ffmpeg_path, FFMPEG_FILE
    
    ffmpeg_path = get_ffmpeg_path()
    if ffmpeg_path.exists():
        os.environ['PATH'] = str(ffmpeg_path.parent) + os.pathsep + os.environ.get('PATH', '')
        if shutil.which('ffmpeg'):
            return True
        # Try direct path
        import subprocess
        try:
            subprocess.run([str(ffmpeg_path), '-version'], capture_output=True, check=True)
            os.environ['PATH'] = str(ffmpeg_path.parent) + os.pathsep + os.environ.get('PATH', '')
            return True
        except Exception:
            pass
    
    print(f"[FFmpeg] Not found. Expected at: {ffmpeg_path}")
    print(f"[FFmpeg] File exists: {ffmpeg_path.exists()}")
    if FFMPEG_FILE.exists():
        print(f"[FFmpeg] FFMPEG_FILE exists: {FFMPEG_FILE}")
    
    msg = QMessageBox()
    msg.setIcon(QMessageBox.Critical)
    msg.setText('FFmpeg Not Found')
    msg.setInformativeText(f"FFmpeg is required for the Vision Context feature.\n\nExpected location:\n{ffmpeg_path}\n\nPlease download from:\nhttps://www.gyan.dev/ffmpeg/builds/")
    msg.setWindowTitle('Dependency Error')
    msg.setStandardButtons(QMessageBox.Ok)
    msg.exec_()
    return False


def main():
    # Verbose logging setup
    logging.basicConfig(
        level=logging.DEBUG,
        format='[%(asctime)s] %(levelname)s %(name)s:%(lineno)d %(message)s',
        datefmt='%H:%M:%S'
    )
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.INFO)
    # Silence verbose PIL debug streams (e.g., PngImagePlugin)
    logging.getLogger('PIL').setLevel(logging.WARNING)
    logging.getLogger('PIL.PngImagePlugin').setLevel(logging.WARNING)

    # Run bootstrap setup (first run check, asset copy)
    if not _run_bootstrap():
        QMessageBox.critical(None, 'Setup Failed', 'Failed to initialize MilkChan. Check logs.')
        sys.exit(1)

    # Initialize SQLite database
    _init_database()
    
    # Initialize auto-updater
    from milkchan.core.config import get_config
    from milkchan.core.updater import get_updater
    
    config = get_config()
    updates_config = config.get('updates', {})
    
    def on_update_available(update_info):
        """Callback when update is available - show system notification"""
        logging.info(f"Auto-update available: {update_info.current_sha[:7]} -> {update_info.latest_sha[:7]}")
    
    updater = get_updater(
        auto_check=updates_config.get('auto_check', True),
        check_interval_hours=updates_config.get('check_interval_hours', 24),
        auto_update=updates_config.get('auto_update', False),
        github_token=updates_config.get('github_token', ''),
        on_update_available=on_update_available
    )
    
    # Start automatic update checking
    if updater.auto_check:
        updater.start_auto_check()
        logging.info("Auto-updater initialized and started")

    app = QApplication(sys.argv)
    # Keep running even if all windows are hidden; required for tray-only operation
    try:
        app.setQuitOnLastWindowClosed(False)
    except Exception:
        pass

    # Windows: set AppUserModelID to ensure proper tray grouping/visibility
    try:
        if sys.platform.startswith('win'):
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('MilkChan.MilkChan')
            print('[Tray] Set AppUserModelID = MilkChan.MilkChan')
    except Exception as e:
        print('[Tray] AppUserModelID set failed:', e)

    # Get assets from user data directory
    from milkchan.bootstrap import get_assets_dir
    assets_dir_global = str(get_assets_dir())
    icon_candidates = [
        os.path.join(assets_dir_global, 'icon.ico'),
        os.path.join(assets_dir_global, 'icon.png'),
    ]
    app_icon = None
    for p in icon_candidates:
        if os.path.exists(p):
            try:
                app_icon = QIcon(p)
                if not app_icon.isNull():
                    app.setWindowIcon(app_icon)
                    print(f"[Tray] Using app icon: {p}")
                    break
            except Exception:
                continue
    if app_icon is None or app_icon.isNull():
        # Fallback to a standard icon so tray can appear even without assets
        try:
            app_style = QApplication.style()
            if app_style is not None:
                app_icon = app_style.standardIcon(QStyle.SP_ComputerIcon) # type: ignore
                app.setWindowIcon(app_icon)
                print("[Tray] Using standard system icon (assets missing)")
        except Exception:
            pass
    if not check_ffmpeg():
        sys.exit(1)
        
    logging.info('Launching SpriteWindow...')
    t0 = time.perf_counter()
    window = SpriteWindow()
    logging.info('SpriteWindow launched in %.2fs', time.perf_counter() - t0)
    window.show()

    # System tray icon with Show/Hide/Exit actions
    try:
        available = QSystemTrayIcon.isSystemTrayAvailable()
        print(f"[Tray] System tray available: {available}")
        if not available:
            raise RuntimeError('System tray not available')

        # Prefer .ico on Windows for tray clarity
        tray_icon = app_icon if (app_icon and not app_icon.isNull()) else window.windowIcon()
        tray = QSystemTrayIcon(tray_icon)
        tray.setIcon(tray_icon)
        tray.setToolTip('MilkChan')
        menu = QMenu()

        def _show_window():
            # Only toggle if currently hidden
            if not window.isVisible():
                window.toggle_visibility()

        def _hide_window():
            # Only toggle if currently visible
            if window.isVisible():
                window.toggle_visibility()

        def _toggle():
            # Ensure window transparency for clicks toggles correctly
            try:
                window.toggle_visibility()
            except Exception:
                try:
                    if window.isVisible():
                        window.hide()
                    else:
                        window.show()
                except Exception:
                    pass
        act_toggle = menu.addAction('Show/Hide MilkChan')
        if act_toggle:
            act_toggle.triggered.connect(_toggle)
        menu.addSeparator()
        act_exit = menu.addAction('Exit')
        def _do_exit():
            # Stop auto-updater if running
            try:
                from milkchan.core.updater import get_updater
                updater = get_updater()
                updater.stop_auto_check()
            except Exception:
                pass
            try:
                tray.hide()
            except Exception:
                pass
            app.quit()
        if act_exit:
            act_exit.triggered.connect(_do_exit)
        tray.setContextMenu(menu)
        tray.setVisible(True)
        # On some Windows setups, calling show() twice helps surface the icon
        tray.show()
        tray.show()
        # Show a one-time message to surface the tray icon in overflow area
        try:
            tray.showMessage('MilkChan', 'Running in system tray. Use right-click to Show/Hide or Exit.', QSystemTrayIcon.MessageIcon.Information, 3000)
        except Exception:
            pass
        # Keep references to avoid garbage collection
        window._tray = tray
        window._tray_menu = menu
        window._tray_toggle = act_toggle
        window._tray_exit = act_exit
    except Exception:
        # If tray creation fails, continue without tray
        pass
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()