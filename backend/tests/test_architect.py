"""The Architect node, offline: the fake model stands in for get_llm. The live test runs it on the real model (OPENROUTER_API_KEY)."""

from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app import llm
from app.graph import stub
from app.graph.graph import build_graph, serde
from app.graph.nodes.architect import Edges, check, scene_graph, scene_nodes
from app.graph.state import RunState
from app.graph.stub import fixture
from app.llm.fake import CALL_USAGE, FakeLLM
from app.schemas import Brief, Critique, SceneGraph
from app.schemas.design import SceneEdge
from app.schemas.layout import CritiqueAction
from app.schemas.run import StepEvent
from tests.test_api import design_input
from tests.test_fixtures import CASES, case

BEDROOM = case("small-bedroom")
FACING = [("bed", "wall_D"), ("nightstand", "wall_D"), ("desk", "wall_B"), ("desk_chair", "desk")]
# the fixture graph's edges, each object facing one way
EDGES = [*BEDROOM["scene_graph"].edges, *(SceneEdge(source=s, relation="facing", target=t) for s, t in FACING)]


def edges(*items: SceneEdge | tuple[str, str, str]) -> str:
    """A model reply holding these edges."""
    return Edges(
        edges=[e if isinstance(e, SceneEdge) else SceneEdge(source=e[0], relation=e[1], target=e[2]) for e in items]
    ).model_dump_json()


def install(monkeypatch: pytest.MonkeyPatch, *replies: str) -> FakeLLM:
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake")  # the real node, not the fixture replay
    fake = FakeLLM(*replies)
    monkeypatch.setattr(llm, "get_llm", lambda role: fake)
    return fake


def state(**values: Any) -> RunState:
    return {"room_spec": BEDROOM["room_spec"], "design_brief": BEDROOM["design_brief"], **values}


