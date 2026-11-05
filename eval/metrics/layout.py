"""Deterministic metrics of a Layout in its room and against its brief, on top of the B-04 checks in app/geometry/checks.py.

Per layout: `out_of_bounds`, `overlap_volume`, `clearance_pass_rate`, `blocked_openings`, `cost`, `budget_fit` and
`must_have_coverage`; `layout_metrics` computes them all (plus the item count). Over a set of layouts: I-Design's
`out_of_bounds_rate` and `bbox_loss`.
"""

import re
from collections.abc import Iterable
from itertools import combinations, product
from statistics import fmean

from app.catalog.loader import load_catalog
from app.geometry import checks
from app.geometry.room import Solid, room_model, solid
from app.schemas import Brief, CatalogItem, Layout, RoomSpec

WALKWAY = 0.6  # m, the narrowest walkway a person passes through
NUMBERS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6}


def out_of_bounds(spec: RoomSpec, layout: Layout) -> bool:
    """Whether any item sticks out of the room: its footprint past the floor (through a wall) or its top above the ceiling.

    Counting the ceiling extends I-Design's floor-boundary definition, so rates are not 1:1 comparable with the paper's."""
    room = room_model(spec)
    through_wall = any(solid(p).shape.difference(room.floor).area > checks.EPS for p in layout.placements)
    return through_wall or bool(checks.above_ceiling(room, layout))


def out_of_bounds_rate(scenes: Iterable[tuple[RoomSpec, Layout]]) -> float:
    """I-Design's Out-of-Boundary rate (OOB, Celen et al. 2024, arXiv:2404.02838, section 4.2): "if any bounding boxes are outside
    the designated room boundaries within a scene, that scene is deemed invalid"; OOB is "the ratio of invalid scenes to the total
    number of generated scenes"; 0 for no scenes."""
    invalid = [out_of_bounds(spec, layout) for spec, layout in scenes]
    return fmean(invalid) if invalid else 0.0


def _intersection_volume(a: Solid, b: Solid) -> float:
    return a.shape.intersection(b.shape).area * max(0.0, min(a.top, b.top) - max(a.bottom, b.bottom))


def overlap_volume(spec: RoomSpec, layout: Layout) -> float:
    """The total volume (m3) of the intersections of the items' bounding boxes (as rotated, so a tight fit) with each other and with
    the room's fixed obstacles (kept furniture, radiators, columns, built-ins). Counting obstacles extends I-Design's object-object
    BBL, so values are not 1:1 comparable with the paper's."""
    items = [solid(p) for p in layout.placements]
    pairs = [*combinations(items, 2), *product(items, room_model(spec).obstacles)]
    return sum(_intersection_volume(a, b) for a, b in pairs)


def bbox_loss(scenes: Iterable[tuple[RoomSpec, Layout]]) -> float:
    """I-Design's Bounding Box Loss (BBL, Celen et al. 2024, arXiv:2404.02838, section 4.2): "the average volume of bounding box
    intersections across generated scenes", here in m3 (see `overlap_volume`); 0 for no scenes."""
    volumes = [overlap_volume(spec, layout) for spec, layout in scenes]
    return fmean(volumes) if volumes else 0.0


def clearance_pass_rate(spec: RoomSpec, layout: Layout, min_walkway: float = WALKWAY) -> float:
    """The share of items a person can walk up to (B-04's clearance check); 1 for an empty layout."""
    if not layout.placements:
        return 1.0
    return 1 - len(checks.clearance_violations(room_model(spec), layout, min_walkway)) / len(layout.placements)


def blocked_openings(spec: RoomSpec, layout: Layout) -> int:
    """The (item, opening) pairs where an item is in a door's swing or rises in front of a window above its sill."""
    room = room_model(spec)
    return len(checks.blocked_openings(room, layout) + checks.blocked_windows(room, layout))


def cost(layout: Layout, catalog: dict[str, CatalogItem]) -> float:
    """EUR: the catalog price of every placed item; placements without a catalog item (or with an unknown one) count 0."""
    return sum(catalog[p.item_id].price for p in layout.placements if p.item_id in catalog)


def budget_fit(layout: Layout, brief: Brief, catalog: dict[str, CatalogItem]) -> bool:
    return cost(layout, catalog) <= brief.budget


def _words(text: str) -> list[str]:
    """Lowercase words, singular (a trailing s dropped)."""
    return [w[:-1] if w.endswith("s") and not w.endswith("ss") and len(w) > 3 else w for w in re.findall(r"[a-z]+", text.lower())]


def must_have_coverage(layout: Layout, brief: Brief, catalog: dict[str, CatalogItem]) -> float:
    """The share of must-haves covered; 1 when the brief has none.

    A must-have is free text, so it is matched leniently: by its head noun (its last word, ignoring a trailing "for ..."), found
    among the words of a placement's node id, catalog name or catalog category, and as many times as a leading number word asks
    ("two nightstands" needs two). Modifiers are ignored ("double bed" is covered by any bed) and synonyms are not matched
    ("chest of drawers" needs a drawer, "shelving unit" a unit).
    """
    if not brief.must_haves:
        return 1.0
    items = [(p, catalog.get(p.item_id or "")) for p in layout.placements]
    texts = [set(_words(f"{p.node_id} {item.name} {item.category}" if item else p.node_id)) for p, item in items]
    covered = 0
    for must in brief.must_haves:
        words = _words(must.split(" for ")[0])
        needed = NUMBERS.get(words[0], 1) if words else 1
        covered += bool(words) and sum(words[-1] in t for t in texts) >= needed
    return covered / len(brief.must_haves)


def layout_metrics(spec: RoomSpec, brief: Brief, layout: Layout, catalog: dict[str, CatalogItem] | None = None) -> dict[str, float | bool]:
    """Every layout metric of one design, by name."""
    catalog = load_catalog() if catalog is None else catalog
    return {
        "out_of_bounds": out_of_bounds(spec, layout),
        "overlap_volume": overlap_volume(spec, layout),
        "clearance_pass_rate": clearance_pass_rate(spec, layout),
        "blocked_openings": blocked_openings(spec, layout),
        "item_count": len(layout.placements),
        "cost": cost(layout, catalog),
        "budget_fit": budget_fit(layout, brief, catalog),
        "must_have_coverage": must_have_coverage(layout, brief, catalog),
    }
