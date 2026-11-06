"""The API's request and response models: the contract the frontend is generated from (contracts/openapi.json)."""

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import Field, JsonValue, model_validator

from app.graph.state import RunState
from app.schemas import ConfirmRoom, ConfirmRoomResume, RunInput, StreamEvent
from app.schemas.base import Model
from app.schemas.run import NodeName

ThreadStatus = Annotated[
    Literal["new", "running", "needs_input", "done", "error"],
    Field(
        description="new: no run yet; running: a run is active; needs_input: an interrupt is open; done: no node left to run; "
        "error: the last run failed, or a restart cut it off (a run with input null continues it)"
    ),
]


class ThreadCreate(Model):
    metadata: dict[str, JsonValue] = Field({}, description="Free-form, e.g. the project's title")


class Thread(Model):
    """A project: one room, designed by its first run and edited by chat runs."""

    thread_id: str
    created_at: datetime
    metadata: dict[str, JsonValue]
    status: ThreadStatus


class Interrupt(Model):
    id: str
    value: ConfirmRoom


class ThreadState(Model):
    """The thread at a checkpoint."""

    values: RunState
    next: list[NodeName | Literal["__start__"]] = Field(description="The nodes that run next; empty when the run is done")
    interrupts: list[Interrupt] = Field(description="The open interrupt, resumed with `command.resume`")
    checkpoint_id: str | None
    created_at: datetime | None
    status: ThreadStatus


class Command(Model):
    resume: ConfirmRoomResume


class RunConfigurable(Model):
    """Ablation flags, read by the nodes from the run's `configurable`."""

    no_critic: bool = False
    analyst_mode: bool = False


class RunConfig(Model):
    configurable: RunConfigurable = RunConfigurable()


class RunCreate(Model):
    """Start a run with a new `input`, resume the open interrupt with `command`, or continue from the last checkpoint with input null."""

    input: RunInput | None = None
    command: Command | None = None
    config: RunConfig | None = None

    @model_validator(mode="after")
    def _input_or_command(self) -> Self:
        if ("input" in self.model_fields_set) == (self.command is not None):
            raise ValueError("pass either input (null to continue) or command")
        return self


class Revert(Model):
    checkpoint_id: str


class Upload(Model):
    key: str = Field(description="Object-storage key, for RunInput.photo_keys")


# Run streams are Server-Sent Events, as the LangGraph Agent Server sends them: each part's `event` is the SSE event
# name and its `data` the SSE data (JSON). The stream ends when the run ends or pauses at an interrupt.


class RunMetadata(Model):
    run_id: str


class MetadataPart(Model):
    """The first part of every stream."""

    event: Literal["metadata"]
    data: RunMetadata


class UpdatesPart(Model):
    """What a node changed, by node name; `__interrupt__` holds an interrupt the run paused at."""

    event: Literal["updates"]
    data: dict[str, RunState | list[Interrupt] | None]


class CustomPart(Model):
    """A node's progress."""

    event: Literal["custom"]
    data: StreamEvent


class MessageChunk(Model):
    id: str | None
    content: str


class MessageMetadata(Model):
    langgraph_node: NodeName


class MessagesPart(Model):
    """A model's reply token, with the node that called the model."""

    event: Literal["messages"]
    data: tuple[MessageChunk, MessageMetadata]


class RunError(Model):
    message: str


class ErrorPart(Model):
    """The run failed; the stream ends."""

    event: Literal["error"]
    data: RunError


StreamPart = Annotated[MetadataPart | UpdatesPart | CustomPart | MessagesPart | ErrorPart, Field(discriminator="event")]
