"""Ablations (E-06): several pipeline variants on the same cases, in one report with charts.

Run from backend/ (eval/ shares its environment):
`PYTHONPATH=..:../eval uv run python -m eval ablate [--variants ...] [--cases ...] [--repeats 3] [--judge] [--out DIR]`.
Each variant runs through the eval runner (runner.py) into `<out>/runs/<variant>/`; every run's row, with its variant, goes to
`<out>/runs.csv`, the means per variant to `<out>/report.md` and one bar chart (SVG) per metric to `<out>/charts/`. `<out>` defaults to
eval/results/ablation-<time>. The variants run one after another; once the model cost spent passes `--max-cost` (USD), the runs
not started yet are skipped (checked before each run: with `--workers` N, up to N runs already started can still add to it).

`--rebuild RUNS_CSV...` runs nothing: it rebuilds the report and the charts in `<out>` from earlier ablations' runs.csv files, e.g.
to report variants run on different days as one ablation.

`--judge` grades each run with the VLM judge (E-04, judge/vlm.py): the run's scene (the baseline's, which has none, is built from its
layout in the labeled room) is written to eval/results/renders/<render>/scene.json, rendered from two corners by
eval/scripts/capture.ts (headless Chromium, F-14's render route; set BASE_URL to reuse a running frontend), and graded; the renders,
the scene and the judge's replies are copied to `<out>/renders/<render>/` for the human raters (agreement.py). It needs live models.

Variants: `baseline`, `no_critic`, `full` and `analyst_mode` (the Room Analyst reads the photos once instead of voting RUNS readings)
by default. `single_agent` is a RunConfigurable flag no node reads yet, so it would run the full graph: it is left out.
"""

import runner  # first: it turns tracing off before langchain is imported

# isort: split
import argparse
import csv
import hashlib
import os
import shutil
import subprocess
import traceback
from collections.abc import Mapping, Sequence
from datetime import datetime
from html import escape
from pathlib import Path
from statistics import fmean
from typing import Any, cast

import pydantic_core
import report
from dataset import REPO, Case, load_cases
from judge import vlm

from app.graph.state import RunState
from app.scene.builder import build_scene

VARIANTS = ["baseline", "no_critic", "full", "analyst_mode"]
CAPTURE = REPO / "eval/scripts/capture.ts"

# the charted columns: their title and their scale's top (None: the largest mean); a column no run has is skipped
CHARTS: dict[str, tuple[str, float | None]] = {
    "cost_usd": ("Model cost per run (USD)", None),
    "latency_s": ("Wall time per run (s)", None),
    "must_have_coverage": ("Must-haves covered (share)", 1),
    "clearance_pass_rate": ("Items a person can reach (share)", 1),
    "budget_fit": ("Runs within budget (share)", 1),
    "out_of_bounds": ("Runs with an item out of the room (share)", 1),
    "overlap_volume": ("Overlapping volume (m³)", None),
    "blocked_openings": ("Blocked doors and windows per run", None),
    "feature_recall": ("Room Analyst: feature recall", 1),
    "feature_precision": ("Room Analyst: feature precision", 1),
    **{f"judge_{c}": (f"Judge: {c.replace('_', ' ')} (0-10)", 10) for c in vlm.Grades.model_fields},
}


def capture(render: str) -> None:
    """Render eval/results/renders/<render>/scene.json from the judge's two corners (capture.ts)."""
    command = ["pnpm", "--dir", str(REPO / "frontend"), "exec", "node", str(CAPTURE), render]
    done = subprocess.run(command, capture_output=True, text=True)
    if done.returncode:
        raise RuntimeError(f"capture failed ({done.returncode}): {(done.stderr or done.stdout)[-2000:]}")


def judge(case: Case, state: RunState) -> dict[str, Any]:
    """A runner Judge: the VLM judge's mean grades of the run's scene rendered from two corners, the judge's cost, the render id."""
    scene = state.get("scene") or build_scene(case.room_spec, state["layout"])
    data = pydantic_core.to_json(scene, indent=2)
    render = "e06-" + hashlib.sha256(data).hexdigest()[:12]  # the same scene renders and grades the same
    (vlm.RENDERS / render).mkdir(parents=True, exist_ok=True)
    (vlm.RENDERS / render / "scene.json").write_bytes(data)
    capture(render)
    record = vlm.grade(vlm.renders(render), case.brief)
    vlm.write(vlm.RENDERS / render / "judge.json", record)
    means = cast(dict[str, float], record["mean"])
    return {"render": render, "judge_cost_usd": cast(dict[str, float], record["usage"])["cost"]} | {
        f"judge_{name}": grade for name, grade in means.items()
    }


