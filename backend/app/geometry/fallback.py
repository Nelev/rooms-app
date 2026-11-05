"""When the solver gives up, find the items that block it, shrink or drop them, and return the best partial layout with a FallbackReport.

The whole graph is tried first. If it is Unsolvable, items are added back one at a time, must-haves before nice-to-haves and each
group in graph order (the Designer's order of importance), re-solving the kept set each time: an item whose addition makes the
kept set unsolvable blocks placement. It is replaced by the next smaller catalog item of its category (same height within
SIZE_TOLERANCE, no wider and no deeper) until one fits, else dropped. An item placed relative only to dropped items is dropped
with them (parents are always tried before their children). Every solve gets a slice of one overall budget; when it runs out,
the last layout found is returned and the items not yet finished are reported, so the fallback never takes much longer than
`budget` seconds. The scene graph is not changed: the caller applies a resized item's item_id and size (from its placement).
"""

from time import monotonic
from typing import Literal

from app.catalog.loader import load_catalog
from app.catalog.search import SIZE_TOLERANCE
from app.geometry.solver import Unsolvable, solve
from app.schemas import CatalogItem, FallbackReport, Layout, RoomSpec, SceneGraph
from app.schemas.design import SceneNode
from app.schemas.layout import FallbackChange


def smaller_variants(item_id: str | None) -> list[CatalogItem]:
    """One catalog item per smaller size of the item's category, the largest first, preferring items sharing a style tag."""
    catalog = load_catalog()
    if (item := catalog.get(item_id or "")) is None:
        return []
    s = item.size
    found: dict[tuple[float, float], CatalogItem] = {}
    for c in sorted(catalog.values(), key=lambda c: (not set(c.style_tags) & set(item.style_tags), c.id)):
        z = c.size
        if (
            c.category == item.category
            and z.width <= s.width
            and z.depth <= s.depth
            and z.width * z.depth < s.width * s.depth
            and abs(z.height - s.height) <= SIZE_TOLERANCE * s.height
        ):
            found.setdefault((z.width, z.depth), c)
    return sorted(found.values(), key=lambda c: -c.size.width * c.size.depth)


def solve_with_fallback(
    graph: SceneGraph, spec: RoomSpec, seed: int = 0, budget: float = 10.0, attempt: float = 0.5
) -> tuple[Layout, FallbackReport]:
    """The layout of the whole graph, or of the most important items that fit, and what was dropped or shrunk; at most ~`budget` s."""
    deadline = monotonic() + budget

    def attempt_solve(nodes: list[SceneNode]) -> Layout | None:
        if (left := deadline - monotonic()) <= 0:
            raise TimeoutError
        ids = {n.id for n in nodes}
        sub = SceneGraph(nodes=nodes, edges=[e for e in graph.edges if e.source in ids and e.target in ids])
        try:
            return solve(sub, spec, seed=seed, budget=min(attempt, left))
        except Unsolvable:
            return None

    fixed = [n for n in graph.nodes if n.kind != "object"]
    objects = [n for n in graph.nodes if n.kind == "object"]
    try:
        if layout := attempt_solve(fixed + objects):
            return layout, FallbackReport(summary="Every item fits")
    except TimeoutError:
        pass

    names = {n.id: n.name for n in graph.nodes}
    kept: list[SceneNode] = []
    dropped: set[str] = set()
    changes: list[FallbackChange] = []
    layout = Layout(placements=[])
    parents = {n.id: {e.target for e in graph.edges if e.source == n.id and e.relation != "facing"} for n in graph.nodes}
    by_id = {n.id: n for n in objects}
    todo: list[SceneNode] = []
    seen: set[str] = set()

    def visit(node: SceneNode) -> None:  # parents first, so a child knows whether its parent was dropped
        if node.id not in seen:
            seen.add(node.id)
            for p in sorted(parents[node.id] & by_id.keys()):
                visit(by_id[p])
            todo.append(node)

    for n in sorted(objects, key=lambda n: n.priority == "nice"):
        visit(n)
    try:
        while todo:
            node = todo[0]
            if parents[node.id] and parents[node.id] <= dropped:
                change = FallbackChange(
                    node_id=node.id,
                    action="dropped",
                    code="depends_on_dropped",
                    message=f"{node.name} goes with {', '.join(names[p] for p in sorted(parents[node.id]))}, which could not fit",
                )
            # on its own first: fast when the item fits, and when it does not, the probe beside the kept items is not needed
            elif (alone := attempt_solve(fixed + [node])) and (found := attempt_solve(fixed + kept + [node]) if kept else alone):
                layout, change = found, None
                kept.append(node)
            else:
                why = (
                    "does not fit in the room even on its own"
                    if alone is None
                    else f"does not fit beside {', '.join(n.name for n in kept)}"
                )
                code: Literal["too_big", "no_space"] = "too_big" if alone is None else "no_space"
                change = FallbackChange(node_id=node.id, action="dropped", code=code, message=f"{node.name} {why}")
                for item in smaller_variants(node.item_id):
                    variant = node.model_copy(update={"item_id": item.id, "size": item.size, "name": item.name})
                    if found := attempt_solve(fixed + kept + [variant]):
                        layout = found
                        kept.append(variant)
                        size = f"{item.size.width:g} x {item.size.depth:g} m"
                        message = f"{change.message}: replaced with {item.name} ({size})"
                        change = change.model_copy(update={"action": "resized", "item_id": item.id, "message": message})
                        break
                if change.action == "dropped":
                    dropped.add(node.id)
            if change:
                changes.append(change)
            todo.pop(0)
    except TimeoutError:
        changes += [
            FallbackChange(node_id=n.id, action="dropped", code="out_of_time", message=f"{n.name} could not be finished in time")
            for n in todo
        ]

    placed = len(objects) - sum(c.action == "dropped" for c in changes)
    summary = f"Placed {placed} of {len(objects)} items"
    for action in ("dropped", "resized"):
        if done := [names[c.node_id] for c in changes if c.action == action]:
            summary += f"; {action}: {', '.join(done)}"
    return layout, FallbackReport(changes=changes, summary=summary)
