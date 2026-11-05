from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.design import BRIEF_EXAMPLE, Brief
from app.schemas.layout import LAYOUT_EXAMPLE, Critique, Layout, LayoutDiff
from app.schemas.room import ROOM_SPEC_EXAMPLE, Dimensions, RoomSpec
from app.schemas.scene import Scene

NodeName = Literal[
    "route_input", "analyze_room", "confirm_room", "design", "architect", "refine", "source", "solve", "critic", "present", "chat_edit"
]


class StepEvent(BaseModel):
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


class ToolEvent(BaseModel):
    """Emitted by chat_edit for each tool it runs, shown as a step chip in the chat."""

    model_config = ConfigDict(json_schema_extra={"examples": [{"type": "tool", "tool": "move_item", "summary": "moved desk", "ok": True}]})

    type: Literal["tool"] = "tool"
    tool: str
    summary: str
    ok: bool = Field(True, description="False when the edit was refused; summary then says why")


StreamEvent = Annotated[StepEvent | ToolEvent, Field(discriminator="type")]


class RunInput(BaseModel):
    """The graph's input: a new design (photos, dimensions and brief) or a chat message on an existing design."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"photo_keys": ["uploads/3f2a/photo-1.jpg"], "dimensions": ROOM_SPEC_EXAMPLE["dimensions"], "brief": BRIEF_EXAMPLE},
                {"chat_message": "Move the desk closer to the window"},
            ],
            # the same rule as _one_kind, for clients generated from the JSON Schema
            "oneOf": [
                {"required": ["photo_keys", "dimensions", "brief"]},
                {"required": ["chat_message"], "properties": {"photo_keys": False, "dimensions": False, "brief": False}},
            ],
        }
    )

    photo_keys: list[str] = Field([], max_length=3, description="Object-storage keys of the uploaded photos")
    dimensions: Dimensions | None = None
    brief: Brief | None = None
    chat_message: str | None = None

    @model_validator(mode="after")
    def _one_kind(self) -> Self:
        parts = (self.photo_keys, self.dimensions, self.brief)
        chat = self.chat_message is not None
        if (chat and any(parts)) or (not chat and not all(parts)):
            raise ValueError("give either photo_keys, dimensions and brief, or chat_message")
        return self


class RunOutput(BaseModel):
    """What a finished run leaves for the frontend."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"layout": LAYOUT_EXAMPLE, "rationale": "The bed sits against wall B, away from the door"}]}
    )

    scene: Scene | None = None
    layout: Layout | None = None
    critique: Critique | None = None
    layout_diff: LayoutDiff | None = None
    rationale: str | None = None


class ConfirmRoom(BaseModel):
    """The confirm_room interrupt payload; the run resumes with the corrected RoomSpec (ConfirmRoomResume)."""

    model_config = ConfigDict(json_schema_extra={"examples": [{"room": ROOM_SPEC_EXAMPLE, "overlay_keys": ["overlays/3f2a/photo-1.png"]}]})

    room: RoomSpec
    overlay_keys: list[str] = Field([], description="Detection overlay image per photo")


ConfirmRoomResume = RoomSpec
