"""Every file in fixtures/ validates against the domain schemas, and each case is consistent and geometrically plausible."""

from itertools import combinations
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter

from app.schemas import Brief, CameraPose, ChatEdit, DesignBrief, Layout, RoomSpec, RunInput, RunOutput, Scene, SceneGraph, StreamEvent
from app.schemas.base import Model
from app.schemas.layout import Placement
from app.schemas.room import KeptItem
from app.schemas.run import ChatMessage, NewDesign

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
CASES = ["small-bedroom", "home-office", "living-room"]


class ChatTurn(Model):
    """One chat exchange: the message, the edits chat_edit attempted, the events it streamed and what the run left."""

    input: ChatMessage
    edits: list[ChatEdit]
    events: list[StreamEvent]
    output: RunOutput


# file name -> type, per case and in negative/
CASE_FILES: dict[str, Any] = {
    "room_spec.json": RoomSpec,
    "brief.json": Brief,
    "design_brief.json": DesignBrief,
    "scene_graph.json": SceneGraph,
    "layout.json": Layout,
    "scene.json": Scene,
    "camera_pose.json": CameraPose,
    "stream_events.json": dict[str, list[StreamEvent]],
    "chat.json": list[ChatTurn],
}
NEGATIVE_FILES: dict[str, Any] = {
    "invalid_scene_graph.json": SceneGraph,
    "impossible_brief.json": Brief,
    "wrong_dimensions.json": RunInput,
}


def load(path: Path, type_: Any) -> Any:
    return TypeAdapter(type_).validate_json(path.read_bytes())


def case(name: str) -> dict[str, Any]:
    return {f.removesuffix(".json"): load(FIXTURES / name / f, t) for f, t in CASE_FILES.items()}


def test_every_fixture_file_is_covered() -> None:
    expected = {f"{c}/{f}" for c in CASES for f in CASE_FILES} | {f"negative/{f}" for f in NEGATIVE_FILES}
    assert {str(p.relative_to(FIXTURES)) for p in FIXTURES.rglob("*.json")} == expected


@pytest.mark.parametrize("name", NEGATIVE_FILES)
def test_negative_fixtures_are_schema_valid(name: str) -> None:
    load(FIXTURES / "negative" / name, NEGATIVE_FILES[name])


def test_invalid_scene_graph_has_its_defects() -> None:
    graph = load(FIXTURES / "negative" / "invalid_scene_graph.json", SceneGraph)
    ids = [n.id for n in graph.nodes]
    kinds = {n.id: n.kind for n in graph.nodes}
    pairs = {(e.source, e.target) for e in graph.edges}
    assert len(ids) > len(set(ids)), "duplicate node id"
    assert any((t, s) in pairs for s, t in pairs), "cycle"
    assert any(e.relation == "against_wall" and kinds.get(e.target) != "wall" for e in graph.edges), "against_wall to a non-wall"
    assert any(e.source not in kinds for e in graph.edges), "edge from an unknown node"


def test_impossible_brief_exceeds_the_small_bedroom() -> None:
    brief = load(FIXTURES / "negative" / "impossible_brief.json", Brief)
    feasible = load(FIXTURES / "small-bedroom" / "brief.json", Brief)
    assert brief.budget < feasible.budget and len(brief.must_haves) > len(feasible.must_haves)


def test_wrong_dimensions_mismatch_the_small_bedroom_photos() -> None:
    run = load(FIXTURES / "negative" / "wrong_dimensions.json", RunInput)
    room = load(FIXTURES / "small-bedroom" / "room_spec.json", RoomSpec)
    assert isinstance(run, NewDesign)
    assert run.photo_keys == sorted(str(p.relative_to(FIXTURES.parent)) for p in (FIXTURES / "small-bedroom").glob("photo-*.jpg"))
    assert run.dimensions != room.dimensions


def footprint(o: Placement | KeptItem) -> tuple[float, float, float, float]:
    assert o.rotation % 90 == 0, "fixtures keep items axis-aligned"
    w, d = (o.size.width, o.size.depth) if o.rotation % 180 == 0 else (o.size.depth, o.size.width)
    return o.x - w / 2, o.y - d / 2, o.x + w / 2, o.y + d / 2


def boxes(room: RoomSpec, layout: Layout) -> dict[str, tuple[float, float, float, float]]:
    return {p.node_id: footprint(p) for p in layout.placements} | {k.id: footprint(k) for k in room.kept_furniture}


def assert_plausible(room: RoomSpec, layout: Layout, eps: float = 1e-9) -> None:
    """Every item inside the room, and no two items (kept furniture included) overlap."""
    footprints = boxes(room, layout)
    for id_, (x0, y0, x1, y1) in footprints.items():
        assert x0 >= -eps and y0 >= -eps and x1 <= room.dimensions.width + eps and y1 <= room.dimensions.length + eps, id_
    for (a, (ax0, ay0, ax1, ay1)), (b, (bx0, by0, bx1, by1)) in combinations(footprints.items(), 2):
        assert min(ax1, bx1) - max(ax0, bx0) <= eps or min(ay1, by1) - max(ay0, by0) <= eps, f"{a} overlaps {b}"


@pytest.mark.parametrize("name", CASES)
def test_case_is_consistent(name: str) -> None:
    c = case(name)
    room, layout, scene, graph = c["room_spec"], c["layout"], c["scene"], c["scene_graph"]

    objects = {n.id for n in graph.nodes if n.kind == "object"}
    fixed = {n.id for n in graph.nodes} - objects
    assert objects == {o.id for o in c["design_brief"].objects} == {p.node_id for p in layout.placements}
    assert fixed <= {f.id for f in room.features} | {f"wall_{w}" for w in "ABCD"}
    assert all({e.source, e.target} <= objects | fixed for e in graph.edges)

    assert scene.room == room
    assert [i.model_dump(exclude={"item"}) for i in scene.items] == [p.model_dump() for p in layout.placements]
    assert all(i.item and i.item.id == i.item_id and i.item.size == i.size for i in scene.items)
    assert scene.cameras == [c["camera_pose"]]
    assert c["camera_pose"].photo_key and (FIXTURES.parent / c["camera_pose"].photo_key).is_file()
    assert 1 <= len(list((FIXTURES / name).glob("photo-*.jpg"))) <= 2

    assert list(c["stream_events"]) == ["first_run", "resumed_run"]
    cam_x, _, cam_z = c["camera_pose"].position  # three.js (x, z, -y), see coords.py
    assert not any(x0 < cam_x < x1 and y0 < -cam_z < y1 for x0, y0, x1, y1 in boxes(room, layout).values())

    assert_plausible(room, layout)
    before = {p.node_id: p for p in layout.placements}
    for turn in c["chat"]:
        if turn.output.layout:
            assert_plausible(room, turn.output.layout)
            after = {p.node_id: p for p in turn.output.layout.placements}
            diff = turn.output.layout_diff
            assert diff and set(diff.added) == after.keys() - before.keys()
            assert set(diff.removed) == before.keys() - after.keys()
            assert set(diff.changed) == {k for k in before.keys() & after.keys() if before[k] != after[k]}
            before = after


def test_chat_fixtures_include_a_refused_edit() -> None:
    turns = [t for name in CASES for t in case(name)["chat"]]
    assert any(not e.ok for t in turns for e in t.events if e.type == "tool")
