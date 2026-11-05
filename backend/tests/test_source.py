"""The Sourcer, offline: the catalog in an in-memory store with fake embeddings, on each fixture case."""

import asyncio
import json
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command
from pydantic import TypeAdapter

from app import llm
from app.catalog.embed import index_config, seed
from app.catalog.loader import load_catalog
from app.graph import stub
from app.graph.graph import build_graph, serde
from app.graph.nodes.analyze_room import RUNS
from app.graph.nodes.critic import judge
from app.graph.nodes.solve import solve_scene
from app.graph.nodes.source import footprint, source_scene, swap_rule, within
from app.graph.routing import keep_best
from app.graph.state import RunState
from app.graph.stub import CASE
from app.llm.fake import CALL_USAGE, FakeLLM
from app.schemas import Brief, Critique, DesignBrief, RoomSpec, SceneGraph
from app.schemas.coords import Size
from app.schemas.layout import CritiqueAction
from tests.test_analyze_room import LABEL, reading
from tests.test_api import design_input
from tests.test_architect import EDGES, edges
from tests.test_catalog_search import FakeEmbeddings

CASES = ["small-bedroom", "home-office", "living-room"]


@pytest.fixture(scope="module")
def store() -> BaseStore:
    store = InMemoryStore(index=index_config(FakeEmbeddings()))
    asyncio.run(seed(store))
    return store


def case_state(case: str) -> RunState:
    """The case's run state at the Sourcer, its scene graph without items: as the Architect leaves it."""

    def load[T](name: str, type_: type[T]) -> T:
        return TypeAdapter(type_).validate_json((CASE.parent / case / f"{name}.json").read_bytes())

    graph = load("scene_graph", SceneGraph)
    graph = graph.model_copy(update={"nodes": [n.model_copy(update={"item_id": None}) for n in graph.nodes]})
    return {"brief": load("brief", Brief), "design_brief": load("design_brief", DesignBrief), "scene_graph": graph, "round": 1}


def total(graph: SceneGraph) -> float:
    catalog = load_catalog()
    return sum(catalog[n.item_id].price * n.quantity for n in graph.nodes if n.item_id)


def check(state: RunState, out: dict[str, Any]) -> SceneGraph:
    """Within budget, every sourced size its item's, the chosen item first in the candidates."""
    graph: SceneGraph = out["scene_graph"]
    catalog = load_catalog()
    assert total(graph) <= state["brief"].budget
    for node in graph.nodes:
        if node.item_id:
            assert node.size == catalog[node.item_id].size
            assert out["candidates"][node.id][0].id == node.item_id
    return graph


@pytest.mark.parametrize("case", CASES)
def test_every_object_gets_an_item_within_budget(store: BaseStore, case: str) -> None:
    state = case_state(case)
    out = source_scene(store, state)
    graph = check(state, out)
    objects = {o.id: o for o in state["design_brief"].objects}
    assert all(n.item_id for n in graph.nodes if n.id in objects)
    assert all(load_catalog()[n.item_id].category == objects[n.id].category for n in graph.nodes if n.item_id)
    assert any(len(c) > 1 for c in out["candidates"].values())  # alternatives for the results view
    assert graph.edges == state["scene_graph"].edges


@pytest.mark.parametrize("budget", [0, 150, 400])
def test_a_tight_budget_is_never_exceeded(store: BaseStore, budget: float) -> None:
    state = case_state("living-room")
    state["brief"] = state["brief"].model_copy(update={"budget": budget})
    graph = check(state, source_scene(store, state))
    if budget == 0:  # nothing affordable: the objects stay boxes
        assert not any(n.item_id for n in graph.nodes) and graph == state["scene_graph"]


def test_kept_items_are_charged_and_not_searched_again() -> None:
    state = case_state("small-bedroom")
    state["scene_graph"] = TypeAdapter(SceneGraph).validate_json((CASE / "scene_graph.json").read_bytes())  # every object has its item
    out = source_scene(None, state)  # no store: nothing is searched
    assert out["scene_graph"] == state["scene_graph"]
    assert {k: [i.id for i in v] for k, v in out["candidates"].items()} == {
        n.id: [n.item_id] for n in state["scene_graph"].nodes if n.item_id
    }


def test_a_kept_item_sets_its_size() -> None:
    state = case_state("small-bedroom")
    graph = TypeAdapter(SceneGraph).validate_json((CASE / "scene_graph.json").read_bytes())
    wrong = Size(width=2.5, depth=2.5, height=2.5)  # a box that is not its item's
    nodes = [n.model_copy(update={"size": wrong}) if n.id == "bed" else n for n in graph.nodes]
    state["scene_graph"] = graph.model_copy(update={"nodes": nodes})
    out = source_scene(None, state)
    check(state, out)
    assert next(n for n in out["scene_graph"].nodes if n.id == "bed").size == load_catalog()["oak-double-bed-140"].size


def swap(store: BaseStore | None, state: RunState, out: dict[str, Any], node_id: str, instruction: str, round_: int = 1) -> dict[str, Any]:
    """Source again after the critic's round `round_` asked for a swap, in round 2."""
    critique = Critique(round=round_, summary="", actions=[CritiqueAction(target="sourcer", node_id=node_id, instruction=instruction)])
    swapped: Any = {**state, **out, "critique": critique, "round": 2}
    return source_scene(store, swapped)


