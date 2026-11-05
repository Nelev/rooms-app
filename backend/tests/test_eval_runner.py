"""The eval runner, offline: each variant runs a few cases end to end and writes its CSV, report and per-case artifacts."""

import csv
import json
import os
from pathlib import Path
from typing import Any

import pytest
import runner
from dataset import load_cases
from runner import main, run

from app.schemas import Layout, RoomSpec
from app.schemas.layout import LAYOUT_EXAMPLE

CASES = dict(list(load_cases().items())[:2])


def artifact(out: Path, case: str, repeat: int) -> Any:
    return json.loads((out / "cases" / f"{case}-{repeat}.json").read_text())


def test_baseline_runs_every_case_repeatedly_on_the_fake_model(tmp_path: Path) -> None:
    rows = run("baseline", CASES, 2, tmp_path)
    assert [(r["case"], r["repeat"]) for r in rows] == [(c, n) for n in (1, 2) for c in CASES]
    assert all(r["error"] is None and "must_have_coverage" in r for r in rows)
    assert all(r[k] is None for r in rows for k in runner.MEASURED)  # offline: the fake model's cost and time are not measurements
    assert "feature_recall" not in rows[0]  # the baseline reads no photos
    assert Layout.model_validate(artifact(tmp_path, rows[0]["case"], 1)["state"]["layout"]) == Layout.model_validate(LAYOUT_EXAMPLE)
    with (tmp_path / "runs.csv").open() as f:
        assert len(list(csv.DictReader(f))) == 4
    report = (tmp_path / "report.md").read_text()
    assert "`baseline`, 2 cases x 2 repeats, fake models" in report and "| **all** | 4 | 0 |" in report
    assert "model cost not measured" in report


def test_importing_the_runner_turns_tracing_and_storage_off() -> None:
    assert os.environ["LANGSMITH_TRACING"] == os.environ["LANGCHAIN_TRACING_V2"] == "false"
    assert "STORAGE_ENDPOINT_URL" not in os.environ


@pytest.mark.parametrize("variant", ["full", "no_critic"])
def test_graph_variants_run_the_graph_from_the_confirmed_room(variant: str, tmp_path: Path) -> None:
    name, case = next(iter(CASES.items()))
    (row,) = run(variant, {name: case}, 1, tmp_path)
    assert row["error"] is None and row["cost_usd"] is None and row["item_count"] > 0
    assert row["feature_recall"] == 1  # the fixture room the stub analyst replays is the first case's labeled room
    state = artifact(tmp_path, row["case"], 1)["state"]
    assert ("critique" in state) == (variant == "full")
    assert RoomSpec.model_validate(state["room_spec"]) == case.room_spec  # resumed with the labeled room


def test_a_judge_grades_each_run_and_a_failed_run_is_recorded(tmp_path: Path) -> None:
    def judge(case: Any, state: Any) -> dict[str, float]:
        if case is CASES[list(CASES)[1]]:
            raise ValueError("judge down")
        return {"brief_fit": 0.5}

    rows = run("baseline", CASES, 1, tmp_path, judge)
    assert rows[0]["brief_fit"] == 0.5 and rows[0]["error"] is None
    assert rows[1]["error"] == "ValueError: judge down" and "must_have_coverage" in rows[1]  # its metrics are kept
    assert "| **all** | 2 | 1 |" in (tmp_path / "report.md").read_text()


def test_cli_runs_a_smoke_eval_and_fails_on_a_failed_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert main(["run", "--variant", "baseline", "--repeats", "1", "--limit", "3", "--out", str(tmp_path / "ok")]) == 0
    assert len(list((tmp_path / "ok" / "cases").iterdir())) == 3
    monkeypatch.setattr(runner, "predict", lambda case: (_ for _ in ()).throw(RuntimeError("down")))
    assert main(["run", "--variant", "baseline", "--repeats", "1", "--limit", "1", "--out", str(tmp_path / "failed")]) == 1


@pytest.mark.live
def test_live_baseline_reports_the_model_cost(tmp_path: Path) -> None:
    (row,) = run("baseline", dict(list(CASES.items())[:1]), 1, tmp_path)
    assert row["error"] is None and row["cost_usd"] > 0 and row["input_tokens"] > 0
    assert "live models" in (tmp_path / "report.md").read_text()


@pytest.mark.live
def test_live_graph_runs_from_the_confirmed_room_and_reports_its_cost(tmp_path: Path) -> None:
    (row,) = run("full", dict(list(CASES.items())[:1]), 1, tmp_path)
    assert row["error"] is None and row["cost_usd"] > 0 and row["input_tokens"] > 0 and row["item_count"] > 0
