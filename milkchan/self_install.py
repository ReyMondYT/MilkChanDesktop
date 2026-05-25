import os
import shutil
import stat
import sys
from pathlib import Path


APP_NAME = "MilkChan"
APP_ID = "milkchan"


def _xdg_dir(env_name: str, default_relative: str) -> Path:
    value = os.environ.get(env_name)
    if value:
        return Path(value).expanduser()
    return Path.home() / default_relative


def get_install_dir() -> Path:
    return _xdg_dir("XDG_DATA_HOME", ".local/share") / "opt" / APP_ID


def get_applications_dir() -> Path:
    return _xdg_dir("XDG_DATA_HOME", ".local/share") / "applications"


def get_bin_dir() -> Path:
    return Path.home() / ".local" / "bin"


def install_current_binary() -> Path:
    if not getattr(sys, "frozen", False):
        raise RuntimeError("--install-user is only supported by the packaged binary")

    source = Path(sys.executable).resolve()
    install_dir = get_install_dir()
    install_dir.mkdir(parents=True, exist_ok=True)

    target = install_dir / APP_NAME
    if source != target:
        shutil.copy2(source, target)
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    launcher = install_dir / f"{APP_ID}.sh"
    launcher.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"\n'
        "export QT_QPA_PLATFORM=\"${QT_QPA_PLATFORM:-xcb}\"\n"
        "export QT_XCB_GL_INTEGRATION=\"${QT_XCB_GL_INTEGRATION:-none}\"\n"
        "export QT_OPENGL=\"${QT_OPENGL:-software}\"\n"
        "export LIBGL_ALWAYS_SOFTWARE=\"${LIBGL_ALWAYS_SOFTWARE:-1}\"\n"
        f"exec \"{target}\" \"$@\"\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)

    icon = _install_icon(install_dir)
    _install_desktop_entry(launcher, icon)
    _install_bin_link(launcher)
    return target


def uninstall_current_binary() -> None:
    desktop_file = get_applications_dir() / f"{APP_ID}.desktop"
    bin_link = get_bin_dir() / APP_ID
    for path in (desktop_file, bin_link):
        try:
            if path.exists() or path.is_symlink():
                path.unlink()
        except OSError:
            pass
    shutil.rmtree(get_install_dir(), ignore_errors=True)


def _install_icon(install_dir: Path) -> Path:
    icon_target = install_dir / "icon.png"
    meipass = Path(getattr(sys, "_MEIPASS", install_dir))
    icon_source = meipass / "assets" / "icon.png"
    if icon_source.exists():
        shutil.copy2(icon_source, icon_target)
    return icon_target


def _install_desktop_entry(launcher: Path, icon: Path) -> None:
    applications_dir = get_applications_dir()
    applications_dir.mkdir(parents=True, exist_ok=True)
    desktop_file = applications_dir / f"{APP_ID}.desktop"
    desktop_file.write_text(
        "[Desktop Entry]\n"
        "Version=1.0\n"
        f"Name={APP_NAME}\n"
        "Comment=AI desktop companion\n"
        f"Exec={launcher}\n"
        f"TryExec={launcher}\n"
        f"Icon={icon}\n"
        "Terminal=false\n"
        "Type=Application\n"
        "Categories=Utility;\n"
        "StartupNotify=true\n",
        encoding="utf-8",
    )


def _install_bin_link(launcher: Path) -> None:
    bin_dir = get_bin_dir()
    bin_dir.mkdir(parents=True, exist_ok=True)
    link = bin_dir / APP_ID
    try:
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(launcher)
    except OSError:
        shutil.copy2(launcher, link)
        link.chmod(0o755)
