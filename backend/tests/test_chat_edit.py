"""The chat edit branch (B-21) with the real chat_edit node: the 10 scripted conversations of its done-when, on the small-bedroom
design, offline with the fake model's tool calls, and live on the real model (OPENROUTER_API_KEY)."""

import asyncio
from collections.abc import Callable
from typing import Any, NamedTuple

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore

from app import llm
from app.catalog.embed import index_config, seed
from app.catalog.loader import load_catalog
from app.graph import stub
from app.graph.chat_tools import TOOLS
from app.graph.graph import build_graph, serde
from app.graph.nodes.chat_edit import TOOLS_BY_NAME
from app.graph.nodes.solve import validate
from app.graph.stub import load
from app.llm.fake import CALL_USAGE, FakeLLM, reply
from app.schemas import Brief, DesignBrief, Layout, LayoutDiff, RoomSpec, SceneGraph
from app.schemas.run import StepEvent, ToolEvent
from tests.test_catalog_search import FakeEmbeddings

Values = dict[str, Any]


class Conversation(NamedTuple):
    message: str
    calls: list[tuple[str, dict[str, Any]]]  # the fake model's tool calls, one per model call, before its answer
    applied: bool  # False: the edit must be refused
    check: Callable[[Values, Values], bool]  # (before, after) -> what the edit must have done
    reason: str = ""  # what a refusal must say


def placement(values: Values, node_id: str) -> Any:
    return next(p for p in values["layout"].placements if p.node_id == node_id)


def price(values: Values, node_id: str) -> float:
    return load_catalog()[placement(values, node_id).item_id].price


def changed(diff: LayoutDiff, *ids: str) -> bool:
    return set(ids) <= set(diff.changed) and not diff.added and not diff.removed


CONVERSATIONS = [
    Conversation(
        "Pull @desk_chair 15 cm back from the desk",
        [("move_item", {"node_id": "desk_chair", "x": 0.95, "y": 2.7})],
        True,
        lambda b, a: changed(a["layout_diff"], "desk_chair") and placement(a, "desk_chair").x > placement(b, "desk_chair").x,
    ),
    Conversation(
        "Slide the desk 40 cm toward wall A",
        [("get_layout", {}), ("move_item", {"node_id": "desk", "x": 0.25, "y": 2.3})],
        True,  # its chair, placed in front of it, moves with it
        lambda b, a: (
            changed(a["layout_diff"], "desk", "desk_chair")
            and all(placement(a, i).y < placement(b, i).y - 0.2 for i in ("desk", "desk_chair"))
        ),
    ),
    Conversation(
        "Turn the nightstand around",
        [("rotate_item", {"node_id": "nightstand", "rotation": 270})],
        True,
        lambda b, a: (
            changed(a["layout_diff"], "nightstand")
            and placement(a, "nightstand").rotation == (placement(b, "nightstand").rotation + 180) % 360
        ),
    ),
    Conversation(
        "Swap the desk chair for a cheaper one",
        [("swap_item", {"node_id": "desk_chair", "request": "cheaper"})],
        True,
        lambda b, a: changed(a["layout_diff"], "desk_chair") and price(a, "desk_chair") < price(b, "desk_chair"),
    ),
    Conversation(
        "I'd like a white bed instead",
        [("swap_item", {"node_id": "bed", "request": "white"})],
        True,
        lambda b, a: "bed" in a["layout_diff"].changed and load_catalog()[placement(a, "bed").item_id].color == "white",
    ),
    Conversation(
        "Add a floor lamp next to the bed",
        [("add_item", {"name": "floor lamp", "category": "lamp", "relation": "adjacent", "target": "bed"})],
        True,
        lambda b, a: (
            len(a["layout_diff"].added) == 1 and load_catalog()[placement(a, a["layout_diff"].added[0]).item_id].category == "lamp"
        ),
    ),
    Conversation(
        "Remove the nightstand",
        [("remove_item", {"node_id": "nightstand"})],
        True,
        lambda b, a: a["layout_diff"] == LayoutDiff(removed=["nightstand"]) and "nightstand" not in {n.id for n in a["scene_graph"].nodes},
    ),
    Conversation(  # inside the room, but in the door's swing: refused
        "Put the bed right in front of the door",
        [("get_layout", {}), ("move_item", {"node_id": "bed", "x": 2.2, "y": 0.9})],
        False,
        lambda b, a: True,
        "refused: bed blocks the door swing of door_1",
    ),
    Conversation(  # no such item: refused
        "Remove the sofa",
        [("remove_item", {"node_id": "sofa"})],
        False,
        lambda b, a: True,
        "refused: there is no item sofa",
    ),
    Conversation(  # a king-size bed does not fit beside the desk and the wardrobe: refused
        "Swap the bed for the catalog item walnut-bed-180",
        [("swap_item", {"node_id": "bed", "request": "", "item_id": "walnut-bed-180"})],
        False,
        lambda b, a: True,
        "refused: walnut-bed-180 does not fit",
    ),
]


