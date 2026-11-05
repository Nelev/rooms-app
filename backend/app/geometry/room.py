"""A Shapely model of a RoomSpec: walls, door swings, window and radiator zones and fixed obstacles, each a Solid."""

from dataclasses import dataclass
from typing import get_args

from shapely import Point, Polygon, box
from shapely.affinity import rotate
from shapely.geometry.base import BaseGeometry

from app.schemas.coords import Wall
from app.schemas.layout import Placement
from app.schemas.room import Feature, KeptItem, RoomSpec

RADIATOR_DEPTH = 0.1  # radiators, columns and built-ins have no depth in RoomSpec: assumed depths
FIXTURE_DEPTH = 0.3
FRONT_ZONE = 0.3  # the strip in front of a window or radiator (beyond its own depth) that must stay clear below its top


@dataclass(frozen=True)
class Solid:
    """A footprint extruded from bottom to top (2.5D)."""

    id: str
    shape: BaseGeometry
    bottom: float
    top: float


@dataclass(frozen=True)
class Room:
    """Walls are the ground beyond each wall (up to the room's width plus length away), so any item outside the room collides."""

    floor: Polygon
    height: float
    walls: list[Solid]
    doors: list[Solid]  # the floor a door sweeps (in) or needs in front of it (out)
    windows: list[Solid]  # the zone in front of each window, from sill to top
    radiators: list[Solid]  # the zone in front of each radiator, from its bottom to its top
    obstacles: list[Solid]  # radiators, columns, built-ins and kept furniture


def footprint(item: Placement | KeptItem, x: float, y: float, rotation: float) -> Polygon:
    """The item's floor rectangle centered on (x, y), turned counterclockwise by rotation degrees."""
    w, d = item.size.width, item.size.depth
    return rotate(box(x - w / 2, y - d / 2, x + w / 2, y + d / 2), rotation, origin=(x, y))


def solid(p: Placement) -> Solid:
    return Solid(p.node_id, footprint(p, p.x, p.y, p.rotation), p.z, p.z + p.size.height)


def _wall_frame(spec: RoomSpec, wall: Wall) -> tuple[tuple[float, float], tuple[float, float], float]:
    """(start corner, unit direction, length) of a wall; the inward normal is the direction turned 90 degrees counterclockwise."""
    w, ln = spec.dimensions.width, spec.dimensions.length
    return {"A": ((0, 0), (1, 0), w), "B": ((w, 0), (0, 1), ln), "C": ((w, ln), (-1, 0), w), "D": ((0, ln), (0, -1), ln)}[wall]


def _along(spec: RoomSpec, wall: Wall, offset: float, width: float, start: float, depth: float) -> Polygon:
    """The rectangle `width` wide centered at `offset` along the wall, from `start` to `start + depth` into the room."""
    (x0, y0), (dx, dy), length = _wall_frame(spec, wall)
    nx, ny = -dy, dx
    cx, cy = x0 + dx * offset * length, y0 + dy * offset * length
    return Polygon(
        [
            (cx + s * dx * width / 2 + nx * n, cy + s * dy * width / 2 + ny * n)
            for s, n in ((-1, start), (1, start), (1, start + depth), (-1, start + depth))
        ]
    )


def _door(spec: RoomSpec, f: Feature) -> Solid:
    zone: BaseGeometry = _along(spec, f.wall, f.offset, f.width, 0, f.width)
    if f.swing == "in":  # a quarter disc about the hinge; seen from inside, left is along the wall's direction
        (x0, y0), (dx, dy), length = _wall_frame(spec, f.wall)
        t = f.offset * length + (f.width / 2 if f.hinge == "left" else -f.width / 2)
        hinge = Point(x0 + dx * t, y0 + dy * t)
        zone = zone.intersection(hinge.buffer(f.width))
    return Solid(f.id, zone, 0, f.height)


def room_model(spec: RoomSpec) -> Room:
    dims = spec.dimensions
    doors: list[Solid] = []
    windows: list[Solid] = []
    radiators: list[Solid] = []
    obstacles: list[Solid] = []
    out = dims.width + dims.length
    walls = [Solid(f"wall_{w}", _along(spec, w, 0.5, _wall_frame(spec, w)[2] + 2 * out, -out, out), 0, dims.height) for w in get_args(Wall)]
    for f in spec.features:
        top = f.sill_height + f.height
        if f.type == "door":
            doors.append(_door(spec, f))
        elif f.type == "window":
            windows.append(Solid(f.id, _along(spec, f.wall, f.offset, f.width, 0, FRONT_ZONE), f.sill_height, top))
        elif f.type == "radiator":
            obstacles.append(Solid(f.id, _along(spec, f.wall, f.offset, f.width, 0, RADIATOR_DEPTH), f.sill_height, top))
            radiators.append(Solid(f.id, _along(spec, f.wall, f.offset, f.width, RADIATOR_DEPTH, FRONT_ZONE), f.sill_height, top))
        elif f.type in ("column", "built_in"):
            obstacles.append(Solid(f.id, _along(spec, f.wall, f.offset, f.width, 0, FIXTURE_DEPTH), f.sill_height, top))
    obstacles += [Solid(k.id, footprint(k, k.x, k.y, k.rotation), 0, k.size.height) for k in spec.kept_furniture]
    return Room(box(0, 0, dims.width, dims.length), dims.height, walls, doors, windows, radiators, obstacles)
