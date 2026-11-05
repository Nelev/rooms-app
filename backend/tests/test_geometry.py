"""The Shapely room model and layout checks: the fixtures' layouts pass, and each check catches a planted violation."""

import math
from typing import Any

import pytest
from shapely import Point

from app.geometry.checks import (
    above_ceiling,
    blocked_openings,
    blocked_radiators,
    blocked_windows,
    clearance_violations,
    collisions,
)
from app.geometry.room import FRONT_ZONE, RADIATOR_DEPTH, footprint, room_model
from app.schemas import Layout, RoomSpec
from app.schemas.coords import Size
from app.schemas.layout import Placement
from app.schemas.room import ROOM_SPEC_EXAMPLE
from tests.test_fixtures import CASES, case

CHECKS = [collisions, blocked_openings, blocked_windows, blocked_radiators, above_ceiling]
WALKWAY = 0.6


def room(**changes: Any) -> RoomSpec:
    """A 3 x 3 x 2.5 m room with a door on wall A, a window and a radiator below it on wall C."""
    spec: dict[str, Any] = {
        "dimensions": {"width": 3, "length": 3, "height": 2.5},
        "features": [
            {"id": "door", "type": "door", "wall": "A", "offset": 0.5, "width": 0.8, "height": 2.1},
            {"id": "window", "type": "window", "wall": "C", "offset": 0.5, "width": 1.2, "height": 1.2, "sill_height": 0.9},
            {"id": "radiator", "type": "radiator", "wall": "C", "offset": 0.5, "width": 1.0, "height": 0.6, "sill_height": 0.1},
        ],
    }
    return RoomSpec.model_validate(spec | changes)


def item(node_id: str, x: float, y: float, w: float = 0.5, d: float = 0.5, h: float = 0.5, rotation: float = 0, z: float = 0) -> Placement:
    return Placement(node_id=node_id, x=x, y=y, z=z, rotation=rotation, size=Size(width=w, depth=d, height=h))


def layout(*placements: Placement) -> Layout:
    return Layout(placements=list(placements))


def issues(spec: RoomSpec, plan: Layout) -> list[tuple[str, list[str]]]:
    model = room_model(spec)
    found = [i for check in CHECKS for i in check(model, plan)] + clearance_violations(model, plan, WALKWAY)
    return [(i.code, i.node_ids) for i in found]


# footprint


def test_footprint_is_centered_and_axis_aligned() -> None:
    assert footprint(item("a", 1, 1, w=2, d=1), 1, 1, 0).bounds == (0, 0.5, 2, 1.5)


def test_footprint_rotation_swaps_width_and_depth() -> None:
    assert footprint(item("a", 0, 0, w=2, d=1), 1, 1, 90).bounds == pytest.approx((0.5, 0, 1.5, 2))


def test_footprint_rotates_counterclockwise_about_its_center() -> None:
    shape = footprint(item("a", 0, 0, w=1, d=1), 0, 0, 45)
    assert shape.area == pytest.approx(1)
    assert shape.bounds == pytest.approx((-(2**0.5) / 2, -(2**0.5) / 2, 2**0.5 / 2, 2**0.5 / 2))


# room model


def test_room_model_features() -> None:
    model = room_model(RoomSpec.model_validate(ROOM_SPEC_EXAMPLE))
    assert model.floor.bounds == (0, 0, 3.2, 4.0)
    assert [w.id for w in model.walls] == ["wall_A", "wall_B", "wall_C", "wall_D"]
    assert [d.id for d in model.doors] == ["door_1"]
    assert [w.id for w in model.windows] == ["window_1"]
    assert [r.id for r in model.radiators] == ["radiator_1"]
    assert [o.id for o in model.obstacles] == ["radiator_1", "kept_1"]
    assert all(w.shape.intersection(model.floor).area == 0 for w in model.walls)


def test_walls_cover_everything_outside_the_room() -> None:
    model = room_model(room())
    for x, y in [(-0.1, 1), (3.1, 1), (1, -0.1), (1, 3.1), (-0.1, -0.1), (3.5, 3.5)]:
        assert any(w.shape.contains(Point(x, y)) for w in model.walls), (x, y)


