from typing import Any

from app.graph.state import ChatEntry, RunState
from app.graph.stub import ask, chat_turn, stub_node
from app.schemas import RunOutput


@stub_node
def chat_edit(state: RunState) -> dict[str, Any]:
    """Apply the chat message's edits; a refused edit leaves an empty layout_diff."""
    output = RunOutput.model_validate(chat_turn(state)["output"])
    rationale = ask(str, output.rationale or "")
    return {"layout_diff": output.layout_diff, "rationale": rationale, "messages": [ChatEntry(role="assistant", content=rationale)]}
