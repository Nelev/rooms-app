from typing import Any

from app.graph.state import RunState
from app.graph.stub import ask, load, stub_node
from app.schemas import RoomSpec


@stub_node
def analyze_room(state: RunState) -> dict[str, Any]:
    return {"room_spec": ask(RoomSpec, load("room_spec", RoomSpec))}
