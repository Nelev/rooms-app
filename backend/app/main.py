from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from app.api import catalog, deps, runs, threads, uploads
from app.graph.graph import build_graph, serde
from app.observability.logs import configure_logging
from app.observability.middleware import RequestId

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.graph = build_graph(InMemorySaver(serde=serde()), InMemoryStore())  # the stub graph, in memory: B-20 moves it to Postgres
    deps.THREADS.clear()  # the thread registry lives as long as the checkpoints
    runs.RUNS.clear()
    yield


app = FastAPI(title="rooms-app", lifespan=lifespan)
app.add_middleware(RequestId)
for module in (threads, runs, uploads, catalog):
    app.include_router(module.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
