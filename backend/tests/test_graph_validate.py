"""The scene-graph validator: the fixtures' graphs pass, and each check catches a planted defect."""

from collections.abc import Sequence
from typing import Any

import pytest

from app.geometry.graph_validate import validate_graph
from app.schemas import RoomSpec, SceneGraph
from tests.test_fixtures import CASES, FIXTURES, case, load

BEDROOM = case("small-bedroom")  # bed against wall B, nightstand adjacent bed, desk against wall D, desk_chair in front of desk


def issues(graph: SceneGraph, spec: RoomSpec) -> list[tuple[str, list[str]]]:
    return [(i.code, i.node_ids) for i in validate_graph(graph, spec).issues]


def bedroom(nodes: Sequence[dict[str, Any]] = (), edges: Sequence[dict[str, str]] = (), **sizes: tuple[float, float, float]) -> SceneGraph:
    """The small-bedroom graph plus walls A and C, extra nodes and edges, and some nodes resized to (width, depth, height)."""
    graph = BEDROOM["scene_graph"].model_dump()
    graph["nodes"] += [{"id": w, "kind": "wall", "name": w} for w in ("wall_A", "wall_C")]
    for node in graph["nodes"]:
        if node["id"] in sizes:
            node["size"] = dict(zip(("width", "depth", "height"), sizes[node["id"]], strict=True))
    return SceneGraph.model_validate({"nodes": [*graph["nodes"], *nodes], "edges": [*graph["edges"], *edges]})


def node(id: str, width: float, depth: float, height: float, quantity: int = 1) -> dict[str, Any]:
    return {"id": id, "name": id, "size": {"width": width, "depth": depth, "height": height}, "quantity": quantity}


def edge(source: str, relation: str, target: str) -> dict[str, str]:
    return {"source": source, "relation": relation, "target": target}


@pytest.mark.parametrize("name", CASES)
def test_fixture_graphs_pass(name: str) -> None:
    data = case(name)
    assert issues(data["scene_graph"], data["room_spec"]) == []


def test_invalid_scene_graph_fixture_fails_with_each_planted_defect() -> None:
    graph = load(FIXTURES / "negative" / "invalid_scene_graph.json", SceneGraph)
    assert issues(graph, case("home-office")["room_spec"]) == [
        ("duplicate_node", ["desk"]),
        ("unknown_node", ["lamp"]),
        ("cycle", ["desk", "desk_chair"]),
        ("not_a_wall", ["desk_chair", "desk"]),
    ]


def test_messages_are_short_sentences() -> None:
    graph = load(FIXTURES / "negative" / "invalid_scene_graph.json", SceneGraph)
    messages = [i.message for i in validate_graph(graph, case("home-office")["room_spec"]).issues]
    assert messages[1] == "lamp on desk refers to an unknown node lamp"
    assert all(0 < len(m) <= 120 for m in messages)


def test_fixed_node_missing_from_the_room_is_unknown() -> None:
    graph = bedroom([{"id": "window_9", "kind": "window", "name": "window"}], [edge("desk", "in_front", "window_9")])
    assert issues(graph, BEDROOM["room_spec"]) == [("unknown_node", ["window_9"])]


@pytest.mark.parametrize(
    ("fixed", "relation"),
    [({"id": "radiator_1", "kind": "wall"}, "against_wall"), ({"id": "wall_A", "kind": "door"}, "in_front")],
)
def test_fixed_node_of_the_wrong_kind_is_unknown(fixed: dict[str, str], relation: str) -> None:
    graph = SceneGraph.model_validate(
        {"nodes": [fixed | {"name": "x"}, node("desk", 1.0, 0.5, 0.75)], "edges": [edge("desk", relation, fixed["id"])]}
    )
    assert issues(graph, BEDROOM["room_spec"]) == [("unknown_node", [fixed["id"]])]


