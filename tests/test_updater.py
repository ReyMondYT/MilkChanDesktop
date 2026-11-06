from pathlib import Path

import pytest

from milkchan.core import updater as updater_module
from milkchan.core.updater import AutoUpdater, UpdateInfo

TREE = [{"path": f"sentientmilk_framework/{name}", "type": "blob"}
        for name in ("__init__.py", "loop.py", "brain.py", "client.py", "server.py", "runs.py",
                     "toolkits/__init__.py", "toolkits/files.py")]
TREE.append({"path": "README.md", "type": "blob"})


@pytest.fixture
def updater(tmp_path: Path, monkeypatch, config) -> AutoUpdater:
    updater = AutoUpdater(data_dir=tmp_path)
    updater._update_info = UpdateInfo(current_sha="old", latest_sha="abc123def", commit_message="update",
                                      commit_date="2026-09-09", available=True)
    monkeypatch.setattr(updater, "_get_tree", lambda _sha: TREE)
    updater.target_path.mkdir()
    (updater.target_path / "loop.py").write_text("old", encoding="utf-8")
    return updater


def fake_download(fail_on=None):
    def download(path, destination, revision):
        assert revision == "abc123def"
        if fail_on and path.endswith(fail_on):
            return False
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("new", encoding="utf-8")
        return True
    return download


def test_partial_update_is_rejected_without_changing_live_files(monkeypatch, updater):
    monkeypatch.setattr(updater, "_download_file", fake_download(fail_on="files.py"))
    assert updater.apply_update() is False
    assert (updater.target_path / "loop.py").read_text(encoding="utf-8") == "old"
    assert updater._load_state().get("last_applied_sha") is None
    assert not any(p.name.startswith(".") for p in updater.target_path.parent.iterdir())


def test_a_commit_from_before_the_v2_brain_is_not_installed(monkeypatch, updater):
    monkeypatch.setattr(updater, "_get_tree", lambda _sha: [i for i in TREE if not i["path"].endswith("runs.py")])
    monkeypatch.setattr(updater, "_download_file", fake_download())
    assert updater.apply_update() is False
    assert (updater.target_path / "loop.py").read_text(encoding="utf-8") == "old"


def test_complete_update_replaces_the_framework_once(monkeypatch, updater):
    monkeypatch.setattr(updater, "_download_file", fake_download())
    assert updater.apply_update() is True
    assert (updater.target_path / "loop.py").read_text(encoding="utf-8") == "new"
    assert not (updater.target_path / "README.md").exists()
    assert updater._load_state()["last_applied_sha"] == "abc123def"
    assert updater.apply_update() is False  # nothing left to apply
    leftovers = [p.name for p in updater.target_path.parent.iterdir() if p.name.startswith(".")]
    assert leftovers == []


def test_checking_never_applies(monkeypatch, updater):
    monkeypatch.setattr(updater, "_api_get", lambda endpoint: {
        "sha": "fff", "commit": {"message": "m", "committer": {"date": "d"}}})
    monkeypatch.setattr(updater, "apply_update", lambda: pytest.fail("check applied an update"))
    info = updater.check_for_updates()
    assert info.available and info.current_sha == "unknown" and info.latest_sha == "fff"


def test_source_checkouts_are_never_updated(monkeypatch, updater):
    monkeypatch.setattr(updater_module.sys, "frozen", False, raising=False)
    updater.start_auto_check()
    assert updater._thread is None
