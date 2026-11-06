"""Start the desktop app: housekeeping, updater, brain, character window and tray icon."""

import logging
import sys

from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from milkchan import paths
from milkchan.core.config import get_config
from milkchan.core.updater import get_updater
from milkchan.desktop.services import brain, legacy
from milkchan.desktop.ui.sprite_window import SpriteWindow

logger = logging.getLogger(__name__)


def _create_tray(app: QApplication, window: SpriteWindow, icon: QIcon) -> QSystemTrayIcon:
    tray = QSystemTrayIcon(icon, app)
    tray.setToolTip('MilkChan')
    menu = QMenu()
    menu.addAction('Show/Hide MilkChan', window.toggle_visibility)
    menu.addSeparator()
    menu.addAction('Exit', app.quit)
    tray.setContextMenu(menu)
    tray.show()
    tray.showMessage('MilkChan', 'Running in system tray. Use right-click to Show/Hide or Exit.',
                     QSystemTrayIcon.Information, 3000)
    tray.menu = menu  # the tray does not take ownership of its menu
    return tray


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # the tray keeps running while the character is hidden
    if sys.platform.startswith('win'):
        import ctypes

        # Groups the tray icon and taskbar entries under MilkChan instead of python.exe.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('MilkChan.MilkChan')

    paths.remove_obsolete_files()
    brain.start()
    app.aboutToQuit.connect(brain.stop)
    try:
        legacy.hand_over(brain.client(), brain.APP, brain.SESSION, get_config())
    except Exception:
        logger.exception("Could not hand MilkChan's earlier data to the brain; trying again next start")
    updater = get_updater()
    updater.start_auto_check()
    app.aboutToQuit.connect(updater.stop_auto_check)

    icon = QIcon(str(paths.get_assets_dir() / ('icon.ico' if sys.platform.startswith('win') else 'icon.png')))
    app.setWindowIcon(icon)
    window = SpriteWindow()
    window.show()
    if QSystemTrayIcon.isSystemTrayAvailable():
        window.tray = _create_tray(app, window, icon)
    else:
        logger.warning('System tray not available; use F8 to show or hide the character')
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
