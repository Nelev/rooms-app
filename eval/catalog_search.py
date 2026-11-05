"""Catalog search's precision@5 on the 20 hand-labeled queries of catalog_search.json.

Run from backend/ (eval/ shares its environment): `PYTHONPATH=. uv run python ../eval/catalog_search.py`. It needs OPENROUTER_API_KEY: the
catalog and the queries are embedded with the real model, in an in-memory store. A query's `relevant` items are those a person judged
good answers that pass its hard filters; its precision@5 is the share of the top 5 that is relevant, out of at most as many as are
relevant (so a query with 2 relevant items scores 1 when both are in the top 5).
"""

import asyncio
from pathlib import Path

from langchain_core.embeddings import Embeddings
from langgraph.store.memory import InMemoryStore
from pydantic import TypeAdapter

from app.catalog.embed import index_config, seed
from app.catalog.search import Filters, search
from app.schemas.base import Model
from app.schemas.coords import Size

K = 5


class Query(Model):
    query: str
    category: str
    size: Size | None = None
    max_price: float | None = None
    relevant: list[str]

    @property
    def filters(self) -> Filters:
        return Filters(self.category, self.size, self.max_price)


QUERIES = TypeAdapter(list[Query]).validate_json((Path(__file__).parent / "catalog_search.json").read_bytes())


async def precision_at_k(embed: Embeddings | None = None) -> dict[str, float]:
    """Each query's precision@5, with `embed` (default: the OpenRouter model)."""
    store = InMemoryStore(index=index_config(embed))
    await seed(store)
    scores = {}
    for q in QUERIES:
        found = [i.id for i in await search(store, q.query, q.filters, limit=K)]
        scores[q.query] = len(set(found) & set(q.relevant)) / min(K, len(q.relevant))
    return scores


if __name__ == "__main__":
    scores = asyncio.run(precision_at_k())
    for query, score in scores.items():
        print(f"{score:.2f}  {query}")
    print(f"precision@{K} (denominator capped at the relevant items): {sum(scores.values()) / len(scores):.3f} on {len(scores)} queries")
