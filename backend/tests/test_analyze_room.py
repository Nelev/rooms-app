"""The Room Analyst, offline: the fake model replies readings of the E-01 cases' labeled rooms. The live test reads the real photos."""

import os
from collections.abc import Callable
from typing import Any

import pytest
from dataset import load_cases
from langgraph.checkpoint.memory import InMemorySaver

from app import llm
from app.graph.graph import build_graph, serde
from app.graph.nodes.analyze_room import RUNS, Estimate, RoomReading, SeenFeature, WallReading, analyze, feature_scores, image_urls
from app.llm.fake import CALL_USAGE, FakeLLM
from app.schemas import RoomSpec
from app.schemas.room import Feature
from tests.test_api import design_input

CASES = {name: case for name, case in load_cases().items() if case.photos_match_room}  # the cases photo analysis is scored on
LABEL = CASES["bedroom-calm"].room_spec  # a door on wall A, a window and a radiator on wall C
PHOTOS = ["data:image/jpeg;base64,AAAA"]
SPURIOUS = Feature(id="window_9", type="window", wall="B", offset=0.5, width=1, height=1)


def reading(room: RoomSpec, *extra: Feature, without: str = "") -> str:
    """The model's reply reading `room`, with `extra` features and without the feature `without`."""
    features = [f for f in [*room.features, *extra] if f.id != without]

    def seen(f: Feature) -> SeenFeature:
        estimates = {name: Estimate(value=getattr(f, name), confidence=0.9) for name in ("offset", "width", "height", "sill_height")}
        return SeenFeature(type=f.type, swing=f.swing, hinge=f.hinge, confidence=0.9, **estimates)

    colors = {w.wall: w.color for w in room.walls}
    walls = [WallReading(wall=w, color=colors.get(w), features=[seen(f) for f in features if f.wall == w]) for w in "ABCD"]
    return RoomReading(walls=walls, floor_material=room.floor_material, notes=[]).model_dump_json()


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeLLM]:
    def install(*replies: str) -> FakeLLM:
        fake = FakeLLM(*replies)
        monkeypatch.setattr(llm, "get_llm", lambda role: fake)
        return fake

    return install


def test_feature_precision_and_recall_on_the_e01_cases(fake_llm: Callable[..., FakeLLM]) -> None:
    """The scoring the Done-when asks for, on fake replies: with real ones (OPENROUTER_API_KEY), see test_live_feature_scores."""
    rooms = []
    for case in CASES.values():
        fake = fake_llm(*[reading(case.room_spec)] * RUNS)
        room, usage = analyze(case.dimensions, PHOTOS)
        assert fake.calls == RUNS and usage == {k: v * RUNS for k, v in CALL_USAGE.items()}
        assert room.dimensions == case.dimensions  # the typed dimensions win, even wrong ones (hard-wrong-dimensions)
        assert room.walls == case.room_spec.walls and room.floor_material == case.room_spec.floor_material
        rooms.append((room, case.room_spec))
    types = {f.type for case in CASES.values() for f in case.room_spec.features}
    assert feature_scores(rooms) == dict.fromkeys(["all", *types], (1.0, 1.0))

    missed = LABEL.model_copy(update={"features": LABEL.features[:1]})  # only the door found
    found_twice = LABEL.model_copy(update={"features": [*LABEL.features, SPURIOUS]})
    assert feature_scores([(missed, LABEL), (found_twice, LABEL)]) == {
        "all": (4 / 5, 4 / 6),
        "door": (1.0, 1.0),
        "radiator": (1.0, 1 / 2),
        "window": (1 / 2, 1 / 2),
    }


def test_the_vote_keeps_features_found_in_two_of_three_runs(fake_llm: Callable[..., FakeLLM]) -> None:
    moved = LABEL.model_copy(update={"features": [f.model_copy(update={"offset": f.offset + 0.05}) for f in LABEL.features]})
    fake_llm(reading(LABEL, SPURIOUS), reading(moved, without="radiator_1"), reading(LABEL))
    room, _ = analyze(LABEL.dimensions, PHOTOS)
    assert [(f.id, f.wall) for f in room.features] == [("door_1", "A"), ("window_1", "C"), ("radiator_1", "C")]  # no spurious window
    assert [f.offset for f in room.features] == [f.offset for f in LABEL.features]  # the median of the runs
    assert room.features[2].confidence == pytest.approx(0.9 * 2 / 3)  # found in 2 of 3 runs
    assert room.warnings == ["1 feature(s) seen in fewer than 2 of 3 readings of the photos were left out"]

    fake_llm(reading(LABEL, SPURIOUS))  # a single reading (analyst_mode) keeps everything it sees
    room, _ = analyze(LABEL.dimensions, PHOTOS, runs=1)
    assert feature_scores([(room, LABEL)])["all"] == (3 / 4, 1.0)


