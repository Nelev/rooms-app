"""The Presenter (B-19): the scene builder on the fixture cases, the rationale, the node keeping the user's cameras, and (live)
the whole graph on real models."""

import asyncio
import os
import time
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command
from pydantic import TypeAdapter

from app import llm
from app.catalog.embed import index_config, seed
from app.graph.graph import build_graph, serde
from app.graph.stub import fixture, load
from app.scene.builder import build_scene, rationale, total
from app.schemas import Brief, CameraPose, Critique, DesignBrief, FallbackReport, Layout, RoomSpec, RunOutput, Scene
from tests.test_api import design_input

FIXTURES = Path(__file__).parents[2] / "fixtures"
CASES = ["small-bedroom", "home-office", "living-room"]


def read[T](case: str, name: str, type_: type[T]) -> T:
    return TypeAdapter(type_).validate_json((FIXTURES / case / f"{name}.json").read_bytes())


@pytest.mark.parametrize("case", CASES)
def test_the_scene_of_a_fixture_layout_is_the_fixture_scene(case: str) -> None:
    """Room, catalog items (GLB URL, front), one area light per window; the cameras are only the ones passed in."""
    scene, camera = read(case, "scene", Scene), read(case, "camera_pose", CameraPose)
    built = build_scene(read(case, "room_spec", RoomSpec), read(case, "layout", Layout))
    assert built == scene.model_copy(update={"cameras": []})
    assert build_scene(scene.room, read(case, "layout", Layout), [camera]).cameras == [camera]
    assert total(built) == sum(i.item.price for i in scene.items if i.item)


def test_rationale_says_the_cost_against_the_budget_what_did_not_fit_and_the_verdict() -> None:
    design, scene = load("design_brief", DesignBrief), load("scene", Scene)
    text = rationale(design, scene, 1200, FallbackReport(summary="Placed 4 of 4 items"), None)
    assert text == f"{design.summary}. 4 items for €806, within the €1,200 budget."  # a fallback without changes says nothing
    box = scene.items[0].model_copy(update={"item": None})
    change = {"node_id": "piano", "action": "dropped", "code": "no_space", "message": "no space"}
    fallback = FallbackReport.model_validate({"changes": [change], "summary": "Placed 4 of 5 items; dropped: piano"})
    critique = Critique(round=2, summary="1 rule fails: the bed faces door_1")
    text = rationale(design, scene.model_copy(update={"items": [box, *scene.items[1:]]}), 200, fallback, critique)
    assert text.endswith(
        "3 items for €357, over the €200 budget. 1 object has no matching catalog item yet. Placed 4 of 5 items; dropped: piano. "
        "Critic: 1 rule fails: the bed faces door_1."
    )


def test_a_design_run_is_presented_with_a_rationale_and_chat_runs_keep_the_matched_cameras() -> None:
    graph = build_graph(InMemorySaver(serde=serde()), InMemoryStore())
    config: Any = {"configurable": {"thread_id": "t1"}}
    graph.invoke(design_input(), config)
    graph.invoke(Command(resume=fixture("room_spec")), config)
    values = graph.get_state(config).values
    assert values["scene"].cameras == [] and values["scene"].lights
    assert values["rationale"].startswith(values["design_brief"].summary) and "Critic: all rules pass" in values["rationale"]

    camera = load("camera_pose", CameraPose)  # as POST /camera-pose saves it
    graph.update_state(config, {"scene": values["scene"].model_copy(update={"cameras": [camera]})})
    graph.invoke(fixture("chat")[0]["input"], config)
    values = graph.get_state(config).values
    assert values["scene"].cameras == [camera] and values["rationale"] == fixture("chat")[0]["output"]["rationale"]
    assert [i.x for i in values["scene"].items] == [p.x for p in values["layout"].placements]


