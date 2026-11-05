"""Every deterministic metric in eval/metrics/ gives its known answer: perfect on the fixtures, and the planted value on planted cases."""

import pytest
from metrics.analyst import FeatureScores, feature_scores
from metrics.layout import (
    bbox_loss,
    blocked_openings,
    budget_fit,
    clearance_pass_rate,
    cost,
    layout_metrics,
    must_have_coverage,
    out_of_bounds,
    out_of_bounds_rate,
    overlap_volume,
)

from app.catalog.loader import load_catalog
from app.schemas import Brief, Layout
from app.schemas.layout import Placement
from tests.test_eval_dataset import CASES as EVAL_CASES
from tests.test_fixtures import CASES, case
from tests.test_geometry import item, layout, room

FIXTURES = {name: case(name) for name in CASES}
BEDROOM = FIXTURES["small-bedroom"]
CATALOG = load_catalog()


def with_items(plan: Layout, *placements: Placement) -> Layout:
    return plan.model_copy(update={"placements": [*plan.placements, *placements]})


# layout metrics


@pytest.mark.parametrize(("name", "items", "price"), [("small-bedroom", 4, 806), ("home-office", 4, 616), ("living-room", 5, 2025)])
def test_fixture_layouts_score_perfectly(name: str, items: int, price: float) -> None:
    f = FIXTURES[name]
    assert layout_metrics(f["room_spec"], f["brief"], f["layout"], CATALOG) == {
        "out_of_bounds": False,
        "overlap_volume": 0,
        "clearance_pass_rate": 1,
        "blocked_openings": 0,
        "item_count": items,
        "cost": price,
        "budget_fit": True,
        "must_have_coverage": 1,
    }


@pytest.mark.parametrize(
    "outside",
    [
        item("bench", 0.1, 1.5),  # 0.15 m through wall D
        item("bench", 1.5, 3.0),  # half through wall C
        item("shelf", 1.5, 1.5, z=2.2),  # its top 0.2 m above the ceiling
    ],
)
def test_out_of_bounds(outside: Placement) -> None:
    assert not out_of_bounds(room(), layout())
    assert out_of_bounds(room(), layout(item("box", 1.5, 1.5), outside))


def test_overlap_with_a_wall_named_item_is_not_out_of_bounds() -> None:
    assert not out_of_bounds(room(), layout(item("box", 1.5, 1.5), item("wall_shelf", 1.6, 1.5)))


def test_out_of_bounds_rate_is_the_share_of_invalid_scenes() -> None:
    scenes = [(f["room_spec"], f["layout"]) for f in FIXTURES.values()]
    assert out_of_bounds_rate(scenes) == 0
    assert out_of_bounds_rate([*scenes, (room(), layout(item("bench", 0.1, 1.5)))]) == 0.25


def test_overlap_volume() -> None:
    assert overlap_volume(room(), layout(item("a", 1, 1, 1, 1, 1), item("b", 2.5, 1, 1, 1, 1))) == 0  # side by side, apart
    assert overlap_volume(room(), layout(item("a", 1, 1, 1, 1, 1), item("b", 1.5, 1, 1, 1, 1))) == pytest.approx(0.5)
    assert overlap_volume(room(), layout(item("a", 1, 1, 1, 1, 1), item("b", 1.5, 1, 1, 1, 1, z=0.5))) == pytest.approx(0.25)
    # a box rotated 90 degrees: 1 x 0.5 becomes 0.5 x 1, wholly inside a 1 x 1 x 1 cube
    assert overlap_volume(room(), layout(item("a", 1, 1, 1, 1, 1), item("b", 1, 1, 1, 0.5, 1, rotation=90))) == pytest.approx(0.5)
    # the small bedroom's kept wardrobe spans x 0-0.6, y 0.4-1.4, up to 2 m
    on_wardrobe = with_items(BEDROOM["layout"], item("box", 0.3, 0.9, 0.4, 0.4, 0.5))
    assert overlap_volume(BEDROOM["room_spec"], on_wardrobe) == pytest.approx(0.08)


def test_bbox_loss_is_the_mean_overlap_volume() -> None:
    overlapping = layout(item("a", 1, 1, 1, 1, 1), item("b", 1.5, 1, 1, 1, 1))
    assert bbox_loss([(room(), overlapping), (room(), layout())]) == pytest.approx(0.25)


def test_clearance_pass_rate() -> None:
    spec = room(features=room().features[:1])
    divider = item("divider", 1.5, 2, w=3, d=0.1, h=1)
    assert clearance_pass_rate(spec, layout()) == 1
    assert clearance_pass_rate(spec, layout(divider, item("box", 1.5, 1))) == 1
    assert clearance_pass_rate(spec, layout(divider, item("box", 1.5, 2.7))) == 0.5  # the box is shut off behind the divider