def bar_chart(title: str, means: Mapping[str, float | None], scale: float | None = None) -> str:
    """A horizontal bar per variant (one series: no legend, the title names it), its value at the tip; light and dark."""
    label_w, bar_w, row_h, top = 110, 380, 32, 44
    peak = scale or max((v for v in means.values() if v is not None), default=0) or 1
    rows = []
    for i, (variant, value) in enumerate(means.items()):
        y = top + i * row_h
        cell = f'<text x="{label_w - 8}" y="{y + 15}" text-anchor="end" class="label">{escape(variant)}</text>'
        if value is None:
            cell += f'<text x="{label_w + 4}" y="{y + 15}" class="value">n/a</text>'
        else:
            w = value / peak * bar_w
            r = min(4, w)  # 4px rounded data end, square at the baseline
            path = f"M{label_w} {y}h{w - r:.1f}a{r:.1f} 4 0 0 1 {r:.1f} 4v12a{r:.1f} 4 0 0 1 -{r:.1f} 4h-{w - r:.1f}z" if w else ""
            tip = f"{variant}: {value:.4g}"
            cell += f'<path d="{path}" class="bar"><title>{escape(tip)}</title></path>' if path else ""
            cell += f'<text x="{label_w + w + 6:.1f}" y="{y + 15}" class="value">{value:.3g}</text>'
        rows.append(cell)
    height = top + len(means) * row_h + 8
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 560 {height}" width="560" height="{height}" role="img">
<title>{escape(title)}</title>
<style>
svg {{ --surface: #fcfcfb; --text: #0b0b0b; --muted: #52514e; --axis: #d5d4ce; --bar: #2a78d6; font-family: system-ui, sans-serif; }}
@media (prefers-color-scheme: dark) {{ svg {{ --surface: #1a1a19; --text: #f0efec; --muted: #c3c2b7; --axis: #3d3d3a; --bar: #3987e5; }} }}
.title {{ fill: var(--text); font-size: 14px; font-weight: 600; }}
.label, .value {{ fill: var(--muted); font-size: 12px; }}
.bar {{ fill: var(--bar); }}
</style>
<rect width="100%" height="100%" fill="var(--surface)"/>
<text x="16" y="24" class="title">{escape(title)}</text>
<line x1="{label_w}" y1="{top - 4}" x2="{label_w}" y2="{height - 8}" stroke="var(--axis)"/>
{chr(10).join(rows)}
</svg>
"""


def charts(rows: Sequence[Mapping[str, Any]], variants: Sequence[str], out: Path) -> list[Path]:
    """One bar chart per charted column with a value in some run: each variant's mean over its runs."""
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for column, (title, scale) in CHARTS.items():
        means: dict[str, float | None] = {}
        for variant in variants:
            values = [float(v) for r in rows if r["variant"] == variant and isinstance(v := r.get(column), int | float)]
            means[variant] = round(fmean(values), 6) if values else None  # float noise (e.g. 1e-18 m³ of overlap) charts as 0
        if any(v is not None for v in means.values()):
            (path := out / f"{column}.svg").write_text(bar_chart(title, means, scale))
            written.append(path)
    return written


def ablate(
    variants: Sequence[str],
    cases: Mapping[str, Case],
    repeats: int,
    out: Path,
    judge: runner.Judge | None = None,
    workers: int = 1,
    max_cost: float = 2.0,
) -> list[runner.Row]:
    """Run each variant in turn until the cost spent passes `max_cost`; write the combined CSV, report and charts."""
    rows: list[runner.Row] = []
    done: list[str] = []
    for variant in variants:
        if (left := max_cost - runner.spent(rows)) < 0:
            break
        done.append(variant)
        try:
            ran = runner.run(variant, cases, repeats, out / "runs" / variant, judge, workers, left)
            rows += [{"variant": variant} | row for row in ran]
        except Exception as error:  # the variant could not run at all (e.g. its graph not built): the others still do
            traceback.print_exc()
            rows.append({"variant": variant, "case": "", "repeat": None, "error": f"{type(error).__name__}: {error}"})
    live = bool(os.environ.get("OPENROUTER_API_KEY"))
    mode = "live models" if live else "fake models and fixture replay (offline): the numbers only check that the pipeline runs"
    title = f"Variants {', '.join(f'`{v}`' for v in done)}; {len(cases)} cases x {repeats} repeats, {mode}"
    if skipped := variants[len(done) :]:
        title += f"; skipped {', '.join(skipped)}: the cost spent passed ${max_cost}"
    write(rows, title, out)
    return rows


def write(rows: Sequence[runner.Row], title: str, out: Path) -> None:
    """The combined runs.csv and report (the judge's cost in its title), the charts, and the judged runs' renders."""
    judge_costs = [c for r in rows if isinstance(c := r.get("judge_cost_usd"), int | float)]
    if judge_costs:
        title += f"; judge cost ${sum(judge_costs):.4f}"
    report.write(rows, out, title, by="variant")
    charts(rows, list(dict.fromkeys(r["variant"] for r in rows)), out / "charts")
    for render in {r["render"] for r in rows if r.get("render")}:
        if (vlm.RENDERS / render).exists():  # a rebuild may not have them: they are in the earlier ablation's out
            shutil.copytree(vlm.RENDERS / render, out / "renders" / render, dirs_exist_ok=True)


def cell(value: str) -> Any:
    """A runs.csv cell as the runner wrote it: blank None, a bool, an int, a float or the text."""
    if value in ("", "True", "False"):
        return {"": None, "True": True, "False": False}[value]
    for kind in (int, float):
        try:
            return kind(value)
        except ValueError:
            pass
    return value


def rebuild(paths: Sequence[Path], out: Path) -> list[runner.Row]:
    """The report and charts of earlier ablations' runs (their runs.csv files), as one ablation; nothing runs."""
    rows: list[runner.Row] = []
    for path in paths:
        with path.open(newline="") as f:
            rows += [{k: v if k in report.KEYS else cell(v) for k, v in r.items()} for r in csv.DictReader(f)]
    variants = ", ".join(f"`{v}`" for v in dict.fromkeys(r["variant"] for r in rows))
    write(rows, f"Variants {variants}; rebuilt from {', '.join(p.name if p.parent == out else str(p) for p in paths)}", out)
    return rows


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m eval ablate", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=["ablate"])
    parser.add_argument("--variants", nargs="+", choices=runner.VARIANTS, default=VARIANTS)
    parser.add_argument("--cases", nargs="+", help="case names (default: every case)")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--judge", action="store_true", help="grade each run's renders with the VLM judge (needs live models)")
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="runs at a time; more is faster, but latency then includes queuing; with --judge, set BASE_URL",
    )
    parser.add_argument(
        "--max-cost",
        type=float,
        default=2.0,
        help="USD: skip the runs not started yet once the cost spent passes it (checked before each run)",
    )
    parser.add_argument("--rebuild", nargs="+", type=Path, metavar="RUNS_CSV", help="run nothing: report these runs.csv as one")
    parser.add_argument("--fake", action="store_true", help="no model calls even with OPENROUTER_API_KEY (automatic without it)")
    parser.add_argument("--out", type=Path, help="default: eval/results/ablation-<time>")
    args = parser.parse_args(argv)
    if args.fake:
        os.environ.pop("OPENROUTER_API_KEY", None)
    every = load_cases()
    cases = {name: every[name] for name in args.cases} if args.cases else every
    out = args.out or runner.RESULTS / f"ablation-{datetime.now():%Y%m%d-%H%M%S}"
    if args.rebuild:
        rows = rebuild(args.rebuild, out)
    else:
        rows = ablate(args.variants, cases, args.repeats, out, judge if args.judge else None, args.workers, args.max_cost)
    print((out / "report.md").read_text())
    failed = [f"{r['variant']} {r['case']}-{r['repeat']}: {r['error']}" for r in rows if r["error"]]
    print(*(f"Failed: {f}" for f in failed), f"Model cost spent: ${runner.spent(rows):.4f}", f"Results in {out}", sep="\n")
    return 1 if failed else 0
