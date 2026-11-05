"""The single-LLM baseline runs on the whole eval dataset, offline: the fake model stands in for get_llm and replies a valid Layout."""

import json
from pathlib import Path

import pytest
from baselines.single_llm import PER_CATEGORY, catalog_subset, run
from dataset import load_cases

from app import llm
from app.catalog.loader import load_catalog
from app.llm.fake import CALL_USAGE, FakeLLM
from app.schemas import Brief, Layout, coords
from app.schemas.layout import LAYOUT_EXAMPLE

CASES = load_cases()
LAYOUT = Layout.model_validate(LAYOUT_EXAMPLE)


def install(monkeypatch: pytest.MonkeyPatch, *replies: str | Exception) -> FakeLLM:
    fake = FakeLLM(*replies)
    monkeypatch.setattr(llm, "get_llm", lambda role: fake)
    return fake


def test_runs_on_the_whole_dataset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = install(monkeypatch, *[LAYOUT.model_dump_json()] * len(CASES))
    results = run(CASES, tmp_path)
    assert results == dict.fromkeys(CASES, LAYOUT) and fake.calls == len(CASES)  # one call per case
    for name in CASES:
        assert json.loads((tmp_path / f"{name}.json").read_text()) == {"layout": LAYOUT.model_dump(mode="json"), "usage": CALL_USAGE}


def test_prompt_holds_the_coordinate_convention_room_brief_and_catalog(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = install(monkeypatch, LAYOUT.model_dump_json())
    case = CASES["living-airy"]
    run({"living-airy": case}, tmp_path)
    text = str(fake.prompts[0][0].content)
    assert coords.__doc__ and coords.__doc__ in text
    assert case.room_spec.model_dump_json() in text and case.brief.model_dump_json() in text
    assert all(f'"id":"{item.id}"' in text for item in catalog_subset(case.brief))


def test_a_failed_case_is_recorded_and_the_run_goes_on(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    install(monkeypatch, "not json", "still not json", LAYOUT.model_dump_json())  # the first case fails its call and its retry
    first, second = list(CASES)[:2]
    results = run({first: CASES[first], second: CASES[second]}, tmp_path)
    assert isinstance(results[first], Exception) and results[second] == LAYOUT
    assert "error" in json.loads((tmp_path / f"{first}.json").read_text())


def test_catalog_subset_prefers_the_brief_styles_then_the_cheapest() -> None:
    subset = catalog_subset(Brief(room_use="bedroom", styles=["japandi"], budget=1000))
    catalog = load_catalog().values()
    for category in {i.category for i in catalog}:
        items = [i for i in subset if i.category == category]
        japandi = [i for i in catalog if i.category == category and "japandi" in i.style_tags]
        assert len(items) == min(PER_CATEGORY, len([i for i in catalog if i.category == category]))
        assert sum("japandi" in i.style_tags for i in items) == min(PER_CATEGORY, len(japandi))
