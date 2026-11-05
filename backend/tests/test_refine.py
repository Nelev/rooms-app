"""The Refiner: it orders ambiguous siblings, keeps the graph acyclic and B-07 valid, and leaves the fixture graphs as they are."""

from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.geometry.graph_validate import validate_graph
from app.graph import stub
from app.graph.graph import build_graph, serde
from app.graph.nodes.refine import refine_graph
from app.graph.stub import fixture
from app.schemas import SceneGraph
from app.schemas.design import SceneEdge, SceneNode
from tests.test_api import design_input
from tests.test_fixtures import CASES, FIXTURES, case, load

AMBIGUOUS = load(FIXTURES / "negative" / "ambiguous_scene_graph.json", SceneGraph)
LIVING_ROOM = case("living-room")["room_spec"]


def edges(*triples: tuple[str, str, str]) -> list[SceneEdge]:
    return [SceneEdge(source=s, relation=r, target=t) for s, r, t in triples]  # type: ignore[arg-type]


def with_edges(*triples: tuple[str, str, str]) -> SceneGraph:
    return AMBIGUOUS.model_copy(update={"edges": [*AMBIGUOUS.edges, *edges(*triples)]})


def test_the_ambiguous_fixture_gets_ordered_and_still_passes_b07() -> None:
    assert validate_graph(AMBIGUOUS, LIVING_ROOM).issues == []
    refined = refine_graph(AMBIGUOUS)
    assert refined.edges == [
        *AMBIGUOUS.edges,
        *edges(("desk_lamp", "right_of", "monitor"), ("plant", "right_of", "desk_lamp"), ("chair_2", "right_of", "chair_1")),
    ]
    assert validate_graph(refined, LIVING_ROOM).issues == []
    assert refine_graph(refined) == refined  # a second round (after the critic) adds nothing


@pytest.mark.parametrize("name", CASES)
def test_fixture_graphs_have_no_ambiguous_siblings(name: str) -> None:
    graph = case(name)["scene_graph"]
    assert refine_graph(graph) == graph


def test_an_ordering_edge_that_closes_a_loop_is_dropped() -> None:
    # monitor already sits right of plant: plant right_of desk_lamp would close desk_lamp -> monitor -> plant -> desk_lamp
    graph = with_edges(("monitor", "right_of", "plant"))
    refined = refine_graph(graph)
    assert refined.edges == [*graph.edges, *edges(("desk_lamp", "right_of", "monitor"), ("chair_2", "right_of", "chair_1"))]
    assert not [i for i in validate_graph(refined, LIVING_ROOM).issues if i.code == "cycle"]


@pytest.mark.parametrize("relation", ["left_of", "right_of", "behind"])
@pytest.mark.parametrize("source,target", [("chair_1", "chair_2"), ("chair_2", "chair_1")])
def test_an_existing_relation_between_siblings_is_kept(source: str, target: str, relation: str) -> None:
    graph = with_edges((source, relation, target))  # no contradicting chair_2 right_of chair_1 is added
    assert [e for e in refine_graph(graph).edges if {e.source, e.target} == {"chair_1", "chair_2"}] == edges((source, relation, target))


def test_facing_and_adjacent_children_are_not_siblings() -> None:
    graph = SceneGraph(
        nodes=AMBIGUOUS.nodes,
        edges=edges(
            ("monitor", "facing", "chair_1"),
            ("plant", "facing", "chair_1"),
            *[("chair_1", "adjacent", "table"), ("chair_2", "adjacent", "table")],
        ),
    )
    assert refine_graph(graph) == graph


@pytest.mark.parametrize("relation,parent", [("against_wall", "wall_A"), ("in_corner", "wall_C"), ("left_of", "door_1")])
def test_children_of_walls_doors_and_windows_are_not_ordered(relation: str, parent: str) -> None:
    door = SceneNode(id="door_1", kind="door", name="door")
    graph = SceneGraph(
        nodes=[*AMBIGUOUS.nodes, door],
        edges=edges(("chair_1", relation, parent), ("chair_2", relation, parent)),
    )
    assert refine_graph(graph) == graph


def test_a_sibling_with_copies_is_not_ordered() -> None:
    # two chairs right_of a single chair would be too_small for B-07 (it lines copies up along chair_1's 0.5 m depth)
    nodes = [n.model_copy(update={"quantity": 2}) if n.id == "chair_2" else n for n in AMBIGUOUS.nodes]
    graph = AMBIGUOUS.model_copy(update={"nodes": nodes})
    refined = refine_graph(graph)
    assert refined.edges == [*graph.edges, *edges(("desk_lamp", "right_of", "monitor"), ("plant", "right_of", "desk_lamp"))]
    assert validate_graph(refined, LIVING_ROOM) == validate_graph(graph, LIVING_ROOM)  # no new issues


def test_in_the_graph_the_live_refiner_streams_its_own_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stub, "live", lambda node: node == "refine")  # only the refiner is "real" (its events are its own)
    graph = build_graph(InMemorySaver(serde=serde()))
    config: Any = {"configurable": {"thread_id": "t1"}}
    graph.invoke(design_input(), config)
    chunks = list(graph.stream(Command(resume=fixture("room_spec")), config, stream_mode="custom"))
    steps = [(c["status"], c["round"], c.get("summary")) for c in chunks if c.get("node") == "refine"]
    assert steps == [("started", 1, None), ("done", 1, "no ambiguous siblings"), ("started", 2, None), ("done", 2, "no ambiguous siblings")]
