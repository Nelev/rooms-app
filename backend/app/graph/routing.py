from typing import Any, Literal

from langchain_core.runnables import RunnableConfig

from app.api.models import RunConfigurable
from app.graph.state import Best, RunState
from app.schemas import Critique

MAX_ROUNDS = 3  # critic rounds before the best layout of the run is presented as it is


def flags(config: RunnableConfig) -> RunConfigurable:
    """The run's ablation flags, from its configurable (which also holds LangGraph's own keys)."""
    configurable = config.get("configurable", {})
    return RunConfigurable.model_validate({k: v for k, v in configurable.items() if k in RunConfigurable.model_fields})


def after_route_input(state: RunState) -> Literal["analyze_room", "chat_edit"]:
    """A chat message edits the design; any other input starts one."""
    return "chat_edit" if state["mode"] == "chat" else "analyze_room"


def after_solve(state: RunState, config: RunnableConfig) -> Literal["critic", "present"]:
    """A chat edit is presented (not re-validated while chat_edit is a stub); a new design goes to the critic, unless the run has
    `no_critic`."""
    return "present" if state["mode"] == "chat" or flags(config).no_critic else "critic"


def keep_best(state: RunState, critique: Critique, hard: int, soft: int) -> dict[str, Any]:
    """The critic's update: the round's design goes back with the critique's actions, or the run ends with the best design of its rounds.

    A round's design is the best so far when it has fewer hard issues than the best before it, or as many and fewer soft ones (ties
    keep the earlier one). The run ends when the critique asks for nothing or after MAX_ROUNDS rounds, whatever it asks: the best
    design is restored, with its critique's actions cleared (its rules still say what fails) and its summary saying so, and `best`
    is cleared."""
    round_ = state["round"]
    design = {k: state[k] for k in ("scene_graph", "candidates", "layout", "validation", "fallback") if k in state}
    current = Best.model_validate({**design, "hard": hard, "soft": soft, "critique": critique})
    best = state.get("best") if round_ > 1 else None  # a design run starts its rounds at 1
    if best is None or (hard, soft) < (best.hard, best.soft):
        best = current
    if critique.actions and round_ < MAX_ROUNDS:
        return {"critique": critique, "round": round_ + 1, "best": best}
    summary = best.critique.summary
    if best.critique.actions:
        summary += f"; not fixed in {round_} round{'s' * (round_ != 1)}"
    if best.critique.round != round_:
        summary += f"; round {best.critique.round}'s design is the best"
    final = best.critique.model_copy(update={"actions": [], "summary": summary})
    return {**{k: getattr(best, k) for k in design}, "critique": final, "best": None}  # only the loop needs it


def after_critic(state: RunState) -> Literal["present", "architect", "source"]:
    """Back to the Architect (when any action is for it) or the Sourcer, until the critique asks for nothing (keep_best clears the
    actions at MAX_ROUNDS; the round test is only a guard for a critic that does not)."""
    critique = state["critique"]
    if not critique.actions or critique.round >= MAX_ROUNDS:
        return "present"
    return "architect" if any(a.target == "architect" for a in critique.actions) else "source"


def after_chat_edit(state: RunState) -> Literal["solve", "__end__"]:
    """A refused edit changes nothing: the run ends with chat_edit's answer."""
    diff = state["layout_diff"]
    return "solve" if diff.added or diff.removed or diff.changed else "__end__"
