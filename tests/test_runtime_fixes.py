import os
import sys
from types import ModuleType, SimpleNamespace


def test_normalize_base_url_strips_concrete_endpoints():
    from milkchan.desktop.services.ai_client import normalize_base_url

    assert normalize_base_url("https://openrouter.ai/api/v1/") == "https://openrouter.ai/api/v1"
    assert normalize_base_url("https://openrouter.ai/api/v1/chat/completions") == "https://openrouter.ai/api/v1"
    assert normalize_base_url("https://api.openai.com/v1/models") == "https://api.openai.com/v1"


def test_configure_qt_environment_sets_safe_linux_defaults(monkeypatch):
    from milkchan.runtime_env import configure_qt_environment

    if not sys.platform.startswith("linux"):
        return
    for key in ("QT_QPA_PLATFORM", "QT_XCB_GL_INTEGRATION", "QT_OPENGL", "LIBGL_ALWAYS_SOFTWARE"):
        monkeypatch.delenv(key, raising=False)

    configure_qt_environment()

    assert os.environ["QT_QPA_PLATFORM"] == "xcb"
    assert os.environ["QT_XCB_GL_INTEGRATION"] == "none"
    assert os.environ["QT_OPENGL"] == "software"
    assert os.environ["LIBGL_ALWAYS_SOFTWARE"] == "1"


def test_external_process_environment_removes_frozen_library_overrides(monkeypatch):
    import milkchan.runtime_env as runtime_env

    monkeypatch.setattr(runtime_env.sys, "frozen", True, raising=False)
    for key in ("LD_LIBRARY_PATH", "PYTHONPATH", "QT_PLUGIN_PATH", "_PYI_APPLICATION_HOME_DIR"):
        monkeypatch.setenv(key, "bad")

    env = runtime_env.external_process_environment()

    assert "LD_LIBRARY_PATH" not in env
    assert "PYTHONPATH" not in env
    assert "QT_PLUGIN_PATH" not in env
    assert "_PYI_APPLICATION_HOME_DIR" not in env


def test_narration_player_prefers_external_linux_backend(monkeypatch, tmp_path):
    from milkchan.desktop.utils.audio_player import NarrationPlayer
    import milkchan.desktop.utils.audio_player as audio_player

    audio = tmp_path / "narr.mp3"
    audio.write_bytes(b"fake")
    monkeypatch.setattr(audio_player.sys, "platform", "linux")
    monkeypatch.setattr(audio_player, "_SYSTEM_BIN_DIRS", ())
    monkeypatch.setattr(audio_player.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "ffplay" else None)

    player = NarrationPlayer(str(audio))

    assert player.backend_name() == "ffplay"
    assert player.is_available()


def test_narration_player_prefers_mpv_before_ffplay(monkeypatch, tmp_path):
    from milkchan.desktop.utils.audio_player import NarrationPlayer
    import milkchan.desktop.utils.audio_player as audio_player

    audio = tmp_path / "narr.mp3"
    audio.write_bytes(b"fake")
    monkeypatch.setattr(audio_player.sys, "platform", "linux")
    monkeypatch.setattr(audio_player, "_SYSTEM_BIN_DIRS", ())
    monkeypatch.setattr(audio_player.shutil, "which", lambda name: f"/usr/bin/{name}" if name in {"mpv", "ffplay"} else None)

    player = NarrationPlayer(str(audio))

    assert player.backend_name() == "mpv"
    assert player.is_available()


def test_narration_player_finds_debian_backend_when_path_is_thin(monkeypatch, tmp_path):
    from milkchan.desktop.utils.audio_player import NarrationPlayer
    import milkchan.desktop.utils.audio_player as audio_player

    audio = tmp_path / "narr.mp3"
    audio.write_bytes(b"fake")
    fake_usr_bin = tmp_path / "usr" / "bin"
    fake_usr_bin.mkdir(parents=True)
    fake_mpv = fake_usr_bin / "mpv"
    fake_mpv.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_mpv.chmod(0o755)

    monkeypatch.setattr(audio_player.sys, "platform", "linux")
    monkeypatch.setattr(audio_player, "_SYSTEM_BIN_DIRS", (str(fake_usr_bin),))
    monkeypatch.setattr(audio_player.shutil, "which", lambda name: None)

    player = NarrationPlayer(str(audio))

    assert player.backend_name() == "mpv"
    assert player.is_available()


