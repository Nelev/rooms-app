"""Run streaming: a run per thread at a time, owned by the run manager (app.runs), sent as Server-Sent Events and rejoinable."""

from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.sse import EventSourceResponse, ServerSentEvent
from langgraph.types import Command

from app import runs
from app.api.deps import Graph, ProjectsDep, ThreadConfig
from app.api.models import RunCreate, StreamPart
from app.scene.builder import total
from app.schemas import Brief, RunOutput

router = APIRouter(tags=["runs"])

STREAM_DOC: dict[int | str, dict[str, Any]] = {200: {"model": StreamPart, "description": "Server-Sent Events, one per StreamPart"}}


async def _start_run(body: RunCreate, graph: Graph, config: ThreadConfig, registry: ProjectsDep) -> runs.Run:
    thread_id = config["configurable"]["thread_id"]
    if (body.command or body.input is None) and not runs.running(thread_id):  # (while one runs, start() refuses it)
        snapshot = await graph.aget_state(config)
        if body.command and not snapshot.interrupts:
            raise HTTPException(409, "The thread has no open interrupt to resume")
        if not body.command and (snapshot.interrupts or not snapshot.next):
            raise HTTPException(409, "The thread has no cut-off run to continue")
    graph_input: Any = None  # input null: continue from the last checkpoint (a run cut off by a restart)
    if body.command:
        graph_input = Command(resume=body.command.resume.model_dump(mode="json"))
    elif body.input:
        graph_input = dict(body.input)
    if body.config:
        config = {**config, "configurable": {**config["configurable"], **body.config.configurable.model_dump()}}
    if runs.running(thread_id):  # checked before touching; start() checks again, with no await in between
        raise HTTPException(409, "A run is already active on this thread")
    await registry.touch(thread_id)  # before the run starts: if it fails, nothing runs and a retry can start it
    try:
        return runs.start(graph, graph_input, config)
    except runs.RunActive:
        raise HTTPException(409, "A run is already active on this thread") from None


def _current_run(config: ThreadConfig) -> runs.Run:
    if run := runs.RUNS.get(config["configurable"]["thread_id"]):
        return run
    raise HTTPException(404, "No run on this thread")


@router.post("/threads/{thread_id}/runs/stream", response_class=EventSourceResponse, responses=STREAM_DOC)
async def stream_run(run: Annotated[runs.Run, Depends(_start_run)]) -> AsyncIterator[ServerSentEvent]:
    """Start a run and stream it; 409 while another run is active on the thread, or when there is nothing to resume or continue."""
    async for part in run.follow():
        yield part


@router.get("/threads/{thread_id}/runs/current/stream", response_class=EventSourceResponse, responses=STREAM_DOC)
async def join_run(run: Annotated[runs.Run, Depends(_current_run)]) -> AsyncIterator[ServerSentEvent]:
    """Stream the thread's latest run from its first part, after a reload, until it ends (at once if it is over); 404 before any run."""
    async for part in run.follow():
        yield part


@router.get(
    "/threads/{thread_id}/runs/{run_id}/result",
    responses={404: {"description": "No such run"}, 409: {"description": "The run has not finished"}},
)
async def get_result(run_id: str, graph: Graph, config: ThreadConfig) -> RunOutput:
    """What a finished run left, from its last checkpoint (the run's ID is in each one's metadata); 404 for an unknown run, 409
    while it has not finished (running, paused at an interrupt, failed or cut off)."""
    async for snapshot in graph.aget_state_history(config, filter={"run_id": run_id}, limit=1):
        if snapshot.next:
            raise HTTPException(409, "The run has not finished")
        values, scene = snapshot.values, snapshot.values.get("scene")
        return RunOutput.model_validate(
            {
                **{k: values.get(k) for k in ("scene", "layout", "critique", "layout_diff", "rationale")},
                "total": total(scene) if scene else None,
                "budget": Brief.model_validate(values["brief"]).budget if "brief" in values else None,
            }
        )
    raise HTTPException(404, "Run not found")
