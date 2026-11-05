from typing import Any

from app.graph.state import RunState
from app.graph.stub import ask, load, stub_node
from app.schemas import CatalogItem, Scene


@stub_node
def source(state: RunState) -> dict[str, Any]:
    candidates = {i.node_id: [i.item] for i in load("scene", Scene).items if i.item}
    return {"candidates": ask(dict[str, list[CatalogItem]], candidates)}
