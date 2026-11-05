"""The solver fallback: the impossible brief gets a partial layout and a correct explanation, within a hard time budget."""

from itertools import count
from time import monotonic

import pytest

from app.catalog.loader import load_catalog
from app.geometry import fallback, solver
from app.geometry.fallback import smaller_variants, solve_with_fallback
from app.schemas import Brief, SceneGraph
from tests.test_fixtures import FIXTURES, case
from tests.test_graph_validate import edge, node
from tests.test_solver import BEDROOM, graph, problems

# impossible_brief.json is a Brief only: its must-haves at catalog sizes (the piano at a typical size: the catalog has none), in the
# small bedroom, each against the wall with the most room for it, the table free.
BRIEF = Brief.model_validate_json((FIXTURES / "negative" / "impossible_brief.json").read_text())
MUST_HAVES = {
    "king-size bed": ("bed", "oak-bed-180", "wall_B"),
    "three-seat sofa": ("sofa", "grey-sofa-3", "wall_D"),
    "dining table for six": ("table", "oak-dining-table-6", None),
    "upright piano": ("piano", None, "wall_A"),
    "desk": ("desk", "oak-desk-120", "wall_C"),
}


def impossible_graph() -> SceneGraph:
    catalog = load_catalog()
    nodes, edges = [], []
    for name in BRIEF.must_haves:
        id_, item, wall = MUST_HAVES[name]
        size = catalog[item].size.model_dump() if item else {"width": 1.5, "depth": 0.6, "height": 1.3}
        nodes.append({"id": id_, "name": name, "size": size, "item_id": item})
        edges += [edge(id_, "against_wall", wall)] if wall else []
    return graph(nodes, edges)


@pytest.fixture
def steady_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every clock read takes 3 ms, about one solver step on an idle machine: the budgets buy the same search on a busy one."""
    ticks = count(0.0, 0.003)
    for module in (solver, fallback):
        monkeypatch.setattr(module, "monotonic", ticks.__next__)


@pytest.mark.usefixtures("steady_clock")
@pytest.mark.parametrize("seed", range(2))
def test_the_impossible_brief_gets_a_partial_layout_and_why(seed: int) -> None:
    g, spec = impossible_graph(), case("small-bedroom")["room_spec"]
    layout, report = solve_with_fallback(g, spec, seed=seed)  # the default budgets
    changes = {c.node_id: c for c in report.changes}
    # the sofa fits no wall beside the door or the kept wardrobe, so it becomes a two-seat; the piano fits nowhere and has no variant
    assert (changes["sofa"].action, changes["sofa"].code) == ("resized", "too_big")
    assert load_catalog()[changes["sofa"].item_id or ""].size.width < 2
    assert (changes["piano"].action, changes["piano"].code) == ("dropped", "too_big")
    assert "on its own" in changes["piano"].message
    # the bed comes first and fits; the table and the desk then compete for what is left
    assert "bed" not in changes
    assert {changes["table"].code, changes["desk"].code} == {"no_space"}
    assert any(changes[n].action == "dropped" for n in ("table", "desk"))
    placed = {p.node_id: p.item_id for p in layout.placements}
    assert set(placed) == {n.id for n in g.nodes if n.kind == "object"} - {c.node_id for c in report.changes if c.action == "dropped"}
    assert placed["bed"] == "oak-bed-180"
    assert all(placed[c.node_id] == c.item_id for c in report.changes if c.action == "resized")
    assert problems(layout, spec) == []
    assert report.summary.startswith("Placed 3 of 5 items; dropped: ")


def test_never_takes_much_longer_than_the_budget() -> None:
    start = monotonic()
    layout, report = solve_with_fallback(impossible_graph(), case("small-bedroom")["room_spec"], budget=1.0, attempt=0.4)
    assert monotonic() - start < 1.2  # solve() is handed only what is left of the budget
    assert report.changes[-1].code == "out_of_time"
    assert problems(layout, case("small-bedroom")["room_spec"]) == []


def test_a_solvable_graph_passes_through() -> None:
    data = case("small-bedroom")
    layout, report = solve_with_fallback(data["scene_graph"], data["room_spec"])
    assert report.changes == [] and len(layout.placements) == 4


def test_children_of_a_dropped_item_are_dropped_and_nice_to_haves_go_first() -> None:
    # Two 2.4 m rugs: either fits the bedroom's free floor on its own, never both; the nice one is listed first but tried last.
    # The lamp is listed before the stage it stands on, but the stage is tried first.
    nice_rug = {**node("rug", 2.4, 2.4, 0.01), "priority": "nice"}
    g = graph(
        [nice_rug, node("lamp", 0.3, 0.3, 1.5), node("stage", 4.0, 1.0, 0.5), node("carpet", 2.4, 2.4, 0.01)],
        [edge("stage", "against_wall", "wall_A"), edge("lamp", "on", "stage")],
    )
    layout, report = solve_with_fallback(g, BEDROOM, attempt=0.2)
    assert [(c.node_id, c.code) for c in report.changes] == [("stage", "too_big"), ("lamp", "depends_on_dropped"), ("rug", "no_space")]
    assert [p.node_id for p in layout.placements] == ["carpet"]
    assert report.summary == "Placed 1 of 4 items; dropped: stage, lamp, rug"


def test_smaller_variants_keep_the_category_and_height() -> None:
    variants = smaller_variants("oak-dining-table-6")
    assert [(v.size.width, v.size.depth) for v in variants] == [(1.4, 0.8)]  # not the coffee or side tables
    assert variants[0].id == "oak-dining-table-4"  # the same style first
    assert smaller_variants(None) == smaller_variants("no-such-item") == []
