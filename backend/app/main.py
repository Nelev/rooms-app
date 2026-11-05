import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

from app import runs as run_manager
from app.api import camera, catalog, deps, runs, threads, uploads
from app.catalog.embed import open_store
from app.db import migrate
from app.graph.graph import build_graph, serde
from app.observability.logs import configure_logging
from app.observability.middleware import RequestId
from app.storage import Storage

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the checkpointer, the store and the projects registry, and compile the graph.

    With DATABASE_URL, all in Postgres (the registry's tables migrated, the checkpointer's set up; the catalog store stays in memory,
    empty and with a warning, without OPENROUTER_API_KEY); without it, in memory, for `make dev-stub` and tests. Photos go to object
    storage when STORAGE_ENDPOINT_URL is set."""
    dsn = os.getenv("DATABASE_URL")
    async with AsyncExitStack() as stack:
        store = await stack.enter_async_context(open_store(dsn))
        pool = None
        checkpointer: BaseCheckpointSaver[str] = InMemorySaver(serde=serde())
        if dsn:
            await asyncio.to_thread(migrate, dsn)
            # a pool, not one connection: it checks a connection before handing it out, replacing one a suspended database dropped
            pool = AsyncConnectionPool[AsyncConnection[DictRow]](
                dsn,
                min_size=1,
                max_size=10,
                max_idle=240,  # under Neon's 5 minutes of idleness
                check=AsyncConnectionPool.check_connection,
                kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},  # what AsyncPostgresSaver asks
                open=False,
            )
            await stack.enter_async_context(pool)
            checkpointer = AsyncPostgresSaver(pool, serde=serde())
            await checkpointer.setup()  # nothing happens when the tables exist
        app.state.graph = build_graph(checkpointer, store)
        app.state.projects = deps.Projects(pool)
        app.state.storage = Storage.from_env() if os.getenv("STORAGE_ENDPOINT_URL") else None
        try:
            yield
        finally:
            await run_manager.shutdown()  # before the pool closes; a cut-off run continues from its last checkpoint


app = FastAPI(title="rooms-app", lifespan=lifespan)
app.add_middleware(RequestId)
for module in (threads, camera, runs, uploads, catalog):
    app.include_router(module.router)

# local development: the Next.js dev server calls this API straight from the browser (CORS_ORIGINS: comma-separated, to allow another)
origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "DELETE"], allow_headers=["Authorization", "Content-Type"]
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
