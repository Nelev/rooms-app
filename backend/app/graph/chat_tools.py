"""The chat edit tools (B-21): each edits the thread's design as the chat asks, or refuses with the reason.

As in CoA's react_agent/tools.py, a tool takes the state (InjectedState) and returns a Command: its state update (the scene graph,
the layout, the candidates) plus a short ToolMessage for the model. A refused edit's ToolMessage has status "error" and the Command
no update, so the layout stays as it was.

Every other item stays where it is (pinned): an edit is checked against them with B-04's checks (collisions, walls, doors, windows,
radiators, ceiling, the floor, and no item left unreachable that was not) before it is applied. A moved or rotated item carries the
items placed relative to it (its children, by the B-11 solver's parent edges) and loses the relations its new place breaks. An added
item, and a swapped item that no longer fits where the old one stood, is re-solved locally: the B-11 solver places it, with what it
carries, among the other items pinned.
"""

from math import cos, radians, sin
from typing import Annotated, Any, Literal

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.config import get_store
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from app.catalog.loader import load_catalog
from app.catalog.search import Filters, search_sync
from app.geometry import checks
from app.geometry.room import room_model, solid
from app.geometry.solver import Unsolvable, fixed_frames, parents, solve
from app.graph.nodes.solve import LAYOUT_CHECKS, WALKWAY, unmet_relations
from app.graph.nodes.source import swap_rule, words
from app.schemas import Brief, CatalogItem, Layout, RoomSpec, SceneGraph
from app.schemas.design import SceneEdge, SceneNode
from app.schemas.layout import Placement

State = Annotated[dict[str, Any], InjectedState]  # not RunState: the tool's input is validated, as in CoA
CallId = Annotated[str, InjectedToolCallId]
PlacingRelation = Literal["left_of", "right_of", "in_front", "behind", "on", "against_wall", "in_corner", "adjacent"]

SEEDS = 3  # solver seeds tried for an item re-solved locally
ATTEMPT = 0.5  # s per solve (as the solve node's)
OPTIONS = 5  # catalog items tried, the best first, for a swap or an addition


def _reply(name: str, call_id: str, content: str, update: dict[str, Any] | None = None) -> Command[Any]:
    """The tool's result: with an update, the edit applied; without one, refused (status "error"), the reason in the message."""
    status: Literal["success", "error"] = "success" if update is not None else "error"
    message = ToolMessage(content if update is not None else f"refused: {content}", name=name, tool_call_id=call_id, status=status)
    return Command(update={**(update or {}), "messages": [message]})


def node_of(graph: SceneGraph, placement_id: str) -> str:
    """The node a placement belongs to: copies of a node are placed as <id>_2, <id>_3..."""
    return placement_id if any(n.id == placement_id for n in graph.nodes) else placement_id.rsplit("_", 1)[0]


def _objects(graph: SceneGraph) -> dict[str, SceneNode]:
    return {n.id: n for n in graph.nodes if n.kind == "object"}


def _unknown(state: dict[str, Any], node_id: str) -> str:
    items = ", ".join(f"{n.id} ({n.name})" for n in _objects(state["scene_graph"]).values())
    return f"there is no item {node_id} in the design (the kept furniture and the room cannot be edited); the items are: {items}"


def problems(spec: RoomSpec, before: Layout, layout: Layout, ids: set[str]) -> list[str]:
    """Why the placements `ids` cannot stand where they are in `layout`, edited from `before`: B-04's checks, the floor, and the
    items it leaves unreachable that were not."""
    room = room_model(spec)
    floor = room.floor.buffer(checks.EPS)
    found = [i.message for check in LAYOUT_CHECKS for i in check(room, layout) if set(i.node_ids) & ids]
    found += [f"{p.node_id} sticks out of the room" for p in layout.placements if p.node_id in ids and not floor.contains(solid(p).shape)]
    if not found:  # the costliest check last
        was = {i.message for i in checks.clearance_violations(room, before, WALKWAY)}
        found = [i.message for i in checks.clearance_violations(room, layout, WALKWAY) if i.message not in was]
    return list(dict.fromkeys(found))


