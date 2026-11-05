"""The Critic: judges the solved layout and sends targeted actions back to the Architect or the Sourcer.

RULE-BASED, no model: the node always runs for real and streams its own step events. It combines
- the solve node's validation (hard): the B-07 graph issues, the B-04 layout issues and the relations the layout does not keep,
  each an Architect action on its node, except an item above the ceiling, which the Sourcer swaps for a shorter one;
- the unmet sibling ordering edges (soft, no action): a `right_of` edge between two items that share a parent item and relation,
  as the B-16 Refiner adds them; the solver only places by each node's first edge, so asking for them would only spend rounds;
- the solver fallback's report: a dropped must-have is hard, and the Sourcer is asked for a smaller one when it did not fit; a
  dropped nice-to-have or a resized item is soft and only explained (the fallback already tried the smaller catalog items);
- three soft rules, each an Architect action when it fails:
  - desk_near_light: every desk within NEAR_LIGHT of a window's zone (the strip in front of it), when the room has a window;
  - bed_not_facing_door: no door's swing centered straight ahead of a bed's foot (ahead of its front, within its width);
  - visual_balance: the footprint-weighted center of the furniture (kept furniture included) at most BALANCE of the room's
    width and length off its center.
Each check is a rule of the Critique; routing.keep_best scores the round (hard issues, then soft) and decides whether it ends.
"""

import time
from collections import defaultdict
from typing import Any

from langgraph.config import get_stream_writer
from shapely import Point

from app.geometry.room import footprint, room_model, solid
from app.graph.nodes.solve import local
from app.graph.routing import keep_best
from app.graph.state import RunState
from app.schemas import Critique
from app.schemas.layout import CritiqueAction, RuleResult, ValidationIssue

NEAR_LIGHT = 1.0  # m from a desk to the zone in front of a window
BALANCE = 0.25  # of the room's width and length: how far the furniture's center may be off the room's center
RULES = {  # the validation codes of each hard rule (the rest are the graph's: graph_valid)
    "relations_kept": {"relation_unmet"},
    "no_collisions": {"collision", "above_ceiling"},
    "openings_clear": {"blocks_opening", "blocks_window", "blocks_radiator"},
    "reachable": {"clearance"},
}
HINTS = {
    "relation_unmet": "the solver places each object by its first placing relation only: make its relations agree, or drop this one",
    "clearance": "leave a walkway to it",
}


