"""The stub API's shared state: the compiled graph and the in-memory thread registry. B-20 moves both to Postgres."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from app.api.models import Thread
from app.graph.graph import RECURSION_LIMIT
from app.graph.state import RunState

THREADS: dict[str, Thread] = {}  # thread id -> the thread, as created (status "new")


def _graph(request: Request) -> CompiledStateGraph[RunState]:
    graph: CompiledStateGraph[RunState] = request.app.state.graph
    return graph


def _thread_config(thread_id: str) -> RunnableConfig:
    if thread_id not in THREADS:
        raise HTTPException(404, "Thread not found")
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": RECURSION_LIMIT}


Graph = Annotated[CompiledStateGraph[RunState], Depends(_graph)]
ThreadConfig = Annotated[RunnableConfig, Depends(_thread_config)]
