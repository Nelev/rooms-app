"""The projects registry, on a real Postgres: TEST_DATABASE_URL (CI sets it), else skipped. Each test gets a schema of its own."""

import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import psycopg
import pytest
from psycopg.conninfo import make_conninfo
from psycopg.sql import SQL, Identifier

from app.db import migrate, projects

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def dsn() -> Any:
    base = os.getenv("TEST_DATABASE_URL") or pytest.skip("TEST_DATABASE_URL is not set")
    schema = f"test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(SQL("CREATE SCHEMA {}").format(Identifier(schema)))
    yield make_conninfo(base, options=f"-csearch_path={schema}")  # the tables, alembic_version included, go in the test's schema
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(SQL("DROP SCHEMA {} CASCADE").format(Identifier(schema)))


@pytest.fixture
async def db(dsn: str) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    migrate(dsn)
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        yield conn


def test_migrate_is_idempotent(dsn: str) -> None:
    migrate(dsn)
    migrate(dsn)  # at every startup: nothing left to apply
    with psycopg.connect(dsn) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchall() == [("0001",)]


async def test_registry(db: psycopg.AsyncConnection[Any]) -> None:
    first = await projects.create(db, "t1", "Bedroom", owner="ann")
    assert (first.thread_id, first.owner, first.title) == ("t1", "ann", "Bedroom")
    assert first.created_at == first.updated_at
    await projects.create(db, "t2", "Office", owner="ann")
    await projects.create(db, "t3", "Bob's", owner="bob")
    await projects.create(db, "t4", "Anonymous")

    assert await projects.get(db, "t1") == first
    assert await projects.get(db, "missing") is None
    assert [p.thread_id for p in await projects.list_owned(db, "ann")] == ["t2", "t1"]  # newest first
    assert [p.thread_id for p in await projects.list_owned(db)] == ["t4"]

    touched = await projects.update(db, "t1")
    assert touched and touched.title == "Bedroom" and touched.updated_at > first.updated_at
    assert [p.thread_id for p in await projects.list_owned(db, "ann")] == ["t1", "t2"]  # updated moves it up
    renamed = await projects.update(db, "t1", title="Main bedroom")
    assert renamed and renamed.title == "Main bedroom" and renamed.created_at == first.created_at
    assert await projects.update(db, "missing", title="x") is None

    assert await projects.delete(db, "t1") is True
    assert await projects.delete(db, "t1") is False
    assert await projects.get(db, "t1") is None
