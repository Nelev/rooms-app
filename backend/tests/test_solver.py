"""The backtracking solver: every fixture graph solves cleanly, fast and deterministically; dead ends backtrack; budgets hold."""

from collections import Counter
from time import monotonic

import pytest

from app.geometry import solver
from app.geometry.checks import EPS, above_ceiling, blocked_openings, blocked_radiators, blocked_windows, collisions
from app.geometry.room import Solid, room_model, solid
from app.geometry.solver import TRIES, Unsolvable, solve
from app.schemas import Layout, RoomSpec, SceneGraph
from app.schemas.layout import Placement
from tests.test_fixtures import CASES, case
from tests.test_graph_validate import edge, node

BEDROOM = case("small-bedroom")["room_spec"]  # radiator in front of the middle of wall C leaves 1.2 m free at either end


def problems(layout: Layout, spec: RoomSpec) -> list[str]:
    """Collisions, items outside the room or above the ceiling and blocked doors, windows or radiators."""
    room = room_model(spec)
    floor = room.floor.buffer(EPS)
    issues = collisions(room, layout) + blocked_openings(room, layout) + blocked_windows(room, layout) + blocked_radiators(room, layout)
    issues += above_ceiling(room, layout)
    return [i.message for i in issues] + [f"{p.node_id} is out of bounds" for p in layout.placements if not floor.contains(solid(p).shape)]


def graph(nodes: list[dict[str, object]], edges: list[dict[str, str]]) -> SceneGraph:
    walls = [{"id": f"wall_{w}", "kind": "wall", "name": f"wall {w}"} for w in "ABCD"]
    return SceneGraph.model_validate({"nodes": walls + nodes, "edges": edges})


@pytest.mark.parametrize("name", CASES)
@pytest.mark.parametrize("seed", range(10))
def test_fixture_graphs_solve_without_problems_in_time(name: str, seed: int) -> None:
    data = case(name)
    start = monotonic()
    layout = solve(data["scene_graph"], data["room_spec"], seed=seed)
    assert monotonic() - start < 2
    assert {(p.node_id, p.item_id) for p in layout.placements} == {
        (n.id, n.item_id) for n in data["scene_graph"].nodes if n.kind == "object"
    }
    assert problems(layout, data["room_spec"]) == []


@pytest.mark.parametrize("name", CASES)
def test_same_seed_same_layout_other_seed_other_layout(name: str) -> None:
    data = case(name)
    graph, spec = data["scene_graph"], data["room_spec"]
    assert solve(graph, spec, seed=7) == solve(graph, spec, seed=7)
    assert solve(graph, spec, seed=7) != solve(graph, spec, seed=8)


def test_relations_are_kept() -> None:
    """Small bedroom: bed flush against wall B facing into the room, desk_chair in front of the desk turned toward it."""
    data = case("small-bedroom")
    placed = {p.node_id: p for p in solve(data["scene_graph"], data["room_spec"]).placements}
    bed, desk, chair = placed["bed"], placed["desk"], placed["desk_chair"]
    assert bed.rotation == 90 and bed.x == pytest.approx(3.2 - bed.size.depth / 2)
    assert desk.rotation == 270 and desk.x == pytest.approx(desk.size.depth / 2)
    assert chair.rotation == 90 and 0 <= chair.x - chair.size.depth / 2 - desk.size.depth <= 0.2 + EPS


def test_on_stacks_on_the_parent() -> None:
    g = graph(
        [node("desk", 1.0, 0.5, 0.75), node("lamp", 0.2, 0.2, 0.4)], [edge("desk", "against_wall", "wall_D"), edge("lamp", "on", "desk")]
    )
    placed = {p.node_id: p for p in solve(g, BEDROOM).placements}
    assert placed["lamp"].z == 0.75
    assert solid(placed["desk"]).shape.contains(solid(placed["lamp"]).shape)


# Two 0.5 m cabinets side by side fit wall C's free 1.2 m only when the first is near an end: often the second cannot be placed
# and the first must be re-sampled. Quantity 2 shelves give two placements.
CABINETS = graph(
    [node("cabinet", 0.5, 0.4, 0.9), node("side", 0.5, 0.4, 0.9), node("shelf", 0.6, 0.3, 1.0, quantity=2)],
    [edge("cabinet", "against_wall", "wall_C"), edge("side", "adjacent", "cabinet"), edge("shelf", "against_wall", "wall_A")],
)


@pytest.mark.parametrize("seed", range(20))
def test_dead_ends_backtrack_and_copies_are_placed(seed: int) -> None:
    layout = solve(CABINETS, BEDROOM, seed=seed)
    assert [p.node_id for p in layout.placements] == ["cabinet", "shelf", "shelf_2", "side"]
    assert problems(layout, BEDROOM) == []


def test_a_dead_end_resamples_the_group_above(monkeypatch: pytest.MonkeyPatch) -> None:
    sampled: Counter[str] = Counter()

    def counting_solid(p: Placement) -> Solid:
        sampled[p.node_id] += 1
        return solid(p)

    monkeypatch.setattr(solver, "solid", counting_solid)
    solve(CABINETS, BEDROOM, seed=10)  # a seed whose first cabinet leaves no room for the second
    assert sampled["side"] > TRIES and sampled["cabinet"] > 1


# Three 0.36 m items in a row in wall C's free 1.2 m: when the first stands too far from an end the third never fits, whatever
# the second does, so backtracking must go two groups up.
ROW = graph(
    [node("a", 0.36, 0.4, 0.9), node("b", 0.36, 0.4, 0.9), node("c", 0.36, 0.4, 0.9)],
    [edge("a", "against_wall", "wall_C"), edge("b", "adjacent", "a"), edge("c", "adjacent", "b")],
)


@pytest.mark.parametrize("seed", range(20))
def test_deep_dead_ends_backtrack_further_up(seed: int) -> None:
    assert problems(solve(ROW, BEDROOM, seed=seed), BEDROOM) == []


def test_gives_up_after_the_budget() -> None:
    g = graph([node(f"box_{i}", 1.0, 1.0, 1.0) for i in range(20)], [])
    start = monotonic()
    with pytest.raises(Unsolvable):
        solve(g, BEDROOM, budget=0.3)
    assert monotonic() - start < 1


def test_an_adjacent_edge_closing_a_loop_is_not_followed() -> None:
    """The validator gives adjacent edges no parent, so it lets this loop through: the solver must not follow it."""
    g = graph(
        [node("a", 0.5, 0.4, 0.9), node("b", 0.5, 0.4, 0.9)],
        [edge("a", "adjacent", "b"), edge("b", "left_of", "a")],
    )
    assert problems(solve(g, BEDROOM), BEDROOM) == []


@pytest.mark.parametrize("seed", range(5))
def test_beside_a_window_stands_flush_against_its_wall(seed: int) -> None:
    window = {"id": "window_1", "kind": "window", "name": "window"}
    g = graph([window, node("shelf", 0.6, 0.3, 0.8)], [edge("shelf", "left_of", "window_1")])
    shelf = solve(g, BEDROOM, seed=seed, budget=0.2).placements[0]
    assert shelf.y == pytest.approx(BEDROOM.dimensions.length - 0.15) and shelf.rotation == 180
