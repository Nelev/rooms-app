"""The solve node, the rule-based Critic and the best-of-rounds routing, offline (all deterministic): planted errors in the fixture
runs are sent back to the Architect or the Sourcer and fixed in a later round, or explained, and every run ends."""

from typing import Any

import pytest

from app.geometry.solver import Frame, solve
from app.graph.nodes.critic import judge
from app.graph.nodes.refine import refine_graph
from app.graph.nodes.solve import kept, solve_scene, unmet_relations, validate
from app.graph.routing import MAX_ROUNDS, keep_best
from app.schemas import FallbackReport, Layout, SceneGraph, ValidationReport
from app.schemas.coords import Size
from app.schemas.design import SceneEdge
from app.schemas.layout import Placement
from tests.test_fallback import impossible_graph
from tests.test_fixtures import CASES, case
from tests.test_refine import AMBIGUOUS


def solved(name: str, round_: int = 1, graph: SceneGraph | None = None) -> dict[str, Any]:
    """The case's state after the solve node, in round `round_`."""
    data = case(name)
    state = {"scene_graph": graph or data["scene_graph"], "room_spec": data["room_spec"], "design_brief": data["design_brief"]}
    return state | {"round": round_} | solve_scene(state | {"round": round_})


def planted(state: dict[str, Any], node_id: str, **at: float) -> dict[str, Any]:
    """`state` with the node's placement moved, and validated again."""
    placements = [p.model_copy(update=at) if p.node_id == node_id else p for p in state["layout"].placements]
    layout = Layout(placements=placements)
    return state | {"layout": layout, "validation": validate(state["scene_graph"], state["room_spec"], layout)}


def failed(state: dict[str, Any]) -> dict[str, str]:
    critique, *_ = judge(state)  # type: ignore[arg-type]
    return {r.rule: r.message for r in critique.rules if not r.passed}


def item(node_id: str, x: float, y: float, rotation: float = 0, width: float = 0.5, depth: float = 0.5, z: float = 0) -> Placement:
    return Placement(node_id=node_id, x=x, y=y, z=z, rotation=rotation, size=Size(width=width, depth=depth, height=0.5))


@pytest.mark.parametrize("name", CASES)
def test_the_fixture_designs_are_accepted_in_one_round(name: str) -> None:
    state = solved(name)
    critique, hard, soft = judge(state)  # type: ignore[arg-type]
    assert (critique.actions, hard, soft, critique.summary) == ([], 0, 0, "all rules pass")
    assert [r.rule for r in critique.rules] == [
        *("graph_valid", "relations_kept", "no_collisions", "openings_clear", "reachable", "everything_fits", "siblings_ordered"),
        *("desk_near_light", "bed_not_facing_door", "visual_balance"),
    ]
    assert state["fallback"] == FallbackReport(summary="Every item fits") and state["scene_graph"] == case(name)["scene_graph"]


@pytest.mark.parametrize("name", CASES)
@pytest.mark.parametrize("seed", range(5))
def test_the_relation_check_agrees_with_the_solver(name: str, seed: int) -> None:
    """Every placing edge the solver honours (the first of each node) is kept on each fixture graph, whatever the seed."""
    graph, spec = case(name)["scene_graph"], case(name)["room_spec"]
    assert unmet_relations(graph, spec, solve(graph, spec, seed=seed)) == []


def test_relations_are_read_as_seen_by_a_viewer_facing_the_parent() -> None:
    parent = Frame(2, 2, 0, 1, 1, 0.75, False)  # 1 x 1 m, front facing +y, so its own right is +x
    assert kept("left_of", parent, item("c", 2.8, 2)) and not kept("right_of", parent, item("c", 2.8, 2))
    assert kept("right_of", parent, item("c", 1.2, 2)) and kept("adjacent", parent, item("c", 1.2, 2))
    assert kept("in_front", parent, item("c", 2, 2.75, rotation=180)) and kept("behind", parent, item("c", 2, 1.2))
    assert kept("on", parent, item("c", 2, 2, z=0.75)) and not kept("on", parent, item("c", 2, 2))
    assert not kept("in_front", parent, item("c", 2, 3.5))  # beyond the solver's 0.2 m gap
    assert kept("facing", parent, item("c", 2, 0.5)) and not kept("facing", parent, item("c", 2, 0.5, rotation=180))


def test_a_planted_collision_is_sent_to_the_architect_and_fixed_in_the_next_round() -> None:
    state = solved("small-bedroom")
    bed = next(p for p in state["layout"].placements if p.node_id == "bed")
    collided = planted(state, "nightstand", x=bed.x, y=bed.y)
    assert "bed overlaps nightstand" in failed(collided)["no_collisions"]
    critique, hard, _ = judge(collided)  # type: ignore[arg-type]
    assert hard > 0 and any(a.target == "architect" and "bed overlaps nightstand" in a.instruction for a in critique.actions)
    assert failed(solved("small-bedroom", round_=2)) == {}


def test_a_planted_blocked_door_is_sent_to_the_architect_and_fixed_in_the_next_round() -> None:
    blocked = planted(solved("small-bedroom"), "nightstand", x=2.4, y=0.3, rotation=0)  # door_1 opens at x 2.4 of wall A
    assert "nightstand blocks the door swing of door_1" in failed(blocked)["openings_clear"]
    critique, *_ = judge(blocked)  # type: ignore[arg-type]
    assert any(a.target == "architect" and a.node_id == "nightstand" for a in critique.actions)
    assert failed(solved("small-bedroom", round_=2)) == {}


