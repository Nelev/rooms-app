"""The chat edit node (B-21): a tool-calling model edits the thread's design as the chat message asks, with graph/chat_tools.py.

A small loop, as CoA's ReAct agent but inside the node: the model is called with the tools bound, each tool it calls runs on the
design as edited so far (its Command updates it, its ToolMessage goes back to the model and its ToolEvent to the run timeline),
until the model answers in plain text. Its calls stream through LangGraph's `messages` mode from this node, so the reply reaches
the chat as it does from the stub. The answer joins the chat history; a LayoutDiff (by placement id) says what changed. When nothing
changed (every edit refused, or none asked) the diff is empty, the layout stays as it was and the run ends here (routing); else
solve validates the edited design and present builds its scene.

Without OPENROUTER_API_KEY (stub.live) the node replays the fixture chat turn, like the rest of the stub graph.
"""

import re
import time
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.config import get_stream_writer

from app import llm
from app.graph import stub
from app.graph.chat_tools import TOOLS
from app.graph.state import ChatEntry, RunState
from app.graph.stub import ask, chat_turn, stub_node
from app.schemas import LayoutDiff, RunOutput, coords

PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "chat_edit" / "system.md"
MAX_CALLS = 8  # model calls per chat message: a guard against a model that keeps calling tools
HISTORY = 10  # chat entries the model sees, the new message included
TOOLS_BY_NAME = {t.name: t for t in TOOLS}


def _prompt(state: RunState, message: str) -> str:
    objects = [n for n in state["scene_graph"].nodes if n.kind == "object"]
    ids = {n.id for n in objects}
    refs = list(dict.fromkeys(re.findall(r"@([\w-]+)", message)))  # the chat panel's item references (F-12)
    unknown = [r for r in refs if r not in ids]
    references = f"The message refers to {', '.join('@' + r for r in refs)}." if refs else ""
    if unknown:
        references += f" These are not items of the design: {', '.join('@' + r for r in unknown)}."
    items = "; ".join(f"{n.id}: {n.name}" for n in objects)
    return PROMPT.read_text().format(coords=coords.__doc__, items=items, references=references)


def _history(state: RunState) -> list[BaseMessage]:
    return [HumanMessage(m.content) if m.role == "user" else AIMessage(m.content) for m in state.get("messages", [])[-HISTORY:]]


def diff(before: RunState, after: dict[str, Any]) -> LayoutDiff:
    """What changed from `before` to `after`, by placement id (a node's copies are placed as <id>_2, <id>_3...)."""
    old = {p.node_id: p for p in before["layout"].placements} if "layout" in before else {}
    new = {p.node_id: p for p in after["layout"].placements} if "layout" in after else {}
    return LayoutDiff(
        added=[i for i in new if i not in old],
        removed=[i for i in old if i not in new],
        changed=[i for i in new if i in old and new[i] != old[i]],
    )


def run_tool(call: dict[str, Any], design: dict[str, Any]) -> ToolMessage:
    """Run a tool the model called on `design` (updated in place with the tool's Command); its message for the model."""
    tool = TOOLS_BY_NAME.get(call["name"])
    try:
        if tool is None:
            raise ValueError(f"no tool {call['name']}; the tools are {', '.join(TOOLS_BY_NAME)}")
        update = dict(tool.invoke({**call, "args": {**call["args"], "state": design}}).update)
    except Exception as e:  # bad arguments or a failing tool: told to the model, the design unchanged (as ToolNode's handle_tool_errors)
        return ToolMessage(f"invalid call: {e}", name=call["name"], tool_call_id=call["id"], status="error")
    message: ToolMessage = update.pop("messages")[0]
    design.update(update)
    return message


def edit(state: RunState) -> tuple[dict[str, Any], str, llm.Usage, int]:
    """The design as the chat message edits it (the state's scene graph, layout and candidates), the model's answer, its usage and
    how many edits the tools refused."""
    write = get_stream_writer()
    model = llm.get_llm("chat_edit").bind_tools(TOOLS)
    history = _history(state)
    messages: list[BaseMessage] = [SystemMessage(_prompt(state, str(history[-1].content))), *history]
    design: dict[str, Any] = dict(state)
    usage: llm.Usage = {"cost": 0.0, "input_tokens": 0, "output_tokens": 0}
    refused = 0
    for _ in range(MAX_CALLS):
        reply = model.invoke(messages)
        usage = llm.add_usage(usage, llm.call_usage(reply))
        if reply.response_metadata.get("finish_reason") == "length":  # cut off: its tool calls or answer would be incomplete
            raise llm.TruncatedReply(f"the chat_edit model's reply hit max_tokens ({llm.ROLES['chat_edit'].max_tokens})")
        messages.append(reply)
        if not reply.tool_calls:
            return design, reply.text, usage, refused
        for call in reply.tool_calls:
            result = run_tool(dict(call), design)
            messages.append(result)
            refused += result.status == "error"
            summary = str(result.content).split("\n")[0][:200]
            write({"type": "tool", "tool": call["name"], "summary": summary, "ok": result.status != "error"})  # a ToolEvent
    return design, "I could not finish this edit; please ask again, one change at a time.", usage, refused


def _replay(state: RunState) -> dict[str, Any]:
    output = RunOutput.model_validate(chat_turn(state)["output"])
    rationale = ask(str, output.rationale or "")
    return {"layout_diff": output.layout_diff, "rationale": rationale, "messages": [ChatEntry(role="assistant", content=rationale)]}


_replay.__name__ = "chat_edit"  # stub_node finds the fixture step events by the node's name
replay = stub_node(_replay)  # the stub graph's chat edit: the fixture chat turn and its stream events


def chat_edit(state: RunState) -> dict[str, Any]:
    """Apply the chat message's edits; a refused edit leaves an empty layout_diff and the design unchanged."""
    if not stub.live("chat_edit"):
        return replay(state)
    write, start = get_stream_writer(), time.monotonic()
    step = {"type": "step", "node": "chat_edit"}  # a StepEvent
    write({**step, "status": "started"})
    if "layout" in state:
        design, answer, usage, refused = edit(state)
    else:  # no design to edit yet (the chat panel only opens on one)
        design, answer, usage, refused = {}, "There is no design to edit yet.", llm.Usage(cost=0.0, input_tokens=0, output_tokens=0), 0
    changes = diff(state, design)
    update: dict[str, Any] = {"layout_diff": changes, "rationale": answer, "messages": [ChatEntry(role="assistant", content=answer)]}
    if changed := bool(changes.added or changes.removed or changes.changed):
        update |= {k: design[k] for k in ("scene_graph", "layout", "candidates") if k in design}
    summary = "edit applied" if changed else "edit refused" if refused else "no change"
    write({**step, "status": "done", "summary": summary, "duration_s": round(time.monotonic() - start, 1), "cost": usage["cost"]})
    return {**update, **usage}
