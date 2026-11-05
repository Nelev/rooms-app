from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore

from app.graph.nodes.analyze_room import analyze_room
from app.graph.nodes.architect import architect
from app.graph.nodes.chat_edit import chat_edit
from app.graph.nodes.confirm_room import confirm_room
from app.graph.nodes.critic import critic
from app.graph.nodes.design import design
from app.graph.nodes.present import present
from app.graph.nodes.refine import refine
from app.graph.nodes.route_input import route_input
from app.graph.nodes.solve import solve
from app.graph.nodes.source import source
from app.graph.routing import after_chat_edit, after_critic, after_route_input, after_solve
from app.graph.state import RunState
from app.schemas.base import Model

RECURSION_LIMIT = 25  # the longest run, resuming at confirm_room with MAX_ROUNDS critic rounds, takes 18 steps


def _models(cls: type[Model]) -> list[type[Model]]:
    return [cls, *(m for sub in cls.__subclasses__() for m in _models(sub))]


def serde() -> JsonPlusSerializer:
    """The checkpointer's serde: only LangGraph's safe types and the app's models load (the default loads any type, with a warning)."""
    return JsonPlusSerializer(allowed_msgpack_modules=_models(Model))


def build_graph(checkpointer: BaseCheckpointSaver[str] | None = None, store: BaseStore | None = None) -> CompiledStateGraph[RunState]:
    """Compile the graph. Pass `{"recursion_limit": RECURSION_LIMIT}` in every run's config."""
    builder = StateGraph(RunState)
    for node in (route_input, analyze_room, confirm_room, design, architect, refine, source, solve, critic, present, chat_edit):
        builder.add_node(node)
    builder.add_edge(START, "route_input")
    builder.add_conditional_edges("route_input", after_route_input)
    builder.add_edge("analyze_room", "confirm_room")
    builder.add_edge("confirm_room", "design")
    builder.add_edge("design", "architect")
    builder.add_edge("architect", "refine")
    builder.add_edge("refine", "source")
    builder.add_edge("source", "solve")
    builder.add_conditional_edges("solve", after_solve)
    builder.add_conditional_edges("critic", after_critic)
    builder.add_conditional_edges("chat_edit", after_chat_edit)
    builder.add_edge("present", END)
    return builder.compile(checkpointer=checkpointer, store=store)
