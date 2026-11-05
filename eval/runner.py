"""The eval runner (after CoA's backend/evals: the dataset is dataset.py, the metric functions metrics/, this runs them): run every case
`--repeats` times on a pipeline variant, in process, and score each run.

Run from backend/ (eval/ shares its environment): `PYTHONPATH=..:../eval uv run python -m eval run --variant <name> --repeats 3`.
Variants: `baseline` (the single-LLM baseline, baselines/single_llm.py), `full` (the agent graph) and one per ablation flag of the
graph (`no_critic`, ...: RunConfigurable). The graph runs with an in-memory checkpointer and catalog store; it pauses at confirm_room
and is resumed with the case's labeled room, as a user confirming it, so the design is scored on the same room as the baseline's.

Without OPENROUTER_API_KEY, or with `--fake`, nothing calls a model: the graph replays the fixtures (stub.live), the baseline gets
the fake model, the catalog store fake embeddings; the report says so, and its numbers only check the pipeline runs.

Each run gets the deterministic metrics (metrics/), the grades of `--judge module:function` when given (a `Judge`), its cost and
tokens (the run's usage in its state: no LangSmith key, so not from traces) and its wall time; offline, those three are left blank
(they would be the fixtures' and the fake model's, not a measurement). The runs go to `<out>/runs.csv`, the
means per case to `<out>/report.md` (report/), each run's final state and row to `<out>/cases/<case>-<repeat>.json`; `<out>` defaults
to eval/results/<variant>-<time>. Exits 1 when a run failed (CI runs a 3-case smoke).

Importing this module turns LangSmith tracing off (before langchain is imported: langsmith caches the variables) and object storage
(the photos are read from the repo), so nothing but the model calls leaves the process, however the runner is called.
"""

# ruff: noqa: E402
import os

os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ.pop("STORAGE_ENDPOINT_URL", None)

import argparse
import asyncio
import json
import math
import pkgutil
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from statistics import fmean
from typing import Any, cast
from unittest.mock import patch

import pydantic_core
import report
from baselines.single_llm import predict
from dataset import Case, load_cases
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command
from metrics.analyst import FeatureScores, feature_scores
from metrics.layout import layout_metrics

from app import llm
from app.api.models import RunConfigurable
from app.catalog.embed import DIMS, get_embeddings, index_config, seed
from app.graph.graph import build_graph, serde
from app.graph.state import RunState
from app.llm.fake import FakeLLM
from app.schemas import RoomSpec
from app.schemas.layout import LAYOUT_EXAMPLE

RESULTS = Path(__file__).resolve().parent / "results"
VARIANTS = ["baseline", "full", *RunConfigurable.model_fields]
MEASURED = ("latency_s", "cost_usd", "input_tokens", "output_tokens")  # blank offline: not real numbers then

Row = dict[str, Any]
Judge = Callable[[Case, RunState], Mapping[str, Any]]  # a run's grades by name, e.g. an LLM judge's (E-04, ablation.judge)
Pipeline = Callable[[str, Case], tuple[RunState, RoomSpec | None]]  # (thread id, case) -> final state, the room the analyst read


def pipeline(variant: str, live: bool) -> Pipeline:
    if variant == "baseline":

        def baseline(thread_id: str, case: Case) -> tuple[RunState, RoomSpec | None]:
            layout, usage = predict(case)
            return RunState(
                layout=layout, cost=usage["cost"], input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"]
            ), None

        return baseline

    if live:  # a new client: the cached one's async connections belong to an earlier pipeline's asyncio.run, whose loop is closed
        get_embeddings.cache_clear()
    store = InMemoryStore(index=index_config(None if live else DeterministicFakeEmbedding(size=DIMS)))
    asyncio.run(seed(store))
    graph = build_graph(InMemorySaver(serde=serde()), store)
    flags = {} if variant == "full" else {variant: True}

    def run_graph(thread_id: str, case: Case) -> tuple[RunState, RoomSpec | None]:
        config: RunnableConfig = {"configurable": {"thread_id": thread_id, **flags}}
        graph.invoke(RunState(photo_keys=case.photo_keys, dimensions=case.dimensions, brief=case.brief), config)
        (pause,) = graph.get_state(config).interrupts  # confirm_room
        graph.invoke(Command(resume=case.room_spec.model_dump(mode="json")), config)
        return cast(RunState, graph.get_state(config).values), RoomSpec.model_validate(pause.value["room"])

    return run_graph


def analyst_metrics(predicted: RoomSpec, labeled: RoomSpec) -> Row:
    """Feature precision and recall over every type, and the mean position error (cm) of the matched features."""
    scores = feature_scores(predicted, labeled).values()
    total = FeatureScores(*(sum(getattr(s, k) for s in scores) for k in ("tp", "fp", "fn")))
    errors = [e for s in scores for e in s.errors_cm]
    return {"feature_precision": total.precision, "feature_recall": total.recall, "position_error_cm": fmean(errors) if errors else None}


