import pytest

from stock_studio.config import load_settings
from stock_studio.store import Store


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "offline")
    monkeypatch.setenv("EMBEDDER", "phash")
    return load_settings(overrides={"workspace": str(tmp_path / "ws"),
                                    "export": {"weekly_cap": 3, "batch_size": 2}})


@pytest.fixture()
def store(settings):
    return Store(settings.db_path)
