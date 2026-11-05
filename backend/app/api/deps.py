"""The API's shared state, set by the lifespan: the compiled graph and the projects registry."""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from psycopg_pool import AsyncConnectionPool

from app.db import projects
from app.db.projects import Project
from app.graph.state import RunState


class Projects:
    """The projects registry (app.db.projects) on the pool; without one (no DATABASE_URL: `make dev-stub`, tests) a dict, as
    short-lived as the in-memory checkpoints."""

    def __init__(self, pool: AsyncConnectionPool[Any] | None = None) -> None:
        self.pool = pool
        self.rows: dict[str, Project] = {}

    async def create(self, thread_id: str, title: str) -> Project:
        if self.pool is None:
            now = datetime.now(UTC)
            self.rows[thread_id] = {"thread_id": thread_id, "owner": None, "title": title, "created_at": now, "updated_at": now}
            return self.rows[thread_id]
        async with self.pool.connection() as db:
            return await projects.create(db, thread_id, title)

    async def get(self, thread_id: str) -> Project | None:
        if self.pool is None:
            return self.rows.get(thread_id)
        async with self.pool.connection() as db:
            return await projects.get(db, thread_id)

    async def list(self) -> list[Project]:
        """Most recently updated first."""
        if self.pool is None:
            return sorted(self.rows.values(), key=lambda p: p["updated_at"], reverse=True)
        async with self.pool.connection() as db:
            return await projects.list_owned(db)  # no owner until there is sign-in

    async def touch(self, thread_id: str) -> None:
        """Mark the project updated now, when a run starts on it."""
        if self.pool is None:
            self.rows[thread_id]["updated_at"] = datetime.now(UTC)
            return
        async with self.pool.connection() as db:
            await projects.update(db, thread_id)


def _graph(request: Request) -> CompiledStateGraph[RunState]:
    graph: CompiledStateGraph[RunState] = request.app.state.graph
    return graph


def _projects(request: Request) -> Projects:
    registry: Projects = request.app.state.projects
    return registry


ProjectsDep = Annotated[Projects, Depends(_projects)]


async def _thread_config(thread_id: str, registry: ProjectsDep) -> RunnableConfig:
    if await registry.get(thread_id) is None:
        raise HTTPException(404, "Thread not found")
    return {"configurable": {"thread_id": thread_id}}


Graph = Annotated[CompiledStateGraph[RunState], Depends(_graph)]
ThreadConfig = Annotated[RunnableConfig, Depends(_thread_config)]
