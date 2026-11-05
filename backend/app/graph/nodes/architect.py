"""The Architect: turns the DesignBrief and the RoomSpec into a SceneGraph, or applies the Critic's relation fixes to the current one.

The nodes come from the inputs (the walls, doors and windows as fixed roots, the brief's objects); the model gives only the edges.
The graph is checked with the B-07 validator plus the Architect's own rules, and repaired once with their messages.
Without OPENROUTER_API_KEY the node replays the fixture graph, like the rest of the stub graph.
"""

import os
import time
from pathlib import Path
from typing import Any, get_args

from langgraph.config import get_stream_writer

from app import llm
from app.geometry.graph_validate import validate_graph
from app.graph.state import RunState
from app.graph.stub import ask, load, stub_node
from app.schemas import DesignBrief, RoomSpec, SceneGraph, coords
from app.schemas.base import Model
from app.schemas.coords import Wall
from app.schemas.design import SceneEdge, SceneNode
from app.schemas.layout import ValidationIssue

PROMPTS = Path(__file__).resolve().parents[2] / "prompts" / "architect"
OBJECT_FIELDS = {"id", "name", "style", "material", "size", "quantity", "priority"}


class Edges(Model):
    """The model's reply: the graph's edges, or in a revision the new edges of the objects it changes."""

    edges: list[SceneEdge]


def _prompt(name: str, spec: RoomSpec, **fields: str) -> str:
    rules = (PROMPTS / "rules.md").read_text().format(coords=coords.__doc__)
    return (PROMPTS / f"{name}.md").read_text().format(rules=rules, room=spec.model_dump_json(), **fields)


def scene_nodes(brief: DesignBrief, spec: RoomSpec) -> list[SceneNode]:
    """The walls, doors and windows of the room (fixed roots), then the brief's objects."""
    walls = [{"id": f"wall_{w}", "kind": "wall", "name": f"wall {w}"} for w in get_args(Wall)]
    openings = [{"id": f.id, "kind": f.type, "name": f.type} for f in spec.features if f.type in ("door", "window")]
    objects = [o.model_dump(include=OBJECT_FIELDS) for o in brief.objects]
    return [SceneNode.model_validate(n) for n in [*walls, *openings, *objects]]


def check(graph: SceneGraph, spec: RoomSpec) -> list[ValidationIssue]:
    """The validator's errors, plus the Architect's rules: fixed nodes are roots, and each object is placed and faces one way."""
    issues = [i for i in validate_graph(graph, spec).issues if i.severity == "error"]
    kinds = {n.id: n.kind for n in graph.nodes}
    issues += [
        ValidationIssue(code="fixed_source", message=f"{e.source} is fixed: it cannot be {e.relation.replace('_', ' ')} {e.target}")
        for e in graph.edges
        if kinds.get(e.source, "object") != "object"
    ]
    placing = [e for e in graph.edges if e.relation != "facing"]
    anchored, grew = {n.id for n in graph.nodes if n.kind != "object"}, True  # placed from a fixed node, adjacent going both ways
    while grew:
        reached = {e.source for e in placing if e.target in anchored} | {
            e.target for e in placing if e.relation == "adjacent" and e.source in anchored
        }
        grew, anchored = not reached <= anchored, anchored | reached
    for n in graph.nodes:
        if n.kind != "object":
            continue
        if sum(e.source == n.id != e.target and e.relation == "facing" for e in graph.edges) != 1:
            issues.append(
                ValidationIssue(code="facing", message=f"{n.id} needs exactly one facing edge, toward another node", node_ids=[n.id])
            )
        if n.id not in anchored:
            message = f"{n.id} is not placed relative to a wall, door or window, directly or through other objects"
            issues.append(ValidationIssue(code="unplaced", message=message, node_ids=[n.id]))
    return issues


def revise(graph: SceneGraph, spec: RoomSpec, instructions: list[str]) -> tuple[SceneGraph, llm.Usage]:
    """Apply `instructions` to `graph`: the reply's edges replace those of the objects they place. The other objects' edges are kept,
    those from a fixed or unknown node (always wrong, and no reply could replace them) dropped."""
    prompt = _prompt("revise", spec, graph=graph.model_dump_json(exclude_none=True), instructions="\n".join(f"- {i}" for i in instructions))
    reply, usage = llm.ask_structured(Edges, prompt, role="architect")
    kept = {n.id for n in graph.nodes if n.kind == "object"} - {e.source for e in reply.edges}
    return graph.model_copy(update={"edges": [e for e in graph.edges if e.source in kept] + reply.edges}), usage


def scene_graph(state: RunState) -> tuple[SceneGraph, llm.Usage, list[ValidationIssue]]:
    """The run's scene graph (with the Critic's fixes when it sent some this round), the calls' usage and the issues left."""
    spec, critique = state["room_spec"], state.get("critique")
    fixes = []
    if critique and critique.round + 1 == state.get("round"):  # the critic sent the run back this round (design restarts at round 1)
        fixes = [f"{a.node_id}: {a.instruction}" if a.node_id else a.instruction for a in critique.actions if a.target == "architect"]
    if fixes:
        graph, usage = revise(state["scene_graph"], spec, fixes)
    else:
        all_nodes = scene_nodes(state["design_brief"], spec)
        prompt = _prompt(
            "draft",
            spec,
            brief=state["design_brief"].model_dump_json(),
            nodes=f"[{','.join(n.model_dump_json(exclude_none=True) for n in all_nodes)}]",
        )
        reply, usage = llm.ask_structured(Edges, prompt, role="architect")
        graph = SceneGraph(nodes=all_nodes, edges=reply.edges)
    if issues := check(graph, spec):  # one repair round
        graph, repair_usage = revise(graph, spec, [i.message for i in issues])
        usage = llm._add(usage, repair_usage)
        issues = check(graph, spec)
    return graph, usage, issues


def _replay(state: RunState) -> dict[str, Any]:
    return {"scene_graph": ask(SceneGraph, load("scene_graph", SceneGraph))}


_replay.__name__ = "architect"  # stub_node finds the fixture step events by the node's name
replay = stub_node(_replay)  # the stub graph's architect: the fixture graph and its stream events


def architect(state: RunState) -> dict[str, Any]:
    if not os.getenv("OPENROUTER_API_KEY"):
        return replay(state)
    write, start, round_ = get_stream_writer(), time.monotonic(), state.get("round")
    step = {"type": "step", "node": "architect", "round": round_}  # a StepEvent
    write({**step, "status": "started"})
    graph, usage, issues = scene_graph(state)
    summary = f"scene graph with {sum(n.kind == 'object' for n in graph.nodes)} objects" + (
        f", {len(issues)} issues left" if issues else ""
    )
    write({**step, "status": "done", "summary": summary, "duration_s": round(time.monotonic() - start, 1), "cost": usage["cost"]})
    return {"scene_graph": graph, **usage}
