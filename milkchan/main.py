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
    
    # Set Qt plugin path to empty to prevent cv2's plugins from loading
    if 'QT_PLUGIN_PATH' in os.environ:
        del os.environ['QT_PLUGIN_PATH']

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