class ModelIds(BaseCallbackHandler):
    """The model id OpenRouter reports for each call, by node: proves which model each role really called."""

    def __init__(self) -> None:
        self.nodes: dict[UUID, str] = {}
        self.seen: set[tuple[str, str]] = set()

    def on_chat_model_start(self, serialized: Any, messages: Any, *, run_id: UUID, metadata: Any = None, **kw: Any) -> None:
        self.nodes[run_id] = (metadata or {}).get("langgraph_node", "?")

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kw: Any) -> None:
        for gen in (g for gens in response.generations for g in gens):  # the reply's own `model`, not the configured one
            reply = getattr(gen, "message", None)
            self.seen.add((self.nodes.get(run_id, "?"), getattr(reply, "response_metadata", {}).get("model_name", "?")))


@pytest.fixture(scope="module")
def catalog_store() -> InMemoryStore:
    """The catalog in memory with real embeddings (B-08's index), as the API's Postgres store holds it: one embedding batch."""
    if not os.environ.get("OPENROUTER_API_KEY"):  # set up before the autouse `offline` fixture skips the live tests
        pytest.skip("needs OPENROUTER_API_KEY")
    store = InMemoryStore(index=index_config())
    asyncio.run(seed(store))
    return store


@pytest.mark.live
@pytest.mark.parametrize("case", CASES)
def test_live_full_graph(case: str, catalog_store: InMemoryStore) -> None:
    """B-19's done-when: the whole graph on real models, from the fixture's photos, dimensions and brief, resumed at confirm_room
    with the analyzed room, to a Scene and a RunOutput. Run with -s for the per-room report (model cost: the source node's
    fixture step cost is not counted, the catalog searches' query embeddings are not measured)."""
    llm.get_llm.cache_clear()
    graph = build_graph(InMemorySaver(serde=serde()), catalog_store)
    models = ModelIds()
    config: Any = {"configurable": {"thread_id": case}, "callbacks": [models]}
    photos = sorted(f"fixtures/{case}/{p.name}" for p in (FIXTURES / case).glob("photo-*.jpg"))
    room_spec = read(case, "room_spec", RoomSpec)
    graph_input = {"photo_keys": photos, "dimensions": room_spec.dimensions, "brief": read(case, "brief", Brief)}
    updates: list[tuple[str, dict[str, Any]]] = []
    start = time.monotonic()
    for chunk in graph.stream(graph_input, config, stream_mode="updates"):
        updates += [(node, u) for node, u in chunk.items() if isinstance(u, dict)]
    (interrupt,) = graph.get_state(config).interrupts
    for chunk in graph.stream(Command(resume=interrupt.value["room"]), config, stream_mode="updates"):
        updates += [(node, u) for node, u in chunk.items() if isinstance(u, dict)]
    duration = time.monotonic() - start

    values = graph.get_state(config).values
    assert not graph.get_state(config).next and isinstance(values["scene"], Scene) and values["scene"].items
    output = RunOutput(scene=values["scene"], layout=values["layout"], critique=values["critique"], rationale=values["rationale"])
    assert output.rationale and values["design_brief"].summary in output.rationale
    model = [(n, u) for n, u in updates if n != "source"]  # source's update carries its fixture step's cost (stub_node)
    cost = sum(u.get("cost", 0.0) for _, u in model)
    tokens = sum(u.get("input_tokens", 0) for _, u in model), sum(u.get("output_tokens", 0) for _, u in model)
    rounds = [u["critique"] for n, u in updates if n == "critic"]
    errors = [i.code for i in values["validation"].issues if i.severity == "error"]
    failed = [r.rule for r in values["critique"].rules if not r.passed]
    print(
        f"\nB-19 live | {case} | ${cost:.4f} | {tokens[0]} in / {tokens[1]} out tokens | {duration:.0f} s | {len(rounds)} rounds "
        f"({'; '.join(c.summary for c in rounds)}) | final: {values['critique'].summary} | errors {errors} | failed rules {failed} | "
        f"fallback: {values['fallback'].summary} | {len(values['scene'].items)} objects, €{total(values['scene']):.0f} of "
        f"€{values['brief'].budget:.0f} | features {[f.id for f in values['room_spec'].features]} | per node "
        f"{ {n: round(sum(u.get('cost', 0.0) for m, u in model if m == n), 4) for n, _ in model} } | models {sorted(models.seen)}"
        f"\nrationale: {output.rationale}"
    )
