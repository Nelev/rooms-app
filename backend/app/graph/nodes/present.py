"""The Presenter: the run's render-ready scene (app.scene.builder) and, for a design run, its rationale.

Deterministic, no model: the node streams its own step events. A chat run keeps chat_edit's answer as its rationale; with chat_edit
a stub (no model key), it streams the fixture's present step, as the chat solve does.
"""

import time
from typing import Any

from langgraph.config import get_stream_writer

from app.graph import stub
from app.graph.state import RunState
from app.graph.stub import stub_node
from app.scene.builder import build_scene, rationale, total
from app.schemas import Brief


def _scene(state: RunState) -> dict[str, Any]:
    """The layout's scene, with the cameras matched to the user's photos so far (none in a new scene: #47)."""
    old = state.get("scene")
    return {"scene": build_scene(state["room_spec"], state["layout"], old.cameras if old else [])}


_scene.__name__ = "present"  # stub_node finds the fixture step events by the node's name
chat = stub_node(_scene)


def present(state: RunState) -> dict[str, Any]:
    edit = state["mode"] == "chat"
    if edit and not stub.live("chat_edit"):
        return chat(state)
    write, start = get_stream_writer(), time.monotonic()
    step = {"type": "step", "node": "present"}  # a StepEvent
    write({**step, "status": "started"})
    scene, budget = _scene(state)["scene"], Brief.model_validate(state["brief"]).budget  # a graph input may be plain JSON
    update: dict[str, Any] = {"scene": scene}
    if not edit:  # a chat edit's rationale is chat_edit's answer
        update["rationale"] = rationale(state["design_brief"], scene, budget, state.get("fallback"), state.get("critique"))
    summary = f"{len(scene.items)} objects, €{total(scene):,.0f} of €{budget:,.0f}"
    write({**step, "status": "done", "summary": summary, "duration_s": round(time.monotonic() - start, 1)})
    return update
