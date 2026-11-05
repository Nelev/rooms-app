"""Turn a validated SceneGraph into a Layout by randomized backtracking.

An edge places its source (the child) relative to its target (the parent), as in graph_validate.py. Walls, doors and windows
are fixed roots; a node's first placing edge (adjacent ones last, none that closes a loop) picks its parent, and its other
placing edges are not enforced; a node without one is free anywhere in the room. Nodes are
placed depth group by depth group, each at a position sampled inside the box its relation allows (in the parent's frame), and
rejected if it collides, blocks a door, window or radiator, or leaves no room inside the room for its cluster (it and its
children). On a dead end the current group is cleared and the group above re-sampled, going one group further up after
every few dead ends in the same group. `facing` is not used. Sides are as seen by a viewer facing the
parent's front (the architect's rule): left_of is the parent's own right; children of an item face the same way, except that a
child in_front of an item turns to face it. A node with quantity n is placed n times, copies after the first as `<id>_2`, `<id>_3`...
"""

from collections.abc import Iterator
from dataclasses import dataclass
from math import cos, radians, sin
from random import Random
from time import monotonic
from typing import get_args

from shapely import box
from shapely.affinity import rotate, translate
from shapely.geometry.base import BaseGeometry

from app.geometry.checks import EPS, overlap
from app.geometry.graph_validate import ON_WALL
from app.geometry.room import Solid, room_model, solid, wall_frame
from app.schemas.coords import Size, Wall
from app.schemas.design import SceneGraph
from app.schemas.layout import Layout, Placement
from app.schemas.room import RoomSpec

GAP = 0.2  # m: the most free space a child leaves between itself and an item parent (none for a wall, door or window)
TRIES = 50  # positions sampled per item before its group is a dead end
RETRIES = 3  # dead ends in a group before backtracking goes one group further up
STEPS = 5_000  # positions sampled before solve() gives up: 0.1-0.4 s on an idle machine; a fixture graph needs < 400


class Unsolvable(Exception):
    """No layout found within the step limit (or the time budget)."""


@dataclass(frozen=True)
class Frame:
    """Where a parent stands: center, rotation, footprint and top; fixed parents are flat, facing into the room."""

    x: float
    y: float
    rotation: float
    width: float
    depth: float
    top: float
    fixed: bool


def fixed_frames(spec: RoomSpec) -> dict[str, Frame]:
    """The frames of the room's walls, doors and windows, by id (also used by the Critic's relation check)."""
    frames: dict[str, Frame] = {}
    for i, w in enumerate(get_args(Wall)):
        (x0, y0), (dx, dy), length = wall_frame(spec, w)
        frames[f"wall_{w}"] = Frame(x0 + dx * length / 2, y0 + dy * length / 2, 90 * i, length, 0, 0, True)
    for f in spec.features:
        (x0, y0), (dx, dy), length = wall_frame(spec, f.wall)
        t = f.offset * length
        frames[f.id] = Frame(x0 + dx * t, y0 + dy * t, 90 * get_args(Wall).index(f.wall), f.width, 0, 0, True)
    return frames


def child_box(relation: str, parent: Frame, size: Size) -> tuple[float, float, float, float, float]:
    """(x range, y range, rotation relative to the parent) of a child's center in the parent's frame, x to the parent's right."""
    pw, pd, cw, cd = parent.width, parent.depth, size.width, size.depth
    gap = 0 if parent.fixed else GAP
    across, along = abs(pw - cw) / 2, abs(pd - cd) / 2  # how far the child's center may slide along the parent's side
    front, side = pd / 2 + cd / 2, pw / 2 + cw / 2
    if relation in (*ON_WALL, "in_front") or (relation == "on" and parent.fixed):
        return -across, across, front, front + gap, 0 if parent.fixed else 180
    if relation == "behind":
        return -across, across, -front - gap, -front, 0
    y0, y1 = (front, front) if parent.fixed else (-along, along)  # beside a door or window: flush against its wall
    if relation == "left_of":  # left as seen facing the parent's front, i.e. the parent's own right (+x)
        return side, side + gap, y0, y1, 0
    if relation == "right_of":
        return -side - gap, -side, y0, y1, 0
    return -across, across, -along, along, 0  # on


def _cluster(node: str, size: Size, children: dict[str, list[tuple[str, str]]], sizes: dict[str, Size]) -> BaseGeometry:
    """The rectangle, in the node's frame, that it and its children need when each child sits as close as its relation allows."""
    shape: BaseGeometry = box(-size.width / 2, -size.depth / 2, size.width / 2, size.depth / 2)
    parent = Frame(0, 0, 0, size.width, size.depth, 0, False)
    for child, relation in children.get(node, []):
        if relation in ("on", "adjacent"):  # on stays within the parent, adjacent may go either side
            continue
        x0, x1, y0, y1, turn = child_box(relation, parent, sizes[child])
        sideways = relation in ("left_of", "right_of")
        x = {"left_of": x0, "right_of": x1}.get(relation, (x0 + x1) / 2)
        y = (y0 + y1) / 2 if sideways else y1 if relation == "behind" else y0
        shape = shape.union(translate(rotate(_cluster(child, sizes[child], children, sizes), turn, origin=(0, 0)), x, y)).envelope
    return shape


