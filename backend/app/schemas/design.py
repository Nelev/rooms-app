from typing import Literal

from pydantic import ConfigDict, Field, JsonValue

from app.schemas.base import Model
from app.schemas.coords import Size

Priority = Literal["must", "nice"]
Relation = Literal["left_of", "right_of", "in_front", "behind", "on", "against_wall", "in_corner", "adjacent", "facing"]

BRIEF_EXAMPLE: dict[str, JsonValue] = {
    "room_use": "bedroom",
    "styles": ["scandinavian"],
    "budget": 1500,
    "must_haves": ["double bed", "desk"],
    "keep": ["wardrobe"],
    "remove": ["old armchair"],
    "notes": "I work from home two days a week",
}


class Brief(Model):
    """What the user asks for in the new-project wizard."""

    model_config = ConfigDict(json_schema_extra={"examples": [BRIEF_EXAMPLE]})

    room_use: str
    styles: list[str] = []
    budget: float = Field(ge=0, description="EUR")
    must_haves: list[str] = []
    keep: list[str] = []
    remove: list[str] = []
    notes: str = ""


class Zone(Model):
    name: str
    purpose: str


class DesignObject(Model):
    id: str
    name: str
    category: str
    style: str
    material: str
    size: Size
    quantity: int = Field(1, ge=1)
    priority: Priority
    zone: str | None = None


DESIGN_BRIEF_EXAMPLE: dict[str, JsonValue] = {
    "zones": [{"name": "sleep", "purpose": "bed and nightstands"}, {"name": "work", "purpose": "desk by the window"}],
    "palette": ["#f2efe9", "#c8b49a", "#3d4a3d"],
    "objects": [
        {
            "id": "bed",
            "name": "double bed",
            "category": "bed",
            "style": "scandinavian",
            "material": "oak",
            "size": {"width": 1.6, "depth": 2.1, "height": 1.0},
            "priority": "must",
            "zone": "sleep",
        },
        {
            "id": "nightstand",
            "name": "nightstand",
            "category": "nightstand",
            "style": "scandinavian",
            "material": "oak",
            "size": {"width": 0.45, "depth": 0.4, "height": 0.5},
            "quantity": 2,
            "priority": "nice",
            "zone": "sleep",
        },
    ],
    "summary": "Calm Scandinavian bedroom with a small work corner by the window",
}


class DesignBrief(Model):
    """The Designer's plan: zones, palette and the objects to place."""

    model_config = ConfigDict(json_schema_extra={"examples": [DESIGN_BRIEF_EXAMPLE]})

    zones: list[Zone] = []
    palette: list[str] = Field([], description="Hex colors")
    objects: list[DesignObject]
    summary: str = ""


class SceneNode(Model):
    id: str = Field(description="For fixed nodes: the RoomSpec feature id, or wall_A to wall_D")
    kind: Literal["object", "wall", "door", "window"] = "object"
    name: str
    style: str | None = None
    material: str | None = None
    size: Size | None = Field(None, description="Bounding box; None for fixed nodes")
    quantity: int = Field(1, ge=1)
    priority: Priority = "must"
    item_id: str | None = Field(None, description="The CatalogItem chosen by the Sourcer")


class SceneEdge(Model):
    source: str = Field(description="The node placed relative to target")
    relation: Relation
    target: str


DESK_NODE: dict[str, JsonValue] = {"id": "desk", "name": "desk", "size": {"width": 1.2, "depth": 0.6, "height": 0.75}}
DESK_EDGE: dict[str, JsonValue] = {"source": "desk", "relation": "in_front", "target": "window_1"}
SCENE_GRAPH_EXAMPLE: dict[str, JsonValue] = {
    "nodes": [
        {"id": "wall_B", "kind": "wall", "name": "wall B"},
        {"id": "window_1", "kind": "window", "name": "window"},
        {
            "id": "bed",
            "name": "double bed",
            "style": "scandinavian",
            "material": "oak",
            "size": {"width": 1.6, "depth": 2.1, "height": 1.0},
        },
        {
            "id": "nightstand",
            "name": "nightstand",
            "size": {"width": 0.45, "depth": 0.4, "height": 0.5},
            "quantity": 2,
            "priority": "nice",
            "item_id": "ikea-hemnes-nightstand",
        },
        DESK_NODE,
    ],
    "edges": [
        {"source": "bed", "relation": "against_wall", "target": "wall_B"},
        {"source": "nightstand", "relation": "adjacent", "target": "bed"},
        DESK_EDGE,
    ],
}


class SceneGraph(Model):
    """Objects and the relations between them; the solver turns it into a Layout."""

    model_config = ConfigDict(json_schema_extra={"examples": [SCENE_GRAPH_EXAMPLE]})

    nodes: list[SceneNode]
    edges: list[SceneEdge] = []


CATALOG_ITEM_EXAMPLE: dict[str, JsonValue] = {
    "id": "ikea-hemnes-nightstand",
    "name": "HEMNES nightstand",
    "category": "nightstand",
    "size": {"width": 0.46, "depth": 0.35, "height": 0.7},
    "price": 89.0,
    "style_tags": ["scandinavian", "traditional"],
    "color": "white",
    "front": "+z",
    "glb_url": "https://example.com/models/hemnes-nightstand.glb",
    "license": "CC-BY-4.0",
    "description": "Solid pine nightstand with one drawer",
}


class CatalogItem(Model):
    model_config = ConfigDict(json_schema_extra={"examples": [CATALOG_ITEM_EXAMPLE]})

    id: str
    name: str
    category: str
    size: Size
    price: float = Field(ge=0, description="EUR")
    style_tags: list[str] = []
    color: str | None = None
    front: Literal["+x", "-x", "+z", "-z"] = Field("+z", description="The GLB's local axis the item's front faces (glTF is y-up)")
    glb_url: str | None = None
    license: str | None = None
    url: str | None = Field(None, description="Product page")
    image_url: str | None = None
    description: str = ""
