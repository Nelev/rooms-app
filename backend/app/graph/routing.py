from typing import Literal

from app.graph.state import RunState

MAX_ROUNDS = 3  # critic rounds before the layout is presented as it is


def after_route_input(state: RunState) -> Literal["analyze_room", "chat_edit"]:
    """A chat message edits the design; any other input starts one."""
    return "chat_edit" if state["mode"] == "chat" else "analyze_room"


def after_solve(state: RunState) -> Literal["critic", "present"]:
    """A chat edit is presented once it is re-validated; a new design goes to the critic."""
    return "present" if state["mode"] == "chat" else "critic"


def after_critic(state: RunState) -> Literal["present", "architect", "source"]:
    critique = state["critique"]
    if not critique.actions or critique.round >= MAX_ROUNDS:
        return "present"
    return "architect" if any(a.target == "architect" for a in critique.actions) else "source"


def after_chat_edit(state: RunState) -> Literal["solve", "__end__"]:
    """A refused edit changes nothing: the run ends with chat_edit's answer."""
    diff = state["layout_diff"]
    return "solve" if diff.added or diff.removed or diff.changed else "__end__"
