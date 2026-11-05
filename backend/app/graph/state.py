import operator
from typing import Annotated, Literal, TypedDict

from app.schemas import (
    Brief,
    CatalogItem,
    Critique,
    DesignBrief,
    FallbackReport,
    Layout,
    LayoutDiff,
    RoomSpec,
    Scene,
    SceneGraph,
    ValidationReport,
)
from app.schemas.base import Model
from app.schemas.room import Dimensions


class ChatEntry(Model):
    role: Literal["user", "assistant"]
    content: str


class Best(Model):
    """INTERNAL loop bookkeeping: the best design of the critic loop so far, the fewest hard issues, then the fewest soft ones
    (routing.keep_best); cleared when the run ends."""

    hard: int
    soft: int
    scene_graph: SceneGraph
    candidates: dict[str, list[CatalogItem]] = {}
    layout: Layout
    validation: ValidationReport
    fallback: FallbackReport
    critique: Critique


class RunState(TypedDict, total=False):
    """The graph's state, kept per thread (project) across its runs; also the `values` the API returns."""

    # the run input (RunInput): a new design, or a chat message, which route_input moves to `messages`
    photo_keys: list[str]
    dimensions: Dimensions
    brief: Brief
    chat_message: str | None
    mode: Literal["design", "chat"]  # the current run's kind, set by route_input from its input

    room_spec: RoomSpec
    design_brief: DesignBrief
    scene_graph: SceneGraph
    candidates: dict[str, list[CatalogItem]]  # scene-graph node id -> catalog items that fit it
    layout: Layout
    validation: ValidationReport
    fallback: FallbackReport  # what the solver fallback dropped or shrank to find the layout
    critique: Critique
    best: Best | None  # INTERNAL: the critic loop's best design so far, which the run ends with; None once the run ends
    round: int  # critic loop round, from 1
    scene: Scene
    layout_diff: LayoutDiff  # what the last chat edit changed
    rationale: str
    messages: Annotated[list[ChatEntry], operator.add]  # the chat history
    # the project's total usage across runs
    cost: Annotated[float, operator.add]  # USD
    input_tokens: Annotated[int, operator.add]
    output_tokens: Annotated[int, operator.add]
