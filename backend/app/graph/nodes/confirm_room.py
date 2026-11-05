from typing import Any

from langgraph.types import interrupt

from app.graph.state import RunState
from app.graph.stub import stub_node
from app.schemas import ConfirmRoom, ConfirmRoomResume


@stub_node
def confirm_room(state: RunState) -> dict[str, Any]:
    """Ask the user to confirm or correct the room; resumes with the confirmed RoomSpec. Calls no model: it starts over on resume."""
    room = interrupt(ConfirmRoom(room=state["room_spec"], overlay_keys=[]).model_dump(mode="json"))  # JSON, as the API sends it
    return {"room_spec": ConfirmRoomResume.model_validate(room)}
