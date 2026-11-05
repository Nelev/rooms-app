"""Regenerate the synthetic placeholder photos: `uv run --no-project --with pillow fixtures/placeholder_photos.py`."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PHOTOS = {"small-bedroom": 2, "home-office": 1, "living-room": 2}


def photo(path: Path, title: str, n: int) -> None:
    img = Image.new("RGB", (640, 480), "#e9e4dc")
    d = ImageDraw.Draw(img)
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
