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

- **2 of the 4 variants ran.** `baseline` and `no_critic` each finished all 3 rooms, and every run was judged. `full` crashed
  before its first run, while seeding its catalog store. `analyst_mode` therefore never ran. Because the owner approved one run
  only, the pilot was not re-run. A fix is applied but unverified live: `full` and `analyst_mode` have not run with real
  models yet (see "The crash" below), and finishing the 3 x 4 matrix needs the owner to approve the command at the end.
- **1 repeat on 3 rooms.** There is one case per fixture room: `bedroom-calm` (small-bedroom), `office-focused` (home-office)
  and `living-airy` (living-room). The differences between variants are anecdotes, not results.
- **The photos are synthetic placeholders** (`fixtures/README.md`). The Room Analyst found no doors, windows or other features in
  any room: feature recall is 0. Precision is 1 only because the analyst predicted nothing. So the analyst variants measure nothing
  real yet. The design itself is scored on the hand-labeled room, because confirm_room is resumed with it.
- **The judge graded block-outs.** Only 4 of the 223 catalog items have a 3D model, and none of the pilot's 31 placed items had one, so every item rendered as a plain grey box. The judge said so in every
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

- Not included: the catalog embeddings used to seed each graph variant's store (text-embedding-3-small, 223 short texts per seed). Their usage is not recorded. They should cost well under $0.001.
- `no_critic`'s pipeline cost is slightly too high. The `source` node's stub wrapper adds the fixture's $0.004 per round even in
  live runs, which is the leak FIX-cost-determinism fixes. With one round per run, that is about $0.012 of the $0.0994.
- From these numbers, a full study would cost roughly $0.02 to $0.05 per run, plus about $0.017 per judged run: 4 variants x 25
  cases x 3 repeats (300 runs, all judged) is about $12 to $20.

## What the 6 runs show

All 6 designs stayed within budget, covered every must-have and had no item out of the room or blocking an opening.

| | baseline | no_critic |
| --- | --- | --- |
| Model cost per run | $0.025 | $0.033 |
| Wall time per run | 17 s | 56 s |
| Items a person can reach | 0.97 | 0.92 |
| Judge (0-10): functionality, layout, color, atmosphere, realism | 3.9, 4.1, 5.7, 3.7, 1.9 | 3.7, 4.4, 5.3, 3.3, 2.0 |

On 3 rooms, 1 repeat and box renders, the judge cannot tell the two variants apart: the gaps are within one grade point. The
agent graph without its Critic costs about a third more and takes about three times longer than the single-call baseline.

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

This report was assembled by hand from the 2 completed variants' runner output, with the module's own `report.write` and
`charts`; `full`'s failed row and the report's title and header line were written by hand (`ablate` writes them itself now). No
model was called again.

## How to run the rest

From backend/, with OPENROUTER_API_KEY set. Each command needs the owner's approval, and the cap stops it before the next variant
once the spend passes `--max-cost`.

```sh
# the variants the pilot missed, same 3 rooms
PYTHONPATH=..:../eval uv run python -m eval ablate --variants full analyst_mode \
  --cases bedroom-calm office-focused living-airy --repeats 1 --judge --out ../eval/results/pilot-2
# the full study: 4 variants x every case x 3 repeats (about $12 to $20)
PYTHONPATH=..:../eval uv run python -m eval ablate --judge --max-cost 20
```
