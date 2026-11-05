"""Catalog search, offline: fake embeddings, an in-memory store, and Postgres when TEST_DATABASE_URL is set (CI sets it)."""

import hashlib
import math
import os
import re
import uuid
from collections import Counter
from collections.abc import Iterator

import psycopg
import pytest
from catalog_search import QUERIES, precision_at_k
from langchain_core.embeddings import Embeddings
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from psycopg.conninfo import make_conninfo
from psycopg.sql import SQL, Identifier

from app.catalog import embed
from app.catalog.embed import DIMS, NAMESPACE, index_config, open_store, seed
from app.catalog.loader import load_catalog
from app.catalog.search import CANDIDATES, Filters, fits, search
from app.schemas.coords import Size

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeEmbeddings(Embeddings):
    """Vectors of the words of a text (from CoA's tests): texts that share words are similar, others are not. Counts the texts embedded."""

    def __init__(self) -> None:
        self.texts = 0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.texts += len(texts)
        vectors = []
        for text in texts:
            vector = [0.0] * DIMS
            for word in re.findall(r"\w+", text.lower()):
                vector[int(hashlib.sha256(word.encode()).hexdigest(), 16) % DIMS] += 1
            norm = math.sqrt(sum(x * x for x in vector)) or 1
            vectors.append([x / norm for x in vector])
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


@pytest.fixture
async def store() -> BaseStore:
    store = InMemoryStore(index=index_config(FakeEmbeddings()))
    await seed(store)
    return store


async def test_seed_loads_every_item_once() -> None:
    fake = FakeEmbeddings()
    store = InMemoryStore(index=index_config(fake))
    await seed(store)
    catalog = load_catalog()
    assert fake.texts == len(catalog)
    hits = await store.asearch(NAMESPACE, limit=1000)
    assert {h.key for h in hits} == catalog.keys()
    sofa = await store.aget(NAMESPACE, "beige-sofa-3")
    assert sofa and {k: sofa.value[k] for k in ("price", "category", "style_tags")} == {
        "price": 819,
        "category": "sofa",
        "style_tags": ["japandi", "minimalist"],
    }
    assert sofa.value["size"]["width"] == 2.15 and sofa.value["description"] == "Three-seat sofa with loose cushions"
    assert (
        sofa.value["text"] == "Beige linen three-seat sofa. Three-seat sofa with loose cushions. Style: japandi, minimalist. Color: beige."
    )

    await seed(store)  # not empty: nothing is loaded again
    assert fake.texts == len(catalog)


async def test_search_ranks_the_category_by_the_query(store: BaseStore) -> None:
    found = await search(store, "walnut mid-century desk", Filters("desk"))
    assert len(found) == 5 and {i.category for i in found} == {"desk"}
    assert found[0].id.startswith("walnut-desk")


async def test_search_applies_the_size_and_the_budget(store: BaseStore) -> None:
    box = Size(width=1.2, depth=0.6, height=0.75)
    found = await search(store, "desk", Filters("desk", box, max_price=170))
    assert {i.id for i in found} == {"black-desk-120", "oak-desk-120", "white-desk-120"}  # ash 189 and walnut 229 are over budget
    assert await search(store, "desk", Filters("desk", box, max_price=50)) == []


def test_fits_checks_the_size_and_the_footprint_aspect_ratio() -> None:
    item = load_catalog()["white-desk-120"]  # 1.2 x 0.6 x 0.75
    assert fits(item, Filters("desk"))
    assert fits(item, Filters("desk", Size(width=1.3, depth=0.65, height=0.8)))  # within 10%
    assert not fits(item, Filters("desk", Size(width=1.2, depth=0.6, height=0.9)))  # too low
    assert not fits(item, Filters("desk", Size(width=1.4, depth=0.6, height=0.75)))  # too narrow
    # width -8% and depth +8%: each within 10%, but the item is squarer than the box (2.0 / 2.6 = 0.77)
    assert not fits(item, Filters("desk", Size(width=1.3, depth=0.5, height=0.75)))
    assert not fits(item, Filters("desk", max_price=item.price - 1))


def test_labeled_queries_are_reachable() -> None:
    catalog = load_catalog()
    assert max(Counter(i.category for i in catalog.values()).values()) < CANDIDATES  # search ranks a whole category
    assert len(QUERIES) == 20
    for q in QUERIES:
        assert q.relevant and all(catalog[i].category == q.category and fits(catalog[i], q.filters) for i in q.relevant), q.query


async def test_precision_at_5_runs_offline() -> None:
    """The real number needs the real embeddings (`../eval/catalog_search.py`); here only that it runs, on fake ones."""
    scores = await precision_at_k(FakeEmbeddings())
    assert len(scores) == 20 and all(0 <= s <= 1 for s in scores.values())
    print(f"precision@5 with fake embeddings: {sum(scores.values()) / len(scores):.3f}")


@pytest.fixture
def dsn() -> Iterator[str]:
    base = os.getenv("TEST_DATABASE_URL") or pytest.skip("TEST_DATABASE_URL is not set")
    schema = f"test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(SQL("CREATE SCHEMA {}").format(Identifier(schema)))
    yield make_conninfo(base, options=f"-csearch_path={schema},public")  # public: where the vector extension may already be
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(SQL("DROP SCHEMA {} CASCADE").format(Identifier(schema)))


@pytest.fixture
def fake_embeddings(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeEmbeddings]:
    fake = FakeEmbeddings()
    monkeypatch.setattr(embed, "get_embeddings", lambda: fake)
    yield fake


async def test_postgres_store_is_seeded_once_and_searched(dsn: str, fake_embeddings: FakeEmbeddings) -> None:
    async with open_store(dsn) as store:
        found = await search(store, "walnut mid-century desk", Filters("desk", max_price=300))
        assert found[0].id.startswith("walnut-desk") and all(i.category == "desk" and i.price <= 300 for i in found)
    seeded = fake_embeddings.texts
    async with open_store(dsn) as store:  # already seeded: only the query is embedded
        assert await search(store, "oak bed", Filters("bed"))
    assert fake_embeddings.texts == seeded + 1


async def test_without_a_database_the_store_is_in_memory_and_empty() -> None:
    async with open_store(None) as store:
        assert isinstance(store, InMemoryStore) and await store.asearch(NAMESPACE) == []


async def test_without_an_openrouter_key_the_store_is_in_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    async with open_store("postgresql://nowhere/rooms") as store:  # not connected: the seed could not embed the catalog
        assert isinstance(store, InMemoryStore)
