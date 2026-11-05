"""The Designer node, offline: the fake model stands in for get_llm. test_live_design runs it on the real model."""

from collections.abc import Callable
from pathlib import Path

import pytest
from dataset import load_cases
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import TypeAdapter

from app import llm
from app.graph import stub
from app.graph.graph import build_graph, serde
from app.graph.nodes import design as node
from app.graph.stub import CASE, fixture
from app.llm.fake import CALL_USAGE, FakeLLM
from app.schemas import Brief, DesignBrief, RoomSpec, coords
from app.schemas.design import DESIGN_BRIEF_EXAMPLE
from tests.test_api import design_input, one_round, stub_cost

FIXTURES = CASE.parent
CASES = sorted(p.name for p in FIXTURES.iterdir() if (p / "brief.json").is_file())
SMALL_ROOM = RoomSpec.model_validate_json((FIXTURES / "small-bedroom" / "room_spec.json").read_bytes())
BIG_ROOM = RoomSpec.model_validate_json((FIXTURES / "living-room" / "room_spec.json").read_bytes())
EXAMPLE = DesignBrief.model_validate(DESIGN_BRIEF_EXAMPLE)
NICE_ONLY = EXAMPLE.model_copy(update={"objects": [o for o in EXAMPLE.objects if o.priority == "nice"]})  # no must-have at all


def read[T](path: Path, type_: type[T]) -> T:
    return TypeAdapter(type_).validate_json(path.read_bytes())


def briefs() -> list[tuple[str, Brief, RoomSpec]]:
    """Every fixture brief with its room: the fixture cases, the impossible brief (in the small bedroom) and the eval dataset."""
    fixtures = [(c, read(FIXTURES / c / "brief.json", Brief), read(FIXTURES / c / "room_spec.json", RoomSpec)) for c in CASES]
    impossible = ("impossible", read(FIXTURES / "negative" / "impossible_brief.json", Brief), SMALL_ROOM)
    return [*fixtures, impossible, *((name, c.brief, c.room_spec) for name, c in load_cases().items())]


BRIEFS = briefs()


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeLLM]:
    def install(*replies: str) -> FakeLLM:
        fake = FakeLLM(*replies)
        monkeypatch.setattr(llm, "get_llm", lambda role: fake)
        return fake

    return install


def coverage(design: DesignBrief, brief: Brief) -> float:
    """The share of the brief's must-haves a must object is named after, checked independently of node.covers."""
    names = [o.name.lower() for o in design.objects if o.priority == "must"]
    return sum(any(m.lower() in n for n in names) for m in brief.must_haves) / max(1, len(brief.must_haves))


@pytest.mark.parametrize(("name", "brief", "room"), BRIEFS, ids=[b[0] for b in BRIEFS])
@pytest.mark.parametrize("reply", [NICE_ONLY, EXAMPLE], ids=["nice-only", "example"])
def test_every_must_have_is_in_the_design(
    fake_llm: Callable[..., FakeLLM], name: str, brief: Brief, room: RoomSpec, reply: DesignBrief
) -> None:
    fake_llm(reply.model_dump_json())
    design, usage = node.plan(brief, room)
    assert coverage(design, brief) == 1 and usage == CALL_USAGE
    assert len({o.id for o in design.objects}) == len(design.objects)
    fits = node.footprint(design.objects) <= node.limits(room)[1] and sum(o.quantity for o in design.objects) <= node.limits(room)[2]
    assert fits or all(any(node.covers(o, m) for m in brief.must_haves) for o in design.objects)  # or the must-haves alone overfill it


@pytest.mark.parametrize("case", CASES)
def test_the_fixture_designs_cover_their_briefs_and_fit_their_rooms_unchanged(case: str) -> None:
    design, brief = read(FIXTURES / case / "design_brief.json", DesignBrief), read(FIXTURES / case / "brief.json", Brief)
    assert node.fit(node.add_must_haves(design, brief), brief, read(FIXTURES / case / "room_spec.json", RoomSpec)) == design
    assert coverage(design, brief) == 1


def test_a_missing_must_have_is_added_with_its_category_and_a_nice_one_is_promoted() -> None:
    brief = Brief(
        room_use="bedroom", styles=["japandi"], budget=1000, must_haves=["nightstand", "desk chair", "upright piano", "Nightstand"]
    )
    design = node.add_must_haves(NICE_ONLY, brief)
    nightstand, chair, piano = design.objects
    assert (nightstand.id, nightstand.priority, nightstand.quantity) == ("nightstand", "must", 2)  # promoted, not added twice
    assert (chair.id, chair.category, chair.style, chair.priority) == ("desk_chair", "chair", "japandi", "must")
    assert (chair.material, chair.zone, piano.zone) == ("oak", "work", None)  # the design's material; the zone mentioning a desk
    assert (piano.category, piano.priority, piano.size) == ("other", "must", node.OTHER_SIZE)
    zoned = node.add_must_haves(EXAMPLE, Brief(room_use="bedroom", budget=1000, must_haves=["desk"]))
    assert zoned.objects[-1].zone == "work"  # the zone whose purpose mentions it


