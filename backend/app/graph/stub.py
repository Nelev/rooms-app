"""What the stub nodes share: the fixture case they replay, the fake model, and the fixture's stream events.

Every stub node replays fixtures/small-bedroom: its output, and the custom stream events of its step (those of the
design run, or of the chat turn the thread is on). Real nodes replace each stub in graph/nodes/.
"""

import json
import os
import time
from collections.abc import Callable
from functools import cache, wraps
from pathlib import Path
from typing import Any

from langgraph.config import get_stream_writer
from pydantic import TypeAdapter

from app.graph.state import RunState
from app.llm.fake import FakeLLM
from app.schemas import CatalogItem, Scene

CASE = Path(__file__).resolve().parents[3] / "fixtures" / "small-bedroom"
PACE = float(os.environ.get("STUB_PACE", "0"))  # seconds slept per second of a step's fixture duration_s; `make dev-stub` slows runs down

Event = dict[str, Any]


def live(node: str) -> bool:
    """Whether a node calls the model: with OPENROUTER_API_KEY every real node does, without it they all replay the fixture.

    Nodes call it as `stub.live(name)`, so a test can make a single node real (monkeypatch `stub.live`)."""
    return bool(os.environ.get("OPENROUTER_API_KEY"))


@cache
def fixture(name: str) -> Any:
    """The fixture file `name`.json, parsed."""
    return json.loads((CASE / f"{name}.json").read_text())


def load[T](name: str, type_: type[T]) -> T:
    """The fixture file `name`.json as a `type_`."""
    return TypeAdapter(type_).validate_python(fixture(name))


def ask[T](type_: Any, value: T) -> T:
    """`value` as a model would return it: the fake model replies with its JSON, so the run streams a real model message."""
    adapter = TypeAdapter[T](type_)
    reply = FakeLLM(adapter.dump_json(value).decode()).invoke("")
    return adapter.validate_json(str(reply.content))


def chat_turn(state: RunState) -> dict[str, Any]:
    """The fixture chat turn of the chat run in progress; the turns repeat once all are used."""
    chat = fixture("chat")
    pending = bool(state.get("chat_message"))  # a chat message route_input has not moved yet
    turns = sum(m.role == "user" for m in state.get("messages", [])) + pending
    return dict(chat[(turns - 1) % len(chat)])


def _run_events(state: RunState, node: str) -> list[Event]:
    """The fixture events of the run in progress. route_input runs before it sets the run's mode: its input says it."""
    if state.get("chat_message") if node == "route_input" else state["mode"] == "chat":
        return list(chat_turn(state)["events"])
    events = fixture("stream_events")
    return [*events["first_run"], *events["resumed_run"]]


def _step(events: list[Event], node: str, round_: int | None) -> tuple[int, int]:
    """Where `node`'s step (its started event to its done event, tool events included) is in `events`; a critic round past the
    fixture's replays the node's last fixture round."""
    if rounds := [e["round"] for e in events if e.get("node") == node and e.get("round")]:
        round_ = min(round_ or 1, max(rounds))

    def match(e: Event, status: str) -> bool:
        return e.get("node") == node and e["status"] == status and e.get("round") in (round_, None)

    end = next(i for i, e in enumerate(events) if match(e, "done"))
    return max(i for i in range(end) if match(events[i], "started")), end  # a resumed node starts twice: the last start


def stub_node(fn: Callable[[RunState], dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Wrap a stub node: it streams its fixture step events around the node's work and adds the step's cost to the usage.

    The fixture's cost is only the replay's: a live node (`live(name)`, a key is set) adds its own usage, none when it calls no model
    (the Sourcer), and its done event carries that cost, so a production run's cost is the models' usage only."""

    @wraps(fn)
    def node(state: RunState) -> dict[str, Any]:
        round_ = state.get("round")
        events = _run_events(state, fn.__name__)
        start, end = _step(events, fn.__name__, round_)
        events = [{**e, "round": round_} if e.get("round") else e for e in events]  # a replayed fixture round has the run's round
        write = get_stream_writer()
        write(events[start])
        update = fn(state)  # may interrupt: the node starts over on resume
        time.sleep(PACE * events[end].get("duration_s", 0))
        cost = update.get("cost", 0.0) if live(fn.__name__) else events[end].get("cost", 0.0)
        if "cost" in events[end]:
            events[end] = {**events[end], "cost": cost}
        for event in events[start + 1 : end + 1]:
            write(event)
        return {**update, "cost": cost}

    return node


@cache
def catalog() -> dict[str, CatalogItem]:
    """The catalog items of every fixture case's scene, by id."""
    scenes = [TypeAdapter(Scene).validate_json(p.read_bytes()) for p in CASE.parent.glob("*/scene.json")]
    return {i.item.id: i.item for s in scenes for i in s.items if i.item}
