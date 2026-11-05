"""The Presenter's work, deterministic: the render-ready Scene of a layout, its shopping list's total, and the design's rationale.

The rationale is composed from the design brief, the fallback report, the critique and the total, not asked of a model: less code,
no cost, and nothing to replay offline (a model's prose would only reword these).
"""

from collections.abc import Sequence

from app.catalog.loader import load_catalog
from app.schemas import Critique, DesignBrief, FallbackReport, Layout, RoomSpec, Scene
from app.schemas.scene import CameraPose, Light, SceneItem

WINDOW_LIGHT = 5.0  # an area light's intensity through each window (the 3D viewer's default, F-09)


def build_scene(room: RoomSpec, layout: Layout, cameras: Sequence[CameraPose] = ()) -> Scene:
    """The room (its geometry, openings, wall colors and floor material), each placement with its catalog item (GLB URL and front
    direction; no item renders a box), an area light per window, and `cameras`: the ones matched to the user's photos (B-10)."""
    catalog = load_catalog()
    items = [SceneItem(**p.model_dump(), item=catalog.get(p.item_id or "")) for p in layout.placements]
    lights = [Light(kind="area", window_id=f.id, intensity=WINDOW_LIGHT) for f in room.features if f.type == "window"]
    return Scene(room=room, items=items, lights=lights, cameras=list(cameras))


def total(scene: Scene) -> float:
    """EUR: the shopping list, the catalog item of every placed object (each copy of one is placed and bought)."""
    return round(sum(i.item.price for i in scene.items if i.item), 2)


def rationale(design: DesignBrief, scene: Scene, budget: float, fallback: FallbackReport | None, critique: Critique | None) -> str:
    """A few sentences: the design's idea, the cost against the budget, what did not fit and the Critic's verdict."""
    bought, cost = sum(1 for i in scene.items if i.item), total(scene)
    parts = [
        design.summary,
        f"{bought} item{'s' * (bought != 1)} for €{cost:,.0f}, {'within' if cost <= budget else 'over'} the €{budget:,.0f} budget",
    ]
    if boxes := len(scene.items) - bought:
        parts.append(f"{boxes} object{'s have' if boxes != 1 else ' has'} no matching catalog item yet")
    if fallback and fallback.changes:
        parts.append(fallback.summary)
    if critique:
        parts.append(f"Critic: {critique.summary}")
    return " ".join(f"{p.strip().rstrip('.')}." for p in parts if p.strip())
