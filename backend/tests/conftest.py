import os

import pytest

LIVE_KEY = os.getenv("OPENROUTER_API_KEY")  # the live tests set it back themselves


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests stay offline (fixtures and the fake model) even when a key is set."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
