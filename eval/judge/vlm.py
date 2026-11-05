"""The VLM judge, after I-Design's protocol (Celen et al. 2024, arXiv:2404.02838, section 4.2): a vision model sees a design's two corner
renders (cornerA and cornerC, eval/scripts/capture.ts) and the brief, comments first, then grades functionality, layout, color scheme,
atmosphere and realism from 0 to 10. It is asked RUNS times; a case's grades are each criterion's mean and standard deviation.
`pairwise` asks instead which of two designs fits the brief better, for ablations, PAIRWISE_RUNS times (an even number, so each
design is shown first equally often).

Run from backend/ (eval/ shares its environment), with OPENROUTER_API_KEY set, after capturing the renders:
- `PYTHONPATH=.:../eval uv run python -m judge.vlm grade [RUN ...]` writes `eval/results/judge/<run>.json` for each run of
  eval/results/renders (default: all of them);
- `PYTHONPATH=.:../eval uv run python -m judge.vlm pairwise RUN_A RUN_B [BRIEF_RUN]` prints and writes
  `eval/results/judge/pairwise/<run_a>-vs-<run_b>.json`.
A run's brief is its eval case's (eval/data/<run>) or its fixture's (fixtures/<run>/brief.json), so a run must be named after one: an
agent thread id is not mapped to its case yet (a run without a brief or renders is recorded as an error and grading goes on).
BRIEF_RUN names the run whose brief two compared runs share (default: RUN_A).
"""

import base64
import json
import sys
from functools import cache
from pathlib import Path
from statistics import fmean, stdev
from typing import Annotated, Literal

from dataset import REPO, load_cases
from pydantic import BaseModel, Field

from app import llm
from app.schemas import Brief

RUNS = 3  # I-Design asks the judge three times
PAIRWISE_RUNS = 4
CORNERS = ("cornerA", "cornerC")
RENDERS = REPO / "eval/results/renders"
OUT = REPO / "eval/results/judge"

Grade = Annotated[int, Field(ge=0, le=10)]

GRADE_PROMPT = """You are an expert interior designer judging a furnished room design. The two images are renders of the same room, \
seen from two opposite corners. The client's brief (JSON):
{brief}

First write your comments on the design: how well it serves the brief's use, how the furniture is laid out (circulation, access to \
doors and windows), its colors and materials, its atmosphere and how realistic it looks. Then grade each of these from 0 (worst) to \
10 (best): functionality, layout, color scheme, atmosphere, realism."""

PAIRWISE_PROMPT = """You are an expert interior designer comparing two furnished designs of the same room. The first two images are \
design A seen from two opposite corners, the last two are design B from the same corners. The client's brief (JSON):
{brief}

First write your comments comparing the two designs against the brief, then say which one fits the brief better: A or B."""


class Grades(BaseModel):
    functionality: Grade
    layout: Grade
    color_scheme: Grade
    atmosphere: Grade
    realism: Grade


class Judgement(BaseModel):
    """One judge reply: the comments come first, so the grades follow from them."""

    comments: str = Field(description="Your comments on the design, written before grading it")
    grades: Grades


class Preference(BaseModel):
    """One pairwise reply: the comments come first, so the choice follows from them."""

    comments: str = Field(description="Your comments comparing the two designs, written before choosing")
    better: Literal["A", "B"] = Field(description="The design that fits the brief better")


def data_url(png: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(png.read_bytes()).decode()


def renders(run: str) -> list[str]:
    """A run's two corner renders, as data URLs."""
    return [data_url(RENDERS / run / f"{corner}.png") for corner in CORNERS]


cases_once = cache(load_cases)  # read and validated once


def brief_of(run: str) -> Brief:
    """A run's brief: its eval case's, or else its fixture's."""
    cases = cases_once()
    return cases[run].brief if run in cases else Brief.model_validate_json((REPO / "fixtures" / run / "brief.json").read_bytes())


def grade(images: list[str], brief: Brief, runs: int = RUNS) -> dict[str, object]:
    """Ask the judge `runs` times; each criterion's mean and (sample) standard deviation, with every reply and the usage."""
    prompt = GRADE_PROMPT.format(brief=brief.model_dump_json())
    judgements: list[Judgement] = []
    usage: llm.Usage = {"cost": 0.0, "input_tokens": 0, "output_tokens": 0}
    for _ in range(runs):
        judgement, call = llm.ask_structured(Judgement, prompt, role="critic", images=images)
        judgements.append(judgement)
        usage = llm.add_usage(usage, call)
    scores = {name: [getattr(j.grades, name) for j in judgements] for name in Grades.model_fields}
    return {
        "mean": {name: fmean(s) for name, s in scores.items()},
        "std": {name: stdev(s) if len(s) > 1 else 0.0 for name, s in scores.items()},
        "judgements": [j.model_dump() for j in judgements],
        "usage": usage,
    }


def pairwise(a: list[str], b: list[str], brief: Brief, runs: int = PAIRWISE_RUNS) -> dict[str, object]:
    """Ask the judge `runs` times which design fits the brief better, swapping their order every other time against position bias;
    the wins of each side, with every reply (`better` as A/B of the arguments, not of the prompt) and the usage."""
    prompt = PAIRWISE_PROMPT.format(brief=brief.model_dump_json())
    wins = {"A": 0, "B": 0}
    replies: list[dict[str, object]] = []
    usage: llm.Usage = {"cost": 0.0, "input_tokens": 0, "output_tokens": 0}
    for i in range(runs):
        swapped = i % 2 == 1
        images = [*b, *a] if swapped else [*a, *b]
        reply, call = llm.ask_structured(Preference, prompt, role="critic", images=images)
        better = {"A": "B", "B": "A"}[reply.better] if swapped else reply.better
        wins[better] += 1
        replies.append({"comments": reply.comments, "better": better, "swapped": swapped})
        usage = llm.add_usage(usage, call)
    return {"wins": wins, "replies": replies, "usage": usage}


def write(path: Path, record: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n")


def grade_runs(runs: list[str], out: Path = OUT) -> None:
    """Grade every run and write `<out>/<run>.json`; a failed run (no renders or brief, a model failure) is recorded and grading goes on."""
    for run in runs:
        try:
            record = grade(renders(run), brief_of(run))
        except Exception as error:
            record = {"error": repr(error)}
        write(out / f"{run}.json", record)
        print(out / f"{run}.json", "(error)" if "error" in record else "")


if __name__ == "__main__":
    command, *args = sys.argv[1:] or ["grade"]
    llm.get_llm("critic")  # fail fast on a setup error (e.g. no OPENROUTER_API_KEY)
    if command == "grade":
        grade_runs(args or sorted(p.name for p in RENDERS.iterdir() if p.is_dir()))
    elif command == "pairwise" and len(args) in (2, 3):
        result = pairwise(renders(args[0]), renders(args[1]), brief_of(args[-1] if len(args) == 3 else args[0]))
        write(OUT / "pairwise" / f"{args[0]}-vs-{args[1]}.json", result)
        print(result["wins"])
    else:
        sys.exit(__doc__)
