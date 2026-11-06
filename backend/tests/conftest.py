"""Tests run offline: the model key is unset, so the graph replays the fixtures, except in tests marked `live`, which run only
when OPENROUTER_API_KEY is set."""

import os

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "live: calls the real models; skipped unless OPENROUTER_API_KEY is set")


@pytest.fixture(autouse=True)
def offline(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if not request.node.get_closest_marker("live"):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("LLM_RECORDINGS", raising=False)  # the E2E stack's recorded model calls (app/llm/recorded.py)
    elif not os.environ.get("OPENROUTER_API_KEY"):
        pytest.skip("needs OPENROUTER_API_KEY")