@pytest.fixture(scope="module")
def store() -> BaseStore:
    store = InMemoryStore(index=index_config(FakeEmbeddings()))
    asyncio.run(seed(store))
    return store


def designed(store: BaseStore) -> tuple[Any, Any]:
    """A graph on a thread whose design is the small-bedroom fixture's, as a finished design run leaves it."""
    graph = build_graph(InMemorySaver(serde=serde()), store)
    config: Any = {"configurable": {"thread_id": "t1"}}
    values = {
        "room_spec": load("room_spec", RoomSpec),
        "brief": load("brief", Brief),
        "design_brief": load("design_brief", DesignBrief),
        "scene_graph": load("scene_graph", SceneGraph),
        "layout": load("layout", Layout),
        "mode": "design",
    }
    graph.update_state(config, values, as_node="present")
    return graph, config


def tool_calls(*calls: tuple[str, dict[str, Any]]) -> list[AIMessage]:
    return [
        reply(tool_calls=[{"name": name, "args": args, "id": f"call_{i}", "type": "tool_call"}]) for i, (name, args) in enumerate(calls)
    ]


def chat(graph: Any, config: Any, message: str) -> tuple[Values, Values, list[tuple[str, Any]]]:
    """The thread's values before and after a chat message, and the run's stream parts."""
    before = graph.get_state(config).values
    parts = list(graph.stream({"chat_message": message}, config, stream_mode=["custom", "updates", "messages"]))
    return before, graph.get_state(config).values, parts


def verdict(conversation: Conversation, before: Values, after: Values) -> bool:
    """Whether the run did what the conversation asks: the edit applied as checked, or refused with the design unchanged."""
    if not conversation.applied:
        unchanged = all(after[k] == before[k] for k in ("scene_graph", "layout"))
        return unchanged and after["layout_diff"] == LayoutDiff() and bool(after["messages"][-1].content)
    was = validate(before["scene_graph"], before["room_spec"], before["layout"]).issues
    return conversation.check(before, after) and not [i for i in after["validation"].issues if i.severity == "error" and i not in was]


