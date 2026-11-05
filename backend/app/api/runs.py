"""Run streaming, stubbed: one in-memory run per thread, streamed by a background task so a client can rejoin it."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.sse import EventSourceResponse, ServerSentEvent
from langgraph.types import Command, StreamMode
from langgraph.types import Interrupt as LgInterrupt

from app.api.deps import Graph, ThreadConfig
from app.api.models import Interrupt, MessageChunk, MessageMetadata, RunCreate, RunError, RunMetadata, StreamPart

router = APIRouter(tags=["runs"])

STREAM_MODES: list[StreamMode] = ["updates", "custom", "messages"]
STREAM_DOC: dict[int | str, dict[str, Any]] = {200: {"model": StreamPart, "description": "Server-Sent Events, one per StreamPart"}}


@dataclass
class Run:
    parts: list[ServerSentEvent] = field(default_factory=list)
    done: bool = False
    changed: asyncio.Condition = field(default_factory=asyncio.Condition)
    task: asyncio.Task[None] | None = None

    async def add(self, part: ServerSentEvent | None) -> None:
        """Buffer a part, or end the run with None."""
        async with self.changed:
            if part:
                self.parts.append(part)
            else:
                self.done = True
            self.changed.notify_all()

    async def follow(self) -> AsyncIterator[ServerSentEvent]:
        """Every part of the run, from the first, until it ends."""
        sent = 0
        while True:
            async with self.changed:
                while sent == len(self.parts) and not self.done:
                    await self.changed.wait()
                parts, done = self.parts[sent:], self.done
            for part in parts:
                yield part
            sent += len(parts)
            if done:
                return


RUNS: dict[str, Run] = {}  # thread id -> its latest run


def running(thread_id: str) -> bool:
    return thread_id in RUNS and not RUNS[thread_id].done


def interrupts(values: Sequence[LgInterrupt]) -> list[Interrupt]:
    return [Interrupt(id=i.id, value=i.value) for i in values]


def _part(mode: str, chunk: Any) -> ServerSentEvent:
    if mode == "updates" and "__interrupt__" in chunk:
        chunk = {"__interrupt__": interrupts(chunk["__interrupt__"])}
    if mode == "messages":
        message, metadata = chunk
        chunk = (MessageChunk(id=message.id, content=message.text), MessageMetadata(langgraph_node=metadata["langgraph_node"]))
    return ServerSentEvent(event=mode, data=chunk)


async def _execute(run: Run, graph: Graph, graph_input: Any, config: ThreadConfig) -> None:
    try:
        async for mode, chunk in graph.astream(graph_input, config, stream_mode=STREAM_MODES):
            await run.add(_part(mode, chunk))
    except Exception as e:  # the stream reports it; the checkpoint keeps the failed task, so the thread's status is error
        await run.add(ServerSentEvent(event="error", data=RunError(message=f"{type(e).__name__}: {e}")))
    finally:
        await run.add(None)


async def _start_run(body: RunCreate, graph: Graph, config: ThreadConfig) -> Run:
    thread_id = config["configurable"]["thread_id"]
    if running(thread_id):
        raise HTTPException(409, "A run is already active on this thread")
    if body.command and not (await graph.aget_state(config)).interrupts:
        raise HTTPException(409, "The thread has no open interrupt to resume")
    graph_input: Any = Command(resume=body.command.resume.model_dump(mode="json")) if body.command else dict(body.input or {})
    if body.config:
        config = {**config, "configurable": {**config["configurable"], **body.config.configurable.model_dump()}}
    run = RUNS[thread_id] = Run(parts=[ServerSentEvent(event="metadata", data=RunMetadata(run_id=uuid4().hex))])
    run.task = asyncio.create_task(_execute(run, graph, graph_input, config))
    return run


def _current_run(config: ThreadConfig) -> Run:
    if run := RUNS.get(config["configurable"]["thread_id"]):
        return run
    raise HTTPException(404, "No run on this thread")


@router.post("/threads/{thread_id}/runs/stream", response_class=EventSourceResponse, responses=STREAM_DOC)
async def stream_run(run: Annotated[Run, Depends(_start_run)]) -> AsyncIterator[ServerSentEvent]:
    """Start a run and stream it; 409 while another run is active on the thread."""
    async for part in run.follow():
        yield part


@router.get("/threads/{thread_id}/runs/current/stream", response_class=EventSourceResponse, responses=STREAM_DOC)
async def join_run(run: Annotated[Run, Depends(_current_run)]) -> AsyncIterator[ServerSentEvent]:
    """Stream the thread's latest run from its first part, after a reload, until it ends (at once if it is over); 404 before any run."""
    async for part in run.follow():
        yield part