def test_the_graph_holds_the_fixed_roots_and_the_brief_objects(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = install(monkeypatch, edges(*EDGES))
    graph, usage, issues = scene_graph(state())
    assert (issues, usage, fake.calls) == ([], CALL_USAGE, 1)
    assert [n.id for n in graph.nodes] == [
        "wall_A",
        "wall_B",
        "wall_C",
        "wall_D",
        "door_1",
        "window_1",
        "bed",
        "nightstand",
        "desk",
        "desk_chair",
    ]
    assert graph.edges == EDGES
    prompt = str(fake.prompts[0][0].content)
    assert "`facing`" in prompt and BEDROOM["room_spec"].model_dump_json() in prompt and BEDROOM["design_brief"].model_dump_json() in prompt


def test_an_invalid_graph_is_repaired_once_with_the_validator_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    bad = [e for e in EDGES if e.source != "desk"] + [SceneEdge(source="desk", relation="against_wall", target="window_1")]  # no facing
    fake = install(monkeypatch, edges(*bad), edges(("desk", "against_wall", "wall_D"), ("desk", "facing", "wall_B")))
    graph, usage, issues = scene_graph(state())
    assert (issues, fake.calls, usage) == ([], 2, llm.add_usage(CALL_USAGE, CALL_USAGE))
    assert sorted(graph.edges, key=str) == sorted(EDGES, key=str)  # only the desk's edges were replaced
    repair = str(fake.prompts[1][0].content)
    assert "desk cannot be against wall window_1, which is not a wall" in repair and "desk needs exactly one facing edge" in repair


def test_a_graph_still_invalid_after_the_repair_is_returned_with_its_issues(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = install(monkeypatch, edges(("bed", "against_wall", "wall_B"), ("wall_B", "behind", "bed")), edges(("wall_A", "left_of", "bed")))
    graph, _, issues = scene_graph(state())
    assert fake.calls == 2  # no second repair
    assert {i.code for i in issues} == {"facing", "unplaced", "fixed_source"}
    assert check(graph, BEDROOM["room_spec"]) == issues
    assert [(e.source, e.target) for e in graph.edges] == [("bed", "wall_B"), ("wall_A", "bed")]  # wall_B's edge was dropped


def test_critic_fixes_are_applied_to_the_current_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    current = SceneGraph(nodes=BEDROOM["scene_graph"].nodes, edges=EDGES)  # with the sourcer's item ids
    critique = Critique(
        round=1, summary="", actions=[CritiqueAction(target="architect", node_id="desk", instruction="Put the desk under the window")]
    )
    fake = install(monkeypatch, edges(("desk", "in_front", "window_1"), ("desk", "facing", "window_1")))
    graph, _, issues = scene_graph(state(scene_graph=current, critique=critique, round=2))
    assert (issues, fake.calls) == ([], 1)
    assert graph.nodes == current.nodes
    assert (
        graph.edges
        == [e for e in EDGES if e.source != "desk"]
        + Edges.model_validate_json(edges(("desk", "in_front", "window_1"), ("desk", "facing", "window_1"))).edges
    )
    assert "- desk: Put the desk under the window" in str(fake.prompts[0][0].content)


def test_a_critic_fix_left_invalid_is_repaired_once(monkeypatch: pytest.MonkeyPatch) -> None:
    current = SceneGraph(nodes=BEDROOM["scene_graph"].nodes, edges=EDGES)
    critique = Critique(
        round=1,
        summary="",
        actions=[
            CritiqueAction(target="architect", node_id="desk", instruction="Put the desk under the window"),
            CritiqueAction(target="sourcer", node_id="bed", instruction="Find a cheaper bed"),
        ],
    )
    fake = install(
        monkeypatch, edges(("desk", "in_front", "window_1")), edges(("desk", "in_front", "window_1"), ("desk", "facing", "window_1"))
    )
    graph, usage, issues = scene_graph(state(scene_graph=current, critique=critique, round=2))
    assert (issues, fake.calls, usage) == ([], 2, llm.add_usage(CALL_USAGE, CALL_USAGE))
    assert "cheaper" not in str(fake.prompts[0][0].content)  # the sourcer's action is not the Architect's
    assert "desk needs exactly one facing edge" in str(fake.prompts[1][0].content)


def test_objects_must_lead_to_a_fixed_node_and_face_another_node() -> None:
    floating = [e for e in EDGES if e.source not in ("desk", "desk_chair")] + [
        SceneEdge(source="desk_chair", relation="in_front", target="desk"),
        SceneEdge(source="desk", relation="adjacent", target="desk_chair"),
        SceneEdge(source="desk", relation="facing", target="desk"),
        SceneEdge(source="desk_chair", relation="facing", target="desk"),
    ]
    issues = check(SceneGraph(nodes=BEDROOM["scene_graph"].nodes, edges=floating), BEDROOM["room_spec"])
    assert {(i.code, i.node_ids[0]) for i in issues if i.code in ("facing", "unplaced")} == {
        ("facing", "desk"),
        ("unplaced", "desk"),
        ("unplaced", "desk_chair"),
    }
    # once the desk is against a wall, the chair is placed through `desk adjacent desk_chair` (adjacent goes both ways)
    anchored = [*floating[:-4], SceneEdge(source="desk", relation="against_wall", target="wall_B"), *floating[-3:-2]]
    anchored += [
        SceneEdge(source="desk", relation="facing", target="wall_D"),
        SceneEdge(source="desk_chair", relation="facing", target="desk"),
    ]
    assert not check(SceneGraph(nodes=BEDROOM["scene_graph"].nodes, edges=anchored), BEDROOM["room_spec"])


def test_an_old_critique_does_not_turn_a_new_design_into_a_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    old = Critique(round=2, summary="", actions=[CritiqueAction(target="architect", instruction="Fix it")])
    install(monkeypatch, edges(*EDGES))
    graph, _, _ = scene_graph(state(scene_graph=SceneGraph(nodes=[]), critique=old, round=1))
    assert len(graph.nodes) == 10


def test_the_fixture_brief_nodes_match_the_fixture_graph_objects() -> None:
    for name in CASES:
        data = case(name)
        objects = [n for n in scene_nodes(data["design_brief"], data["room_spec"]) if n.kind == "object"]
        assert [n.id for n in objects] == [n.id for n in data["scene_graph"].nodes if n.kind == "object"]


def test_in_the_graph_the_architect_streams_its_steps_and_applies_the_critic_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    # round 1 draws a graph with a second placing edge the solver does not keep; the critic sends it back, and the Architect's fix
    # (the chair's edges without it) applies to the (refined) round-1 graph and passes
    drawn = [*EDGES, SceneEdge(source="desk_chair", relation="left_of", target="bed")]
    fix = edges(("desk_chair", "in_front", "desk"), ("desk_chair", "facing", "desk"))
    fake = install(monkeypatch, edges(*drawn), fix)
    monkeypatch.setattr(stub, "live", lambda node: node == "architect")  # only the architect is real
    graph = build_graph(InMemorySaver(serde=serde()))
    config: Any = {"configurable": {"thread_id": "t1"}}
    graph.invoke({**design_input(), "brief": Brief.model_validate(fixture("brief"))}, config)  # as the API passes it, for the Sourcer
    chunks = list(graph.stream(Command(resume=fixture("room_spec")), config, stream_mode=["custom", "updates"]))
    steps = [StepEvent.model_validate(c).model_dump() for mode, c in chunks if mode == "custom" and c.get("node") == "architect"]
    assert [(s["status"], s["round"]) for s in steps] == [("started", 1), ("done", 1), ("started", 2), ("done", 2)]
    assert steps[1]["summary"] == "scene graph with 4 objects" and steps[1]["cost"] == CALL_USAGE["cost"]
    first, fixed = [c["architect"]["scene_graph"] for mode, c in chunks if mode == "updates" and "architect" in c]
    assert first.edges == drawn and not check(fixed, BEDROOM["room_spec"]) and fake.calls == 2
    assert "desk_chair: desk_chair is not left of bed in the layout" in str(fake.prompts[1][0].content)
    assert [e for e in fixed.edges if e.source == "desk_chair"] == Edges.model_validate_json(fix).edges
    assert graph.get_state(config).values["critique"].summary == "all rules pass"


@pytest.mark.live
def test_live_most_fixture_runs_give_a_valid_graph_without_the_critic() -> None:
    """Done-when of B-15: >= 90% of runs valid. UNVERIFIED: no real-model rate has been measured yet (no key exists).

    Run: `OPENROUTER_API_KEY=... uv run pytest tests/test_architect.py -k live -s`.
    """
    runs = [(name, *scene_graph(state(room_spec=case(name)["room_spec"], design_brief=case(name)["design_brief"]))) for name in CASES * 4]
    for name, graph, usage, issues in runs:
        print(name, usage, [i.message for i in issues], graph.model_dump_json(exclude_none=True))
    assert sum(not issues for *_, issues in runs) >= 0.9 * len(runs)
