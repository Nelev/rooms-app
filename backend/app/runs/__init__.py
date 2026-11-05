"""The in-process run manager: at most one active run per thread, streamed by a background task into an in-memory buffer of
Server-Sent Events, so a client that disconnects can rejoin the run from its first part.

The checkpointer saves the run after every node; this only holds what a stream needs. A run that a restart cut off is lost
here but not in the checkpoints: streaming with input null continues it from the last one. Single process only.
"""

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from fastapi.sse import ServerSentEvent
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Interrupt as LgInterrupt
from langgraph.types import StreamMode

from app.api.models import Interrupt, MessageChunk, MessageMetadata, RunError, RunMetadata
from app.graph.state import RunState
from app.observability.tracing import traced

STREAM_MODES: list[StreamMode] = ["updates", "custom", "messages"]


class RunActive(Exception):
    """The thread already has an active run."""


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


# Thread id -> its latest run, kept after it ends so a client can rejoin it (one buffer per thread).
RUNS: dict[str, Run] = {}


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


async def _execute(run: Run, graph: CompiledStateGraph[RunState], graph_input: Any, config: RunnableConfig) -> None:
    try:
        async for mode, chunk in graph.astream(graph_input, config, stream_mode=STREAM_MODES):
            await run.add(_part(mode, chunk))
    except Exception as e:  # the stream reports it; the checkpoint keeps the failed task, so the thread's status is error
        await run.add(ServerSentEvent(event="error", data=RunError(message=f"{type(e).__name__}: {e}")))
    finally:
        await run.add(None)


def start(graph: CompiledStateGraph[RunState], graph_input: Any, config: RunnableConfig) -> Run:
    """Start a run of `graph` on the config's thread (`graph_input`: an input, a Command, or None to continue from the last checkpoint).

    Raises RunActive while the thread has an active run. No await before the run is registered: two requests cannot both start one."""
    thread_id = config["configurable"]["thread_id"]
    if running(thread_id):
        raise RunActive(thread_id)
    run_id = uuid4()
    run = RUNS[thread_id] = Run(parts=[ServerSentEvent(event="metadata", data=RunMetadata(run_id=run_id.hex))])
    run.task = asyncio.create_task(_execute(run, graph, graph_input, traced(config, run_id)))
    return run


async def shutdown() -> None:
    """Cancel the active runs (at shutdown; each continues from its last checkpoint when streamed with input null) and forget them all."""
    tasks = [run.task for run in RUNS.values() if run.task and not run.task.done()]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    RUNS.clear()
