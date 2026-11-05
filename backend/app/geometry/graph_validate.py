"""Check a SceneGraph against its room before solving. An edge places its source (the child) relative to its target (the parent).

Codes: duplicate_node, unknown_node, cycle, not_a_wall, pushed_out, too_small, between_adjacent, blocks_opening, blocks_window.
Children are assumed to turn their smaller side toward their parent, and only direct children of a wall-placed node are checked.
"""

from collections import Counter, defaultdict
from graphlib import CycleError, TopologicalSorter
from math import inf
from typing import cast, get_args

from app.geometry.checks import EPS, blocked_openings, blocked_windows
from app.geometry.room import Room, _wall_frame, room_model
from app.schemas.coords import Size, Wall
from app.schemas.design import SceneGraph
from app.schemas.layout import Layout, Placement, ValidationIssue, ValidationReport
from app.schemas.room import RoomSpec

OPPOSITE = {"left_of": "right_of", "right_of": "left_of", "in_front": "behind", "behind": "in_front"}
ON_WALL = ("against_wall", "in_corner")
STEP = 0.01  # m between the positions tried along a wall


def _issue(code: str, message: str, *node_ids: str) -> ValidationIssue:
    return ValidationIssue(code=code, message=message, node_ids=list(node_ids))


def _blocks(room: Room, spec: RoomSpec, node_id: str, size: Size, wall: Wall, t: float) -> list[ValidationIssue]:
    """The doors and windows an item blocks standing flush against `wall`, centered `t` m from the wall's start corner."""
    (x0, y0), (dx, dy), _ = _wall_frame(spec, wall)
    n = size.depth / 2  # along the inward normal (-dy, dx)
    rotation = 90 * get_args(Wall).index(wall)  # front facing into the room
    layout = Layout(placements=[Placement(node_id=node_id, x=x0 + dx * t - dy * n, y=y0 + dy * t + dx * n, rotation=rotation, size=size)])
    return blocked_openings(room, layout) + blocked_windows(room, layout)