def test_near_miss_names_do_not_count_as_must_haves() -> None:
    lamp = EXAMPLE.objects[0].model_copy(update={"id": "lamp", "name": "desk lamp", "category": "lamp", "priority": "nice"})
    brief = Brief(room_use="office", budget=1000, must_haves=["desk", "armchair", "bedside table"])
    design = node.add_must_haves(EXAMPLE.model_copy(update={"objects": [lamp]}), brief)
    assert design.objects[0] == lamp  # not promoted: a desk lamp is no desk
    assert [(o.name, o.category, o.priority) for o in design.objects[1:]] == [
        ("desk", "desk", "must"),
        ("armchair", "armchair", "must"),
        ("bedside table", "table", "must"),
    ]
    assert [node.category_of(n) for n in ("bookshelf", "dining table for six", "tv stand", "upright piano")] == [
        "shelf",
        "table",
        "tv_stand",
        "other",
    ]


def test_object_count_scales_with_the_floor_area() -> None:
    nightstands = EXAMPLE.objects[1].model_copy(update={"quantity": 12})
    crowded = EXAMPLE.model_copy(update={"objects": [*EXAMPLE.objects, nightstands]})
    brief = Brief(room_use="bedroom", budget=1000, must_haves=["double bed"])
    small, big = node.fit(crowded, brief, SMALL_ROOM), node.fit(crowded, brief, BIG_ROOM)
    count = lambda d: sum(o.quantity for o in d.objects)  # noqa: E731
    assert count(small) <= node.limits(SMALL_ROOM)[2] < count(big) <= node.limits(BIG_ROOM)[2] < count(crowded)
    assert crowded.objects[0] in small.objects  # the must-have stays
    assert node.footprint(small.objects) <= node.limits(SMALL_ROOM)[1]


def test_the_brief_must_haves_stay_when_they_overfill_the_room() -> None:
    bed = EXAMPLE.objects[0].model_copy(update={"quantity": 9})
    desk = bed.model_copy(update={"id": "desk", "name": "desk", "quantity": 1})  # a must the model added, no must-have of the brief
    brief = Brief(room_use="bedroom", budget=1000, must_haves=["double bed"])
    design = node.fit(EXAMPLE.model_copy(update={"objects": [bed, desk, EXAMPLE.objects[1]]}), brief, SMALL_ROOM)
    assert design.objects == [bed]


def test_the_node_designs_with_the_model_once_a_key_is_set(fake_llm: Callable[..., FakeLLM], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    fake = fake_llm(NICE_ONLY.model_dump_json())
    monkeypatch.setattr(stub, "live", lambda node: node == "design")  # only the designer is real
    graph, config = build_graph(InMemorySaver(serde=serde())), {"configurable": {"thread_id": "t1"}}
    graph.invoke(design_input(), config)
    graph.invoke(Command(resume=fixture("room_spec")), config)
    values = graph.get_state(config).values
    brief, room = Brief.model_validate(fixture("brief")), RoomSpec.model_validate(fixture("room_spec"))
    assert values["design_brief"] == node.fit(node.add_must_haves(NICE_ONLY, brief), brief, room)
    assert fake.calls == 1 and values["input_tokens"] == CALL_USAGE["input_tokens"]  # the other nodes are stubs: no model tokens
    text = str(fake.prompts[0][0].content)
    assert brief.model_dump_json() in text and room.model_dump_json() in text and coords.__doc__ and coords.__doc__ in text
    design_cost = next(e["cost"] for e in fixture("stream_events")["resumed_run"] if e.get("node") == "design" and "cost" in e)
    fixture_cost = stub_cost(fixture("stream_events")["first_run"] + one_round(fixture("stream_events")["resumed_run"]))
    assert values["cost"] == pytest.approx(fixture_cost - design_cost + CALL_USAGE["cost"])  # the model call's cost, not the fixture's


@pytest.mark.live
@pytest.mark.parametrize("case", CASES)
def test_live_design(case: str) -> None:
    brief, room = read(FIXTURES / case / "brief.json", Brief), read(FIXTURES / case / "room_spec.json", RoomSpec)
    llm.get_llm.cache_clear()
    design, usage = node.plan(brief, room)
    assert coverage(design, brief) == 1 and node.footprint(design.objects) <= node.limits(room)[1]
    assert design.zones and design.palette and usage["cost"] > 0
