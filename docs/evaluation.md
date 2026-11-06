# Evaluation

The eval compares the agent graph with a single-LLM baseline and with ablations of itself. It covers 25 room cases and uses
deterministic layout metrics and a VLM judge. All code lives in `eval/`, and every command below runs from `backend/`, because
`eval/` shares the backend's environment.

> **Cost warning.** `make eval` and `make ablate` pass the root `.env` to the runner (`uv run --env-file ../.env`). If that file
> holds an `OPENROUTER_API_KEY`, they call real models and spend money: the pilot measured $0.025 (baseline), $0.033 (no_critic), $0.027 (analyst_mode) and $0.042 (full) per run, plus $0.017 per judged run.
> Add `--fake`, or leave the key unset, to run offline for free.

## Pieces

| Piece | Where | What it does |
| --- | --- | --- |
| Dataset (E-01) | `eval/data/<case>/`, `eval/dataset.py` | 25 cases: bedrooms, living rooms, offices, and 5 hard cases (tiny room, budget too low, three doors, impossible brief, wrong dimensions). Each case has a labeled room, a brief and photos ([eval/data/README.md](../eval/data/README.md)) |
| Metrics (E-02) | `eval/metrics/` | Layout: items out of bounds, overlap volume, clearance pass rate (items a person can reach), blocked openings, budget fit, must-have coverage. Room Analyst: feature precision and recall against the labels, position error |
| Single-LLM baseline (E-03) | `eval/baselines/single_llm.py` | LayoutGPT-style: one model call places the furniture directly, as absolute positions. It returns the same `Layout`, so every metric applies |
| VLM judge (E-04) | `eval/judge/vlm.py` | I-Design's protocol: a vision model sees two corner renders (captured headless by `eval/scripts/capture.ts`) and the brief. It writes comments first, then grades functionality, layout, color scheme, atmosphere and realism from 0 to 10. A pairwise mode compares two designs |
| Runner (E-05) | `eval/runner.py` | Runs every case on a variant, in process, and resumes `confirm_room` with the labeled room, so every variant is scored on the same room |
| Ablations (E-06) | `eval/ablation.py` | Several variants on the same cases, one report and one SVG chart per metric, with a `--max-cost` cap |
| Judge-human agreement | `eval/agreement.py` | Pearson, Spearman and binned Cohen's kappa between the judge's grades and `eval/data/human_ratings.csv` |

Variants: `baseline` (the single-LLM baseline), `full` (the agent graph), `no_critic` (no Critic loop) and `analyst_mode` (the Room
Analyst reads the photos once instead of voting).

## Commands

```sh
cd backend
# offline smoke: fixture replay and fake models, $0 (the numbers only check that the pipeline runs)
PYTHONPATH=..:../eval uv run python -m eval run --variant full --limit 3 --repeats 1 --fake
PYTHONPATH=..:../eval uv run python -m eval ablate --fake --cases bedroom-calm --repeats 1
# rebuild the pilot's report and charts from its runs.csv, no model call
PYTHONPATH=..:../eval uv run python -m eval ablate --rebuild ../eval/results/pilot/runs.csv --out ../eval/results/pilot
# live (OPENROUTER_API_KEY set, costs money): a variant, or the full ablation with the judge and a cost cap
PYTHONPATH=..:../eval uv run python -m eval run --variant full --repeats 3
PYTHONPATH=..:../eval uv run python -m eval ablate --judge --max-cost 20
# judge-human agreement, once people have filled in eval/data/human_ratings.csv
PYTHONPATH=.:..:../eval uv run python ../eval/agreement.py report ../eval/results/pilot/runs.csv
```

`--judge` also needs Playwright's Chromium for the corner renders: `pnpm --dir frontend exec playwright install chromium`.
Results go to `eval/results/<variant>-<time>/` or `eval/results/ablation-<time>/`. That folder is gitignored, except the pilot.

## Pilot results (E-06, 2026-11-05)

[`eval/results/pilot/`](../eval/results/pilot/) holds a small paid run that checked the pipeline end to end with live models. It
cost **about $0.58 in total**, in two sittings (OpenRouter usage, judge included). Its own [README](../eval/results/pilot/README.md) has every detail.

| Variant | Runs | Cost / run | Wall time / run | Clearance pass rate | Out of bounds | Blocked openings | Budget fit | Must-have coverage | Judge: functionality, layout, color, atmosphere, realism (0-10) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `baseline` (single LLM) | 3 | $0.025 | 17 s | 0.97 | 0 | 0 | 1 | 1 | 3.9, 4.1, 5.7, 3.7, 1.9 |
| `no_critic` (graph, no Critic) | 3 | $0.033 | 56 s | 0.92 | 0 | 0 | 1 | 1 | 3.7, 4.4, 5.3, 3.3, 2.0 |
| `full` (graph + Critic) | 3 | $0.042 | 57 s | 0.92 | 0 | 0 | 1 | 1 | 4.0, 4.7, 5.9, 3.6, 2.0 |
| `analyst_mode` (single-pass analyst) | 3 | $0.027 | 47 s | 1.00 | 0 | 0 | 1 | 1 | 3.7, 4.4, 5.8, 3.4, 2.0 |

<p>
  <img src="../eval/results/pilot/charts/cost_usd.svg" alt="Model cost per run: baseline $0.025, no_critic $0.033, full $0.042, analyst_mode $0.027" width="420">
  <img src="../eval/results/pilot/charts/latency_s.svg" alt="Wall time per run: baseline 17 s, no_critic 56 s, full 57 s, analyst_mode 47 s" width="420">
</p>

### Read these numbers with care

- **Two sittings.** `baseline` and `no_critic` ran first; `full` then crashed while seeding its catalog store (`Event loop is
  closed`: a cached embeddings client reused across event loops). After the fix, a second approved sitting ran `full` and
  `analyst_mode` on the same rooms, which also verified the fix live.
- **3 rooms, 1 repeat.** One case per room type (`bedroom-calm`, `office-focused`, `living-airy`). The gaps between variants are
  anecdotes, not results.
- **The photos are synthetic placeholders.** The Room Analyst finds nothing in them: feature recall is 0, and precision is 1 only
  because nothing was predicted. The designs are scored on the hand-labeled room.
- **Box renders.** None of the placed items had a 3D model, so the judge graded grey block-outs and said so in every comment.
  Realism (about 2/10) and atmosphere reflect the renders more than the designs.
- **Human ratings are pending.** `eval/data/human_ratings.csv` has a blank row per judged run. Judge-human agreement is not measured
  yet.

On these 12 runs, every design stayed in budget, covered every must-have and had nothing out of the room or blocking an opening. The
judge cannot tell the variants apart: every gap is within one grade point. The full graph (with the Critic) costs about 70% more
than the single call and takes about three times longer; the single-pass analyst saves about a third of the full graph's cost. A full study (4 variants x 25 cases x 3 repeats, all judged)
would cost about $12 to $20.
