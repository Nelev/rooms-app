"""The furniture catalog: data/catalog/<category>.json, each a list of CatalogItem.

`uv run python -m app.catalog.loader` validates it and reports the item count per category and per style.
"""

from collections import Counter
from functools import cache
from pathlib import Path

from pydantic import TypeAdapter

from app.schemas import CatalogItem

CATALOG_DIR = Path(__file__).resolve().parents[3] / "data" / "catalog"
# the categories every design may need; each has at least 5 items
CORE_CATEGORIES = (
    "bed",
    "nightstand",
    "wardrobe",
    "dresser",
    "desk",
    "chair",
    "armchair",
    "sofa",
    "table",
    "tv_stand",
    "shelf",
    "lamp",
    "rug",
)

_items = TypeAdapter(list[CatalogItem])


@cache
def load_catalog(directory: Path = CATALOG_DIR) -> dict[str, CatalogItem]:
    """Every catalog item by id, validated against CatalogItem."""
    items = [item for path in sorted(directory.glob("*.json")) for item in _items.validate_json(path.read_bytes())]
    if not items:
        raise FileNotFoundError(f"No catalog items in {directory}")
    if duplicates := [id_ for id_, n in Counter(i.id for i in items).items() if n > 1]:
        raise ValueError(f"Duplicate catalog item ids: {duplicates}")
    return {i.id: i for i in items}


if __name__ == "__main__":
    catalog = load_catalog().values()
    print(f"{len(catalog)} items")
    print("per category:", dict(sorted(Counter(i.category for i in catalog).items())))
    print("per style:", dict(sorted(Counter(s for i in catalog for s in i.style_tags).items())))
