"""Regenerate the synthetic placeholder photos: `uv run --no-project --with pillow fixtures/placeholder_photos.py`."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PHOTOS = {"small-bedroom": 2, "home-office": 1, "living-room": 2}
# small-bedroom/photo-1: the room's edges as its camera_pose.json sees them, in pixels, copied from the camera matching UI's
# wireframe (frontend/src/components/scene3d/camera-match/wireframe.ts), whose test checks the two still line up
POSED = {
    ("small-bedroom", 1): [
        ((4262.7, 12710.8), (831.6, 579.1)),
        ((4262.7, -8905.2), (831.6, -8.7)),
        ((831.6, 579.1), (306.1, 387)),
        ((831.6, -8.7), (306.1, 132.2)),
        ((831.6, 579.1), (831.6, -8.7)),
        ((306.1, 387), (-184.8, 555)),
        ((306.1, 132.2), (-184.8, 9)),
        ((306.1, 387), (306.1, 132.2)),
        ((-184.8, 555), (-3623.2, 12710.8)),
        ((-184.8, 9), (-3623.2, -8905.2)),
        ((-184.8, 555), (-184.8, 9)),
    ]
}


def photo(path: Path, title: str, n: int) -> None:
    img = Image.new("RGB", (640, 480), "#e9e4dc")
    d = ImageDraw.Draw(img)
    edges = POSED.get((path.parent.name, n))
    if edges is None:
        d.polygon([(0, 480), (160, 330), (480, 330), (640, 480)], fill="#c8b49a")  # floor
        d.rectangle([160, 90, 480, 330], outline="#555", width=3)  # back wall
        edges = [((0, 0), (160, 90)), ((640, 0), (480, 90)), ((0, 480), (160, 330)), ((640, 480), (480, 330))]
    for a, b in edges:
        d.line([a, b], fill="#555", width=3)
    d.rectangle([40, 180, 600, 290], fill="#ffffffdd", outline="#c00", width=4)
    d.text((320, 210), f"PLACEHOLDER - {title} - photo {n}", fill="#c00", font=ImageFont.load_default(size=26), anchor="mm")
    d.text((320, 260), "synthetic image, replace with a real photo", fill="#333", font=ImageFont.load_default(size=18), anchor="mm")
    img.save(path, "JPEG", quality=60, optimize=True)


if __name__ == "__main__":
    for case, count in PHOTOS.items():
        for n in range(1, count + 1):
            photo(Path(__file__).parent / case / f"photo-{n}.jpg", case.replace("-", " "), n)
