"""Pure checks of a Layout in a Room, each returning ValidationIssues (codes: collision, clearance, blocks_opening,
blocks_window, blocks_radiator, above_ceiling). Overlaps count only with positive area and positive height in common."""

from collections.abc import Iterable
from itertools import combinations, product

from shapely import get_parts, unary_union

from app.geometry.room import Room, Solid, solid
from app.schemas.layout import Layout, ValidationIssue

EPS = 1e-6


def overlap(a: Solid, b: Solid) -> bool:
    return min(a.top, b.top) - max(a.bottom, b.bottom) > EPS and a.shape.intersection(b.shape).area > EPS


def _issues(pairs: Iterable[tuple[Solid, Solid]], code: str, verb: str) -> list[ValidationIssue]:
    return [ValidationIssue(code=code, message=f"{a.id} {verb} {b.id}", node_ids=[a.id, b.id]) for a, b in pairs if overlap(a, b)]


def _against(layout: Layout, zones: list[Solid], code: str, verb: str) -> list[ValidationIssue]:
    return _issues(product([solid(p) for p in layout.placements], zones), code, verb)


def collisions(room: Room, layout: Layout) -> list[ValidationIssue]:
    """Placements overlapping each other, a wall (sticking out of the room) or a fixed obstacle."""
    items = [solid(p) for p in layout.placements]
    pairs = [*combinations(items, 2), *product(items, room.walls + room.obstacles)]
    return _issues(pairs, "collision", "overlaps")


def blocked_openings(room: Room, layout: Layout) -> list[ValidationIssue]:
    """Placements in a door's swing (or, for a door opening outward, the floor in front of it)."""
    return _against(layout, room.doors, "blocks_opening", "blocks the door swing of")


def blocked_windows(room: Room, layout: Layout) -> list[ValidationIssue]:
    """Placements in front of a window that rise above its sill."""
    return _against(layout, room.windows, "blocks_window", "rises above the sill of")


def blocked_radiators(room: Room, layout: Layout) -> list[ValidationIssue]:
    """Placements in front of a radiator, below its top."""
    return _against(layout, room.radiators, "blocks_radiator", "stands in front of")


def above_ceiling(room: Room, layout: Layout) -> list[ValidationIssue]:
    return [
        ValidationIssue(code="above_ceiling", message=f"{p.node_id} is taller than the {room.height} m ceiling", node_ids=[p.node_id])
        for p in layout.placements
        if p.z + p.size.height > room.height + EPS
    ]


def clearance_violations(room: Room, layout: Layout, min_walkway: float) -> list[ValidationIssue]:
    """Placements a person min_walkway wide cannot walk up to from a door (from the largest open area if the room has none),
    except those within half a walkway of a placement they can walk up to (a nightstand by the bed, a chair under the desk)."""
    r = min_walkway / 2
    items = [solid(p) for p in layout.placements]
    free = room.floor.difference(unary_union([s.shape for s in items + room.obstacles]))
    areas = list(get_parts(free.buffer(-r)))  # where the walker's center fits
    if room.doors:
        areas = [a for a in areas if any(a.distance(d.shape) <= EPS for d in room.doors)]
    elif areas:
        areas = [max(areas, key=lambda a: a.area)]
    reached = [s for s in items if any(a.distance(s.shape) <= r + EPS for a in areas)]
    return [
        ValidationIssue(code="clearance", message=f"{s.id} cannot be reached through a {min_walkway} m walkway", node_ids=[s.id])
        for s in items
        if not any(t.shape.distance(s.shape) <= r + EPS for t in reached)
    ]