def test_cycles_fail_and_chains_pass() -> None:
    chain = bedroom(edges=[edge("bed", "left_of", "desk_chair")])  # bed -> desk_chair -> desk -> wall_D
    assert issues(chain, BEDROOM["room_spec"]) == []
    assert issues(bedroom(edges=[edge("bed", "adjacent", "bed")]), BEDROOM["room_spec"]) == [("cycle", ["bed"])]
    assert issues(bedroom(edges=[edge("bed", "adjacent", "nightstand")]), BEDROOM["room_spec"]) == [("cycle", ["bed", "nightstand"])]


def test_items_facing_each_other_are_not_a_cycle() -> None:
    graph = bedroom(edges=[edge("bed", "facing", "desk_chair"), edge("desk_chair", "facing", "bed")])
    assert issues(graph, BEDROOM["room_spec"]) == []


# pushed_out: room is 3.2 (walls A, C) x 3.4 (walls B, D); desk is 1.0 x 0.5 against wall D, bed 1.4 x 2.0 against wall B


@pytest.mark.parametrize(
    ("graph", "expected"),
    [
        (bedroom(edges=[edge("desk_chair", "behind", "desk")]), [("pushed_out", ["desk_chair", "desk"])]),
        (
            bedroom([node("stool", 0.4, 0.4, 0.5)], [edge("desk", "in_front", "stool")]),
            [("pushed_out", ["stool", "desk"])],
        ),  # read from its other end
        (bedroom([node("rug", 1.3, 1.3, 0.01)], [edge("rug", "in_front", "bed")]), [("pushed_out", ["rug", "bed"])]),
        (bedroom([node("cabinet", 2.5, 2.5, 1.0)], [edge("cabinet", "left_of", "desk")]), [("pushed_out", ["cabinet", "desk"])]),
        (bedroom(bed=(3.5, 2.0, 0.9)), [("pushed_out", ["bed", "wall_B"])]),
    ],
)
def test_pushed_out_by_a_wall_placed_parent(graph: SceneGraph, expected: list[tuple[str, list[str]]]) -> None:
    assert issues(graph, BEDROOM["room_spec"]) == expected


def test_children_that_fit_beside_a_wall_placed_parent_pass() -> None:
    graph = bedroom(
        [node("rug", 1.2, 1.2, 0.01), node("shelf", 2.0, 0.3, 1.0)], [edge("rug", "in_front", "bed"), edge("shelf", "left_of", "desk")]
    )
    assert issues(graph, BEDROOM["room_spec"]) == []


# too_small: desk is 1.0 x 0.5, nightstand 0.4 x 0.35


@pytest.mark.parametrize(
    ("graph", "expected"),
    [
        (
            bedroom([node("chair", 0.45, 0.45, 0.85, quantity=3)], [edge("chair", "in_front", "desk")]),
            [("too_small", ["desk", "chair", "desk_chair"])],
        ),
        (bedroom([node("lamp", 0.5, 0.5, 0.4)], [edge("lamp", "on", "nightstand")]), [("too_small", ["nightstand", "lamp"])]),
        (
            bedroom(
                [node("a", 0.3, 0.3, 0.5), node("b", 0.3, 0.3, 0.5)],
                [edge("a", "left_of", "nightstand"), edge("b", "left_of", "nightstand")],
            ),
            [("too_small", ["nightstand", "a", "b"])],
        ),
        (
            bedroom(
                [node("a", 0.4, 0.4, 0.5), node("b", 0.4, 0.4, 0.5)],
                [edge("nightstand", "right_of", "a"), edge("nightstand", "right_of", "b")],
            ),
            [("too_small", ["nightstand", "a", "b"])],
        ),  # read from its other end
    ],
)
def test_parent_too_small_for_its_children(graph: SceneGraph, expected: list[tuple[str, list[str]]]) -> None:
    assert issues(graph, BEDROOM["room_spec"]) == expected


