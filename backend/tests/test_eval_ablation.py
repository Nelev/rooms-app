"""Ablations and judge-human agreement (E-06), offline: the variants run on fake models and fixture replay, the render capture is
replaced by drawn PNGs and the judge by the fake model; the agreement statistics run on synthetic ratings."""

import csv
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import ablation
import agreement
import pytest
import runner
from dataset import load_cases
from judge import vlm
from PIL import Image

from app import llm
from app.llm.fake import CALL_USAGE, FakeLLM
from app.schemas import Layout
from app.schemas.layout import LAYOUT_EXAMPLE

read = agreement.read
NAME = "bedroom-calm"
CASES = {NAME: load_cases()[NAME]}


def test_variants_run_into_one_report_with_a_chart_per_metric(tmp_path: Path) -> None:
    rows = ablation.ablate(["baseline", "no_critic"], CASES, 1, tmp_path)
    assert [(r["variant"], r["case"], r["error"]) for r in rows] == [("baseline", NAME, None), ("no_critic", NAME, None)]
    assert [r["variant"] for r in read(tmp_path / "runs.csv")] == ["baseline", "no_critic"]
    report = (tmp_path / "report.md").read_text()
    assert "Variants `baseline`, `no_critic`; 1 cases x 1 repeats, fake models" in report
    assert "| variant | runs | failed |" in report and "| no_critic | 1 | 0 |" in report and "| **all** | 2 | 0 |" in report
    assert (tmp_path / "runs" / "no_critic" / "cases" / f"{NAME}-1.json").exists()  # each variant's own runner output
    charts = {p.stem for p in (tmp_path / "charts").iterdir()}
    assert {"must_have_coverage", "clearance_pass_rate", "feature_recall"} <= charts
    assert "cost_usd" not in charts  # offline: not measured, so not charted
    svg = ET.parse(tmp_path / "charts" / "feature_recall.svg").getroot()
    assert "baseline" in ET.tostring(svg, encoding="unicode") and "n/a" in ET.tostring(svg, encoding="unicode")  # it reads no photos


def test_bounded_metrics_are_charted_on_their_whole_scale() -> None:
    assert "h186.0a4.0 4" in ablation.bar_chart("Judge", {"full": 5.0}, 10)  # half of the 380px bar width, less its 4px rounded end
    assert "h376.0a4.0 4" in ablation.bar_chart("Latency", {"full": 5.0, "baseline": 2.0})  # the largest mean fills it


def test_the_remaining_variants_are_skipped_once_the_cost_passes_the_cap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ran = []

    def run(variant: str, *args: Any) -> list[runner.Row]:
        ran.append(variant)
        return [{"case": NAME, "repeat": 1, "error": None, "cost_usd": 0.8, "judge_cost_usd": 0.3}]

    monkeypatch.setattr(runner, "run", run)
    ablation.ablate(ablation.VARIANTS, CASES, 1, tmp_path, max_cost=2.0)
    assert ran == ["baseline", "no_critic"]  # $2.20 spent after two
    report = (tmp_path / "report.md").read_text()
    assert "skipped full, analyst_mode: the cost spent passed $2.0" in report and "judge cost $0.6000" in report


def test_the_runs_not_started_are_skipped_once_the_cost_passes_the_cap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "not-a-key")  # live, but the baseline's pipeline is replaced: nothing is sent
    row = {"case": NAME, "repeat": 1, "error": None, "cost_usd": 0.6, "judge_cost_usd": 0.2}
    monkeypatch.setattr(runner, "evaluate", lambda *args: (row, {}))
    rows = runner.run("baseline", CASES, 4, tmp_path, max_cost=1.0)
    assert [r["error"] for r in rows] == [None, None, *["skipped: the cost spent passed the cap"] * 2]  # $1.60 spent after two


