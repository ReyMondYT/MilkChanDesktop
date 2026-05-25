import importlib
import sys
from pathlib import Path


def import_bootstrap(monkeypatch, tmp_path):
    home = tmp_path / "home"
    data_home = tmp_path / "xdg-data"
    config_home = tmp_path / "xdg-config"
    home.mkdir()
    data_home.mkdir()
    config_home.mkdir()

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))

    sys.modules.pop("milkchan.bootstrap", None)
    return importlib.import_module("milkchan.bootstrap"), home, data_home, config_home


def test_uses_xdg_paths_for_user_data_and_config(monkeypatch, tmp_path):
    bootstrap, _home, data_home, config_home = import_bootstrap(monkeypatch, tmp_path)

    assert bootstrap.get_user_data_dir() == data_home / "milkchan"
    assert bootstrap.get_config_path() == config_home / "milkchan" / "config.json"
    assert bootstrap.get_assets_dir() == data_home / "milkchan" / "assets"
    assert bootstrap.get_db_path() == data_home / "milkchan" / "milkchan.db"


def test_does_not_auto_migrate_legacy_milkchan_directory(monkeypatch, tmp_path):
    home = tmp_path / "home"
    data_home = tmp_path / "xdg-data"
    config_home = tmp_path / "xdg-config"
    legacy = home / ".milkchan"
    legacy_assets = legacy / "assets"
    legacy_framework = legacy / "sentientmilk_framework"
    legacy_assets.mkdir(parents=True)
    legacy_framework.mkdir(parents=True)
    data_home.mkdir()
    config_home.mkdir()

    (legacy / "config.json").write_text('{"openai_api_key": "old"}', encoding="utf-8")
    (legacy / "milkchan.db").write_bytes(b"sqlite")
    (legacy / "ffmpeg").write_bytes(b"binary")
    (legacy_assets / "MILKCHAN.md").write_text("persona", encoding="utf-8")
    (legacy_framework / "__init__.py").write_text("class LLM: pass\n", encoding="utf-8")

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))

    sys.modules.pop("milkchan.bootstrap", None)
    bootstrap = importlib.import_module("milkchan.bootstrap")

    assert legacy.exists()
    assert not (config_home / "milkchan" / "config.json").exists()
    assert not (data_home / "milkchan" / "milkchan.db").exists()
    assert bootstrap.get_user_data_dir() == data_home / "milkchan"


def test_explicitly_migrates_legacy_milkchan_directory_without_deleting_it(monkeypatch, tmp_path):
    home = tmp_path / "home"
    data_home = tmp_path / "xdg-data"
    config_home = tmp_path / "xdg-config"
    legacy = home / ".milkchan"
    legacy_assets = legacy / "assets"
    legacy_framework = legacy / "sentientmilk_framework"
    legacy_assets.mkdir(parents=True)
    legacy_framework.mkdir(parents=True)
    data_home.mkdir()
    config_home.mkdir()

    (legacy / "config.json").write_text('{"openai_api_key": "old"}', encoding="utf-8")
    (legacy / "milkchan.db").write_bytes(b"sqlite")
    (legacy / "ffmpeg").write_bytes(b"binary")
    (legacy_assets / "MILKCHAN.md").write_text("persona", encoding="utf-8")
    (legacy_framework / "__init__.py").write_text("class LLM: pass\n", encoding="utf-8")

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))

    sys.modules.pop("milkchan.bootstrap", None)
    bootstrap = importlib.import_module("milkchan.bootstrap")

    assert bootstrap.migrate_legacy_user_data() is True
    assert legacy.exists()
    assert (config_home / "milkchan" / "config.json").read_text(encoding="utf-8") == '{"openai_api_key": "old"}'
    assert (data_home / "milkchan" / "milkchan.db").read_bytes() == b"sqlite"
    assert (data_home / "milkchan" / "ffmpeg").read_bytes() == b"binary"
    assert (bootstrap.get_assets_dir() / "MILKCHAN.md").read_text(encoding="utf-8") == "persona"
    assert (data_home / "milkchan" / "sentientmilk_framework" / "__init__.py").exists()


def test_screenshot_temp_directory_uses_xdg_data(monkeypatch, tmp_path):
    bootstrap, home, data_home, _config_home = import_bootstrap(monkeypatch, tmp_path)
    sys.modules.pop("milkchan.desktop.utils.screenshot", None)
    screenshot = importlib.import_module("milkchan.desktop.utils.screenshot")

    assert screenshot.TEMP_DIR == data_home / "milkchan" / "recordings" / "temp"
    assert screenshot.TEMP_DIR.exists()
    assert not (home / ".milkchan").exists()
    assert screenshot.TEMP_DIR.is_relative_to(bootstrap.get_user_data_dir())