def _with(layout: Layout, *placements: Placement) -> Layout:
    """`layout` with `placements` replacing those of the same id, new ones appended."""
    new = {p.node_id: p for p in placements}
    kept = [new.pop(p.node_id, p) for p in layout.placements]
    return Layout(placements=kept + list(new.values()))


def _group(graph: SceneGraph, layout: Layout, placement_id: str) -> list[Placement]:
    """The placement, first, and those it carries: of the nodes placed relative to its node, directly or through others (by their
    first placing edge); a copy of a node (<id>_2...) carries nothing."""
    parent = {child: target for child, (_, target) in parents(graph).items()}
    nodes, grew = {placement_id}, True
    while grew:
        more = {c for c, p in parent.items() if p in nodes} - nodes
        grew, nodes = bool(more), nodes | more
    others = [q for q in layout.placements if q.node_id != placement_id and node_of(graph, q.node_id) in nodes - {placement_id}]
    return [p for p in layout.placements if p.node_id == placement_id] + others


def _rigid(group: list[Placement], x: float, y: float, rotation: float) -> list[Placement]:
    """`group` moved as one piece: its first placement's center to (x, y), turned to `rotation`."""
    p, turn = group[0], (rotation - group[0].rotation) % 360
    a = radians(turn)
    return [
        q.model_copy(
            update={
                "x": round(x + (q.x - p.x) * cos(a) - (q.y - p.y) * sin(a), 3),
                "y": round(y + (q.x - p.x) * sin(a) + (q.y - p.y) * cos(a), 3),
                "rotation": (q.rotation + turn) % 360,
            }
        )
        for q in group
    ]


def place(spec: RoomSpec, layout: Layout, graph: SceneGraph, ids: set[str]) -> Layout | None:
    """The local re-solve: `layout` with the placements `ids` (of nodes of `graph`, maybe not in `layout` yet) placed anew by the
    B-11 solver, every other placement pinned; None when no seed of SEEDS gives a place that passes `problems`."""
    pinned = Layout(placements=[p for p in layout.placements if p.node_id not in ids])
    placed = {node_of(graph, i) for i in ids} | {node_of(graph, p.node_id) for p in pinned.placements}
    graph = graph.model_copy(update={"nodes": [n for n in graph.nodes if n.kind != "object" or n.id in placed]})  # not what B-12 dropped
    for seed in range(SEEDS):
        try:
            new = solve(graph, spec, seed, ATTEMPT, pinned)
        except Unsolvable:
            return None
        if not problems(spec, layout, new, ids):
            return new
    return None


def _transform(state: dict[str, Any], name: str, call_id: str, placement_id: str, x: float, y: float, rotation: float) -> Command[Any]:
    """Move `placement_id`'s center to (x, y), turned to `rotation`, with the items it carries; refused where it does not fit."""
    graph, spec, layout = state["scene_graph"], state["room_spec"], state["layout"]
    if not any(p.node_id == placement_id for p in layout.placements):
        return _reply(name, call_id, _unknown(state, placement_id))
    moved = _rigid(_group(graph, layout, placement_id), x, y, rotation)
    new = _with(layout, *moved)
    ids = {q.node_id for q in moved}
    if found := problems(spec, layout, new, ids):
        return _reply(name, call_id, "; ".join(found))
    moved_nodes = {node_of(graph, i) for i in ids}
    unmet = {(i.node_ids[0], i.node_ids[1]) for i in unmet_relations(graph, spec, new) if set(i.node_ids) & moved_nodes}
    edges = [e for e in graph.edges if (e.source, e.target) not in unmet]
    carried = f" with {', '.join(sorted(ids - {placement_id}))}" if len(ids) > 1 else ""
    what = f"{placement_id}{carried} now at x={x:.2f}, y={y:.2f}, rotation {rotation % 360:g}"
    dropped = f"; relations it no longer keeps were dropped: {', '.join(f'{s} to {t}' for s, t in sorted(unmet))}" if unmet else ""
    return _reply(name, call_id, what + dropped, {"layout": new, "scene_graph": graph.model_copy(update={"edges": edges})})