def test_unknown_values_take_the_type_default_with_a_warning(fake_llm: Callable[..., FakeLLM]) -> None:
    known, unknown = Estimate(value=0.3, confidence=0.8), Estimate(value=None, confidence=0)
    door = SeenFeature(type="door", offset=known, width=unknown, height=known, sill_height=known, swing="in", confidence=0.9)
    outlet = door.model_copy(update={"type": "outlet"})  # a swing on a non-door is dropped
    walls = [
        WallReading(wall="A", color=None, features=[door, outlet]),
        *(WallReading(wall=w, color="#ffffff", features=[]) for w in "BCD"),
    ]
    fake_llm(RoomReading(walls=walls, floor_material=None, notes=["Wall A is dark"]).model_dump_json())
    room, _ = analyze(LABEL.dimensions, PHOTOS, runs=1)
    assert [(f.id, f.width, f.swing, f.confidence) for f in room.features] == [("door_1", 0.8, "in", 0.8), ("outlet_1", 0.08, None, 0.8)]
    assert [w.color for w in room.walls] == [None, "#ffffff", "#ffffff", "#ffffff"] and room.floor_material is None
    assert room.warnings == [
        "The width of the door on wall A is unknown: assumed 0.8",
        "The width of the outlet on wall A is unknown: assumed 0.08",
        "Wall A is dark",
    ]


def test_the_prompt_holds_the_typed_dimensions_photos_and_overlays(fake_llm: Callable[..., FakeLLM]) -> None:
    fake = fake_llm(reading(LABEL))
    analyze(LABEL.dimensions, PHOTOS, overlays=["data:image/png;base64,BBBB"], runs=1)
    text, *images = fake.prompts[0][0].content
    assert isinstance(text, dict) and "walls A and C are 3.2 m long, walls B and D are 3.4 m long" in text["text"]
    assert "1 detection overlay(s)" in text["text"]
    assert [i["image_url"]["url"] for i in images] == [*PHOTOS, "data:image/png;base64,BBBB"]


@pytest.mark.parametrize(("analyst_mode", "calls"), [(False, RUNS), (True, 1)])
def test_the_node_streams_its_step_and_adds_its_usage(
    fake_llm: Callable[..., FakeLLM], monkeypatch: pytest.MonkeyPatch, analyst_mode: bool, calls: int
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")  # the real node, on the fake model
    fake = fake_llm(*[reading(LABEL)] * calls)
    graph = build_graph(InMemorySaver(serde=serde()))
    config: Any = {"configurable": {"thread_id": "t1", "analyst_mode": analyst_mode}}
    parts = list(graph.stream(design_input(), config, stream_mode=["custom", "messages"]))
    events = [data for mode, data in parts if mode == "custom" and data.get("node") == "analyze_room"]
    started, done = events
    assert started == {"type": "step", "node": "analyze_room", "status": "started"}
    assert done["summary"] == "found 1 door, 1 window, 1 radiator" and done["cost"] == pytest.approx(CALL_USAGE["cost"] * calls)
    assert sum(mode == "messages" and data[1]["langgraph_node"] == "analyze_room" for mode, data in parts) == calls
    assert fake.calls == calls and fake.prompts[0][0].content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    state = graph.get_state(config)
    assert [f.model_dump(exclude={"confidence"}) for f in state.values["room_spec"].features] == [
        f.model_dump(exclude={"confidence"}) for f in LABEL.features
    ]
    assert state.next == ("confirm_room",)


def test_image_urls_reads_fixture_photos_only() -> None:
    assert image_urls(design_input()["photo_keys"])[0].startswith("data:image/jpeg;base64,/9j/")  # a JPEG
    for key in ("../../etc/x.jpg", "backend/x.jpg"):
        with pytest.raises(ValueError, match="outside fixtures/"):
            image_urls([key])
    with pytest.raises(ValueError, match="not an image"):
        image_urls(["backend/pyproject.toml"])


@pytest.mark.skipif(not os.environ.get("OPENROUTER_API_KEY"), reason="needs OPENROUTER_API_KEY: calls the real vision model")
def test_live_feature_scores() -> None:
    """Feature precision and recall of the real model on the E-01 cases (run with -s to see them); one analysis per photo set."""
    rooms: dict[tuple[str, ...], RoomSpec] = {}
    for case in CASES.values():
        key = (*case.photo_keys, case.dimensions.model_dump_json())
        if key not in rooms:
            rooms[key], _ = analyze(case.dimensions, image_urls(case.photo_keys))
    scores = feature_scores((rooms[(*c.photo_keys, c.dimensions.model_dump_json())], c.room_spec) for c in CASES.values())
    for type_, (precision, recall) in scores.items():
        print(f"{type_:>10}: precision {precision:.2f}, recall {recall:.2f}")
    assert "all" in scores
