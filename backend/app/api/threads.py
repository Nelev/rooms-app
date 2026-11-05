"""Threads (projects) and their state, stubbed on an in-memory checkpointer."""

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from langchain_core.runnables import RunnableConfig
from langgraph.types import StateSnapshot

from app.api.deps import THREADS, Graph, ThreadConfig
from app.api.models import Revert, Thread, ThreadCreate, ThreadState, ThreadStatus
from app.api.runs import interrupts, running

router = APIRouter(prefix="/threads", tags=["threads"])


def _status(snapshot: StateSnapshot, running: bool) -> ThreadStatus:
    if running:
        return "running"
    if snapshot.interrupts:
        return "needs_input"
    if any(task.error for task in snapshot.tasks):
        return "error"
    return "done" if snapshot.values else "new"


def _state(snapshot: StateSnapshot, running: bool = False) -> ThreadState:
    return ThreadState.model_validate(
        {
            "values": snapshot.values,
            "next": snapshot.next,
            "interrupts": interrupts(snapshot.interrupts),
            "checkpoint_id": snapshot.config["configurable"].get("checkpoint_id"),
            "created_at": snapshot.created_at,
            "status": _status(snapshot, running),
        }
    )


async def _current(graph: Graph, config: ThreadConfig) -> ThreadState:
    return _state(await graph.aget_state(config), running(config["configurable"]["thread_id"]))


def _idle(config: ThreadConfig) -> None:
    if running(config["configurable"]["thread_id"]):
        raise HTTPException(409, "A run is active on this thread")


@router.post("")
async def create_thread(body: ThreadCreate) -> Thread:
    """Create a project."""
    thread = Thread(thread_id=uuid4().hex, created_at=datetime.now(UTC), metadata=body.metadata, status="new")
    THREADS[thread.thread_id] = thread
    return thread


@router.get("")
async def list_threads(graph: Graph) -> list[Thread]:
    """The caller's projects, newest first."""  # stub: every thread; the auth task adds an owner to filter on
    threads = sorted(THREADS.values(), key=lambda t: t.created_at, reverse=True)
    return [t.model_copy(update={"status": (await _current(graph, {"configurable": {"thread_id": t.thread_id}})).status}) for t in threads]


@router.get("/{thread_id}/state")
async def get_state(graph: Graph, config: ThreadConfig) -> ThreadState:
    return await _current(graph, config)


@router.get("/{thread_id}/history")
async def get_history(graph: Graph, config: ThreadConfig) -> list[ThreadState]:
    """The thread's checkpoints, newest first."""
    return [_state(s) async for s in graph.aget_state_history(config)]


@router.post("/{thread_id}/revert")
async def revert(body: Revert, graph: Graph, config: ThreadConfig) -> ThreadState:
    """Make an earlier checkpoint the thread's current state; 409 while a run is active."""
    _idle(config)
    target: RunnableConfig = {
        **config,
        "configurable": {**config["configurable"], "checkpoint_ns": "", "checkpoint_id": body.checkpoint_id},
    }
    if not (await graph.aget_state(target)).created_at:
        raise HTTPException(404, "Checkpoint not found")
    await graph.aupdate_state(target, None)  # a new checkpoint, forked from the target
    return await _current(graph, config)
