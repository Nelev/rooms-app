import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.memory import InMemorySaver

from app.api import camera, catalog, deps, runs, threads, uploads
from app.catalog.embed import open_store
from app.graph.graph import build_graph, serde
from app.observability.logs import configure_logging
from app.observability.middleware import RequestId

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with open_store(os.getenv("DATABASE_URL")) as store:  # the catalog, in Postgres; without DATABASE_URL in memory, empty
        app.state.graph = build_graph(InMemorySaver(serde=serde()), store)  # the stub graph, checkpoints in memory: B-20 moves them
        deps.THREADS.clear()  # the thread registry lives as long as the checkpoints
        runs.RUNS.clear()
        yield


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
