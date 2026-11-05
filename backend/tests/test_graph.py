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
from app.graph.routing import MAX_ROUNDS, after_critic, flags
from app.graph.state import RunState
from app.graph.stub import fixture, load
from app.observability.tracing import traced
from app.schemas import Critique, Layout, RoomSpec
from app.schemas.layout import CritiqueAction
from tests.test_api import design_input

DESIGN = ["route_input", "analyze_room", "confirm_room"]
RESUMED = ["confirm_room", "design", *["architect", "refine", "source", "solve", "critic"] * 2, "present"]  # the fixture's 2 critic rounds
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
    assert values["layout"] == load("layout", Layout)
    assert values["critique"].round == 2 and not graph.get_state(config).next

    applied, refused = fixture("chat")
    assert traced_nodes(graph, applied["input"]) == CHAT
    assert traced_nodes(graph, refused["input"]) == CHAT[:2]  # a refused edit ends at chat_edit
    values = graph.get_state(config).values
    assert [m.role for m in values["messages"]] == ["user", "assistant"] * 2
    assert values["cost"] == pytest.approx(  # the thread's usage, added up across its runs
        sum(e.get("cost", 0) for e in [*fixture("stream_events")["first_run"], *fixture("stream_events")["resumed_run"]])
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