def test_a_variant_that_cannot_run_is_recorded_and_the_others_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    real = runner.run

    def run(variant: str, *args: Any) -> list[runner.Row]:
        if variant == "full":
            raise RuntimeError("Event loop is closed")
        return real(variant, *args)

    monkeypatch.setattr(runner, "run", run)
    rows = ablation.ablate(["full", "baseline"], CASES, 1, tmp_path)
    assert [(r["variant"], r["error"]) for r in rows] == [("full", "RuntimeError: Event loop is closed"), ("baseline", None)]
    assert "| full | 1 | 1 |" in (tmp_path / "report.md").read_text()
    assert "RuntimeError: Event loop is closed" in capsys.readouterr().err  # shown when it happens, with its traceback


def test_a_rebuild_reports_earlier_ablations_as_one(tmp_path: Path) -> None:
    ablation.ablate(["baseline"], CASES, 1, tmp_path / "a")
    ablation.ablate(["no_critic"], CASES, 1, tmp_path / "b")
    argv = ["ablate", "--rebuild", str(tmp_path / "a" / "runs.csv"), str(tmp_path / "b" / "runs.csv"), "--out", str(tmp_path / "ab")]
    assert ablation.main(argv) == 0
    earlier = [*read(tmp_path / "a" / "runs.csv"), *read(tmp_path / "b" / "runs.csv")]
    rebuilt = read(tmp_path / "ab" / "runs.csv")  # the same cells (parsed back as the runner wrote them), in the union of columns
    assert [{k: v for k, v in r.items() if v} for r in rebuilt] == [{k: v for k, v in r.items() if v} for r in earlier]
    report = (tmp_path / "ab" / "report.md").read_text()
    assert "Variants `baseline`, `no_critic`; rebuilt from" in report and "| no_critic | 1 | 0 |" in report
    assert (tmp_path / "ab" / "charts" / "must_have_coverage.svg").exists()


def test_each_live_graph_pipeline_gets_its_own_embeddings_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pilot's crash: a second live graph variant seeded its store with the first one's cached client, whose async connections
    belonged to the first asyncio.run's closed loop. No request is sent: seeding is replaced."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "not-a-key")
    stores = []

    async def seed(store: Any) -> None:
        stores.append(store)

    monkeypatch.setattr(runner, "seed", seed)
    try:
        runner.pipeline("no_critic", live=True)
        runner.pipeline("full", live=True)
    finally:
        runner.get_embeddings.cache_clear()  # no client with the fake key left for later live tests
    assert stores[0].embeddings is not stores[1].embeddings


def fake_capture(render: str) -> None:
    for corner in vlm.CORNERS:
        Image.new("RGB", (8, 8), "gray").save(vlm.RENDERS / render / f"{corner}.png")