def validate_graph(graph: SceneGraph, spec: RoomSpec) -> ValidationReport:
    features = {f.id: f for f in spec.features}
    nodes = {n.id: n for n in graph.nodes}
    issues = [
        _issue("duplicate_node", f"More than one node has the id {i}", i) for i, k in Counter(n.id for n in graph.nodes).items() if k > 1
    ]
    walls = {f"wall_{w}" for w in get_args(Wall)}
    missing = {
        i
        for i, n in nodes.items()
        if n.kind != "object" and not (i in walls if n.kind == "wall" else i in features and features[i].type == n.kind)
    }
    issues += [_issue("unknown_node", f"{i} is not a {nodes[i].kind} of the room", i) for i in sorted(missing)]
    for e in graph.edges:
        issues += [
            _issue("unknown_node", f"{e.source} {e.relation.replace('_', ' ')} {e.target} refers to an unknown node {i}", i)
            for i in (e.source, e.target)
            if i not in nodes
        ]
    edges = [e for e in graph.edges if {e.source, e.target} <= nodes.keys() - missing]

    parents: defaultdict[str, set[str]] = defaultdict(set)
    for e in edges:
        if e.relation not in ("facing", "adjacent"):  # facing only turns an item and adjacent is symmetric, so neither has a parent
            parents[e.source].add(e.target)
    while True:  # report every loop: break each one found and look again
        try:
            TopologicalSorter(parents).prepare()
            break
        except CycleError as err:
            loop: list[str] = err.args[1]  # each node is a parent of the next
            issues.append(_issue("cycle", f"The relations go round in a loop: {' -> '.join(loop)}", *loop[:-1]))
            parents[loop[1]].discard(loop[0])

    sizes = {i: n.size for i, n in nodes.items() if n.size}
    along = {w: _wall_frame(spec, w)[2] for w in get_args(Wall)}
    across = {w: spec.dimensions.length if w in "AC" else spec.dimensions.width for w in get_args(Wall)}
    on_wall: dict[str, Wall] = {}
    for e in edges:
        if e.relation in ON_WALL and nodes[e.target].kind != "wall":
            issues.append(
                _issue(
                    "not_a_wall", f"{e.source} cannot be {e.relation.replace('_', ' ')} {e.target}, which is not a wall", e.source, e.target
                )
            )
        elif e.relation in ON_WALL and e.source in sizes:
            on_wall[e.source] = cast(Wall, e.target.removeprefix("wall_"))

    # (child, direction, parent), each relation also read from its other end
    relations = sorted(
        {(e.source, e.relation, e.target) for e in edges}
        | {(e.target, OPPOSITE[e.relation], e.source) for e in edges if e.relation in OPPOSITE}
    )
    for p, wall in on_wall.items():
        ps = sizes[p]
        if ps.width > along[wall] + EPS:
            issues.append(_issue("pushed_out", f"{p} is {ps.width} m wide, wall {wall} only {along[wall]} m", p, f"wall_{wall}"))
        for c, r, parent in relations:
            if parent != p or c not in sizes:
                continue
            span = min(sizes[c].width, sizes[c].depth)
            need, room_side = {
                "behind": (inf, 0.0),
                "in_front": (ps.depth + span, across[wall]),
                "left_of": (ps.width + span, along[wall]),
                "right_of": (ps.width + span, along[wall]),
            }.get(r, (0.0, 0.0))
            if need > room_side + EPS:
                issues.append(_issue("pushed_out", f"{c} {r.replace('_', ' ')} {p} would be pushed out of the room by wall {wall}", c, p))

    sides: defaultdict[tuple[str, str], list[str]] = defaultdict(list)
    for c, r, parent in relations:
        if r in (*OPPOSITE, "on") and c in sizes and parent in sizes:
            sides[parent, r].append(c)
    for (p, r), children in sides.items():
        ps, count = sizes[p], sum(nodes[c].quantity for c in children)
        if r == "on":  # everything on a parent must fit on its top
            need, have = sum(sizes[c].width * sizes[c].depth * nodes[c].quantity for c in children), ps.width * ps.depth
        else:  # a single child may overhang its parent's side, several must line up along it
            need, have = (
                sum(min(sizes[c].width, sizes[c].depth) * nodes[c].quantity for c in children),
                ps.width if r in ("in_front", "behind") else ps.depth,
            )
        if (r == "on" or count > 1) and need > have + EPS:
            issues.append(_issue("too_small", f"{p} is too small for {', '.join(children)} {r.replace('_', ' ')} it", p, *children))

    direction = {(c, parent): r for c, r, parent in relations if r in OPPOSITE}
    for e in edges:
        if e.relation == "adjacent":
            for c in nodes:
                side = direction.get((c, e.source))
                if side and c not in (e.source, e.target) and direction.get((c, e.target)) == OPPOSITE[side]:
                    issues.append(
                        _issue(
                            "between_adjacent",
                            f"{c} sits between {e.source} and {e.target}, which should be adjacent",
                            c,
                            e.source,
                            e.target,
                        )
                    )

    room = room_model(spec)
    for e in edges:
        size, target = sizes.get(e.source), nodes[e.target]
        if size is None:
            continue
        if e.relation in ON_WALL and target.kind == "wall":  # the item must fit somewhere along its wall without blocking anything
            wall = cast(Wall, e.target.removeprefix("wall_"))
            length = along[wall]
            if size.width > length + EPS:
                continue  # already pushed_out
            stops = round((length - size.width) / STEP)
            spots = (
                [size.width / 2, length - size.width / 2]
                if e.relation == "in_corner"
                else [size.width / 2 + k * STEP for k in range(stops + 1)]
            )
            tried: list[list[ValidationIssue]] = []
            for t in spots:
                tried.append(_blocks(room, spec, e.source, size, wall, t))
                if not tried[-1]:
                    break
            where = "in either corner of" if e.relation == "in_corner" else "anywhere along"
            issues += [i.model_copy(update={"message": f"{i.message} {where} wall {wall}"}) for i in min(tried, key=len)]
        elif e.relation in ("in_front", "on") and target.kind in ("door", "window"):
            f = features[e.target]
            issues += _blocks(room, spec, e.source, size, f.wall, f.offset * along[f.wall])
    return ValidationReport(issues=issues)
