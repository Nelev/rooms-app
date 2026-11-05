"""The camera that took a photo, from image points matched to known room points (OpenCV solvePnP)."""

import math
from collections.abc import Sequence

import cv2
import numpy as np
from cv2.typing import MatLike
from numpy.typing import NDArray

from app.schemas import CameraPose

Array = NDArray[np.float64]

FULL_FRAME_DIAGONAL_MM = math.hypot(36, 24)  # 35 mm equivalent focal lengths are relative to this diagonal
FOCAL_SEARCH = (0.3, 1.5)  # unknown focal length: f / the image's longer side, about 118 to 37 degrees across it
# (telephoto photos, narrower than that, need the EXIF focal length)
ROOM_TO_THREE = np.array([[1.0, 0, 0], [0, 0, 1], [0, -1, 0]])  # room (x, y, z) -> three.js (x, z, -y), see coords.py
CV_TO_THREE_CAMERA = np.diag([1.0, -1, -1])  # an OpenCV camera looks down +z with y down, a three.js one down -z with y up


def _solve(room: Array, image: Array, f: float, width: int, height: int) -> tuple[float, MatLike, MatLike]:
    """The RMS reprojection error in pixels and the pose (rvec, tvec) for focal length f in pixels; ValueError if none fits."""
    k = np.array([[f, 0, width / 2], [0, f, height / 2], [0, 0, 1]])
    try:
        ok, rvec, tvec = cv2.solvePnP(room, image, k, None, flags=cv2.SOLVEPNP_SQPNP)
    except cv2.error:  # degenerate points, e.g. one corner clicked four times
        ok = False
    if not ok:
        raise ValueError("No camera pose fits these points")
    rvec, tvec = cv2.solvePnPRefineLM(room, image, k, None, rvec, tvec)
    projected, _ = cv2.projectPoints(room, rvec, tvec, k, None)
    return float(np.sqrt(np.mean(np.sum((projected.reshape(-1, 2) - image) ** 2, axis=1)))), rvec, tvec


def solve_camera_pose(
    image_points: Sequence[tuple[float, float]],
    room_points: Sequence[tuple[float, float, float]],
    image_width: int,
    image_height: int,
    focal_length_35mm: float | None = None,
) -> CameraPose:
    """The pose in the three.js convention; without a focal length (EXIF), the one with the lowest error in FOCAL_SEARCH."""
    room, image = np.array(room_points, dtype=np.float64), np.array(image_points, dtype=np.float64)
    if focal_length_35mm:
        f = focal_length_35mm * math.hypot(image_width, image_height) / FULL_FRAME_DIAGONAL_MM
    else:  # a coarse grid, then a fine one around its best

        def error(f: float) -> float:
            try:
                return _solve(room, image, float(f), image_width, image_height)[0]
            except ValueError:
                return math.inf

        coarse = np.geomspace(*FOCAL_SEARCH, 60) * max(image_width, image_height)
        best, step = min(coarse, key=error), coarse[1] / coarse[0]
        f = float(min(np.geomspace(best / step, best * step, 41), key=error))
    reprojection_error, rvec, tvec = _solve(room, image, f, image_width, image_height)

    to_camera, _ = cv2.Rodrigues(rvec)  # room -> OpenCV camera
    position = ROOM_TO_THREE @ (-to_camera.T @ tvec.ravel())
    rotation, _ = cv2.Rodrigues(ROOM_TO_THREE @ to_camera.T @ CV_TO_THREE_CAMERA)  # three.js camera -> three.js world
    angle = float(np.linalg.norm(rotation))
    x, y, z = rotation.ravel() * (math.sin(angle / 2) / angle if angle else 0)
    return CameraPose(
        position=(float(position[0]), float(position[1]), float(position[2])),
        quaternion=(float(x), float(y), float(z), math.cos(angle / 2)),
        fov=math.degrees(2 * math.atan(image_height / 2 / f)),
        image_width=image_width,
        image_height=image_height,
        reprojection_error=reprojection_error,
    )
