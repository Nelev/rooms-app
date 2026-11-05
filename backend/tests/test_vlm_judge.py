"""The VLM judge's protocol, offline: the fake model stands in for get_llm and replies the judge's schemas; the renders are PNGs drawn
here. The grades a real model gives are not checked (the live test only checks that one replies)."""

import json
from pathlib import Path

import pytest
from baselines.single_llm import run as run_baseline
from dataset import load_cases
from judge import vlm
from PIL import Image, ImageDraw
from pydantic import ValidationError

from app import llm
from app.llm.fake import CALL_USAGE, FakeLLM
from app.schemas import Layout
from app.schemas.layout import LAYOUT_EXAMPLE

CASE = "bedroom-calm"
BRIEF = load_cases()[CASE].brief


def install(monkeypatch: pytest.MonkeyPatch, *replies: str, role: llm.Role = "critic") -> FakeLLM:
    fake = FakeLLM(*replies)
    monkeypatch.setattr(llm, "get_llm", lambda r: fake if r == role else pytest.fail(f"not the {role}: {r}"))
    return fake


def judgement(grade: int) -> str:
    grades = dict.fromkeys(vlm.Grades.model_fields, grade)
    return json.dumps({"comments": f"worth a {grade}", "grades": grades})


def draw(layout: Layout, renders: Path) -> None:
    """Stand-ins for a layout's corner renders: its footprints from above."""
    renders.mkdir(parents=True)
    for corner in vlm.CORNERS:
        image = Image.new("RGB", (64, 64), "white")
        for p in layout.placements:
            ImageDraw.Draw(image).rectangle([p.x * 10, p.y * 10, (p.x + p.size.width) * 10, (p.y + p.size.depth) * 10], fill="gray")
        image.save(renders / f"{corner}.png")


def test_comments_come_before_the_grades_and_the_choice() -> None:
    assert list(vlm.Judgement.model_json_schema()["properties"]) == ["comments", "grades"]
    assert list(vlm.Preference.model_json_schema()["properties"]) == ["comments", "better"]
    assert list(vlm.Grades.model_fields) == ["functionality", "layout", "color_scheme", "atmosphere", "realism"]


def test_grades_are_the_mean_and_std_of_three_runs_stored_per_case(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    draw(Layout.model_validate(LAYOUT_EXAMPLE), tmp_path / "renders" / CASE)
    monkeypatch.setattr(vlm, "RENDERS", tmp_path / "renders")
    fake = install(monkeypatch, judgement(6), judgement(7), judgement(8))
    vlm.grade_runs([CASE], tmp_path / "judge")
    record = json.loads((tmp_path / "judge" / f"{CASE}.json").read_text())
    assert fake.calls == vlm.RUNS == 3
    assert record["mean"] == dict.fromkeys(vlm.Grades.model_fields, 7) and record["std"] == dict.fromkeys(vlm.Grades.model_fields, 1)
    assert [j["comments"] for j in record["judgements"]] == ["worth a 6", "worth a 7", "worth a 8"]
    assert record["usage"] == {k: v * 3 for k, v in CALL_USAGE.items()}
    content = fake.prompts[0][0].content  # the brief and the two corners, as PNG data URLs
    assert isinstance(content, list) and BRIEF.model_dump_json() in content[0]["text"]
    assert [c["image_url"]["url"] for c in content[1:]] == vlm.renders(CASE)
    assert all(url.startswith("data:image/png;base64,") for url in vlm.renders(CASE))


def test_grades_are_bounded_from_0_to_10() -> None:
    with pytest.raises(ValidationError):
        vlm.Judgement.model_validate_json(judgement(11))


def test_a_run_without_renders_is_recorded_and_grading_goes_on(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    draw(Layout.model_validate(LAYOUT_EXAMPLE), tmp_path / "renders" / CASE)
    monkeypatch.setattr(vlm, "RENDERS", tmp_path / "renders")
    install(monkeypatch, judgement(6), judgement(7), judgement(8))
    vlm.grade_runs(["missing", CASE], tmp_path / "judge")
    assert "FileNotFoundError" in json.loads((tmp_path / "judge" / "missing.json").read_text())["error"]
    assert "mean" in json.loads((tmp_path / "judge" / f"{CASE}.json").read_text())


def test_pairwise_on_two_baseline_outputs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Two single-LLM baseline layouts of one case (the fake model's), drawn, then compared; the order is swapped every other run."""
    first = Layout.model_validate(LAYOUT_EXAMPLE)
    second = first.model_copy(update={"placements": first.placements[:1]})
    cases = {CASE: load_cases()[CASE]}
    layouts = []
    for name, layout in (("baseline-1", first), ("baseline-2", second)):
        install(monkeypatch, layout.model_dump_json(), role="architect")
        out = run_baseline(cases, tmp_path / name)[CASE]
        assert isinstance(out, Layout)
        draw(out, tmp_path / "renders" / name)
        layouts.append(name)
    monkeypatch.setattr(vlm, "RENDERS", tmp_path / "renders")
    a, b = (vlm.renders(name) for name in layouts)
    # the judge prefers baseline-1 every time: "A" when it is shown first, "B" when swapped
    fake = install(monkeypatch, *(json.dumps({"comments": "c", "better": better}) for better in ("A", "B", "A", "B")))
    result = vlm.pairwise(a, b, BRIEF)
    assert result["wins"] == {"A": 4, "B": 0}
    assert [r["swapped"] for r in result["replies"]] == [False, True, False, True]
    images = [[c["image_url"]["url"] for c in prompt[0].content[1:]] for prompt in fake.prompts]
    assert images == [a + b, b + a, a + b, b + a]


def test_a_run_brief_is_its_case_or_fixture() -> None:
    assert vlm.brief_of(CASE) == BRIEF
    assert vlm.brief_of("small-bedroom").room_use == "bedroom"


@pytest.mark.live
def test_live_judge_grades_a_drawn_layout(tmp_path: Path) -> None:
    draw(Layout.model_validate(LAYOUT_EXAMPLE), tmp_path)
    images = [vlm.data_url(tmp_path / f"{corner}.png") for corner in vlm.CORNERS]
    record = vlm.grade(images, BRIEF, runs=1)
    assert set(record["mean"]) == set(vlm.Grades.model_fields)
