from typing import Any

from app.graph.state import ChatEntry, RunState
from app.graph.stub import stub_node


@stub_node
def route_input(state: RunState) -> dict[str, Any]:
    """Set the run's mode from its input, moving a chat message input to the chat history."""
    if message := state.get("chat_message"):
        return {"mode": "chat", "chat_message": None, "messages": [ChatEntry(role="user", content=message)]}
    return {"mode": "design"}
