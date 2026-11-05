"""Catalog search: the items of a category most like a query, that fit the requested bounding box and the remaining budget.

Nodes call it with their runtime's store (`runtime.store`), which embed.py loads with the catalog. The store ranks a category's items by
similarity to the query; the hard filters are applied here, in code. The aspect-ratio check keeps items whose footprint has the shape
of the requested box: an item scaled to fit a box of another shape looks distorted (I-Design's resize distortion).
"""

from collections.abc import Iterable
from typing import NamedTuple

from langgraph.store.base import BaseStore, SearchItem

from app.catalog.embed import NAMESPACE
from app.schemas import CatalogItem
from app.schemas.coords import Size

SIZE_TOLERANCE = 0.1  # an item's width, depth and height may differ from the requested box's by 10%
ASPECT_TOLERANCE = 0.1  # and its width / depth from the box's by 10%
CANDIDATES = 100  # items ranked by the store before the hard filters: more than any category holds


class Filters(NamedTuple):
    category: str
    size: Size | None = None  # the requested bounding box
    max_price: float | None = None  # EUR: what is left of the budget


def _close(value: float, target: float, tolerance: float) -> bool:
    return abs(value - target) <= tolerance * target


def fits(item: CatalogItem, filters: Filters) -> bool:
    """The hard filters: the size within SIZE_TOLERANCE of the box with a matching footprint aspect ratio, the price within the budget."""
    if filters.max_price is not None and item.price > filters.max_price:
        return False
    if (box := filters.size) is None:
        return True
    size = item.size
    return (
        _close(size.width, box.width, SIZE_TOLERANCE)
        and _close(size.depth, box.depth, SIZE_TOLERANCE)
        and _close(size.height, box.height, SIZE_TOLERANCE)
        and _close(size.width / size.depth, box.width / box.depth, ASPECT_TOLERANCE)
    )


def _fitting(hits: Iterable[SearchItem], filters: Filters, limit: int) -> list[CatalogItem]:
    items = (CatalogItem.model_validate({k: v for k, v in hit.value.items() if k != "text"}) for hit in hits)
    return [item for item in items if fits(item, filters)][:limit]


async def search(store: BaseStore, query: str, filters: Filters, limit: int = 5) -> list[CatalogItem]:
    """The `limit` items of `filters.category` most similar to `query` that pass the hard filters, the most similar first."""
    hits = await store.asearch(NAMESPACE, query=query, filter={"category": filters.category}, limit=CANDIDATES)
    return _fitting(hits, filters, limit)


def search_sync(store: BaseStore, query: str, filters: Filters, limit: int = 5) -> list[CatalogItem]:
    """`search` for sync nodes, which run in a worker thread where the store's sync API works."""
    hits = store.search(NAMESPACE, query=query, filter={"category": filters.category}, limit=CANDIDATES)
    return _fitting(hits, filters, limit)
