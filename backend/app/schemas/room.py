from typing import Literal

from pydantic import ConfigDict, Field, JsonValue

from app.schemas.base import Model
from app.schemas.coords import Degrees, Fraction, Meters, Size, Wall

FeatureType = Literal["window", "door", "radiator", "outlet", "built_in", "column", "other"]


class Dimensions(Model):
    width: Meters = Field(description="Length of walls A and C (x)")
    length: Meters = Field(description="Length of walls B and D (y)")
    height: Meters = Field(description="Ceiling height")


class WallSpec(Model):
    wall: Wall
    color: str | None = Field(None, description="Hex color, e.g. #f2efe9")


class Feature(Model):
    id: str
    type: FeatureType
    wall: Wall
    offset: Fraction = Field(description="Feature center as a fraction of the wall length from the wall's start corner")
    width: Meters
    height: Meters
    sill_height: Meters = Field(0, description="Height of the feature's bottom edge above the floor; 0 for doors")
    confidence: Fraction = 1


class KeptItem(Model):
    id: str
    name: str
    x: float
    y: float
    rotation: Degrees = 0
    size: Size


ROOM_SPEC_EXAMPLE: dict[str, JsonValue] = {
    "dimensions": {"width": 3.2, "length": 4.0, "height": 2.6},
    "walls": [{"wall": w, "color": "#f2efe9"} for w in "ABCD"],
    "floor_material": "oak",
    "features": [
        {"id": "door_1", "type": "door", "wall": "A", "offset": 0.15, "width": 0.8, "height": 2.1, "confidence": 0.95},
        {
            "id": "window_1",
            "type": "window",
            "wall": "C",
            "offset": 0.5,
            "width": 1.2,
            "height": 1.4,
            "sill_height": 0.9,
            "confidence": 0.9,
        },
        {
            "id": "radiator_1",
            "type": "radiator",
            "wall": "C",
            "offset": 0.5,
            "width": 1.0,
            "height": 0.6,
            "sill_height": 0.1,
            "confidence": 0.7,
        },
    ],
    "kept_furniture": [
        {"id": "kept_1", "name": "wardrobe", "x": 0.3, "y": 2.0, "rotation": 270, "size": {"width": 1.2, "depth": 0.6, "height": 2.0}}
    ],
    "warnings": ["Radiator width estimated from one photo"],
}


class RoomSpec(Model):
    """The room as analyzed from the photos and confirmed by the user."""

    model_config = ConfigDict(json_schema_extra={"examples": [ROOM_SPEC_EXAMPLE]})

    dimensions: Dimensions
    walls: list[WallSpec] = []
    floor_material: str | None = None
    features: list[Feature] = []
    kept_furniture: list[KeptItem] = []
    warnings: list[str] = []