@pytest.mark.parametrize("conversation", CONVERSATIONS, ids=[c.message for c in CONVERSATIONS])
def test_scripted_conversations(conversation: Conversation, store: BaseStore, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeLLM(*tool_calls(*conversation.calls), reply("Done: here is why."))
    monkeypatch.setattr(llm, "get_llm", lambda role: fake)
    monkeypatch.setattr(stub, "live", lambda node: node == "chat_edit")  # only chat_edit is real
    graph, config = designed(store)
    before, after, parts = chat(graph, config, conversation.message)

    assert verdict(conversation, before, after)
    tools = [ToolEvent.model_validate(c) for mode, c in parts if mode == "custom" and c.get("type") == "tool"]
    assert [t.tool for t in tools] == [name for name, _ in conversation.calls]
    assert tools[-1].ok == conversation.applied and tools[-1].summary.startswith(conversation.reason)
    steps = [StepEvent.model_validate(c) for mode, c in parts if mode == "custom" and c.get("type") == "step"]
    path = ["route_input", "chat_edit", "solve", "present"] if conversation.applied else ["route_input", "chat_edit"]
    assert [s.node for s in steps if s.status == "done"] == path
    done = next(s for s in steps if s.node == "chat_edit" and s.status == "done")
    assert done.summary == ("edit applied" if conversation.applied else "edit refused")
    assert done.cost == pytest.approx(CALL_USAGE["cost"] * fake.calls) and fake.calls == len(conversation.calls) + 1
    # the answer streams as plain text from chat_edit, and joins the history
    messages = [chunk for mode, chunk in parts if mode == "messages"]
    tokens = "".join(m.text for m, meta in messages if meta["langgraph_node"] == "chat_edit")
    assert tokens == "Done: here is why." == after["messages"][-1].content == after["rationale"]
    if conversation.applied:
        assert {i.node_id for i in after["scene"].items} == {p.node_id for p in after["layout"].placements}


def test_a_move_out_of_the_room_is_refused_with_the_reason_and_the_model_hears_it(
    store: BaseStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeLLM(*tool_calls(("move_item", {"node_id": "bed", "x": 3.0, "y": 2.25})), reply("It would go through wall B."))
    monkeypatch.setattr(llm, "get_llm", lambda role: fake)
    monkeypatch.setattr(stub, "live", lambda node: node == "chat_edit")
    graph, config = designed(store)
    before, after, _ = chat(graph, config, "Push the bed 80 cm into wall B")
    assert after["layout"] == before["layout"] and after["layout_diff"] == LayoutDiff()
    tool_message = fake.prompts[1][-1]
    assert tool_message.status == "error" and "bed overlaps wall_B" in tool_message.content


def test_the_prompt_resolves_item_references_and_the_history_reaches_the_model(store: BaseStore, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeLLM(reply("First."), *tool_calls(("explain", {"node_id": "desk"}), ("frobnicate", {})), reply("Second."))
    monkeypatch.setattr(llm, "get_llm", lambda role: fake)
    monkeypatch.setattr(stub, "live", lambda node: node == "chat_edit")
    graph, config = designed(store)
    chat(graph, config, "Hello")
    _, after, _ = chat(graph, config, "Why is @desk there, and @lamp?")
    system, *history = fake.prompts[1]
    assert "desk: desk" in system.content and "not items of the design: @lamp" in system.content
    assert [m.content for m in history[:3]] == ["Hello", "First.", "Why is @desk there, and @lamp?"]
    explained, unknown = [m for m in fake.prompts[3] if isinstance(m, ToolMessage)]
    assert "relations: desk against wall wall_D; desk_chair in front desk" in explained.content
    assert unknown.status == "error" and "no tool frobnicate" in unknown.content
    assert after["layout_diff"] == LayoutDiff() and after["messages"][-1].content == "Second."


def test_every_tool_hides_the_injected_state_from_the_model() -> None:
    for tool in TOOLS:
        assert not {"state", "tool_call_id"} & set(tool.tool_call_schema.model_json_schema()["properties"])
    assert set(TOOLS_BY_NAME) == {"get_layout", "move_item", "rotate_item", "swap_item", "add_item", "remove_item", "explain"}


@pytest.mark.live
def test_live_scripted_conversations() -> None:
    """Done-when of B-21 on the real model: the 10 conversations, each on a fresh copy of the design; prints a pass/fail and cost
    table. The catalog search uses the real embeddings (one batch request to seed the store).

    Run once: `OPENROUTER_API_KEY=... uv run pytest tests/test_chat_edit.py -k live -s`.
    """
    store = InMemoryStore(index=index_config())
    asyncio.run(seed(store))
    rows = []
    for conversation in CONVERSATIONS:
        graph, config = designed(store)
        before, after, parts = chat(graph, config, conversation.message)
        tools = [f"{c['tool']}{'' if c['ok'] else ' (refused)'}" for mode, c in parts if mode == "custom" and c.get("type") == "tool"]
        rows.append(
            (conversation.message, verdict(conversation, before, after), after.get("cost", 0.0), tools, after["messages"][-1].content)
        )
    print("\n| # | conversation | expected | result | cost (USD) | tools | answer |\n|---|---|---|---|---|---|---|")
    for i, ((message, ok, cost, tools, answer), c) in enumerate(zip(rows, CONVERSATIONS, strict=True), 1):
        expected = "applied" if c.applied else "refused"
        print(f"| {i} | {message} | {expected} | {'pass' if ok else 'FAIL'} | {cost:.4f} | {', '.join(tools)} | {answer} |")
    print(f"total cost: {sum(r[2] for r in rows):.4f} USD")
    assert all(ok for _, ok, *_ in rows)
