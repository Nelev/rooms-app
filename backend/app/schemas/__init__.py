"""Every model the system passes around. The coordinate convention is in coords.py."""

from typing import Any

from app.schemas.design import Brief, CatalogItem, DesignBrief, SceneGraph
from app.schemas.layout import ChatEdit, Critique, Layout, LayoutDiff, ValidationReport
from app.schemas.room import RoomSpec
from app.schemas.run import ConfirmRoom, ConfirmRoomResume, RunInput, RunOutput, StreamEvent
from app.schemas.scene import CameraPose, Scene

# exported to contracts/schemas/<name>.json
CONTRACTS: dict[str, Any] = {
    "RoomSpec": RoomSpec,
    "Brief": Brief,
    "DesignBrief": DesignBrief,
    "SceneGraph": SceneGraph,
    "CatalogItem": CatalogItem,
    "Layout": Layout,
    "ValidationReport": ValidationReport,
    "Critique": Critique,
    "Scene": Scene,
    "ChatEdit": ChatEdit,
    "LayoutDiff": LayoutDiff,
    "StreamEvent": StreamEvent,
    "CameraPose": CameraPose,
    "RunInput": RunInput,
    "RunOutput": RunOutput,
    "ConfirmRoom": ConfirmRoom,
}

__all__ = [
    "Brief",
    "CameraPose",
    "CatalogItem",
    "ChatEdit",
    "ConfirmRoom",
    "ConfirmRoomResume",
    "Critique",
    "DesignBrief",
    "Layout",
    "LayoutDiff",
    "RoomSpec",
    "RunInput",
    "RunOutput",
    "Scene",
    "SceneGraph",
    "StreamEvent",
    "ValidationReport",
]
