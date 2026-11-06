"""PyInstaller runtime hook: Qt settings must be in place before Qt loads."""

from milkchan.runtime_env import configure_qt_environment

configure_qt_environment()
