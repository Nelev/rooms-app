from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.schemas.design import CATALOG_ITEM_EXAMPLE, CatalogItem
from app.schemas.layout import BED_PLACEMENT, Placement
from app.schemas.room import ROOM_SPEC_EXAMPLE, RoomSpec

CAMERA_POSE_EXAMPLE: dict[str, JsonValue] = {
    "photo_key": "uploads/3f2a/photo-1.jpg",
    "position": [0.4, 1.5, -0.3],
    "quaternion": [0.0, 0.9239, 0.0, 0.3827],
    "fov": 55.0,
    "image_width": 4032,
    "image_height": 3024,
    "reprojection_error": 3.2,
}


class CameraPose(BaseModel):
    """A camera in the three.js convention (y-up: room (x, y, z) is three.js (x, z, -y)), e.g. the one that took a photo."""

    model_config = ConfigDict(json_schema_extra={"examples": [CAMERA_POSE_EXAMPLE]})

    photo_key: str | None = None
    position: tuple[float, float, float]
    quaternion: tuple[float, float, float, float] = Field(description="x, y, z, w")
    fov: float = Field(gt=0, lt=180, description="Vertical field of view in degrees")
    image_width: int = Field(gt=0)
    image_height: int = Field(gt=0)
    reprojection_error: float | None = Field(None, ge=0, description="Pixels")


class Light(BaseModel):
    kind: Literal["area", "directional"]
    window_id: str = Field(description="The RoomSpec window feature the light comes through")
    intensity: float = Field(ge=0)


class SceneItem(Placement):
    item: CatalogItem | None = Field(None, description="None renders a box")


class Scene(BaseModel):
    """Everything the 2D plan and the 3D viewer need to render the design."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "room": ROOM_SPEC_EXAMPLE,
                    "items": [
                        BED_PLACEMENT,
                        {
                            "node_id": "nightstand",
                            "item_id": "ikea-hemnes-nightstand",
                            "x": 3.0,
                            "y": 3.3,
                            "rotation": 90,
                            "size": CATALOG_ITEM_EXAMPLE["size"],
                            "item": CATALOG_ITEM_EXAMPLE,
                        },
                    ],
                    "lights": [{"kind": "area", "window_id": "window_1", "intensity": 5.0}],
                    "cameras": [CAMERA_POSE_EXAMPLE],
                }
            ]
        }
    )

    room: RoomSpec
    items: list[SceneItem]
    lights: list[Light] = []
    cameras: list[CameraPose] = []
