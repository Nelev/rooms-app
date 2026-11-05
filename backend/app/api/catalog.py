from fastapi import APIRouter, HTTPException

from app.graph.stub import catalog
from app.schemas import CatalogItem

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/items/{item_id}")
async def get_item(item_id: str) -> CatalogItem:
    """A catalog item. Stub: the items of the fixture scenes."""
    if item := catalog().get(item_id):
        return item
    raise HTTPException(404, "Item not found")