def test_parent_large_enough_for_its_children_passes() -> None:
    graph = bedroom(
        [node("chair", 0.45, 0.45, 0.85), node("lamp", 0.2, 0.2, 0.4), node("armchair", 0.8, 0.8, 0.8)],
        [
            edge("chair", "in_front", "desk"),
            edge("lamp", "on", "nightstand"),
            edge("armchair", "right_of", "nightstand"),
        ],  # one child may overhang
    )
    assert issues(graph, BEDROOM["room_spec"]) == []


# between_adjacent: nightstand is adjacent to bed


def test_object_between_adjacent_objects_fails() -> None:
    graph = bedroom(edges=[edge("desk_chair", "right_of", "nightstand"), edge("desk_chair", "left_of", "bed")])
    assert issues(graph, BEDROOM["room_spec"]) == [("between_adjacent", ["desk_chair", "nightstand", "bed"])]
    graph = bedroom(edges=[edge("nightstand", "left_of", "desk_chair"), edge("desk_chair", "left_of", "bed")])  # read from its other end
    assert issues(graph, BEDROOM["room_spec"]) == [("between_adjacent", ["desk_chair", "nightstand", "bed"])]


def test_object_beside_adjacent_objects_passes() -> None:
    graph = bedroom([node("platform", 1.8, 1.8, 0.3)], [edge("platform", "right_of", "nightstand"), edge("platform", "right_of", "bed")])
    assert issues(graph, BEDROOM["room_spec"]) == []


# blocks_opening, blocks_window: door_1 is 0.8 wide on wall A (x 2.0-2.8), window_1 is 1.0 wide on wall C, sill at 0.9


@pytest.mark.parametrize(
    ("graph", "expected"),
    [
        (bedroom(edges=[edge("desk_chair", "in_front", "door_1")]), [("blocks_opening", ["desk_chair", "door_1"])]),
        (
            bedroom([node("wardrobe", 1.0, 0.6, 2.0)], [edge("wardrobe", "in_front", "window_1")]),
            [("blocks_window", ["wardrobe", "window_1"])],
        ),
        (
            bedroom([node("sideboard", 2.5, 0.4, 0.8)], [edge("sideboard", "against_wall", "wall_A")]),
            [("blocks_opening", ["sideboard", "door_1"])],
        ),
        (
            bedroom([node("wardrobe", 1.5, 0.6, 2.0)], [edge("wardrobe", "against_wall", "wall_C")]),
            [("blocks_window", ["wardrobe", "window_1"])],
        ),
    ],
)
def test_relation_blocking_a_door_or_window_fails(graph: SceneGraph, expected: list[tuple[str, list[str]]]) -> None:
    assert issues(graph, BEDROOM["room_spec"]) == expected


def test_relation_clear_of_doors_and_windows_passes() -> None:
    graph = bedroom(
        [node("sideboard", 1.9, 0.4, 0.8), node("wardrobe", 1.0, 0.6, 2.0), node("lamp", 0.3, 0.3, 1.6)],
        [
            edge("desk", "in_front", "window_1"),  # below the sill
            edge("sideboard", "against_wall", "wall_A"),  # fits left of the door
            edge("wardrobe", "against_wall", "wall_C"),  # fits beside the window
            edge("lamp", "in_corner", "wall_A"),  # the corner away from the door
        ],
    )
    assert issues(graph, BEDROOM["room_spec"]) == []


def test_corner_items_only_try_the_corners() -> None:
    door_2 = {"id": "door_2", "type": "door", "wall": "A", "offset": 0.15, "width": 0.8, "height": 2.1}  # x 0.08-0.88
    spec = BEDROOM["room_spec"].model_dump()
    spec = RoomSpec.model_validate(spec | {"features": [*spec["features"], door_2]})
    lamp = node("lamp", 0.5, 0.3, 1.6)  # each corner of wall A overlaps a door, the middle (x 0.88-2.0) does not
    assert issues(bedroom([lamp], [edge("lamp", "against_wall", "wall_A")]), spec) == []
    assert issues(bedroom([lamp], [edge("lamp", "in_corner", "wall_A")]), spec) == [("blocks_opening", ["lamp", "door_2"])]