@tool
def get_layout(state: State, tool_call_id: CallId) -> Command[Any]:
    """The room (walls, doors, windows, radiators, kept furniture) and every item of the design: its id, name, catalog item and
    price, center (x, y in m), rotation (degrees) and size, and its relations."""
    spec, graph, layout = state["room_spec"], state["scene_graph"], state["layout"]
    catalog, frames, d = load_catalog(), fixed_frames(spec), spec.dimensions
    lines = [
        f"the layout: {len(layout.placements)} items",
        f"room {d.width} x {d.length} m, ceiling {d.height} m; walls: A y=0, B x={d.width}, C y={d.length}, D x=0",
        *(
            f"{f.id}: {f.type} on wall {f.wall}, centered at x={frames[f.id].x:.2f}, y={frames[f.id].y:.2f}, {f.width} m wide"
            for f in spec.features
        ),
        *(
            f"{k.id} (kept {k.name}, fixed): x={k.x}, y={k.y}, rotation {k.rotation:g}, size {k.size.width} x {k.size.depth} m"
            for k in spec.kept_furniture
        ),
    ]
    for p in layout.placements:
        node = node_of(graph, p.node_id)
        item = catalog.get(p.item_id or "")
        name = next((n.name for n in graph.nodes if n.id == node), node)
        relations = ", ".join(f"{e.relation} {e.target}" for e in graph.edges if e.source == node)
        s = p.size
        what = f"{item.name}, {item.price:g} EUR" if item else "no catalog item"
        lines.append(
            f"{p.node_id} ({name}; {what}): x={p.x}, y={p.y}, z={p.z}, rotation {p.rotation:g}, "
            f"size {s.width} x {s.depth} x {s.height} m; {relations or 'no relations'}"
        )
    return _reply("get_layout", tool_call_id, "\n".join(lines), {})


@tool
def move_item(node_id: str, x: float, y: float, state: State, tool_call_id: CallId) -> Command[Any]:
    """Move an item (with what stands on or by it) so its center is at (x, y), in meters; it keeps its rotation."""
    p = next((p for p in state["layout"].placements if p.node_id == node_id), None)
    return _transform(state, "move_item", tool_call_id, node_id, x, y, p.rotation if p else 0)


@tool
def rotate_item(node_id: str, rotation: float, state: State, tool_call_id: CallId) -> Command[Any]:
    """Turn an item in place (with what stands on or by it) to `rotation` degrees, counterclockwise; 0 faces +y."""
    p = next((p for p in state["layout"].placements if p.node_id == node_id), None)
    return _transform(state, "rotate_item", tool_call_id, node_id, p.x if p else 0, p.y if p else 0, rotation % 360)


def _budget_left(state: dict[str, Any], without: str | None = None) -> float:
    """EUR of the brief's budget not spent on the items of the layout (except `without`'s)."""
    catalog, graph = load_catalog(), state["scene_graph"]
    spent = sum(
        catalog[p.item_id].price for p in state["layout"].placements if p.item_id in catalog and node_of(graph, p.node_id) != without
    )
    return Brief.model_validate(state["brief"]).budget - spent


def _search(request: str, about: str, category: str, max_price: float) -> list[CatalogItem]:
    """The catalog items of `category` within `max_price`, the most like the request and what it is `about` first (B-08's search),
    of the color the request names if it names one."""
    found = search_sync(get_store(), f"{request} {about}", Filters(category, max_price=max_price), limit=100)
    colors = words(request) & {i.color for i in found if i.color}
    return [i for i in found if not colors or i.color in colors]


