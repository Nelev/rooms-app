"""Regenerate the synthetic placeholder photos: `uv run --no-project --with pillow fixtures/placeholder_photos.py`.

photo-1 is the room's edges as its `camera_pose.json` sees them, so the camera matching UI can be checked against it.
"""

import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PHOTOS = {"small-bedroom": 2, "home-office": 1, "living-room": 2}
NEAR = 0.05  # m: the part of an edge closer to the camera's plane than this is cut off


def rotate(q: list[float], v: list[float]) -> list[float]:
    """v turned by the unit quaternion q (x, y, z, w)."""
    x, y, z, w = q
    tx, ty, tz = 2 * (y * v[2] - z * v[1]), 2 * (z * v[0] - x * v[2]), 2 * (x * v[1] - y * v[0])
    return [v[0] + w * tx + y * tz - z * ty, v[1] + w * ty + z * tx - x * tz, v[2] + w * tz + x * ty - y * tx]


def room_edges(case: Path) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """The room's 12 edges in pixels, as the case's camera (three.js convention, room (x, y, z) is (x, z, -y)) sees them."""
    pose, d = json.loads((case / "camera_pose.json").read_text()), json.loads((case / "room_spec.json").read_text())["dimensions"]
    q = [-pose["quaternion"][0], -pose["quaternion"][1], -pose["quaternion"][2], pose["quaternion"][3]]
    f = pose["image_height"] / 2 / math.tan(math.radians(pose["fov"]) / 2)
    floor = [(0, 0), (d["width"], 0), (d["width"], d["length"]), (0, d["length"])]

    def local(i: int, z: float) -> list[float]:  # in the camera's frame, which looks down -z
        x, y = floor[i % 4]
        return rotate(q, [x - pose["position"][0], z - pose["position"][1], -y - pose["position"][2]])

    def pixel(p: list[float]) -> tuple[float, float]:
        return pose["image_width"] / 2 + f * p[0] / -p[2], pose["image_height"] / 2 - f * p[1] / -p[2]

    def cut(p: list[float], q: list[float]) -> list[float]:  # p moved along the edge to the near plane, if behind it
        t = (p[2] + NEAR) / (p[2] - q[2]) if p[2] > -NEAR else 0
        return [a + t * (b - a) for a, b in zip(p, q, strict=True)]

    edges = [
        e
        for i in range(4)
        for e in ((local(i, 0), local(i + 1, 0)), (local(i, d["height"]), local(i + 1, d["height"])), (local(i, 0), local(i, d["height"])))
    ]
    return [(pixel(cut(a, b)), pixel(cut(b, a))) for a, b in edges if min(a[2], b[2]) <= -NEAR]


def photo(path: Path, title: str, n: int) -> None:
    img = Image.new("RGB", (640, 480), "#e9e4dc")
    d = ImageDraw.Draw(img)
    if n == 1:
        for a, b in room_edges(path.parent):
            d.line([a, b], fill="#555", width=3)
    else:
        d.polygon([(0, 480), (160, 330), (480, 330), (640, 480)], fill="#c8b49a")  # floor
        d.rectangle([160, 90, 480, 330], outline="#555", width=3)  # back wall
        for a, b in [((0, 0), (160, 90)), ((640, 0), (480, 90)), ((0, 480), (160, 330)), ((640, 480), (480, 330))]:
            d.line([a, b], fill="#555", width=3)
    d.rectangle([40, 180, 600, 290], fill="#ffffffdd", outline="#c00", width=4)
    d.text((320, 210), f"PLACEHOLDER - {title} - photo {n}", fill="#c00", font=ImageFont.load_default(size=26), anchor="mm")
    d.text((320, 260), "synthetic image, replace with a real photo", fill="#333", font=ImageFont.load_default(size=18), anchor="mm")
    img.save(path, "JPEG", quality=60, optimize=True)


if __name__ == "__main__":
    for case, count in PHOTOS.items():
        for n in range(1, count + 1):
            photo(Path(__file__).parent / case / f"photo-{n}.jpg", case.replace("-", " "), n)
