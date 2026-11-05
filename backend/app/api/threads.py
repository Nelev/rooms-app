"""Threads (projects): a row in the projects registry each, their state and history in the checkpointer."""

from uuid import uuid4

from fastapi import APIRouter, HTTPException
from langchain_core.runnables import RunnableConfig
from langgraph.types import StateSnapshot

from app.api.deps import Graph, ProjectsDep, ThreadConfig
from app.api.models import Revert, Thread, ThreadCreate, ThreadState, ThreadStatus
from app.db.projects import Project
from app.runs import interrupts, running

router = APIRouter(prefix="/threads", tags=["threads"])


def _status(snapshot: StateSnapshot, running: bool | None) -> ThreadStatus:
    """`running` is None for a history entry, whose pending `next` is just the run moving on."""
    if running:
        return "running"
    if snapshot.interrupts:
        return "needs_input"
    if any(task.error for task in snapshot.tasks) or (running is not None and snapshot.next):
        return "error"  # failed, or cut off by a restart: input null continues it
    return "done" if snapshot.values else "new"


def _state(snapshot: StateSnapshot, running: bool | None = None) -> ThreadState:
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


def idle(config: ThreadConfig) -> None:
    if running(config["configurable"]["thread_id"]):
        raise HTTPException(409, "A run is active on this thread")


def _thread(project: Project, status: ThreadStatus) -> Thread:
    return Thread(thread_id=project["thread_id"], created_at=project["created_at"], metadata={"title": project["title"]}, status=status)


@router.post("")
async def create_thread(body: ThreadCreate, registry: ProjectsDep) -> Thread:
    """Create a project; only `metadata.title` is kept."""
    title = body.metadata.get("title")
    return _thread(await registry.create(uuid4().hex, title if isinstance(title, str) else ""), "new")


@router.get("")
async def list_threads(graph: Graph, registry: ProjectsDep) -> list[Thread]:
    """The caller's projects, most recently updated first."""  # every project: the auth task adds an owner to filter on
    return [_thread(p, (await _current(graph, {"configurable": {"thread_id": p["thread_id"]}})).status) for p in await registry.list()]


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
    idle(config)
    target: RunnableConfig = {
        **config,
        "configurable": {**config["configurable"], "checkpoint_ns": "", "checkpoint_id": body.checkpoint_id},
    }
    if not (await graph.aget_state(target)).created_at:
        raise HTTPException(404, "Checkpoint not found")
    await graph.aupdate_state(target, None)  # a new checkpoint, forked from the target
    return await _current(graph, config)
