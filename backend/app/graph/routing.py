from typing import Literal

from langchain_core.runnables import RunnableConfig

from app.api.models import RunConfigurable
from app.graph.state import RunState

MAX_ROUNDS = 3  # critic rounds before the layout is presented as it is


def flags(config: RunnableConfig) -> RunConfigurable:
    """The run's ablation flags, from its configurable (which also holds LangGraph's own keys)."""
    configurable = config.get("configurable", {})
    return RunConfigurable.model_validate({k: v for k, v in configurable.items() if k in RunConfigurable.model_fields})


def after_route_input(state: RunState) -> Literal["analyze_room", "chat_edit"]:
    """A chat message edits the design; any other input starts one."""
    return "chat_edit" if state["mode"] == "chat" else "analyze_room"


def after_solve(state: RunState, config: RunnableConfig) -> Literal["critic", "present"]:
    """A chat edit is presented once it is re-validated; a new design goes to the critic, unless the run has `no_critic`."""
    return "present" if state["mode"] == "chat" or flags(config).no_critic else "critic"


def after_critic(state: RunState) -> Literal["present", "architect", "source"]:
    critique = state["critique"]
    if not critique.actions or critique.round >= MAX_ROUNDS:
        return "present"
    return "architect" if any(a.target == "architect" for a in critique.actions) else "source"


def after_chat_edit(state: RunState) -> Literal["solve", "__end__"]:
    """A refused edit changes nothing: the run ends with chat_edit's answer."""
    diff = state["layout_diff"]
    return "solve" if diff.added or diff.removed or diff.changed else "__end__"
