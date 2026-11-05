from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.schemas.coords import Degrees, Meters, Size
from app.schemas.design import DESK_EDGE, DESK_NODE, SceneEdge, SceneNode


class Placement(BaseModel):
    node_id: str
    item_id: str | None = None
    x: float
    y: float
    z: Meters = 0
    rotation: Degrees = 0
    size: Size


BED_PLACEMENT: dict[str, JsonValue] = {
    "node_id": "bed",
    "x": 2.15,
    "y": 2.0,
    "rotation": 90,
    "size": {"width": 1.6, "depth": 2.1, "height": 1.0},
}
LAYOUT_EXAMPLE: dict[str, JsonValue] = {
    "placements": [
        BED_PLACEMENT,
        {
            "node_id": "desk",
            "item_id": "ikea-micke-desk",
            "x": 1.6,
            "y": 3.7,
            "rotation": 180,
            "size": {"width": 1.05, "depth": 0.5, "height": 0.75},
        },
    ]
}


class Layout(BaseModel):
    """Where each SceneGraph node ended up, in room coordinates."""

    model_config = ConfigDict(json_schema_extra={"examples": [LAYOUT_EXAMPLE]})

    placements: list[Placement]


class ValidationIssue(BaseModel):
    code: str = Field(description="Machine-readable, e.g. cycle, unknown_node, blocks_opening")
    message: str = Field(description="One short sentence the Critic can pass on")
    severity: Literal["error", "warning"] = "error"
    node_ids: list[str] = []


class ValidationReport(BaseModel):
    """Problems found in a SceneGraph or Layout; no error issues means valid."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"issues": [{"code": "blocks_opening", "message": "The desk blocks the door swing", "node_ids": ["desk", "door_1"]}]}
            ]
        }
    )

    issues: list[ValidationIssue] = []


class RuleResult(BaseModel):
    rule: str
    passed: bool
    message: str = ""


class CritiqueAction(BaseModel):
    target: Literal["architect", "sourcer"]
    node_id: str | None = None
    instruction: str


class Critique(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "round": 1,
                    "rules": [
                        {"rule": "desk_near_light", "passed": True},
                        {"rule": "bed_not_facing_door", "passed": False, "message": "The bed faces the door"},
                    ],
                    "actions": [{"target": "architect", "node_id": "bed", "instruction": "Put the bed against wall D"}],
                    "summary": "One rule fails: the bed faces the door",
                }
            ]
        }
    )

    round: int = Field(ge=1)
    rules: list[RuleResult] = []
    actions: list[CritiqueAction] = Field([], description="Empty when the layout is accepted")
    summary: str


class MoveOp(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"op": "move", "node_id": "desk", "x": 1.2, "y": 3.7}]})

    op: Literal["move"] = "move"
    node_id: str
    x: float
    y: float


class RotateOp(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"op": "rotate", "node_id": "desk", "rotation": 90}]})

    op: Literal["rotate"] = "rotate"
    node_id: str
    rotation: Degrees


class SwapOp(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"op": "swap", "node_id": "desk", "item_id": "ikea-lagkapten-desk"}]})

    op: Literal["swap"] = "swap"
    node_id: str
    item_id: str


class AddOp(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "op": "add",
                    "node": DESK_NODE,
                    "edges": [DESK_EDGE],
                }
            ]
        }
    )

    op: Literal["add"] = "add"
    node: SceneNode
    edges: list[SceneEdge] = []


class RemoveOp(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"op": "remove", "node_id": "nightstand"}]})

    op: Literal["remove"] = "remove"
    node_id: str


ChatEdit = Annotated[MoveOp | RotateOp | SwapOp | AddOp | RemoveOp, Field(discriminator="op")]


class LayoutDiff(BaseModel):
    """What a chat edit changed, by node id, so the views can highlight it."""

    model_config = ConfigDict(json_schema_extra={"examples": [{"added": [], "removed": ["nightstand"], "changed": ["desk"]}]})

    added: list[str] = []
    removed: list[str] = []
    changed: list[str] = Field([], description="Moved, rotated or swapped")
