"""The Sourcer: a catalog item for each object of the scene graph, within the brief's budget, its size the item's real size.

The objects that keep their item are charged first. Each other object (without an item, or whose item the Critic asked to swap)
gets a share of what is left of the budget, in proportion to its category's median catalog price times its quantity (swaps first,
then must-haves): it takes the item most like it that fits its box and its share, or else one of another shape that fits in its box
(see choose). So the total stays within the budget, unless the items the Architect kept already exceed it. The chosen item replaces
the object's box with its real size, so the solver places the real furniture.

Swaps come from the Critic's `sourcer` actions on a node ("smaller sofa", "cheaper desk"): the current item is excluded, and the
instruction's words decide the constraint: cheaper (a lower price), smaller or larger (a smaller or larger footprint), shorter (a
lower height, for an item above the ceiling).
"""

import re
from collections.abc import Callable
from statistics import median
from typing import Any

from langgraph.config import get_store
from langgraph.store.base import BaseStore

from app.catalog.loader import load_catalog
from app.catalog.search import CANDIDATES, SIZE_TOLERANCE, Filters, search_sync
from app.graph.state import RunState
from app.graph.stub import stub_node
from app.schemas import CatalogItem, SceneGraph
from app.schemas.coords import Size
from app.schemas.design import DesignObject, SceneNode

ALTERNATIVES = 4  # catalog items recorded per object besides the chosen one, for the results view
LARGER = {"larger", "bigger", "wider", "longer"}


def words(instruction: str) -> set[str]:
    return set(re.findall(r"\w+", instruction.lower()))


def footprint(item: CatalogItem) -> float:
    return item.size.width * item.size.depth


def swap_rule(instruction: str, current: CatalogItem) -> Callable[[CatalogItem], bool]:
    """What a swap instruction asks of the new item, besides being another one."""
    asked = words(instruction)
    if asked & {"cheaper", "inexpensive", "budget", "affordable"}:
        return lambda i: i.price < current.price
    if "shorter" in asked:  # the Critic's ask for an item above the ceiling
        return lambda i: i.size.height < current.size.height
    if asked & {"smaller", "compact", "narrower"}:
        return lambda i: footprint(i) < footprint(current)
    if asked & LARGER:
        return lambda i: footprint(i) > footprint(current)
    return lambda i: True


def within(item: CatalogItem, box: Size) -> bool:
    """The item's footprint fits in the box's, to SIZE_TOLERANCE: it takes no more room than the layout gave the object."""
    return item.size.width <= box.width * (1 + SIZE_TOLERANCE) and item.size.depth <= box.depth * (1 + SIZE_TOLERANCE)


def choose(
    store: BaseStore | None, node: SceneNode, obj: DesignObject, share: float, current: CatalogItem | None, instruction: str
) -> list[CatalogItem]:
    """The items for `node` within `share` (EUR, all its units), the best first: of its box's size and shape, else of another shape.

    HEURISTIC (provisional) fallback: the Architect's boxes are estimates and a category holds few items of each size, so an item of
    another shape may replace the box, but only one that fits in it (a "larger" swap's may not): the item is placed at its real size,
    never scaled, so it is not distorted, and it takes no room the layout did not give the object.
    """
    if store is None:
        return []
    query = " ".join(filter(None, [instruction, node.name, node.style, node.material]))
    rule = swap_rule(instruction, current) if current else lambda i: True
    grow, size = bool(words(instruction) & LARGER), node.size
    box = Filters(obj.category, size, max_price=share / node.quantity)
    other_shape = lambda i: rule(i) and (grow or size is None or within(i, size))  # noqa: E731
    for filters, allowed in ((box, rule), (box._replace(size=None), other_shape)):
        if found := [i for i in search_sync(store, query, filters, CANDIDATES) if i != current and allowed(i)]:
            return found
    return []


def source_scene(store: BaseStore | None, state: RunState) -> dict[str, Any]:
    """The scene graph with an item, and its size, per object, and the candidates of each: the chosen item first, then alternatives."""
    catalog, graph = load_catalog(), state["scene_graph"]
    objects = {o.id: o for o in state["design_brief"].objects}
    critique = state.get("critique")
    # Only the critique of the critic round that just ended, not one an earlier design run of the thread left: the critic tags its
    # critique with the round it judged and moves `round` on when it sends the layout back (test_source checks it with the critic).
    actions = critique.actions if critique and critique.round == state.get("round", 1) - 1 else []
    swaps = {a.node_id: a.instruction for a in actions if a.target == "sourcer" and a.node_id}
    prices: dict[str, list[float]] = {}
    for c in catalog.values():
        prices.setdefault(c.category, []).append(c.price)

    nodes = {n.id: n for n in graph.nodes if n.id in objects and n.size and objects[n.id].category in prices}
    current = {n.id: catalog[n.item_id] for n in nodes.values() if n.item_id in catalog}
    to_source = sorted((i for i in nodes if i in swaps or i not in current), key=lambda i: (i not in swaps, nodes[i].priority != "must"))
    spent = sum(current[i].price * nodes[i].quantity for i in current.keys() - to_source)
    # HEURISTIC (provisional): shares proportional to the category's median catalog price times the quantity
    weight = {i: median(prices[objects[i].category]) * nodes[i].quantity for i in to_source}

    candidates = dict(state.get("candidates", {}))
    for i in current.keys() - to_source:  # a kept item still sets the size: the box it came with may not be the item's
        nodes[i] = nodes[i].model_copy(update={"size": current[i].size})
        candidates[i] = [current[i], *(c for c in candidates.get(i, []) if c != current[i])]
    for n, i in enumerate(to_source):
        share = (state["brief"].budget - spent) * weight[i] / sum(weight[j] for j in to_source[n:])
        found = choose(store, nodes[i], objects[i], share, current.get(i), swaps.get(i, ""))
        old = current.get(i)
        if not found and old and spent + old.price * nodes[i].quantity <= state["brief"].budget:
            found = [old]  # no swap fits: the object keeps its item, when the budget still allows it
        if not found:  # an object without an item keeps its box, which the frontend renders as a box
            nodes[i] = nodes[i].model_copy(update={"item_id": None})
            candidates[i] = []
            continue
        item = found[0]
        nodes[i] = nodes[i].model_copy(update={"item_id": item.id, "size": item.size})
        candidates[i] = found[: ALTERNATIVES + 1]
        spent += item.price * nodes[i].quantity
    scene_graph = SceneGraph(nodes=[nodes.get(n.id, n) for n in graph.nodes], edges=graph.edges)
    return {"scene_graph": scene_graph, "candidates": candidates}


@stub_node  # only for the run timeline's step events and cost: the fixture's, until real nodes emit their own
def source(state: RunState) -> dict[str, Any]:
    return source_scene(get_store(), state)
