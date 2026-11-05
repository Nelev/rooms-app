"""The Sourcer, offline: the catalog in an in-memory store with fake embeddings, on each fixture case."""

import asyncio
from typing import Any

import pytest
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from pydantic import TypeAdapter

from app.catalog.embed import index_config, seed
from app.catalog.loader import load_catalog
from app.graph.nodes.source import footprint, source_scene
from app.graph.state import RunState
from app.graph.stub import CASE
from app.schemas import Brief, Critique, DesignBrief, SceneGraph
from app.schemas.coords import Size
from app.schemas.layout import CritiqueAction
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


def test_a_stale_or_impossible_swap_keeps_the_item(store: BaseStore) -> None:
    state = case_state("small-bedroom")
    first = source_scene(store, state)
    assert swap(store, state, first, "desk", "cheaper desk", round_=2)["scene_graph"] == first["scene_graph"]  # an earlier run's
    assert swap(None, state, first, "desk", "cheaper desk")["scene_graph"] == first["scene_graph"]  # no store: no other desk