@tool
def swap_item(node_id: str, request: str, state: State, tool_call_id: CallId, item_id: str | None = None) -> Command[Any]:
    """Replace an item's catalog item: `request` says what the user wants of the new one (e.g. "cheaper", "smaller", "white",
    "larger oak"); `item_id` picks a catalog item by id instead. The new item must be of the same category and within the budget."""
    graph, layout, catalog = state["scene_graph"], state["layout"], load_catalog()
    node = _objects(graph).get(node_id)
    if node is None:
        return _reply("swap_item", tool_call_id, _unknown(state, node_id))
    current = catalog.get(node.item_id or "")
    category = next((o.category for o in state["design_brief"].objects if o.id == node_id), current.category if current else "")
    max_price = _budget_left(state, node_id) / node.quantity
    if item_id:
        options = [catalog[item_id]] if item_id in catalog and catalog[item_id].category == category else []
        why = f"{item_id} is not a {category} of the catalog"
        if options and options[0].price > max_price:
            why, options = f"{item_id} costs {options[0].price:g} EUR, and only {max_price:.0f} EUR of the budget is left for it", []
    else:
        rule = swap_rule(request, current) if current else lambda i: True
        about = " ".join(filter(None, [node.name, node.style, node.material]))
        options = [i for i in _search(request, about, category, max_price) if i != current and rule(i)]
        why = f"the catalog has no {category} that is {request or 'different'} within the {max_price:.0f} EUR left of the budget"
    copies = [p for p in layout.placements if node_of(graph, p.node_id) == node_id]
    for item in options[:OPTIONS]:
        nodes = [n.model_copy(update={"item_id": item.id, "size": item.size}) if n.id == node_id else n for n in graph.nodes]
        new, swapped = layout, graph.model_copy(update={"nodes": nodes})
        for p in copies:  # where the old item stood, else re-solved with what it carries and the others pinned
            q = p.model_copy(update={"item_id": item.id, "size": item.size})
            if not problems(state["room_spec"], layout, _with(new, q), {q.node_id}):
                new = _with(new, q)
            elif moved := place(state["room_spec"], new, swapped, {g.node_id for g in _group(swapped, new, q.node_id)}):
                new = moved
            else:
                break
        else:
            old = state.get("candidates", {}).get(node_id, [])
            candidates = {**state.get("candidates", {}), node_id: [item, *(c for c in old if c != item)]}
            was = f" (was {current.name}, {current.price:g} EUR)" if current else ""
            message = f"{node_id} is now {item.name}, {item.price:g} EUR, {item.size.width} x {item.size.depth} m{was}"
            return _reply("swap_item", tool_call_id, message, {"scene_graph": swapped, "layout": new, "candidates": candidates})
        what = f"{item_id} does not fit" if item_id else f"no {category} that is {request or 'different'} fits"
        why = f"{what} in the room beside the other items"
    return _reply("swap_item", tool_call_id, why)