def test_blocked_openings() -> None:
    # the small bedroom's door spans x 2.0-2.8 on wall A; its window x 1.1-2.1 on wall C, above a 0.9 m sill
    in_door = item("in_door", 2.4, 0.3, 0.4, 0.4)
    tall = item("tall", 1.6, 3.15, 0.4, 0.2, 1.2)
    low = item("low", 1.6, 3.15, 0.4, 0.2, 0.3, z=0.5)  # its top 0.8 m, below the sill: fine
    spec, plan = BEDROOM["room_spec"], BEDROOM["layout"]
    assert blocked_openings(spec, with_items(plan, low)) == 0
    assert blocked_openings(spec, with_items(plan, in_door)) == 1
    assert blocked_openings(spec, with_items(plan, in_door, tall)) == 2


def test_budget_fit() -> None:
    plan, brief = BEDROOM["layout"], BEDROOM["brief"]
    assert cost(plan, CATALOG) == 806  # oak double bed 140, oak nightstand, birch desk 100, grey desk chair
    assert budget_fit(plan, brief.model_copy(update={"budget": 806}), CATALOG)
    assert not budget_fit(plan, brief.model_copy(update={"budget": 805}), CATALOG)
    # a box and a made-up item cost nothing
    extra = with_items(plan, item("box", 1, 1), item("ghost", 1, 1).model_copy(update={"item_id": "not-in-catalog"}))
    assert cost(extra, CATALOG) == 806


def test_must_have_coverage() -> None:
    plan = BEDROOM["layout"]  # oak double bed, oak nightstand, birch desk, grey desk chair
    brief = Brief(
        room_use="bedroom", budget=1000, must_haves=["double bed", "two nightstands", "dining table for four", "chest of drawers"]
    )
    assert must_have_coverage(plan, brief, CATALOG) == 0.25  # the bed only: one nightstand of two
    second = item("nightstand_2", 0.5, 3).model_copy(update={"item_id": "oak-nightstand"})
    table = item("table", 1.5, 1.5).model_copy(update={"item_id": "oak-dining-table-4"})
    assert must_have_coverage(with_items(plan, second, table), brief, CATALOG) == 0.75
    assert must_have_coverage(layout(item("bed", 1, 1)), brief, {}) == 0.25  # matched by node id without a catalog item
    assert must_have_coverage(plan, brief.model_copy(update={"must_haves": []}), CATALOG) == 1
    assert must_have_coverage(layout(), brief, CATALOG) == 0


# Room Analyst metrics


@pytest.mark.parametrize("name", CASES)
def test_labels_against_themselves_score_perfectly(name: str) -> None:
    spec = FIXTURES[name]["room_spec"]
    scores = feature_scores(spec, spec)
    assert set(scores) == {f.type for f in spec.features}
    assert all(s.precision == s.recall == 1 and s.fn == s.fp == 0 and s.errors_cm == [0] * s.tp for s in scores.values())


def test_planted_analyst_errors() -> None:
    labeled = EVAL_CASES["hard-three-doors"].room_spec  # 3.5 x 3.5 m; doors on A (0.5), B (0.2), D (0.8); window on C (0.5, sill 0.9)
    doors = {f.id: f for f in labeled.features}
    predicted = labeled.model_copy(
        update={
            "features": [
                doors["door_1"].model_copy(update={"offset": 0.6}),  # 0.35 m off along wall A
                doors["door_2"].model_copy(update={"wall": "C"}),  # on the wrong wall
                # door_3 missed
                doors["window_1"].model_copy(update={"sill_height": 1.0}),  # 0.1 m too high
                doors["window_1"].model_copy(update={"id": "window_2", "offset": 0.1}),  # 1.4 m away, no overlap: a false positive
                doors["window_1"].model_copy(update={"id": "radiator_1", "type": "radiator"}),  # no radiator labeled
            ]
        }
    )
    scores = feature_scores(predicted, labeled)
    assert scores.keys() == {"door", "window", "radiator"}
    door, window, radiator = scores["door"], scores["window"], scores["radiator"]
    assert (door.tp, door.fp, door.fn) == (1, 1, 2) and door.errors_cm == [pytest.approx(35)]
    assert (door.precision, door.recall) == (0.5, pytest.approx(1 / 3))
    assert (window.tp, window.fp, window.fn) == (1, 1, 0) and window.errors_cm == [pytest.approx(10)]
    assert (window.precision, window.recall) == (0.5, 1)
    assert (radiator.precision, radiator.recall) == (0, 1)


def test_matching_is_one_to_one_closest_first() -> None:
    labeled = room(features=room().features[:1])  # a 0.8 m door at x 1.5 on wall A of a 3 m room
    door = labeled.features[0]
    far, near = door.model_copy(update={"id": "far", "offset": 0.6}), door.model_copy(update={"id": "near", "offset": 0.45})
    scores = feature_scores(labeled.model_copy(update={"features": [far, near]}), labeled)
    assert scores["door"] == FeatureScores(tp=1, fp=1, fn=0, errors_cm=[pytest.approx(15)])


def test_wrong_room_size_shows_as_position_error() -> None:
    labeled = room(features=room().features[:1])  # door center 1.5 m along wall A
    wider = labeled.model_copy(update={"dimensions": labeled.dimensions.model_copy(update={"width": 3.4})})  # 1.7 m along
    assert feature_scores(wider, labeled)["door"].errors_cm == [pytest.approx(20)]