QUARTER_DISC = math.pi * 0.8**2 / 4


@pytest.mark.parametrize(
    ("hinge", "swing", "area", "inside", "outside"),
    [  # seen from inside, facing wall A, left is +x; the door spans x 1.1-1.9
        ("left", "in", QUARTER_DISC, (1.85, 0.75), (1.15, 0.75)),
        ("right", "in", QUARTER_DISC, (1.15, 0.75), (1.85, 0.75)),
        ("left", "out", 0.8 * 0.8, (1.15, 0.75), (1.5, 0.85)),
    ],
)
def test_door_swing(hinge: str, swing: str, area: float, inside: tuple[float, float], outside: tuple[float, float]) -> None:
    door = {"id": "door", "type": "door", "wall": "A", "offset": 0.5, "width": 0.8, "height": 2.1, "hinge": hinge, "swing": swing}
    zone = room_model(room(features=[door])).doors[0].shape
    assert zone.bounds == pytest.approx((1.1, 0, 1.9, 0.8))
    assert zone.area == pytest.approx(area, rel=0.01)
    assert zone.contains(Point(inside)) and not zone.contains(Point(outside))


@pytest.mark.parametrize("field", [{"swing": "out"}, {"hinge": "right"}])
def test_swing_and_hinge_are_for_doors_only(field: dict[str, str]) -> None:
    window = {"id": "window", "type": "window", "wall": "C", "offset": 0.5, "width": 1.2, "height": 1.4, **field}
    with pytest.raises(ValueError, match="doors only"):
        room(features=[window])


@pytest.mark.parametrize(
    ("wall", "inside", "outside"),
    [
        ("A", (0.95, 0.45), (0.55, 0.45)),
        ("B", (2.55, 0.95), (2.55, 0.55)),
        ("C", (2.05, 2.55), (2.45, 2.55)),
        ("D", (0.45, 2.05), (0.45, 2.45)),
    ],
)
def test_left_hinge_is_toward_the_wall_end(wall: str, inside: tuple[float, float], outside: tuple[float, float]) -> None:
    door = {"id": "door", "type": "door", "wall": wall, "offset": 0.25, "width": 0.5, "height": 2.1}
    zone = room_model(room(features=[door])).doors[0].shape
    assert zone.contains(Point(inside)) and not zone.contains(Point(outside))


def test_window_and_radiator_zones() -> None:
    model = room_model(room())
    window, radiator = model.windows[0], model.radiators[0]
    assert window.shape.bounds == pytest.approx((0.9, 3 - FRONT_ZONE, 2.1, 3))
    assert (window.bottom, window.top) == (0.9, 2.1)
    assert radiator.shape.bounds == pytest.approx((1.0, 3 - RADIATOR_DEPTH - FRONT_ZONE, 2.0, 3 - RADIATOR_DEPTH))
    assert (radiator.bottom, radiator.top) == pytest.approx((0.1, 0.7))


# the fixtures' layouts have no violations


@pytest.mark.parametrize("name", CASES)
def test_fixture_layouts_have_no_violations(name: str) -> None:
    c = case(name)
    layouts = [c["layout"]] + [t.output.layout for t in c["chat"] if t.output.layout]
    for plan in layouts:
        assert issues(c["room_spec"], plan) == []


def test_empty_layout_is_valid() -> None:
    assert issues(room(), layout()) == []


# one planted violation per check


def test_collision_between_placements() -> None:
    assert issues(room(), layout(item("a", 1, 1.5), item("b", 1.3, 1.5))) == [("collision", ["a", "b"])]


def test_touching_placements_do_not_collide() -> None:
    assert issues(room(), layout(item("a", 1, 1.5), item("b", 1.5, 1.5))) == []


def test_stacked_placements_do_not_collide() -> None:
    assert issues(room(), layout(item("table", 1, 1.5), item("lamp", 1, 1.5, w=0.2, d=0.2, z=0.5))) == []


