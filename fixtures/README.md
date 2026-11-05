# Fixtures

Sample data for frontend mocks, backend unit tests, the stub graph and the eval smoke test. Every file validates against the domain schemas in `backend/app/schemas/` (JSON Schema in `contracts/schemas/`); `backend/tests/test_fixtures.py` checks that, plus that each case is consistent and that every layout keeps items inside the room without overlaps.

## Layout

`fixtures/<case>/<file>`, one folder per case: `small-bedroom` (3.2 x 3.4 m), `home-office` (3.0 x 3.0 m) and `living-room` (4.5 x 5.0 m).

| File | Schema | Notes |
| --- | --- | --- |
| `photo-1.jpg`, `photo-2.jpg` | | Placeholders, see below |
| `room_spec.json` | `RoomSpec` | The confirmed room, with kept furniture |
| `brief.json` | `Brief` | |
| `design_brief.json` | `DesignBrief` | |
| `scene_graph.json` | `SceneGraph` | Object node ids match the design brief's object ids |
| `layout.json` | `Layout` | One placement per object node, axis-aligned, no overlaps |
| `scene.json` | `Scene` | `room_spec.json` + `layout.json` + catalog items + `camera_pose.json` |
| `camera_pose.json` | `CameraPose` | The pose of `photo-1.jpg`; `photo_key` is the path from the repo root |
| `stream_events.json` | `{"first_run": StreamEvent[], "resumed_run": StreamEvent[]}` | The design run up to the `confirm_room` interrupt, then the run resumed with `room_spec.json` |
| `chat.json` | list of `{input: ChatMessage, edits: ChatEdit[] (attempted), events: StreamEvent[], output: RunOutput}` | Chat turns in order; each `output.layout` applies to the previous one. `small-bedroom` has a refused edit (a `tool` event with `ok: false`, empty `layout_diff`, no layout) |

`negative/` holds data that is schema-valid but must be rejected or handled downstream:

- `invalid_scene_graph.json` (`SceneGraph`): a duplicate node id (`desk`), a cycle (`desk_chair` in front of `desk`, `desk` behind `desk_chair`), `against_wall` pointing at a non-wall, and an edge from an unknown node (`lamp`).
- `impossible_brief.json` (`Brief`): use with `small-bedroom/room_spec.json`; the must-haves fit neither the room nor the budget.
- `wrong_dimensions.json` (`RunInput`, a new design): the `small-bedroom` photos with typed dimensions of 6.4 x 1.7 m instead of 3.2 x 3.4 m, for the depth cross-check.

## Photos are placeholders

There are no real room photos yet. Each `photo-*.jpg` is a 640 x 480 synthetic image (an empty room drawn with Pillow and labeled PLACEHOLDER), so detection, depth and camera matching produce nothing meaningful on them. Replace them with real photos of matching rooms (same file names, max ~300 KB each), then update `room_spec.json` and `camera_pose.json` (`image_width`, `image_height`, the pose) to match.
