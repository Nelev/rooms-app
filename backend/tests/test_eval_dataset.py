"""The eval dataset in eval/data/ loads, validates and covers every brief category and hard case."""

import json
from collections import Counter
from pathlib import Path

import pytest
from dataset import DATA, Case, load_cases
from pydantic import ValidationError

CASES = load_cases()
HARD = {"hard-tiny-room", "hard-three-doors", "hard-wrong-dimensions", "hard-impossible-brief", "hard-budget-too-low"}


def test_every_case_folder_loads() -> None:
    assert set(CASES) == {p.name for p in DATA.iterdir() if p.is_dir()}


def test_briefs_cover_every_category() -> None:
    plain = [c for c in CASES.values() if c.expected is None]
    assert len(plain) >= 20
    counts = Counter(c.category for c in plain)
    assert set(counts) == {"functionality", "layout", "color_scheme", "atmosphere"}
    assert min(counts.values()) >= 5


def test_hard_cases_say_what_a_correct_run_does() -> None:
    assert {name for name, c in CASES.items() if c.expected is not None} == HARD


@pytest.mark.parametrize("name", CASES)
def test_case_is_consistent(name: str) -> None:
    case = CASES[name]
    # only hard-wrong-dimensions types dimensions that disagree with the room
    assert (case.dimensions == case.room_spec.dimensions) == (name != "hard-wrong-dimensions")
    assert set(case.brief.keep) <= {k.name for k in case.room_spec.kept_furniture}


def test_loader_rejects_a_missing_photo(tmp_path: Path) -> None:
    case = json.loads((DATA / "bedroom-sage" / "case.json").read_text())
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "case.json").write_text(json.dumps(case | {"photo_keys": ["fixtures/nope.jpg"]}))
    with pytest.raises(ValidationError, match="missing photos"):
        load_cases(tmp_path)


def test_loader_rejects_an_unknown_field() -> None:
    case = json.loads((DATA / "bedroom-sage" / "case.json").read_text())
    with pytest.raises(ValidationError, match="extra_forbidden"):
        Case.model_validate(case | {"photos": []})
