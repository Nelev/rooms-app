"""Tracing and logging, offline: a mock LangSmith client records what the tracer would send."""

import io
import json
import logging
from typing import Any, TypedDict
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.tracers.context import tracing_v2_enabled
from langchain_core.tracers.langchain import wait_for_all_tracers
from langgraph.graph import START, StateGraph
from langsmith import Client

from app.main import app
from app.observability.logs import JsonFormatter
from app.observability.tracing import traced


class State(TypedDict, total=False):
    text: str


def reply(cost: float | None, tokens: int) -> AIMessage:
    """A model reply as OpenRouter gives it: tokens in usage_metadata, the cost charged in token_usage (none when
    streamed)."""
    usage = {"input_tokens": tokens, "output_tokens": 1, "total_tokens": tokens + 1}
    return AIMessage("ok", usage_metadata=usage, response_metadata={} if cost is None else {"token_usage": {"cost": cost}})


def two_node_graph(replies: list[AIMessage]) -> Any:
    """`first` makes one model call, `second` two (the last one streamed); `replies` collects what the nodes get back."""
    model = FakeMessagesListChatModel(responses=[reply(0.01, 10), reply(0.02, 20), reply(None, 30)])

    def call(prompt: str) -> str:
        replies.append(model.invoke(prompt))  # type: ignore[arg-type]
        return str(replies[-1].content)

    def first(state: State) -> State:
        return {"text": call("first")}

    def second(state: State) -> State:
        return {"text": call("second") + call("second, streamed")}

    builder = StateGraph(State)
    builder.add_node(first)
    builder.add_node(second)
    builder.add_edge(START, "first")
    builder.add_edge("first", "second")
    return builder.compile()


def test_a_run_is_one_trace_with_nested_node_spans_and_costs() -> None:
    client = MagicMock(spec=Client)
    run_id = uuid4()
    config = traced({"configurable": {"thread_id": "t1", "no_critic": True}}, run_id)
    replies: list[AIMessage] = []
    with tracing_v2_enabled(client=client):
        two_node_graph(replies).invoke({}, config)
    wait_for_all_tracers()

    runs = {c.kwargs["id"]: c.kwargs for c in client.create_run.call_args_list}
    for c in client.update_run.call_args_list:  # a run's end (outputs, usage) comes as an update
        runs[c.kwargs["run_id"]] |= c.kwargs

    root = runs[run_id]
    assert root.get("parent_run_id") is None
    assert {r["trace_id"] for r in runs.values()} == {run_id}  # one trace
    assert "no_critic" in root["tags"]
    assert root["extra"]["metadata"] | {"thread_id": "t1", "no_critic": True, "single_agent": False} == root["extra"]["metadata"]

    nodes = {r["name"]: r for r in runs.values() if r.get("parent_run_id") == run_id and r["name"] in ("first", "second")}
    assert set(nodes) == {"first", "second"}
    llm_runs = [r for r in runs.values() if r["run_type"] == "llm"]
    usage = [(r["extra"]["metadata"]["usage_metadata"], runs[r["parent_run_id"]]["name"]) for r in llm_runs]
    assert sorted((u["input_tokens"], u.get("total_cost"), node) for u, node in usage) == [
        (10, 0.01, "first"),
        (20, 0.02, "second"),
        (30, None, "second"),  # streamed: no provider cost, LangSmith prices it from its model table
    ]
    assert all("total_cost" not in r.usage_metadata for r in replies)  # type: ignore[operator]  # graph state stays clean


def test_requests_get_an_id_on_their_json_logs() -> None:
    out = io.StringIO()
    handler = logging.StreamHandler(out)
    handler.setFormatter(JsonFormatter())
    logging.getLogger("app.request").addHandler(handler)
    try:
        with TestClient(app) as client:
            assert len(client.get("/health").headers["X-Request-ID"]) == 32
            assert client.get("/health", headers={"X-Request-ID": "abc"}).headers["X-Request-ID"] == "abc"
            for bad in (b"\xff\xfe", "\u20ac".encode(), b"a b"):  # not a plain token: replaced, never echoed
                assert len(client.get("/health", headers={b"x-request-id": bad}).headers["X-Request-ID"]) == 32
    finally:
        logging.getLogger("app.request").removeHandler(handler)
    first, second, *_ = (json.loads(line) for line in out.getvalue().splitlines())
    assert len(first["request_id"]) == 32
    assert second | {"message": "GET /health 200", "request_id": "abc", "status": 200, "level": "INFO"} == second
    assert isinstance(second["duration_ms"], float)
