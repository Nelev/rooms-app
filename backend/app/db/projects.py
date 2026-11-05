"""The projects registry: a row per thread (its id, owner, title and times), since open-source LangGraph cannot search threads.

The thread's state and history stay in the checkpointer; nothing about a run's progress goes here. Each function runs one statement on
the caller's connection (e.g. from a pool), which commits it.
"""

from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

# A project is a dict row of these columns; owner is the sign-in id, none before there is sign-in.
COLUMNS = "thread_id, owner, title, created_at, updated_at"
Project = dict[str, Any]


async def _rows(db: AsyncConnection[Any], query: str, args: tuple[object, ...]) -> list[Project]:
    async with db.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(query, args)
        return await cursor.fetchall()


async def create(db: AsyncConnection[Any], thread_id: str, title: str, owner: str | None = None) -> Project:
    query = f"INSERT INTO projects (thread_id, owner, title) VALUES (%s, %s, %s) RETURNING {COLUMNS}"
    return (await _rows(db, query, (thread_id, owner, title)))[0]


async def get(db: AsyncConnection[Any], thread_id: str) -> Project | None:
    rows = await _rows(db, f"SELECT {COLUMNS} FROM projects WHERE thread_id = %s", (thread_id,))
    return rows[0] if rows else None


async def list_owned(db: AsyncConnection[Any], owner: str | None = None) -> list[Project]:
    """A person's projects (none: those without an owner), most recently updated first."""
    query = f"SELECT {COLUMNS} FROM projects WHERE owner IS NOT DISTINCT FROM %s ORDER BY updated_at DESC"
    return await _rows(db, query, (owner,))


async def update(db: AsyncConnection[Any], thread_id: str, title: str | None = None) -> Project | None:
    """Mark the project updated now (e.g. after a run), renaming it when `title` is given. None if there is no such project."""
    query = f"UPDATE projects SET title = COALESCE(%s, title), updated_at = now() WHERE thread_id = %s RETURNING {COLUMNS}"
    rows = await _rows(db, query, (title, thread_id))
    return rows[0] if rows else None


async def delete(db: AsyncConnection[Any], thread_id: str) -> bool:
    """Remove the project's row (its checkpoints and stored files are the caller's to delete). False if there was none."""
    return (await db.execute("DELETE FROM projects WHERE thread_id = %s", (thread_id,))).rowcount > 0
