"""The eval report: every run's row in `runs.csv`, and in `report.md` a markdown table of the means per case and over all runs."""

import csv
from collections.abc import Sequence
from pathlib import Path
from statistics import fmean
from typing import Any

KEYS = ("case", "category", "repeat", "error")  # the row's columns that are not averaged


def mean(rows: Sequence[dict[str, Any]], column: str) -> str:
    """The mean of a column's numbers (True counts 1); blank when there are none."""
    values = [float(v) for r in rows if isinstance(v := r.get(column), int | float)]
    return f"{fmean(values):.4g}" if values else ""  # significant digits: a run's model cost can be under $0.001


def markdown(rows: Sequence[dict[str, Any]], columns: Sequence[str], title: str) -> str:
    metrics = [c for c in columns if c not in KEYS]
    by_case: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_case.setdefault(row["case"], []).append(row)
    costs = [c for r in rows if isinstance(c := r.get("cost_usd"), int | float)]
    cost = f"total model cost ${sum(costs):.4f}" if costs else "model cost not measured"
    lines = [
        "# Eval report",
        "",
        title + ".",
        f"{len(rows)} runs, {sum(bool(r['error']) for r in rows)} failed; {cost}. Means over each case's runs:",
        "",
        "| " + " | ".join(["case", "runs", "failed", *metrics]) + " |",
        "|" + " --- |" * (len(metrics) + 3),
    ]
    for case, group in [*by_case.items(), ("**all**", list(rows))]:
        cells = [case, str(len(group)), str(sum(bool(r["error"]) for r in group)), *(mean(group, m) for m in metrics)]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def write(rows: Sequence[dict[str, Any]], out: Path, title: str) -> None:
    columns = list(dict.fromkeys(k for r in rows for k in r))
    out.mkdir(parents=True, exist_ok=True)
    with (out / "runs.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, columns)
        writer.writeheader()
        writer.writerows(rows)
    (out / "report.md").write_text(markdown(rows, columns, title))
