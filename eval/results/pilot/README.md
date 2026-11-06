# E-06 paid pilot: ablations on 3 rooms

A small paid pilot of the ablation pipeline (`eval/ablation.py`), run once on 2026-11-05. It is not the full study. It checks that
the pipeline works end to end with live models, and what a full run would cost.

- `report.md`: the mean of each metric per variant (layout metrics from E-02, Room Analyst scores, the VLM judge's grades from
  E-04, cost and wall time).
- `runs.csv`: one row per run.
- `charts/`: one SVG bar chart per metric, for the final presentation. They work in light and dark themes.
- `renders/<render>/`: what the judge saw, kept so people can rate the same images. Each folder has the two corner renders, the
  scene and the judge's replies with its comments.

## Read this before the numbers

- **All 4 variants ran, in two sittings.** `baseline` and `no_critic` ran first; `full` then crashed (see "The crash"). After the
  fix, the owner approved a second small run of `full` and `analyst_mode` on the same 3 rooms, on main with the cost-leak fix and
  the solver step limit (#53). The two sittings are combined in `runs.csv`; the crashed `full` row was dropped.
- **1 repeat on 3 rooms.** There is one case per fixture room: `bedroom-calm` (small-bedroom), `office-focused` (home-office)
  and `living-airy` (living-room). The differences between variants are anecdotes, not results.
- **The photos are synthetic placeholders** (`fixtures/README.md`). The Room Analyst found no doors, windows or other features in
  any room: feature recall is 0. Precision is 1 only because the analyst predicted nothing. So the analyst variants measure nothing
  real yet. The design itself is scored on the hand-labeled room, because confirm_room is resumed with it.
- **The judge graded block-outs.** Only 4 of the 223 catalog items have a 3D model, and none of the pilot's 62 placed items (22 distinct catalog items) had one, so every item rendered as a plain grey box. The judge said so in every
  comment ("placeholder geometry", "block-model proposal"). Its realism (about 2/10) and atmosphere grades reflect the renders
  more than the designs. The renders were captured headless with F-14's capture script (Playwright Chromium, software WebGL); the
  top-down stand-ins were not needed.
- **Judge-human agreement is pending.** `eval/data/human_ratings.csv` has one blank row per judged run. Once people fill in the
  grades, `PYTHONPATH=.:..:../eval uv run python ../eval/agreement.py report ../eval/results/pilot/runs.csv` (from backend/) reports
  Pearson, Spearman and binned Cohen's kappa per criterion.

## Cost

**$0.2732 in total**, as OpenRouter reported it in the runs' usage:

| | pipeline | judge (3 asks per run, each with both renders) | total |
| --- | --- | --- | --- |
| baseline, 3 runs | $0.0749 | $0.0490 | $0.1239 |
| no_critic, 3 runs | $0.0994 | $0.0499 | $0.1493 |
| full, 3 runs | $0.1274 | $0.0513 | $0.1787 |
| analyst_mode, 3 runs | $0.0817 | $0.0479 | $0.1296 |
| **pilot total** | | | **about $0.58** |

- Not included: the catalog embeddings used to seed each graph variant's store (text-embedding-3-small, 223 short texts per seed). Their usage is not recorded. They should cost well under $0.001.
- `no_critic`'s pipeline cost is slightly too high. The `source` node's stub wrapper adds the fixture's $0.004 per round even in
  live runs, which is the leak FIX-cost-determinism (#53) fixes. With one round per run, that is about $0.012 of the $0.0994. The
  second sitting (`full`, `analyst_mode`) ran with the fix.
- From these numbers, a full study would cost roughly $0.02 to $0.05 per run, plus about $0.017 per judged run: 4 variants x 25
  cases x 3 repeats (300 runs, all judged) is about $12 to $20.

## What the 12 runs show

All 12 designs stayed within budget, covered every must-have and had no item out of the room or blocking an opening.

| | baseline | no_critic | full | analyst_mode |
| --- | --- | --- | --- | --- |
| Model cost per run | $0.025 | $0.033 | $0.042 | $0.027 |
| Wall time per run | 17 s | 56 s | 57 s | 47 s |
| Items a person can reach | 0.97 | 0.92 | 0.92 | 1.00 |
| Judge (0-10): functionality, layout, color, atmosphere, realism | 3.9, 4.1, 5.7, 3.7, 1.9 | 3.7, 4.4, 5.3, 3.3, 2.0 | 4.0, 4.7, 5.9, 3.6, 2.0 | 3.7, 4.4, 5.8, 3.4, 2.0 |

On 3 rooms, 1 repeat and box renders, the judge cannot tell the variants apart: every gap is within one grade point, and
realism is about 2 everywhere because the renders are boxes. The full system (with the Critic) costs about 70% more than the
single-call baseline and takes about three times longer; the single-pass analyst saves about a third of the full system's cost.
`analyst_mode` measures nothing real about the Room Analyst here: on placeholder photos every variant's analyst finds no features.

## The crash

Running `full` failed with `RuntimeError: Event loop is closed`, in `runner.pipeline` -> `asyncio.run(seed(store))` -> the
OpenRouter embeddings client.

- **Cause.** `get_embeddings()` is cached. Its async HTTP connections were opened inside the first graph variant's (`no_critic`'s)
  `asyncio.run`, whose event loop was closed by the time the second variant reused the client.
- **Why E-05 missed it.** Offline runs use fake embeddings, and one live variant per process never reuses the client.
- **Fix** (in this branch, verified offline only): `runner.pipeline` clears the cache before each live store, so each variant
  gets a new client. The regression test, `test_each_live_graph_pipeline_gets_its_own_embeddings_client`, checks the clients
  differ with seeding replaced; no live run of a second graph variant has succeeded yet.
- **Hardening.** `ablate` now records a variant that cannot run as a failed row and goes on with the next variant, instead of
  losing the variants that already ran.

The fix was then verified live: the second sitting ran `full` and `analyst_mode` (two graph variants in one process) without error. `report.md` and `charts/` are rebuilt from `runs.csv` by the ablation command, with no model call:
`PYTHONPATH=..:../eval uv run python -m eval ablate --rebuild ../eval/results/pilot/runs.csv --out ../eval/results/pilot` (from
backend/).

## How to run the rest

The pilot is complete. From backend/, with OPENROUTER_API_KEY set (the cap skips the runs not started yet once the spend passes
`--max-cost`):

```sh
# the full study: 4 variants x every case x 3 repeats (about $12 to $20)
PYTHONPATH=..:../eval uv run python -m eval ablate --judge --max-cost 20
```