@pytest.mark.parametrize("round_", range(1, MAX_ROUNDS + 1))
def test_unmet_sibling_ordering_edges_are_soft_and_ask_for_nothing(round_: int) -> None:
    state = solved("living-room", round_=round_, graph=refine_graph(AMBIGUOUS))  # the Refiner's edges, which the solver does not place by
    unmet = [i.message for i in state["validation"].issues if i.code == "relation_unmet"]
    assert unmet and {m.split()[0] for m in unmet} <= {"desk_lamp", "plant", "chair_2"}
    critique, hard, soft = judge(state)  # type: ignore[arg-type]
    assert failed(state)["siblings_ordered"] == "; ".join(unmet) and "relations_kept" not in failed(state)
    assert hard == 0 and soft >= 1
    # the only actions left are soft-rule ones (here visual_balance), none for the ordering edges
    soft_rules = ("desk_near_light", "bed_not_facing_door", "visual_balance")
    assert len(critique.actions) == sum(bool(failed(state).get(r)) for r in soft_rules)
    assert not any("is not right of" in a.instruction for a in critique.actions)


def test_a_non_ordering_unmet_relation_stays_hard_and_goes_to_the_architect() -> None:
    graph = refine_graph(AMBIGUOUS)
    graph = graph.model_copy(update={"edges": [*graph.edges, SceneEdge(source="plant", relation="in_front", target="table")]})
    state = solved("living-room", graph=graph)
    critique, hard, _ = judge(state)  # type: ignore[arg-type]
    assert failed(state)["relations_kept"] == "plant is not in front table in the layout" and hard == 1
    assert [(a.target, a.node_id) for a in critique.actions if "is not in front" in a.instruction] == [("architect", "plant")]


def test_the_impossible_brief_is_explained_and_the_sourcer_asked_for_smaller_items() -> None:
    data = case("small-bedroom")
    state: Any = {"scene_graph": impossible_graph(), "room_spec": data["room_spec"], "design_brief": data["design_brief"], "round": 1}
    state |= solve_scene(state)
    report = state["fallback"]
    resized = {c.node_id: c.item_id for c in report.changes if c.action == "resized"}
    assert all(n.item_id == resized[n.id] for n in state["scene_graph"].nodes if n.id in resized)
    assert all(state["candidates"][n][0].id == item_id for n, item_id in resized.items())  # the chosen item first
    critique, hard, _ = judge(state)
    assert failed(state)["everything_fits"] == report.summary and hard > 0
    dropped = {c.node_id for c in report.changes if c.action == "dropped" and c.code in ("too_big", "no_space")}
    assert {a.node_id for a in critique.actions if a.target == "sourcer"} == dropped
    # nothing changes it: the run ends after MAX_ROUNDS with the explanation
    for round_ in range(1, MAX_ROUNDS + 1):
        update = keep_best(state | {"round": round_}, critique.model_copy(update={"round": round_}), hard, 0)
        state |= update
    assert "round" not in update and update["critique"].actions == [] and update["critique"].round == 1
    assert update["critique"].summary.endswith(f"not fixed in {MAX_ROUNDS} rounds; round 1's design is the best")
    assert update["fallback"] == report


def test_soft_rules() -> None:
    data = case("small-bedroom")  # window_1 in the middle of wall C (y 3.4), door_1 at x 2.4 of wall A (y 0), wardrobe by wall D
    base: Any = {**data, "fallback": FallbackReport(summary=""), "validation": ValidationReport(), "round": 1}

    def rules(*placements: Placement) -> dict[str, str]:
        return failed(base | {"layout": Layout(placements=list(placements))})

    bed = item("bed", 2.4, 1.6, rotation=180, width=1.4, depth=2.0)  # its foot toward wall A, the door ahead of it
    assert rules(bed) == {"bed_not_facing_door": "bed faces door_1"}
    assert rules(bed.model_copy(update={"rotation": 90})) == {}
    assert rules(item("desk", 0.8, 1.6), bed.model_copy(update={"rotation": 90})) == {
        "desk_near_light": "desk is more than 1.0 m from window_1"
    }
    assert rules(item("desk", 1.6, 2.6), bed.model_copy(update={"rotation": 90})) == {}
    crowded = rules(item("desk", 0.5, 2.0, width=1.0, depth=2.0))
    assert crowded == {"visual_balance": "the furniture crowds wall D"}


def test_the_best_round_wins_ties_keep_the_earlier_and_a_new_design_run_starts_over() -> None:
    state = solved("small-bedroom")
    critique, *_ = judge(state)  # type: ignore[arg-type]
    asks = critique.model_copy(update={"actions": [{"target": "architect", "instruction": "Fix it"}]})
    first = keep_best(state, asks, 1, 0)
    assert first["round"] == 2 and first["best"].layout == state["layout"]
    other = solved("small-bedroom", round_=2)
    second = keep_best(other | {"best": first["best"]}, asks.model_copy(update={"round": 2}), 1, 0)
    assert second["best"] == first["best"]  # a tie keeps round 1
    third = keep_best(other | {"best": first["best"], "round": 1}, asks, 2, 0)
    assert third["best"].layout == other["layout"]  # round 1 of a new design run: the old best is ignored
    done = keep_best(other | {"best": first["best"], "round": 2}, critique.model_copy(update={"round": 2}), 0, 0)
    assert (done["layout"], done["critique"].summary, "round" in done) == (other["layout"], "all rules pass", False)
