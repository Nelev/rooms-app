import operator
from typing import Annotated, Literal, TypedDict

from app.schemas import Brief, CatalogItem, Critique, DesignBrief, Layout, LayoutDiff, RoomSpec, Scene, SceneGraph, ValidationReport
from app.schemas.base import Model
from app.schemas.room import Dimensions


class ChatEntry(Model):
    role: Literal["user", "assistant"]
    content: str


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
    critique: Critique
    round: int  # critic loop round, from 1
    scene: Scene
    layout_diff: LayoutDiff  # what the last chat edit changed
    rationale: str
    messages: Annotated[list[ChatEntry], operator.add]  # the chat history
    # the project's total usage across runs
    cost: Annotated[float, operator.add]  # USD
    input_tokens: Annotated[int, operator.add]
    output_tokens: Annotated[int, operator.add]
