"""The graph's wiring on the stub nodes, in memory: each run's path through the nodes, as its LangSmith trace shows it."""

from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from langchain_core.tracers.context import tracing_v2_enabled
from langchain_core.tracers.langchain import wait_for_all_tracers
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command
from langsmith import Client

from app.graph.graph import RECURSION_LIMIT, build_graph, serde
from app.graph.nodes import critic
from app.graph.routing import MAX_ROUNDS, after_critic, flags
from app.graph.state import RunState
from app.graph.stub import fixture, load
from app.observability.tracing import traced
from app.schemas import Critique, RoomSpec
from app.schemas.layout import CritiqueAction
from tests.test_api import design_input, one_round, stub_cost

DESIGN = ["route_input", "analyze_room", "confirm_room"]
ROUND = ["architect", "refine", "source", "solve", "critic"]
RESUMED = ["confirm_room", "design", *ROUND, "present"]  # the real critic accepts the fixture design in one round
CHAT = ["route_input", "chat_edit", "solve", "present"]


def traced_nodes(graph: Any, graph_input: Any, **configurable: Any) -> list[str]:
    """Run `graph` on thread t1 with a mock LangSmith client: the nodes its one trace shows, in order."""
    client, run_id = MagicMock(spec=Client), uuid4()
    with tracing_v2_enabled(client=client):
        graph.invoke(graph_input, traced({"configurable": {"thread_id": "t1", **configurable}}, run_id))
    wait_for_all_tracers()
    runs = [c.kwargs for c in client.create_run.call_args_list]
    assert {r["trace_id"] for r in runs} == {run_id}
    return [r["name"] for r in runs if r.get("parent_run_id") == run_id]


def test_design_run_pauses_at_confirm_room_then_chat_runs_take_the_chat_branch() -> None:
    graph = build_graph(InMemorySaver(serde=serde()), InMemoryStore())
    config: Any = {"configurable": {"thread_id": "t1"}}
    assert graph.config and graph.config["recursion_limit"] == RECURSION_LIMIT  # every run's default

    assert traced_nodes(graph, design_input()) == DESIGN
    (interrupt,) = graph.get_state(config).interrupts
    assert RoomSpec.model_validate(interrupt.value["room"]) == load("room_spec", RoomSpec)

    assert traced_nodes(graph, Command(resume=fixture("room_spec"))) == RESUMED
    values: RunState = graph.get_state(config).values
    assert values["best"] is None and values["fallback"].changes == []  # best is the loop's, cleared at the end
    assert (values["critique"].round, values["critique"].actions) == (1, []) and not graph.get_state(config).next
    assert values["scene"].cameras == []  # the fixture scene's camera is matched to the fixture photo, not the user's

    applied, refused = fixture("chat")
    assert traced_nodes(graph, applied["input"]) == CHAT
    assert traced_nodes(graph, refused["input"]) == CHAT[:2]  # a refused edit ends at chat_edit
    values = graph.get_state(config).values
    assert [m.role for m in values["messages"]] == ["user", "assistant"] * 2
    events = fixture("stream_events")
    assert values["cost"] == pytest.approx(  # the thread's usage, added up across its runs
        stub_cost(events["first_run"] + one_round(events["resumed_run"]))
        + sum(e.get("cost", 0) for turn in fixture("chat") for e in turn["events"])
    )


def test_no_critic_presents_the_first_layout() -> None:
    graph = build_graph(InMemorySaver(serde=serde()))
    assert traced_nodes(graph, design_input(), no_critic=True) == DESIGN
    assert traced_nodes(graph, Command(resume=fixture("room_spec")), no_critic=True) == [*RESUMED[:6], "present"]


def test_critic_rounds_are_capped() -> None:
    fix = Critique(round=1, summary="", actions=[CritiqueAction(target="architect", instruction="Fix it")])
    swap = Critique(round=1, summary="", actions=[CritiqueAction(target="sourcer", instruction="Swap it")])
    assert after_critic({"critique": fix}) == "architect"
    assert after_critic({"critique": swap}) == "source"
    assert after_critic({"critique": Critique(round=1, summary="")}) == "present"
    assert after_critic({"critique": fix.model_copy(update={"round": MAX_ROUNDS})}) == "present"


def test_flags_come_from_the_configurable() -> None:
    assert flags({"configurable": {"thread_id": "t1", "single_agent": True}}).model_dump() == {
        "no_critic": False,
        "single_agent": True,
        "analyst_mode": False,
    }
    assert not flags({}).no_critic


def test_a_critic_that_always_asks_for_fixes_ends_after_max_rounds_with_the_best_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    hard = {1: 2, 2: 0, 3: 1}  # round 2's design is the best

    def judge(state: RunState) -> tuple[Critique, int, int]:
        fix = CritiqueAction(target="architect", instruction="Fix it")
        return Critique(round=state["round"], actions=[fix], summary=f"round {state['round']}"), hard[state["round"]], 0

    monkeypatch.setattr(critic, "judge", judge)
    graph = build_graph(InMemorySaver(serde=serde()), InMemoryStore())
    config: Any = {"configurable": {"thread_id": "t1"}}
    graph.invoke(design_input(), config)
    updates = list(graph.stream(Command(resume=fixture("room_spec")), config, stream_mode="updates"))
    assert [node for update in updates for node in update] == [*RESUMED[:2], *ROUND * MAX_ROUNDS, "present"]
    layouts = [u["solve"]["layout"] for u in updates if "solve" in u]  # each round samples its own layout
    values = graph.get_state(config).values
    assert values["layout"] == layouts[1] != layouts[2]
    assert [i.x for i in values["scene"].items] == [p.x for p in layouts[1].placements]
    critique = values["critique"]
    assert (critique.round, critique.actions) == (2, [])
    assert critique.summary == f"round 2; not fixed in {MAX_ROUNDS} rounds; round 2's design is the best"
