from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from app.schemas.base import Model
from app.schemas.design import BRIEF_EXAMPLE, Brief
from app.schemas.layout import LAYOUT_EXAMPLE, Critique, Layout, LayoutDiff
from app.schemas.room import ROOM_SPEC_EXAMPLE, Dimensions, RoomSpec
from app.schemas.scene import Scene

NodeName = Literal[
    "route_input", "analyze_room", "confirm_room", "design", "architect", "refine", "source", "solve", "critic", "present", "chat_edit"
]


class StepEvent(Model):
    """Emitted by a node when it starts and ends, for the run timeline."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "type": "step",
                    "node": "critic",
                    "status": "done",
                    "round": 1,
                    "summary": "1 rule fails",
                    "duration_s": 4.2,
                    "cost": 0.003,
                }
            ]
        }
    )

    type: Literal["step"] = "step"
    node: NodeName
    status: Literal["started", "done", "error"]
    round: int | None = Field(None, ge=1, description="Critic loop round, for nodes inside the loop")
    summary: str = ""
    duration_s: float | None = Field(None, ge=0)
    cost: float | None = Field(None, ge=0, description="USD")


class ToolEvent(Model):
    """Emitted by chat_edit for each tool it runs, shown as a step chip in the chat."""

    model_config = ConfigDict(json_schema_extra={"examples": [{"type": "tool", "tool": "move_item", "summary": "moved desk", "ok": True}]})

    type: Literal["tool"] = "tool"
    tool: str
    summary: str
    ok: bool = Field(True, description="False when the edit was refused; summary then says why")


StreamEvent = Annotated[StepEvent | ToolEvent, Field(discriminator="type")]


class NewDesign(Model):
    """Run input for a new design."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"photo_keys": ["uploads/3f2a/photo-1.jpg"], "dimensions": ROOM_SPEC_EXAMPLE["dimensions"], "brief": BRIEF_EXAMPLE}
            ]
        }
    )

    photo_keys: list[str] = Field(min_length=1, max_length=3, description="Object-storage keys of the uploaded photos")
    dimensions: Dimensions
    brief: Brief


class ChatMessage(Model):
    """Run input for a chat edit on an existing design."""

    model_config = ConfigDict(json_schema_extra={"examples": [{"chat_message": "Move the desk closer to the window"}]})

    chat_message: str = Field(min_length=1)


# extra="forbid" makes the two shapes mutually exclusive, so no tag field is needed
RunInput = Annotated[NewDesign | ChatMessage, Field(description="The graph's input: a new design or a chat message on an existing design")]


class RunOutput(Model):
    """What a finished run leaves for the frontend."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"layout": LAYOUT_EXAMPLE, "rationale": "The bed sits against wall B, away from the door"}]}
    )

    scene: Scene | None = None
    layout: Layout | None = None
    critique: Critique | None = None
    layout_diff: LayoutDiff | None = None
    rationale: str | None = None


class ConfirmRoom(Model):
    """The confirm_room interrupt payload; the run resumes with the corrected RoomSpec (ConfirmRoomResume)."""

    model_config = ConfigDict(json_schema_extra={"examples": [{"room": ROOM_SPEC_EXAMPLE, "overlay_keys": ["overlays/3f2a/photo-1.png"]}]})

    room: RoomSpec
    overlay_keys: list[str] = Field([], description="Detection overlay image per photo")


ConfirmRoomResume = RoomSpec