def evaluate(run: Pipeline, name: str, case: Case, repeat: int, judge: Judge | None) -> tuple[Row, RunState]:
    """One run of a case, scored; a failed run is recorded with its error, not raised."""
    row: Row = {"case": name, "category": case.category, "repeat": repeat, "error": None}
    state: RunState = {}
    start = time.perf_counter()
    try:
        state, predicted = run(f"{name}-{repeat}", case)
        row["latency_s"] = round(time.perf_counter() - start, 3)
        row |= {
            "cost_usd": state.get("cost", 0.0),
            "input_tokens": state.get("input_tokens", 0),
            "output_tokens": state.get("output_tokens", 0),
        }
        if predicted and case.photos_match_room:
            row |= analyst_metrics(predicted, case.room_spec)
        metrics = layout_metrics(case.room_spec, case.brief, state["layout"])
        metrics["furniture_eur"] = metrics.pop("cost")  # not to be mistaken for the run's cost_usd
        row |= metrics
        if judge:
            row |= judge(case, state)
    except Exception as error:  # a failed run is a result of the eval, not a crash of it
        row["error"] = f"{type(error).__name__}: {error}"
    return row, state


def spent(rows: Sequence[Mapping[str, Any]]) -> float:
    """USD: the model cost of the runs and of their grading (every `*cost_usd` column, e.g. the judge's)."""
    return sum(v for r in rows for k, v in r.items() if k.endswith("cost_usd") and isinstance(v, int | float))


def run(
    variant: str,
    cases: Mapping[str, Case],
    repeats: int,
    out: Path,
    judge: Judge | None = None,
    workers: int = 1,
    max_cost: float = math.inf,
) -> list[Row]:
    """Run and score every case `repeats` times, `workers` runs at a time; write the CSV, the report and the per-case artifacts.
    Live, once the cost spent passes `max_cost` (USD), the runs not started yet are skipped: recorded as failed with that error."""
    live = bool(os.environ.get("OPENROUTER_API_KEY"))
    fake = patch.object(llm, "get_llm", lambda role: FakeLLM(json.dumps(LAYOUT_EXAMPLE)))
    cost: list[Row] = []  # the finished runs' rows, for their cost

    def job(pipe: Pipeline, name: str, case: Case, n: int) -> tuple[Row, RunState]:
        if live and spent(cost) > max_cost:
            return {"case": name, "category": case.category, "repeat": n, "error": "skipped: the cost spent passed the cap"}, {}
        result = evaluate(pipe, name, case, n, judge)
        cost.append(result[0])
        return result

    with nullcontext() if live else fake:
        pipe = pipeline(variant, live)
        with ThreadPoolExecutor(workers) as pool:
            jobs = [pool.submit(job, pipe, name, case, n) for n in range(1, repeats + 1) for name, case in cases.items()]
            results = [job.result() for job in jobs]
    rows = [row if live else row | dict.fromkeys(MEASURED) for row, _ in results]
    (out / "cases").mkdir(parents=True, exist_ok=True)
    for row, (_, state) in zip(rows, results, strict=True):
        artifact = {"row": row, "state": state}
        (out / "cases" / f"{row['case']}-{row['repeat']}.json").write_bytes(pydantic_core.to_json(artifact, indent=2) + b"\n")
    mode = "live models" if live else "fake models and fixture replay (offline): the numbers only check that the pipeline runs"
    report.write(rows, out, f"`{variant}`, {len(cases)} cases x {repeats} repeats, {mode}")
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["run"])
    parser.add_argument("--variant", choices=VARIANTS, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--limit", type=int, help="only the first N cases")
    parser.add_argument("--fake", action="store_true", help="no model calls even with OPENROUTER_API_KEY (automatic without it)")
    parser.add_argument("--judge", help="grade each run with this Judge, as module:function")
    parser.add_argument("--workers", type=int, default=1, help="runs at a time; more is faster, but latency then includes queuing")
    parser.add_argument("--out", type=Path, help="default: eval/results/<variant>-<time>")
    args = parser.parse_args(argv)
    if args.fake:
        os.environ.pop("OPENROUTER_API_KEY", None)
    judge = cast(Judge, pkgutil.resolve_name(args.judge)) if args.judge else None
    cases = dict(list(load_cases().items())[: args.limit])
    out = args.out or RESULTS / f"{args.variant}-{datetime.now():%Y%m%d-%H%M%S}"
    rows = run(args.variant, cases, args.repeats, out, judge, args.workers)
    print((out / "report.md").read_text())
    failed = [f"{r['case']}-{r['repeat']}: {r['error']}" for r in rows if r["error"]]
    print(*(f"Failed: {f}" for f in failed), f"Results in {out}", sep="\n")
    return 1 if failed else 0
