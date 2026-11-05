from typing import Any

from app.graph.state import RunState
from app.graph.stub import catalog, load, stub_node
from app.schemas import Scene
from app.schemas.scene import SceneItem


@stub_node
def present(state: RunState) -> dict[str, Any]:
    """The scene of the current layout."""
    # a new scene starts from the fixture's, without its cameras: they were matched to the fixture's photo, not the user's
    scene = state.get("scene") or load("scene", Scene).model_copy(update={"cameras": []})
    items = [SceneItem(**p.model_dump(), item=catalog().get(p.item_id or "")) for p in state["layout"].placements]
    return {"scene": scene.model_copy(update={"room": state["room_spec"], "items": items})}
