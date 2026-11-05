from typing import Any

from app.graph.state import RunState
from app.graph.stub import ask, load, stub_node
from app.schemas import SceneGraph


@stub_node
def refine(state: RunState) -> dict[str, Any]:
    return {"scene_graph": ask(SceneGraph, load("scene_graph", SceneGraph))}
