"""
Runtime hook to fix Qt plugin conflict between OpenCV and PyQt5 on Linux.
This ensures PyQt5's Qt plugins are used instead of OpenCV's bundled ones.
"""
import sys
import os

# On Linux, OpenCV bundles Qt plugins that conflict with PyQt5
# We need to ensure PyQt5's plugins are used by setting QT_PLUGIN_PATH
if sys.platform.startswith('linux'):
    # Get PyQt5's plugin path
    try:
        import PyQt5
        pyqt5_path = os.path.dirname(PyQt5.__file__)
        qt_plugin_path = os.path.join(pyqt5_path, 'Qt5', 'plugins')
        
        # Set QT_PLUGIN_PATH to PyQt5's plugins (prepend to override OpenCV)
        current_path = os.environ.get('QT_PLUGIN_PATH', '')
        if current_path:
            os.environ['QT_PLUGIN_PATH'] = qt_plugin_path + os.pathsep + current_path
        else:
            os.environ['QT_PLUGIN_PATH'] = qt_plugin_path
            
        # Also unset OpenCV's Qt plugin path if in QT_QPA_PLATFORM_PLUGIN_PATH
        qpa_path = os.environ.get('QT_QPA_PLATFORM_PLUGIN_PATH', '')
        if 'cv2' in qpa_path or 'opencv' in qpa_path:
            del os.environ['QT_QPA_PLATFORM_PLUGIN_PATH']
    except Exception:
        pass
