"""The camera pose, recovered from the room corners a known camera sees in each fixture room."""

import math
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.graph.stub import fixture
from app.main import app
from app.schemas import CameraPose, RoomSpec
from app.vision.camera import FULL_FRAME_DIAGONAL_MM, solve_camera_pose
from tests.test_api import design_input, stream
from tests.test_fixtures import CASES, case

CORNERS = {"A": (0, 0), "B": (1, 0), "C": (1, 1), "D": (0, 1)}  # in room width and length


def rotate(q: tuple[float, float, float, float], v: Any) -> Any:
    xyz, w = np.array(q[:3]), q[3]
    return v + 2 * w * np.cross(xyz, v) + 2 * np.cross(xyz, np.cross(xyz, v))


def camera(room: RoomSpec, x: float, yaw: float, pitch: float, fov: float) -> CameraPose:
    """A 4032 x 3024 camera at 1.5 m height, 0.2 m from wall A at `x` of its width, turned by `yaw` and `pitch` (degrees)."""
    (sy, cy), (sx, cx) = [(math.sin(math.radians(a) / 2), math.cos(math.radians(a) / 2)) for a in (yaw, pitch)]
    position = (x * room.dimensions.width, 1.5, -0.2)  # three.js (x, z, -y)
    return CameraPose(position=position, quaternion=(cy * sx, sy * cx, -sy * sx, cy * cx), fov=fov, image_width=4032, image_height=3024)


CAMERAS = [(0.2, -30, -10, 80), (0.1, -40, -5, 85), (0.05, -45, -5, 90)]  # x, yaw, pitch, fov: 4 to 6 corners in view


def click(known: CameraPose, room: RoomSpec) -> list[dict[str, Any]]:
    """The room corners the camera sees, as integer pixels, projected the three.js way (independently of the solver)."""
    d, f = room.dimensions, known.image_height / 2 / math.tan(math.radians(known.fov) / 2)
    points = []
    for corner, (u, v) in CORNERS.items():
        for ceiling in (False, True):
            x, y, z = u * d.width, v * d.length, d.height if ceiling else 0
            local = rotate((*(-np.array(known.quaternion[:3])), known.quaternion[3]), np.array([x, z, -y]) - known.position)
            if local[2] < 0:  # in front of a three.js camera, which looks down -z
                px, py = known.image_width / 2 + f * local[0] / -local[2], known.image_height / 2 - f * local[1] / -local[2]
                if 0 <= px <= known.image_width and 0 <= py <= known.image_height:
                    points.append({"corner": corner, "ceiling": ceiling, "x": round(px), "y": round(py)})
    return points


def assert_close(pose: CameraPose, known: CameraPose) -> None:
    assert np.linalg.norm(np.subtract(pose.position, known.position)) < 0.05  # meters
    assert math.degrees(2 * math.acos(min(1, abs(np.dot(pose.quaternion, known.quaternion))))) < 1
    assert pose.fov == pytest.approx(known.fov, abs=1)
    assert pose.reprojection_error is not None and pose.reprojection_error < 1  # pixels: clicks are rounded


@pytest.mark.parametrize("name", CASES)
@pytest.mark.parametrize("pose", CAMERAS)
@pytest.mark.parametrize("exif", [True, False])
def test_recovers_a_known_camera(name: str, pose: tuple[float, float, float, float], exif: bool) -> None:
    room = case(name)["room_spec"]
    known, d = camera(room, *pose), room.dimensions
    points = click(known, room)
    assert len(points) >= 4
    f = known.image_height / 2 / math.tan(math.radians(known.fov) / 2)
    solved = solve_camera_pose(
        [(p["x"], p["y"]) for p in points],
        [(CORNERS[p["corner"]][0] * d.width, CORNERS[p["corner"]][1] * d.length, d.height if p["ceiling"] else 0) for p in points],
        known.image_width,
        known.image_height,
        f * FULL_FRAME_DIAGONAL_MM / math.hypot(known.image_width, known.image_height) if exif else None,
    )
    assert_close(solved, known)


def test_endpoint_saves_the_pose_in_the_scene() -> None:
    room = RoomSpec.model_validate(fixture("room_spec"))
    known = camera(room, *CAMERAS[0]).model_copy(update={"photo_key": fixture("camera_pose")["photo_key"]})
    body = {"photo_key": known.photo_key, "image_width": 4032, "image_height": 3024, "points": click(known, room)}
    with TestClient(app) as client:
        url = f"/threads/{client.post('/threads', json={}).json()['thread_id']}"
        assert client.post(f"{url}/camera-pose", json=body).status_code == 409  # no scene yet
        stream(client, f"{url}/runs/stream", {"input": design_input()})
        stream(client, f"{url}/runs/stream", {"command": {"resume": fixture("room_spec")}})
        assert client.post(f"{url}/camera-pose", json={**body, "points": body["points"][:3]}).status_code == 422
        assert client.post(f"{url}/camera-pose", json={**body, "points": body["points"][:1] * 4}).status_code == 400

        pose = CameraPose.model_validate(client.post(f"{url}/camera-pose", json=body).json())
        assert_close(pose, known)
        assert pose.photo_key == known.photo_key
        assert client.get(f"{url}/state").json()["values"]["scene"]["cameras"] == [pose.model_dump(mode="json")]