def test_the_judge_grades_the_renders_of_the_run_scene(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(vlm, "RENDERS", tmp_path)
    monkeypatch.setattr(ablation, "capture", fake_capture)
    replies = [json.dumps({"comments": "ok", "grades": dict.fromkeys(vlm.Grades.model_fields, g)}) for g in (5, 6, 7) * 2]  # judged twice
    fake = FakeLLM(*replies)
    monkeypatch.setattr(llm, "get_llm", lambda role: fake)
    layout = Layout.model_validate(LAYOUT_EXAMPLE)
    grades = ablation.judge(CASES[NAME], {"layout": layout})  # the baseline: a layout and no scene
    assert grades["judge_realism"] == 6 and grades["judge_cost_usd"] == CALL_USAGE["cost"] * 3
    folder = tmp_path / grades["render"]
    scene = json.loads((folder / "scene.json").read_text())  # built from the layout in the labeled room
    assert [i["node_id"] for i in scene["items"]] == [p.node_id for p in layout.placements]
    assert json.loads((folder / "judge.json").read_text())["mean"]["layout"] == 6
    assert ablation.judge(CASES[NAME], {"layout": layout})["render"] == grades["render"]  # the same scene, the same render


def test_judged_runs_carry_their_renders_for_the_human_raters(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(vlm, "RENDERS", tmp_path / "renders")
    monkeypatch.setattr(ablation, "capture", fake_capture)
    monkeypatch.setattr(vlm, "grade", lambda images, brief: {"mean": {"layout": 4.0}, "usage": {"cost": 0.01}})
    (row,) = ablation.ablate(["baseline"], CASES, 1, tmp_path / "out", ablation.judge)
    assert row["judge_layout"] == 4.0 and (tmp_path / "out" / "renders" / row["render"] / "cornerA.png").exists()
    assert (tmp_path / "out" / "charts" / "judge_layout.svg").exists()


def test_cli_runs_an_offline_ablation(tmp_path: Path) -> None:
    argv = ["ablate", "--variants", "baseline", "full", "--cases", NAME, "--repeats", "1", "--out", str(tmp_path)]
    assert ablation.main(argv) == 0
    assert len(read(tmp_path / "runs.csv")) == 2


def ratings(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, [*agreement.KEY, "render", "rater", *agreement.CRITERIA])
        writer.writeheader()
        writer.writerows(rows)


def test_agreement_on_synthetic_ratings(tmp_path: Path) -> None:
    judged = [
        {"variant": "full", "case": c, "repeat": "1", "judge_layout": str(g), "judge_realism": "5"}
        for c, g in zip("abcd", (2, 5, 8, 9), strict=True)
    ]
    people = [
        *(
            {"variant": "full", "case": c, "repeat": "1", "layout": g, "realism": r}
            for c, g, r in zip("abcd", (1, 5, 7, 10), (3, 4, 6, 8), strict=True)
        ),
        {"variant": "full", "case": "d", "repeat": "1", "layout": 10, "realism": ""},  # a second rater, realism not rated
        {"variant": "full", "case": "z", "repeat": "1", "layout": 3},  # a run the judge did not grade
    ]
    ratings(tmp_path / "ratings.csv", people)
    table = agreement.agreement(judged, read(tmp_path / "ratings.csv"))
    assert table["layout"]["n"] == 4 and table["layout"]["spearman"] == 1 and table["layout"]["kappa"] == 1  # same order and bins
    assert 0.9 < (table["layout"]["pearson"] or 0) < 1
    assert table["realism"]["pearson"] is None  # the judge's grades are constant: undefined
    assert table["functionality"] == {"n": 0, "pearson": None, "spearman": None, "kappa": None}  # nobody rated it
    assert "| layout | 4 | 0.9" in agreement.markdown(table)


def test_kappa_counts_agreement_beyond_chance() -> None:
    assert agreement.kappa([0, 1, 2, 2], [0, 1, 2, 2]) == 1
    assert agreement.kappa([0, 0, 1, 1], [0, 1, 0, 1]) == 0
    assert agreement.kappa([2, 2], [2, 2]) is None
    assert [agreement.binned(g) for g in (0, 3, 3.5, 6, 7, 10)] == [0, 0, 1, 1, 2, 2]


def test_the_ratings_template_has_a_blank_row_per_judged_run(tmp_path: Path) -> None:
    runs = [{"variant": "full", "case": NAME, "repeat": "1", "render": "e06-abc"}, {"variant": "full", "case": "x", "repeat": "1"}]
    agreement.template(runs, tmp_path / "ratings.csv")
    (row,) = read(tmp_path / "ratings.csv")
    assert row["render"] == "e06-abc" and row["rater"] == row["layout"] == ""
    with pytest.raises(SystemExit):
        agreement.template(runs, tmp_path / "ratings.csv")  # people's ratings are kept
    agreement.template([{**runs[0], "render": "e06-def"}], tmp_path / "ratings.csv", force=True)
    assert [r["render"] for r in read(tmp_path / "ratings.csv")] == ["e06-def"]


@pytest.mark.live
def test_live_judged_ablation_of_the_baseline(tmp_path: Path) -> None:
    """One baseline run, rendered headless into eval/results/renders (needs the frontend's deps and Playwright's Chromium) and graded
    by the real judge."""
    (row,) = ablation.ablate(["baseline"], CASES, 1, tmp_path / "out", ablation.judge)
    assert row["error"] is None and row["judge_cost_usd"] > 0 and 0 <= row["judge_layout"] <= 10
