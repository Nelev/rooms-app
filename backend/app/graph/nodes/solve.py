from typing import Any

from app.graph.state import RunState
from app.graph.stub import chat_turn, load, stub_node
from app.schemas import Layout, RunOutput, ValidationReport


@stub_node
def solve(state: RunState) -> dict[str, Any]:
    layout = RunOutput.model_validate(chat_turn(state)["output"]).layout if state["mode"] == "chat" else load("layout", Layout)
    return {"layout": layout, "validation": ValidationReport()}