def judge(state: RunState) -> tuple[Critique, int, int]:
    """The round's critique, and its hard and soft issue counts."""
    graph, spec, layout, fallback = state["scene_graph"], state["room_spec"], state["layout"], state["fallback"]
    nodes = {n.id: n for n in graph.nodes}
    category = {o.id: o.category for o in state["design_brief"].objects}

    def node_of(placement_id: str) -> str:  # copies of a node are placed as <id>_2, <id>_3...
        return placement_id if placement_id in nodes else placement_id.rsplit("_", 1)[0]

    rules: list[RuleResult] = []
    actions: list[CritiqueAction] = []
    parents: defaultdict[str, set[tuple[str, str]]] = defaultdict(set)  # each item's parent items and relations, as refine.py groups
    for e in graph.edges:
        if e.relation not in ("facing", "adjacent") and e.target in nodes and nodes[e.target].kind == "object":
            parents[e.source].add((e.target, e.relation))
    ordering = {(e.source, e.target) for e in graph.edges if e.relation == "right_of" and parents[e.source] & parents[e.target]}
    errors: list[ValidationIssue] = []
    unordered: list[ValidationIssue] = []
    for i in state["validation"].issues:
        if i.severity == "error":
            (unordered if i.code == "relation_unmet" and tuple(i.node_ids) in ordering else errors).append(i)
    rule_of = {code: rule for rule, codes in RULES.items() for code in codes}
    for rule in ("graph_valid", *RULES):
        found = [i for i in errors if rule_of.get(i.code, "graph_valid") == rule]
        rules.append(RuleResult(rule=rule, passed=not found, message="; ".join(i.message for i in found)))
        for i in found:
            node = node_of(i.node_ids[0]) if i.node_ids else None
            if i.code == "above_ceiling":
                actions.append(CritiqueAction(target="sourcer", node_id=node, instruction=f"shorter {node}: {i.message}"))
            else:
                hint = HINTS.get(i.code, "place it elsewhere" if rule != "graph_valid" else "fix it")
                actions.append(CritiqueAction(target="architect", node_id=node, instruction=f"{i.message}: {hint}"))
    hard, soft = len(errors), 0

    rules.append(RuleResult(rule="everything_fits", passed=not fallback.changes, message="" if not fallback.changes else fallback.summary))
    for c in fallback.changes:
        must = c.node_id in nodes and nodes[c.node_id].priority == "must"
        hard, soft = (hard + 1, soft) if must and c.action == "dropped" else (hard, soft + 1)
        if must and c.action == "dropped" and c.code in ("too_big", "no_space"):
            actions.append(CritiqueAction(target="sourcer", node_id=c.node_id, instruction=f"smaller {nodes[c.node_id].name}: {c.message}"))

    room = room_model(spec)
    of = {kind: [p for p in layout.placements if category.get(node_of(p.node_id)) == kind] for kind in ("desk", "bed")}
    far = [p for p in of["desk"] if room.windows and min(solid(p).shape.distance(w.shape) for w in room.windows) > NEAR_LIGHT]
    windows = ", ".join(w.id for w in room.windows)
    soft_rules: list[tuple[str, str | None, str, str]] = [
        ("desk_near_light", node_of(p.node_id), f"{p.node_id} is more than {NEAR_LIGHT} m from {windows}", "move it near a window")
        for p in far
    ]
    for p in of["bed"]:
        for door in room.doors:
            x, y = local(p, door.shape.centroid.x, door.shape.centroid.y)
            if y > p.size.depth / 2 and abs(x) < p.size.width / 2:
                message = f"{p.node_id} faces {door.id}"
                soft_rules.append(
                    ("bed_not_facing_door", node_of(p.node_id), message, f"turn or move it so its foot does not face {door.id}")
                )
    shapes = [solid(p).shape for p in layout.placements] + [footprint(k, k.x, k.y, k.rotation) for k in spec.kept_furniture]
    if area := sum(s.area for s in shapes):
        center = Point(sum(s.centroid.x * s.area for s in shapes) / area, sum(s.centroid.y * s.area for s in shapes) / area)
        dims = spec.dimensions
        off_x, off_y = center.x / dims.width - 0.5, center.y / dims.length - 0.5
        if max(abs(off_x), abs(off_y)) > BALANCE:
            wall = ("B" if off_x > 0 else "D") if abs(off_x) >= abs(off_y) else ("C" if off_y > 0 else "A")
            soft_rules.append(("visual_balance", None, f"the furniture crowds wall {wall}", "spread it more evenly over the room"))
    rules.append(RuleResult(rule="siblings_ordered", passed=not unordered, message="; ".join(i.message for i in unordered)))
    soft += bool(unordered)
    for rule in ("desk_near_light", "bed_not_facing_door", "visual_balance"):
        failed = [r for r in soft_rules if r[0] == rule]
        rules.append(RuleResult(rule=rule, passed=not failed, message="; ".join(r[2] for r in failed)))
        soft += bool(failed)
        for _, node, message, hint in failed:
            actions.append(CritiqueAction(target="architect", node_id=node, instruction=f"{message}: {hint}"))

    fails = [r for r in rules if not r.passed]
    summary = f"{len(fails)} rule{' fails' if len(fails) == 1 else 's fail'}: {fails[0].message}" if fails else "all rules pass"
    actions = list({(a.target, a.node_id, a.instruction): a for a in actions}.values())  # one action per instruction
    return Critique(round=state["round"], rules=rules, actions=actions, summary=summary), hard, soft


def critic(state: RunState) -> dict[str, Any]:
    write, start = get_stream_writer(), time.monotonic()
    step = {"type": "step", "node": "critic", "round": state["round"]}  # a StepEvent
    write({**step, "status": "started"})
    update = keep_best(state, *judge(state))
    write({**step, "status": "done", "summary": update["critique"].summary, "duration_s": round(time.monotonic() - start, 1)})
    return update
