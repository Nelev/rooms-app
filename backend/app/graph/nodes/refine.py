"""The Refiner: orders the siblings that share a parent and a relation, so the solver has one interpretation of them.

Siblings are the children of one item (an object node) through one relation, read as the B-07 validator reads parents (facing
and adjacent give none). Children of walls, doors and windows (against_wall, in_corner, left_of a door...) are left alone: the
solver spreads them along their wall, and an item-to-item order there could fight the corner it picks. Siblings with
quantity > 1 are left alone too: B-07 lines their copies up along their left neighbour's depth (too_small). Each remaining
sibling after the first, in graph order, gets a `right_of` edge to the one before it (the solver's left/right convention). A
pair that already has an edge between them, either way, keeps it, and an edge that would close a loop is not added (the
newest edge goes). The edges are appended, so each node's first placing edge, which the solver places it by, stays the one
to its parent.

Limit: the solver places each node only by its first placing edge, so these ordering edges do not yet change layouts; they
record the order (and feed B-07's footprint checks) until the solver honours a node's other edges.

Deterministic, no model: the node always runs for real; only its stream events are the fixture's in the stub graph.
"""

import time
from collections import defaultdict
from itertools import pairwise
from typing import Any

from langgraph.config import get_stream_writer

from app.graph import stub
from app.graph.state import RunState
from app.graph.stub import stub_node
from app.schemas import SceneGraph
from app.schemas.design import SceneEdge


def refine_graph(graph: SceneGraph) -> SceneGraph:
    """`graph` with ordering edges between its siblings."""
    nodes = {n.id: n for n in graph.nodes}
    parents: defaultdict[str, set[str]] = defaultdict(set)
    siblings: defaultdict[tuple[str, str], list[str]] = defaultdict(list)
    for e in graph.edges:
        if e.relation not in ("facing", "adjacent"):
            parents[e.source].add(e.target)
            orderable = e.target in nodes and nodes[e.target].kind == "object" and e.source in nodes and nodes[e.source].quantity == 1
            if orderable and e.source not in siblings[e.target, e.relation]:
                siblings[e.target, e.relation].append(e.source)

    def ancestor(node: str, of: str) -> bool:
        """Whether `node` is `of` or one of its ancestors."""
        todo, seen = [of], set()
        while todo:
            if (n := todo.pop()) == node:
                return True
            if n not in seen:
                seen.add(n)
                todo += parents[n]
        return False

    linked = {frozenset((e.source, e.target)) for e in graph.edges}
    added: list[SceneEdge] = []
    for group in siblings.values():
        for left, right in pairwise(group):
            pair = frozenset((left, right))
            if pair not in linked and not ancestor(right, left):  # the newest edge goes if it closes a loop
                linked.add(pair)
                parents[right].add(left)
                added.append(SceneEdge(source=right, relation="right_of", target=left))
    return graph.model_copy(update={"edges": [*graph.edges, *added]})


def _replay(state: RunState) -> dict[str, Any]:
    return {"scene_graph": refine_graph(state["scene_graph"])}


_replay.__name__ = "refine"  # stub_node finds the fixture step events by the node's name
replay = stub_node(_replay)  # the stub graph's refine: the real refinement, with the fixture's stream events


def refine(state: RunState) -> dict[str, Any]:
    if not stub.live("refine"):
        return replay(state)
    write, start, round_ = get_stream_writer(), time.monotonic(), state.get("round")
    step = {"type": "step", "node": "refine", "round": round_}  # a StepEvent
    write({**step, "status": "started"})
    graph = refine_graph(state["scene_graph"])
    added = len(graph.edges) - len(state["scene_graph"].edges)
    summary = f"{added} ordering edge{'s' * (added != 1)} added" if added else "no ambiguous siblings"
    write({**step, "status": "done", "summary": summary, "duration_s": round(time.monotonic() - start, 1)})
    return {"scene_graph": graph}