@pytest.mark.parametrize(("node_id", "instruction"), [("desk", "cheaper desk"), ("bed", "smaller bed"), ("desk", "a larger desk")])
def test_swaps_follow_the_instruction(store: BaseStore, node_id: str, instruction: str) -> None:
    state = case_state("small-bedroom")
    first = source_scene(store, state)
    second = swap(store, state, first, node_id, instruction)
    check(state, second)
    catalog = load_catalog()
    old, new = ({n.id: catalog[n.item_id] for n in out["scene_graph"].nodes if n.item_id}[node_id] for out in (first, second))
    assert new != old
    if "cheaper" in instruction:
        assert new.price < old.price
    elif "smaller" in instruction:
        assert footprint(new) < footprint(old)
    else:
        assert footprint(new) > footprint(old)
    unchanged = [n for n in first["scene_graph"].nodes if n.id != node_id]
    assert unchanged == [n for n in second["scene_graph"].nodes if n.id != node_id]


def test_a_shorter_swap_compares_heights() -> None:  # the Critic's ask for an item above the ceiling
    catalog = load_catalog()
    shorter = swap_rule("shorter desk_chair: desk_chair is taller than the 2.5 m ceiling", catalog["mesh-office-chair"])
    assert shorter(catalog["white-desk-chair"]) and not shorter(catalog["mesh-office-chair"])
    assert not swap_rule("shorter", catalog["white-desk-chair"])(catalog["black-desk-chair"])  # a larger footprint but taller


def test_a_stale_or_impossible_swap_keeps_the_item(store: BaseStore) -> None:
    state = case_state("small-bedroom")
    first = source_scene(store, state)
    assert swap(store, state, first, "desk", "cheaper desk", round_=2)["scene_graph"] == first["scene_graph"]  # an earlier run's
    assert swap(None, state, first, "desk", "cheaper desk")["scene_graph"] == first["scene_graph"]  # no store: no other desk


def test_the_critics_swap_is_current_for_the_sourcer_after_it(store: BaseStore) -> None:
    """The staleness check against the critic's own round numbering: its critique, as it leaves it, is the round that just ended."""
    state = case_state("small-bedroom")
    first = source_scene(store, state)
    solved: Any = {**state, **first, "room_spec": stub.load("room_spec", RoomSpec)}
    solved |= solve_scene(solved)
    critique, hard, soft = judge(solved)
    actions = [CritiqueAction(target="sourcer", node_id="desk", instruction="cheaper desk")]
    after: Any = {**solved, **keep_best(solved, critique.model_copy(update={"actions": actions}), hard, soft)}
    desk = {n.id: n.item_id for n in source_scene(store, after)["scene_graph"].nodes}["desk"]
    assert desk != {n.id: n.item_id for n in first["scene_graph"].nodes}["desk"]


def with_box(state: RunState, node_id: str, scale: float) -> RunState:
    """`state` with the node's box scaled in width and depth: no item of its category has that size."""
    nodes = [
        n.model_copy(update={"size": n.size.model_copy(update={"width": n.size.width * scale, "depth": n.size.depth * scale})})
        if n.id == node_id and n.size
        else n
        for n in state["scene_graph"].nodes
    ]
    return {**state, "scene_graph": state["scene_graph"].model_copy(update={"nodes": nodes})}


def test_an_item_of_another_shape_must_fit_in_the_box(store: BaseStore) -> None:
    state = with_box(case_state("small-bedroom"), "bed", 1.6)
    bed = next(n for n in check(state, source_scene(store, state)).nodes if n.id == "bed")
    box = next(n.size for n in state["scene_graph"].nodes if n.id == "bed")
    assert bed.item_id and box and bed.size != box and within(load_catalog()[bed.item_id], box)

    state = with_box(case_state("small-bedroom"), "bed", 0.3)  # smaller than any bed: it stays a box
    assert next(n for n in check(state, source_scene(store, state)).nodes if n.id == "bed").item_id is None


def test_a_live_run_costs_the_models_usage_only(store: BaseStore, monkeypatch: pytest.MonkeyPatch) -> None:
    """With a key every node is live: the Sourcer (no model) adds nothing, its done event says so, and the run's cost is the
    fake model's calls only (the analyst's readings, the designer, the architect), none of the fixture's step costs."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    replies = [*[reading(LABEL)] * RUNS, json.dumps(stub.fixture("design_brief")), edges(*EDGES)]
    fake = FakeLLM(*replies)
    monkeypatch.setattr(llm, "get_llm", lambda role: fake)
    graph, config = build_graph(InMemorySaver(serde=serde()), store), {"configurable": {"thread_id": "t1"}}
    graph.invoke({**design_input(), "brief": Brief.model_validate(stub.fixture("brief"))}, config)
    chunks = list(graph.stream(Command(resume=stub.fixture("room_spec")), config, stream_mode="custom"))
    values = graph.get_state(config).values
    assert fake.calls == RUNS + 2 and values["critique"].summary == "all rules pass"
    assert values["cost"] == pytest.approx(fake.calls * CALL_USAGE["cost"])
    assert values["input_tokens"] == fake.calls * CALL_USAGE["input_tokens"]
    assert [c["cost"] for c in chunks if c.get("node") == "source" and c["status"] == "done"] == [0]