def test_collision_with_wall() -> None:
    assert issues(room(), layout(item("a", 0.1, 1.5))) == [("collision", ["a", "wall_D"])]


def test_placement_outside_the_room_collides() -> None:
    assert ("collision", ["a", "wall_B"]) in issues(room(), layout(item("a", 5, 1.5)))


def test_collision_with_kept_furniture() -> None:
    kept = [{"id": "kept", "name": "wardrobe", "x": 2.7, "y": 1.5, "rotation": 90, "size": {"width": 1, "depth": 0.6, "height": 2}}]
    assert issues(room(kept_furniture=kept), layout(item("a", 2.2, 1.5))) == [("collision", ["a", "kept"])]


def test_collision_with_column() -> None:
    column = {"id": "column", "type": "column", "wall": "B", "offset": 0.5, "width": 0.4, "height": 2.5}
    assert issues(room(features=[column]), layout(item("a", 2.6, 1.5))) == [("collision", ["a", "column"])]


def test_blocked_door_swing() -> None:
    assert ("blocks_opening", ["a", "door"]) in issues(room(), layout(item("a", 1.5, 0.5)))


def test_outward_door_needs_the_floor_in_front() -> None:
    door = {"id": "door", "type": "door", "wall": "A", "offset": 0.5, "width": 0.8, "height": 2.1, "swing": "out"}
    assert ("blocks_opening", ["a", "door"]) in issues(room(features=[door]), layout(item("a", 1.2, 0.5, w=0.2, d=0.2)))


def test_item_beside_the_door_swing_is_fine() -> None:
    assert issues(room(), layout(item("a", 0.6, 0.3))) == []


def test_tall_item_blocks_window() -> None:
    plan = layout(item("shelf", 1.0, 2.8, w=0.6, d=0.4, h=1.8))
    assert issues(room(features=room().features[1:2]), plan) == [("blocks_window", ["shelf", "window"])]


def test_low_item_under_window_is_fine() -> None:
    assert issues(room(features=room().features[1:2]), layout(item("desk", 1.5, 2.65, w=1, d=0.7, h=0.75))) == []


def test_item_in_front_of_radiator() -> None:
    assert issues(room(), layout(item("sofa", 1.5, 2.55, w=1.6, d=0.6, h=0.8))) == [("blocks_radiator", ["sofa", "radiator"])]


def test_shelf_above_radiator_is_fine() -> None:
    assert issues(room(), layout(item("shelf", 1.5, 2.75, w=0.8, d=0.3, h=0.1, z=0.8))) == []


def test_item_above_ceiling() -> None:
    assert issues(room(), layout(item("wardrobe", 0.3, 1.5, d=0.6, h=2.6))) == [("above_ceiling", ["wardrobe"])]


def test_unreachable_placement() -> None:
    divider = item("divider", 1.5, 2, w=3, d=0.1, h=1)
    assert issues(room(features=room().features[:1]), layout(divider, item("box", 1.5, 2.7))) == [("clearance", ["box"])]


def test_narrow_gap_blocks_a_wide_walkway_only() -> None:
    spec = room(features=room().features[:1])
    plan = layout(item("divider", 1.2, 2, w=2.4, d=0.1, h=1), item("box", 1.5, 2.7))  # a 0.6 m gap at the end of the divider
    assert issues(spec, plan) == []
    assert [i.node_ids for i in clearance_violations(room_model(spec), plan, 0.7)] == [["box"]]


def test_item_next_to_a_reachable_item_counts_as_reachable() -> None:
    spec = room(features=room().features[:1])
    plan = layout(item("divider", 1.5, 2, w=3, d=0.1, h=1), item("box", 1.5, 2.5))  # 0.2 m behind the divider
    assert issues(spec, plan) == []


def test_room_without_doors_uses_the_largest_open_area() -> None:
    model = room_model(room(features=[]))
    plan = layout(item("divider", 1.5, 2, w=3, d=0.1, h=1), item("box", 1.5, 2.7))
    assert [i.node_ids for i in clearance_violations(model, plan, WALKWAY)] == [["box"]]