def test_support_images_flag_disables_screenshots_even_with_legacy_vision_enabled():
    from milkchan.desktop.utils.vision import support_images_enabled

    cfg = {
        "processing": {
            "support_images": False,
            "vision_enabled": True,
            "vision_mode": "image",
            "screenshot_on_disabled_vision": True,
        }
    }

    assert support_images_enabled(cfg) is False


def test_support_images_legacy_config_stays_enabled_for_old_users():
    from milkchan.desktop.utils.vision import support_images_enabled

    cfg = {"processing": {"vision_mode": "image"}}

    assert support_images_enabled(cfg) is True


def test_sprite_speech_animation_starts_shared_audio_backend(monkeypatch):
    from milkchan.desktop.ui.sprite_window import SpriteWindow

    monkeypatch.setattr(SpriteWindow, "__del__", lambda self: None, raising=False)
    calls = []

    class Timer:
        def start(self, interval):
            calls.append(("timer", interval))

    class Player:
        def is_available(self):
            return True

        def stop(self):
            calls.append(("stop", None))

        def play(self):
            calls.append(("play", None))

        def ensure_playing(self):
            calls.append(("ensure", None))

    sprite = SpriteWindow.__new__(SpriteWindow)
    sprite.chat_overlay = SimpleNamespace(char_delay=50, audio_player=Player())
    sprite.mouth_timer = Timer()
    sprite.is_speaking = False

    sprite.start_speech_animation()

    assert sprite.is_speaking is True
    assert ("timer", 100) in calls
    assert ("play", None) in calls


def test_ipc_chat_uses_same_send_message_pipeline(monkeypatch):
    from milkchan.desktop.services.ipc_server import IPCServer
    import milkchan.desktop.agents.agent_workers as agent_workers

    calls = []

    def fake_send_message(message, video_filepath=None):
        calls.append((message, video_filepath))
        return {"response": "hi", "emotion": {"emotion": ["arms_down", "smile", 1]}, "error": None, "tools": []}

    monkeypatch.setattr(agent_workers, "send_message", fake_send_message)

    server = IPCServer()
    result = server._handle_chat({"message": "hello", "history": [{"role": "user", "content": "ignored"}]})

    assert calls == [("hello", None)]
    assert result["status"] == "ok"
    assert result["response"] == "hi"


def test_terminal_formats_exec_tool_output():
    from milkchan.terminal_chat import format_tool_result

    formatted = format_tool_result({
        "returncode": 0,
        "stdout": "hello\nworld\n",
        "stderr": "",
        "cwd": "/tmp",
    })

    assert "returncode: 0" in formatted
    assert "stdout:" in formatted
    assert "hello" in formatted
    assert "world" in formatted


def test_terminal_formats_read_tool_output():
    from milkchan.terminal_chat import format_tool_result

    formatted = format_tool_result("[Ln 1] # HTFDeeds\n[Ln 2] bot\n")

    assert "[Ln 1] # HTFDeeds" in formatted


def test_normal_gui_start_does_not_install_system_dependencies(monkeypatch):
    import milkchan.main as milkchan_main

    calls = []
    fake_desktop_app = ModuleType("milkchan.desktop.app")
    fake_desktop_app.main = lambda: calls.append("desktop")
    fake_system_deps = ModuleType("milkchan.system_deps")
    fake_system_deps.ensure_runtime_system_dependencies = lambda: (_ for _ in ()).throw(AssertionError("sudo path called"))

    monkeypatch.setattr(milkchan_main.sys, "argv", ["MilkChan"])
    monkeypatch.setitem(sys.modules, "milkchan.desktop.app", fake_desktop_app)
    monkeypatch.setitem(sys.modules, "milkchan.system_deps", fake_system_deps)

    milkchan_main.main()

    assert calls == ["desktop"]
