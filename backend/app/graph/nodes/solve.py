"""The solve node: places the scene graph with the B-11 solver, through the B-12 fallback, and validates the layout.

The fallback drops or shrinks what does not fit; a resized item's catalog item and size are applied to the scene graph (and put
first among its candidates, the Sourcer's convention for the chosen item), so the next rounds and the results see the real item.
The seed is the critic round (1, 2, 3), not the thread id: the same input always gives the same layouts (the solver stops on a
step limit, the time budget is only a safety net), so runs and evals are reproducible, and a graph the Critic sends back
unchanged is still sampled anew.
The validation combines the B-07 graph check, the B-04 layout checks and a check of every
relation of the graph against the layout: the solver only places each node by its first placing edge (B-11), so the others
(the Refiner's ordering edges, a second relation, `facing`) may be broken.

Deterministic, no model: the node always runs for real and streams its own step events. A chat edit is not re-solved: its
layout is still the fixture's (stub), until the chat edit node is real.
"""

import time
from math import cos, radians, sin
from typing import Any

from langgraph.config import get_stream_writer

from app.catalog.loader import load_catalog
from app.geometry import checks
from app.geometry.fallback import solve_with_fallback
from app.geometry.graph_validate import validate_graph
from app.geometry.room import room_model
from app.geometry.solver import Frame, child_box, fixed_frames
from app.graph.state import RunState
from app.graph.stub import chat_turn, stub_node
from app.schemas import Layout, RoomSpec, RunOutput, SceneGraph, ValidationReport
from app.schemas.layout import Placement, ValidationIssue

WALKWAY = 0.6  # m, the narrowest walkway a person passes through (as eval/metrics/layout.py)
TOL = 0.05  # m a placement may miss its relation's box by and still keep it (the solver rounds positions to 1 mm)


def local(frame: Frame | Placement, x: float, y: float) -> tuple[float, float]:
    """The room point (x, y) in the frame of a parent or item: x to its right, y to its front."""
    a, dx, dy = radians(frame.rotation), x - frame.x, y - frame.y
    return dx * cos(a) + dy * sin(a), -dx * sin(a) + dy * cos(a)


def _seen_from(frame: Frame, p: Placement) -> tuple[float, float, Placement]:
    """p's center in the frame, and p with its size turned to the frame's axes."""
    x, y = local(frame, p.x, p.y)
    if round((p.rotation - frame.rotation) / 90) % 2:
        p = p.model_copy(update={"size": p.size.model_copy(update={"width": p.size.depth, "depth": p.size.width})})
    return x, y, p


def kept(relation: str, frame: Frame, p: Placement) -> bool:
    """Whether p stands where the solver would put a child `relation` its parent `frame` (B-11's boxes), to TOL.

    `facing` is kept when the parent's center is ahead of p (in front of its front side), `adjacent` when p is left or right of it."""
    x, y, p = _seen_from(frame, p)
    if relation == "facing":
        return local(p, frame.x, frame.y)[1] > TOL
    for r in ("left_of", "right_of") if relation == "adjacent" else (relation,):
        x0, x1, y0, y1, _ = child_box(r, frame, p.size)
        along = min(abs(x - x0), abs(x - x1)) <= TOL if r == "in_corner" else x0 - TOL <= x <= x1 + TOL
        on_top = r != "on" or frame.fixed or abs(p.z - frame.top) <= TOL
        if along and y0 - TOL <= y <= y1 + TOL and on_top:
            return True
    return False


def unmet_relations(graph: SceneGraph, spec: RoomSpec, layout: Layout) -> list[ValidationIssue]:
    """Every edge of an object whose placements (each copy) do not keep it; edges to or from an item not placed are skipped."""
    nodes = {n.id: n for n in graph.nodes}
    placed = {p.node_id: p for p in layout.placements}
    frames = fixed_frames(spec)
    for n, p in placed.items():
        frames[n] = Frame(p.x, p.y, p.rotation, p.size.width, p.size.depth, p.z + p.size.height, False)
    issues = []
    for e in graph.edges:
        if e.source not in nodes or nodes[e.source].kind != "object" or e.target not in frames:
            continue
        copies = [e.source] + [f"{e.source}_{k}" for k in range(2, nodes[e.source].quantity + 1)]
        for c in copies:
            if c in placed and c != e.target and not kept(e.relation, frames[e.target], placed[c]):
                message = f"{c} is not {e.relation.replace('_', ' ')} {e.target} in the layout"
                issues.append(ValidationIssue(code="relation_unmet", message=message, node_ids=[e.source, e.target]))
    return issues


def validate(graph: SceneGraph, spec: RoomSpec, layout: Layout) -> ValidationReport:
    """The graph's B-07 issues, the layout's B-04 issues (collisions, clearance, blocked openings, ceiling) and its unmet relations."""
    room = room_model(spec)
    layout_checks = (checks.collisions, checks.blocked_openings, checks.blocked_windows, checks.blocked_radiators, checks.above_ceiling)
    issues = validate_graph(graph, spec).issues + [i for check in layout_checks for i in check(room, layout)]
    issues += checks.clearance_violations(room, layout, WALKWAY) + unmet_relations(graph, spec, layout)
    return ValidationReport(issues=issues)


def solve_scene(state: RunState) -> dict[str, Any]:
    """The run's layout, its fallback report and validation, and the scene graph and candidates with the resized items applied."""
    graph, spec = state["scene_graph"], state["room_spec"]
    layout, report = solve_with_fallback(graph, spec, seed=state.get("round", 1))  # B-12's time caps: a safety net only
    placed = {p.node_id: p for p in layout.placements}
    candidates = dict(state.get("candidates", {}))
    nodes = []
    for n in graph.nodes:
        if (p := placed.get(n.id)) and p.item_id != n.item_id:  # resized by the fallback
            n = n.model_copy(update={"item_id": p.item_id, "size": p.size})
            item = load_catalog()[p.item_id or ""]
            candidates[n.id] = [item, *(c for c in candidates.get(n.id, []) if c != item)]
        nodes.append(n)
    graph = graph.model_copy(update={"nodes": nodes})
    return {
        "layout": layout,
        "fallback": report,
        "validation": validate(graph, spec, layout),
        "scene_graph": graph,
        "candidates": candidates,
    }


def _chat(state: RunState) -> dict[str, Any]:
    return {"layout": RunOutput.model_validate(chat_turn(state)["output"]).layout, "validation": ValidationReport()}


_chat.__name__ = "solve"  # stub_node finds the fixture step events by the node's name
chat = stub_node(_chat)  # a chat edit's layout: the fixture's, with its stream events (stub)


def solve(state: RunState) -> dict[str, Any]:
    if state["mode"] == "chat":
        return chat(state)
    write, start = get_stream_writer(), time.monotonic()
    step = {"type": "step", "node": "solve", "round": state.get("round")}  # a StepEvent
    write({**step, "status": "started"})
    update = solve_scene(state)
    errors = sum(i.severity == "error" for i in update["validation"].issues)
    report = update["fallback"]
    summary = report.summary if report.changes else f"placed {len(update['layout'].placements)} objects"
    summary += f", {errors} issue{'s' * (errors != 1)}" if errors else ""
    write({**step, "status": "done", "summary": summary, "duration_s": round(time.monotonic() - start, 1)})
    return update
