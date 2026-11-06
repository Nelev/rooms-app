"""The catalog in LangGraph's store, for semantic search (search.py): one item per catalog item in the ("catalog",) namespace.

An item's value is the CatalogItem (description, size, price, category, style...) plus `text`, what is embedded: the item's name,
description, style tags and color, since the descriptions alone rarely say what an item looks like. Embeddings come from OpenRouter
(get_embeddings, configured like app.llm's models); tests pass fake embeddings to index_config instead.
"""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import cache
from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings
from langgraph.store.base import BaseStore, PutOp
from langgraph.store.memory import InMemoryStore
from langgraph.store.postgres import AsyncPostgresStore
from langgraph.store.postgres.base import PostgresIndexConfig

from app.catalog.loader import load_catalog
from app.llm import recorded
from app.schemas import CatalogItem

logger = logging.getLogger(__name__)

NAMESPACE = ("catalog",)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL") or "openai/text-embedding-3-small"
DIMS = 1536  # text-embedding-3-small's; another model needs its own


@cache
def get_embeddings() -> OpenAIEmbeddings:
    settings: dict[str, Any] = {
        "model": EMBEDDING_MODEL,
        "base_url": "https://openrouter.ai/api/v1",
        "check_embedding_ctx_length": False,  # the length check sends token ids, which OpenRouter's other providers do not take
    }
    if recorded.directory():  # LLM_RECORDINGS: answered from recordings (app/llm/recorded.py)
        return recorded.RecordedEmbeddings(api_key=os.environ.get("OPENROUTER_API_KEY") or "replay", **settings)  # type: ignore[arg-type]
    return OpenAIEmbeddings(api_key=os.environ["OPENROUTER_API_KEY"], **settings)  # type: ignore[arg-type]  # a str is kept as a SecretStr


def index_config(embed: Embeddings | None = None) -> PostgresIndexConfig:
    """The store's vector index: `text` is embedded, with `embed` (default: the OpenRouter model)."""
    return {"dims": DIMS, "embed": embed or get_embeddings(), "fields": ["text"]}


def embedding_text(item: CatalogItem) -> str:
    return f"{item.name}. {item.description}. Style: {', '.join(item.style_tags)}. Color: {item.color or 'unspecified'}."


async def seed(store: BaseStore) -> None:
    """Load the catalog into the store when its namespace is empty (one batch: the embeddings go in one request).

    An item added to the catalog later is not loaded: empty the namespace to reload it.
    """
    if await store.asearch(NAMESPACE, limit=1):
        return
    items = load_catalog().values()
    await store.abatch([PutOp(NAMESPACE, i.id, {**i.model_dump(mode="json"), "text": embedding_text(i)}) for i in items])


@asynccontextmanager
async def open_store(database_url: str | None) -> AsyncIterator[BaseStore]:
    """The graph's store: Postgres (pgvector) at `database_url`, set up and seeded.

    Without a database URL or an OpenRouter key (the seed needs embeddings; recorded ones, LLM_RECORDINGS, do too), the stub graph's
    empty in-memory store.
    """
    if not (database_url and (os.getenv("OPENROUTER_API_KEY") or recorded.directory())):
        if database_url:
            logger.warning("OPENROUTER_API_KEY is unset: the catalog store stays in memory, empty")
        yield InMemoryStore()
        return
    async with AsyncPostgresStore.from_conn_string(database_url, index=index_config()) as store:
        await store.setup()
        await seed(store)
        yield store
