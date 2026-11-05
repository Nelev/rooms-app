# Eval dataset

One folder per case, `eval/data/<case>/case.json`, loaded and validated by `eval/dataset.py` (`load_cases()`); `backend/tests/test_eval_dataset.py` checks every case. From `backend/`, `PYTHONPATH=. uv run python ../eval/dataset.py` validates the dataset and prints a summary.

## `case.json`

A `NewDesign` run input plus the labels:

| Field | Type | Notes |
| --- | --- | --- |
| `photo_keys` | 1 to 3 paths from the repo root | Each must exist |
| `dimensions` | `Dimensions` | What the user types; equal to `room_spec.dimensions` except in `hard-wrong-dimensions` |
| `brief` | `Brief`, or a path from the repo root to one | |
| `room_spec` | `RoomSpec`, or a path from the repo root to one | The room as a person labeled it from the photos |
| `category` | `functionality`, `layout`, `color_scheme` or `atmosphere` | I-Design's brief categories: what the brief mainly asks for |
| `expected` | string, hard cases only | What a correct run does instead of a plain design |

Put a real room's photos next to its `case.json` (`eval/data/<case>/photo-1.jpg`, referenced as `eval/data/<case>/photo-1.jpg`) and label its `RoomSpec` inline.

## Cases

- 20 briefs, 5 per category, on the three fixture rooms (`fixtures/small-bedroom`, `home-office`, `living-room`): they reference the fixtures' photos and `room_spec.json`.
- Hard cases (`hard-*`): `tiny-room` (1.8 x 2.1 m), `three-doors`, `wrong-dimensions` (the typed dimensions of `fixtures/negative/wrong_dimensions.json`), `impossible-brief` (`fixtures/negative/impossible_brief.json`) and `budget-too-low` (EUR 150).

## Not done yet

- **No real rooms.** Every photo is a fixture placeholder (see `fixtures/README.md`), so the room specs are not labeled from real photos and photo analysis cannot be scored. `hard-tiny-room` and `hard-three-doors` borrow photos of other fixture rooms. Labeling the first 10 real rooms needs real photos.
- **No dark-photo case**: it needs a real dark photo.
