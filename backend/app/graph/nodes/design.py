from typing import Any

from app.graph.state import RunState
from app.graph.stub import ask, load, stub_node
from app.schemas import DesignBrief


@stub_node
def design(state: RunState) -> dict[str, Any]:
    return {"design_brief": ask(DesignBrief, load("design_brief", DesignBrief)), "round": 1}
