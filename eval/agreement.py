"""Judge-human agreement (E-06): how close the VLM judge's grades (judge/vlm.py) are to people's, per criterion.

People grade the renders of judged runs (`<ablation out>/renders/<render>/cornerA.png` and `cornerC.png`, with the case's brief) from
0 to 10 on the judge's five criteria, one CSV row per run and rater, in eval/data/human_ratings.csv; a blank grade is not rated.
For each criterion, over the runs both graded (a run's human grade is its raters' mean): Pearson's and Spearman's correlation, and
Cohen's kappa on the grades binned as poor (0-3), fair (4-6) and good (7-10). None where it is undefined (under 2 runs, constant grades).

Run from backend/ (eval/ shares its environment), `PYTHONPATH=.:..:../eval uv run python ../eval/agreement.py`:
- `template RUNS_CSV [--force]` writes the ratings template, a blank row per judged run of an ablation's runs.csv; it keeps an
  existing one (people's ratings) unless `--force`;
- `report RUNS_CSV` prints the agreement table.
"""

import csv
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from statistics import StatisticsError, correlation, fmean

from dataset import DATA
from judge import vlm

CRITERIA = tuple(vlm.Grades.model_fields)
RATINGS = DATA / "human_ratings.csv"
KEY = ("variant", "case", "repeat")
BINS = (3, 6)  # upper bounds of poor and fair

Row = Mapping[str, str]


def read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def kappa(a: Sequence[int], b: Sequence[int]) -> float | None:
    """Cohen's kappa of two raters' labels; None when chance agreement is total (both gave one same label)."""
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    chance = sum(a.count(k) * b.count(k) for k in set(a) | set(b)) / n**2
    return None if chance == 1 else (observed - chance) / (1 - chance)


def binned(grade: float) -> int:
    return sum(grade > bound for bound in BINS)


def agreement(runs: Sequence[Row], ratings: Sequence[Row]) -> dict[str, dict[str, float | None]]:
    """Per criterion: the runs graded by both (n), Pearson, Spearman and the binned kappa."""
    judged = {tuple(r[k] for k in KEY): r for r in runs}
    table: dict[str, dict[str, float | None]] = {}
    for criterion in CRITERIA:
        human: dict[tuple[str, ...], list[float]] = {}
        for r in ratings:
            if r.get(criterion, "").strip():
                human.setdefault(tuple(r[k] for k in KEY), []).append(float(r[criterion]))
        pairs = [(float(j), fmean(h)) for key, h in human.items() if (j := judged.get(key, {}).get(f"judge_{criterion}", ""))]
        judge, people = [p[0] for p in pairs], [p[1] for p in pairs]
        row: dict[str, float | None] = {"n": len(pairs)}
        for name, ranked in (("pearson", False), ("spearman", True)):
            try:
                row[name] = correlation(judge, people, method="ranked" if ranked else "linear")
            except StatisticsError:  # under 2 pairs, or constant grades
                row[name] = None
        row["kappa"] = kappa([binned(g) for g in judge], [binned(g) for g in people]) if pairs else None
        table[criterion] = row
    return table


def cell(value: float | None) -> str:
    return "" if value is None else f"{value:.3g}"


def markdown(table: Mapping[str, Mapping[str, float | None]]) -> str:
    lines = ["| criterion | n | Pearson | Spearman | kappa (binned) |", "| --- | --- | --- | --- | --- |"]
    lines += [f"| {c} | {r['n']:.0f} | {cell(r['pearson'])} | {cell(r['spearman'])} | {cell(r['kappa'])} |" for c, r in table.items()]
    return "\n".join(lines) + "\n"


def template(runs: Sequence[Row], path: Path = RATINGS, force: bool = False) -> None:
    """A blank ratings row (rater and grades empty) per judged run; an existing file is kept unless `force`."""
    if path.exists() and not force:
        sys.exit(f"{path} exists: not overwritten (--force overwrites it)")
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, [*KEY, "render", "rater", *CRITERIA])
        writer.writeheader()
        writer.writerows({k: r[k] for k in (*KEY, "render")} for r in runs if r.get("render"))


if __name__ == "__main__":
    match sys.argv[1:]:
        case ["template", runs, *force] if force in ([], ["--force"]):
            template(read(Path(runs)), force=bool(force))
        case ["report", runs]:
            print(markdown(agreement(read(Path(runs)), read(RATINGS))))
        case _:
            sys.exit(__doc__)