def solve(graph: SceneGraph, spec: RoomSpec, seed: int = 0, budget: float = 10.0, steps: int = STEPS) -> Layout:
    """Place every object node; the same seed gives the same layout. Raises Unsolvable after `steps` sampled positions.

    The step limit decides the outcome, so it is the same on any machine; `budget` (seconds) is only a safety net, which should
    never be reached before it on a normal one: both are checked before each group of items is placed.

    Only each node's parent edge and `in_front`'s turn are honoured: other edges of a node with several, and `facing`, are not
    checked, so a caller (B-18's solve node) should run the layout checks it needs on the result."""
    deadline, rng, room = monotonic() + budget, Random(seed), room_model(spec)
    frames = fixed_frames(spec)
    objects = [n for n in graph.nodes if n.kind == "object"]
    sizes = {n.id: n.size for n in objects if n.size}
    if missing := [n.id for n in objects if not n.size]:
        raise Unsolvable(f"No size for {', '.join(missing)}")
    items = {n.id: n.item_id for n in objects}
    parent: dict[str, tuple[str, str]] = {}  # child -> (relation, parent), from its first placing edge

    def ancestors(n: str) -> Iterator[str]:
        while n in parent:
            n = parent[n][1]
            yield n

    # adjacent edges last, and only where they close no loop: the validator gives them no parent, so it lets such loops through
    for e in sorted(graph.edges, key=lambda e: e.relation == "adjacent"):
        if e.relation != "facing" and e.source in sizes and e.source not in parent and e.source not in (e.target, *ancestors(e.target)):
            parent[e.source] = (e.relation, e.target)
    children: dict[str, list[tuple[str, str]]] = {}
    for c, (r, p) in parent.items():
        children.setdefault(p, []).append((c, r))

    def depth(n: str) -> int:
        return 1 + depth(parent[n][1]) if n in parent and parent[n][1] in sizes else 1

    groups: dict[int, list[tuple[str, str]]] = {}  # depth -> (placement id, node id), in graph order
    for n in objects:
        groups.setdefault(depth(n.id), []).extend((n.id if k == 0 else f"{n.id}_{k + 1}", n.id) for k in range(n.quantity))
    levels = [groups[d] for d in sorted(groups)]
    clusters = {n: _cluster(n, s, children, sizes) for n, s in sizes.items()}
    blockers = room.walls + room.obstacles + room.doors + room.windows + room.radiators
    floor = room.floor.buffer(EPS)
    placed: dict[str, tuple[Placement, Solid]] = {}
    sampled = 0

    def sample(node: str) -> Placement:
        size = sizes[node]
        if node not in parent:  # free: anywhere in the room, turned to any side
            x, y, rotation, z = rng.uniform(0, spec.dimensions.width), rng.uniform(0, spec.dimensions.length), 90.0 * rng.randrange(4), 0.0
        else:
            relation, target = parent[node]
            if target in sizes:
                p = placed[target][0]
                frame = Frame(p.x, p.y, p.rotation, p.size.width, p.size.depth, p.z + p.size.height, False)
            else:
                frame = frames[target]
            if relation == "adjacent":
                relation = rng.choice(["left_of", "right_of"])
            x0, x1, y0, y1, turn = child_box(relation, frame, size)
            lx = rng.choice([x0, x1]) if relation == "in_corner" else rng.uniform(x0, x1)
            ly = rng.uniform(y0, y1)
            a = radians(frame.rotation)
            x, y = frame.x + lx * cos(a) - ly * sin(a), frame.y + lx * sin(a) + ly * cos(a)
            rotation, z = (frame.rotation + turn) % 360, frame.top if relation == "on" and not frame.fixed else 0.0
        return Placement(node_id=node, item_id=items[node], x=round(x, 3), y=round(y, 3), z=z, rotation=rotation, size=size)

    def fits(p: Placement, s: Solid) -> bool:
        cluster = translate(rotate(clusters[p.node_id], p.rotation, origin=(0, 0)), p.x, p.y)
        return (
            s.top <= room.height + EPS
            and floor.contains(cluster)
            and not any(overlap(s, b) for b in blockers)
            and not any(overlap(s, o) for _, o in placed.values())
        )

    def place(level: list[tuple[str, str]]) -> bool:
        nonlocal sampled
        for pid, node in level:
            for _ in range(TRIES):
                sampled += 1
                p = sample(node)
                s = solid(p)
                if fits(p, s):
                    placed[pid] = p.model_copy(update={"node_id": pid}), s
                    break
            else:
                return False
        return True

    i, dead_ends = 0, [0] * len(levels)
    while i < len(levels):
        if sampled >= steps:
            raise Unsolvable(f"No layout found in {steps} sampled positions")
        if monotonic() > deadline:
            raise Unsolvable(f"No layout found in {budget} s")
        if place(levels[i]):
            i += 1
            continue
        # dead end: clear this group and re-sample the one above, or one more group up after every RETRIES dead ends here
        dead_ends[i] += 1
        up = min(i, 1 + dead_ends[i] // RETRIES)
        for pid, _ in (p for level in levels[i - up : i + 1] for p in level):
            placed.pop(pid, None)
        i -= up
    return Layout(placements=[placed[pid][0] for level in levels for pid, _ in level])
