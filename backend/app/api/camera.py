"""The camera that took a photo, from room corners the user clicks on it; the 3D view reads it from the thread's scene."""

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import Field

from app.api.deps import Graph, ThreadConfig
from app.api.threads import _idle
from app.schemas import CameraPose, Scene
from app.schemas.base import Model
from app.schemas.coords import Wall
from app.vision.camera import solve_camera_pose

router = APIRouter(prefix="/threads", tags=["threads"])


class CornerPoint(Model):
    """A room corner clicked on the photo."""

    corner: Wall = Field(description="The floor corner where this wall starts: A (0, 0), B (width, 0), C (width, length), D (0, length)")
    ceiling: bool = Field(False, description="The ceiling corner above it instead")
    x: float = Field(description="Pixels from the image's left edge")
    y: float = Field(description="Pixels from the image's top edge")


class CameraPoseRequest(Model):
    photo_key: str | None = None
    image_width: int = Field(gt=0)
    image_height: int = Field(gt=0)
    focal_length_35mm: float | None = Field(None, gt=0, description="EXIF FocalLengthIn35mmFilm; searched for when missing")
    points: list[CornerPoint] = Field(min_length=4)


@router.post("/{thread_id}/camera-pose")
async def set_camera_pose(body: CameraPoseRequest, graph: Graph, config: ThreadConfig) -> CameraPose:
    """Solve the photo's camera and save it in the scene; 409 before the scene exists, 400 if no pose fits the points."""
    _idle(config)
    scene: Scene | None = (await graph.aget_state(config)).values.get("scene")
    if scene is None:
        raise HTTPException(409, "The thread has no scene yet")
    d = scene.room.dimensions
    floor = {"A": (0, 0), "B": (d.width, 0), "C": (d.width, d.length), "D": (0, d.length)}
    try:
        pose = (
            await asyncio.to_thread(
                solve_camera_pose,
                [(p.x, p.y) for p in body.points],
                [(*floor[p.corner], d.height if p.ceiling else 0) for p in body.points],
                body.image_width,
                body.image_height,
                body.focal_length_35mm,
            )
        ).model_copy(update={"photo_key": body.photo_key})
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    scene = scene.model_copy(update={"cameras": [*(c for c in scene.cameras if c.photo_key != pose.photo_key), pose]})
    await graph.aupdate_state(config, {"scene": scene})
    return pose