@tool
def add_item(
    name: str, category: str, relation: PlacingRelation, target: str, state: State, tool_call_id: CallId, request: str = ""
) -> Command[Any]:
    """Add a new item from the catalog: `name` (e.g. "floor lamp"), its catalog `category`, and where it goes: `relation` to the
    `target` item, wall (wall_A to wall_D), door or window id (not kept furniture). `request` says what the user wants of it
    (e.g. "white", "small")."""
    graph, spec, catalog = state["scene_graph"], state["room_spec"], load_catalog()
    categories = sorted({c.category for c in catalog.values()})
    if category not in categories:
        return _reply("add_item", tool_call_id, f"the catalog has no {category}; its categories are {', '.join(categories)}")
    kinds = {f.id: f.type for f in spec.features if f.type in ("door", "window")} | {f"wall_{w}": "wall" for w in "ABCD"}
    if target not in {n.id for n in graph.nodes} | kinds.keys():
        return _reply("add_item", tool_call_id, _unknown(state, target))
    base = "_".join(name.lower().split()) or category
    node_id = base if base not in {n.id for n in graph.nodes} else f"{base}_{len(graph.nodes)}"
    # a wall, door or window the graph does not hold yet joins it as a fixed node
    fixed = (
        [] if target in {n.id for n in graph.nodes} else [SceneNode.model_validate({"id": target, "kind": kinds[target], "name": target})]
    )
    for item in _search(request, name, category, _budget_left(state))[:OPTIONS]:
        node = SceneNode.model_validate({"id": node_id, "name": name, "size": item.size, "priority": "nice", "item_id": item.id})
        graph2 = SceneGraph(
            nodes=[*graph.nodes, *fixed, node], edges=[*graph.edges, SceneEdge(source=node_id, relation=relation, target=target)]
        )
        if new := place(spec, state["layout"], graph2, {node_id}):
            p = next(p for p in new.placements if p.node_id == node_id)
            candidates = {**state.get("candidates", {}), node_id: [item]}
            message = f"added {node_id}: {item.name}, {item.price:g} EUR, at x={p.x}, y={p.y}, rotation {p.rotation:g}"
            return _reply("add_item", tool_call_id, message, {"scene_graph": graph2, "layout": new, "candidates": candidates})
    return _reply("add_item", tool_call_id, f"no {category} within the budget fits {relation.replace('_', ' ')} {target}")


@tool
def remove_item(node_id: str, state: State, tool_call_id: CallId) -> Command[Any]:
    """Remove an item from the design, with what stands on it."""
    graph = state["scene_graph"]
    if node_id not in _objects(graph):
        return _reply("remove_item", tool_call_id, _unknown(state, node_id))
    gone, grew = {node_id}, True
    while grew:  # what stands on it would float
        more = {e.source for e in graph.edges if e.relation == "on" and e.target in gone} - gone
        grew, gone = bool(more), gone | more
    update = {
        "scene_graph": SceneGraph(
            nodes=[n for n in graph.nodes if n.id not in gone], edges=[e for e in graph.edges if not {e.source, e.target} & gone]
        ),
        "layout": Layout(placements=[p for p in state["layout"].placements if node_of(graph, p.node_id) not in gone]),
        "candidates": {k: v for k, v in state.get("candidates", {}).items() if k not in gone},
    }
    return _reply("remove_item", tool_call_id, f"removed {', '.join(sorted(gone))}", update)


@tool
def explain(node_id: str, state: State, tool_call_id: CallId) -> Command[Any]:
    """Why an item is where it is and what it is: its relations, catalog item and alternatives, and the checks that fail for it."""
    graph = state["scene_graph"]
    node = _objects(graph).get(node_id)
    if node is None:
        return _reply("explain", tool_call_id, _unknown(state, node_id))
    item = load_catalog().get(node.item_id or "")
    relations = "; ".join(f"{e.source} {e.relation.replace('_', ' ')} {e.target}" for e in graph.edges if node_id in (e.source, e.target))
    others = [c.name for c in state.get("candidates", {}).get(node_id, []) if c != item]
    issues = [i.message for i in state["validation"].issues if node_id in i.node_ids] if state.get("validation") else []
    what = f"{item.name}, {item.price:g} EUR, {item.description}" if item else "no catalog item"
    lines = [
        f"{node_id} ({node.name}, {node.priority} have): {what}",
        f"relations: {relations or 'none'}",
        f"alternatives: {', '.join(others) or 'none'}",
        f"issues: {'; '.join(issues) or 'none'}",
    ]
    return _reply("explain", tool_call_id, "\n".join(lines), {})


TOOLS = [get_layout, move_item, rotate_item, swap_item, add_item, remove_item, explain]
