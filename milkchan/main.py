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

# Fix Qt plugin conflict on Linux (must be before any Qt imports)
if sys.platform.startswith('linux'):
    # Force xcb platform for X11/VNC
    if 'QT_QPA_PLATFORM' not in os.environ:
        os.environ['QT_QPA_PLATFORM'] = 'xcb'
    
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
    
    logger.info("MilkChan v1.0 starting...")
    
    # Run desktop GUI directly - no API server!
    from milkchan.desktop.app import main as desktop_main
    desktop_main()


if __name__ == "__main__":
    main()
