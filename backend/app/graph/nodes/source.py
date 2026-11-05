"""The Sourcer: a catalog item for each object of the scene graph, within the brief's budget, its size the item's real size.

The objects that keep their item are charged first. Each other object (without an item, or whose item the Critic asked to swap)
gets a share of what is left of the budget, in proportion to its category's median catalog price times its quantity (swaps first,
then must-haves): it takes the item most like it that fits its box and its share, or else one of any size within its share. So the
total stays within the budget, unless the items the Architect kept already exceed it. The chosen item replaces the object's box with
its real size, so the solver places the real furniture.

Swaps come from the Critic's `sourcer` actions on a node ("smaller sofa", "cheaper desk"): the current item is excluded, and the
instruction's words decide the constraint: cheaper (a lower price), smaller or larger (a smaller or larger footprint).
"""

import re
from collections.abc import Callable
from statistics import median
from typing import Any

from langgraph.config import get_store
from langgraph.store.base import BaseStore

from app.catalog.embed import NAMESPACE
from app.catalog.loader import load_catalog
from app.catalog.search import CANDIDATES, Filters, fits
from app.graph.state import RunState
from app.graph.stub import stub_node
from app.schemas import CatalogItem, SceneGraph
from app.schemas.design import DesignObject, SceneNode

ALTERNATIVES = 4  # catalog items recorded per object besides the chosen one, for the results view


def search(store: BaseStore | None, query: str, filters: Filters) -> list[CatalogItem]:
    """app.catalog.search.search, synchronous: a sync node runs in a worker thread, where the store's sync API works."""
    if store is None:
        return []
    hits = store.search(NAMESPACE, query=query, filter={"category": filters.category}, limit=CANDIDATES)
    items = (CatalogItem.model_validate({k: v for k, v in hit.value.items() if k != "text"}) for hit in hits)
    return [item for item in items if fits(item, filters)]


def footprint(item: CatalogItem) -> float:
    return item.size.width * item.size.depth


def swap_rule(instruction: str, current: CatalogItem) -> Callable[[CatalogItem], bool]:
    """What a swap instruction asks of the new item, besides being another one."""
    words = set(re.findall(r"\w+", instruction.lower()))
    if words & {"cheaper", "inexpensive", "budget", "affordable"}:
        return lambda i: i.price < current.price
    if words & {"smaller", "compact", "narrower", "shorter"}:
        return lambda i: footprint(i) < footprint(current)
    if words & {"larger", "bigger", "wider", "longer"}:
        return lambda i: footprint(i) > footprint(current)
    return lambda i: True


def choose(
    store: BaseStore | None, node: SceneNode, obj: DesignObject, share: float, current: CatalogItem | None, instruction: str
) -> list[CatalogItem]:
    """The items for `node` within `share` (EUR, all its units), the best first: in its box, else of any size."""
    query = " ".join(filter(None, [instruction, node.name, node.style, node.material]))
    rule = swap_rule(instruction, current) if current else lambda i: True
    for size in (node.size, None):
        found = search(store, query, Filters(obj.category, size, max_price=share / node.quantity))
        if found := [i for i in found if i != current and rule(i)]:
            return found
    return []


def source_scene(store: BaseStore | None, state: RunState) -> dict[str, Any]:
    """The scene graph with an item, and its size, per object, and the candidates of each: the chosen item first, then alternatives."""
    catalog, graph = load_catalog(), state["scene_graph"]
    objects = {o.id: o for o in state["design_brief"].objects}
    critique = state.get("critique")
    # the critique of the critic round that just ended (critic moves `round` on), not one left by an earlier design run
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
