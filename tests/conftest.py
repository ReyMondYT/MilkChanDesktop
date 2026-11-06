import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROVIDER = "https://provider.invalid/v1"


@pytest.fixture
def config(tmp_path, monkeypatch):
    """A fresh settings file, used by everything that calls get_config()."""
    from milkchan.core import config as core_config

    cfg = core_config.Config(str(tmp_path / "config.json"))
    monkeypatch.setattr(core_config, "_config", cfg)
    return cfg


@pytest.fixture
def brain(tmp_path, monkeypatch):
    """A real SentientMilk brain in tmp_path whose provider is faked.

    Queue the provider's replies in ``brain.replies``; requests it got are in ``brain.sent``.
    """
    from sentientmilk_framework.server import start
    from sentientmilk_framework.testing import FakeProvider

    from milkchan.desktop.services import brain as link

    fake = FakeProvider(PROVIDER).install(monkeypatch)
    hosted = start(tmp_path / "brain")
    client = link.framework.BrainClient(hosted.url, hosted.token)
    monkeypatch.setattr(link, "_client", client)
    client.update_config(api_key="sk-test", base_url=PROVIDER)
    fake.client, fake.server = client, hosted
    yield fake
    hosted.close()


@pytest.fixture(scope="session")
def qapp():
    from PyQt5.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])
