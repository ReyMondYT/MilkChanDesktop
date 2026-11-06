import importlib
import json

import pytest

from milkchan.core.config import Config


def test_legacy_settings_are_translated(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({
        'sprite_resolution_scale': 1.5,
        'sprite_pack': 'abc',
        'scale_factor': 300,
        'processing': {'vision_mode': 'text', 'video_resize_factor': 0.5, 'buffer_seconds': 4},
        'proactive': {'enabled': False, 'sample_interval_ms': 900},
        'updates': {'github_repo': 'x/y', 'github_token': 't'},
    }))
    config = Config(str(path)).as_dict()
    assert 'sprite_resolution_scale' not in config and 'sprite_pack' not in config
    assert config['scale_factor'] == 300
    assert config['processing'] == {'support_images': False, 'screenshot_scale': 0.5}
    assert config['proactive'] == {'enabled': False}
    assert config['updates']['github_token'] == 't' and 'github_repo' not in config['updates']
    assert config['character'] == ''


def test_save_is_atomic_and_round_trips(tmp_path):
    path = tmp_path / 'config.json'
    config = Config(str(path))
    config.set('processing.screenshot_scale', 0.25)
    config.update({'position': {'x_offset': -40}})
    assert [p.name for p in tmp_path.iterdir()] == ['config.json']
    reloaded = Config(str(path))
    assert reloaded.get('processing.screenshot_scale') == 0.25
    assert reloaded.get('position') == {'x_offset': -40, 'y_offset': 0}


def test_unreadable_settings_are_kept_aside(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text('{"openai_api_key": "precious"')
    config = Config(str(path))
    assert config.get('openai_api_key') is None and config.get('scale_factor') == 100
    assert 'precious' in (tmp_path / 'config.json.invalid').read_text()


@pytest.fixture
def paths(monkeypatch, tmp_path):
    """milkchan.paths re-read with XDG dirs inside tmp_path."""
    import milkchan.paths

    for name in ('home', 'data', 'config'):
        (tmp_path / name).mkdir()
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
    yield importlib.reload(milkchan.paths)
    monkeypatch.undo()
    importlib.reload(milkchan.paths)


def test_user_files_follow_xdg(paths, tmp_path):
    assert paths.get_user_data_dir() == tmp_path / 'data' / 'milkchan'
    assert paths.get_config_path() == tmp_path / 'config' / 'milkchan' / 'config.json'
    assert paths.get_db_path() == tmp_path / 'data' / 'milkchan' / 'milkchan.db'
    assert (paths.get_assets_dir() / 'characters' / 'milkchan' / 'character.json').exists()


def test_obsolete_files_are_removed_and_user_content_kept(paths):
    data = paths.get_user_data_dir()
    (data / 'assets' / 'sprites').mkdir(parents=True)
    (data / 'sprite_cache.pkl').write_bytes(b'cache')
    (data / 'ffmpeg.exe').write_bytes(b'binary')
    (paths.get_config_path().parent / 'backups').mkdir(parents=True)
    for kept in ('milkchan.db', 'updater_state.json'):
        (data / kept).write_text('keep')
    (data / 'sprite_packs' / 'mine').mkdir(parents=True)
    (data / 'characters' / ('a' * 32)).mkdir(parents=True)

    paths.remove_obsolete_files()

    assert sorted(p.name for p in data.iterdir()) == ['characters', 'milkchan.db', 'sprite_packs',
                                                      'updater_state.json']
    assert not (paths.get_config_path().parent / 'backups').exists()


def test_legacy_directory_is_copied_only_on_request(paths, tmp_path):
    legacy = tmp_path / 'home' / '.milkchan'
    (legacy / 'sentientmilk_framework').mkdir(parents=True)
    (legacy / 'sentientmilk_framework' / '__init__.py').write_text('')
    (legacy / 'config.json').write_text('{"openai_api_key": "old"}')
    (legacy / 'milkchan.db').write_bytes(b'sqlite')
    assert not paths.get_config_path().exists()

    assert paths.migrate_legacy_user_data() is True
    assert legacy.exists()
    assert paths.get_config_path().read_text() == '{"openai_api_key": "old"}'
    assert paths.get_db_path().read_bytes() == b'sqlite'
    assert (paths.get_user_data_dir() / 'sentientmilk_framework' / '__init__.py').exists()



def test_remove_deletes_nested_keys_and_ignores_missing_ones(tmp_path):
    config = Config(str(tmp_path / 'config.json'))
    config.update({'tools': {'web_search_token': 'x'}, 'processing': {'max_request_bytes': 1}})
    config.remove('tools', 'processing.max_request_bytes', 'missing.key', 'scale_factor.deeper')
    reloaded = Config(str(tmp_path / 'config.json'))
    assert reloaded.get('tools') is None and 'max_request_bytes' not in reloaded.get('processing')
    assert reloaded.get('scale_factor') == 100
