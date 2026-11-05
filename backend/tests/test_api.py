"""The stub API end to end: a thread's design run to the confirm_room interrupt, its resume and chat runs, all on fixtures."""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from app.api.export import OUT, render
from app.api.models import StreamPart
from app.graph.graph import build_graph
from app.graph.stub import fixture
from app.main import app
from app.schemas import CameraPose, CatalogItem, ConfirmRoom, Layout, LayoutDiff, Scene
from app.schemas.run import NodeName

PARTS = TypeAdapter(list[StreamPart])


def as_sent(type_: Any, data: Any) -> Any:
    """`data` as the API sends it: through the model, with its defaults."""
    adapter = TypeAdapter(type_)
    return adapter.dump_python(adapter.validate_python(data), mode="json")


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client


def stream(client: TestClient, url: str, body: dict[str, Any] | None = None) -> list[tuple[str, Any]]:
    """The run's Server-Sent Events as (event, data), checked against the StreamPart contract."""
    with client.stream("POST" if body else "GET", url, json=body) as response:
        assert response.status_code == 200, response.read()
        blocks = response.read().decode().strip().split("\n\n")
    parts = [dict(line.split(": ", 1) for line in block.splitlines()) for block in blocks]
    PARTS.validate_python([{"event": p["event"], "data": json.loads(p["data"])} for p in parts])
    return [(p["event"], json.loads(p["data"])) for p in parts]


def design_input() -> dict[str, Any]:
    return {
        "photo_keys": [fixture("camera_pose")["photo_key"]],
        "dimensions": fixture("room_spec")["dimensions"],
        "brief": fixture("brief"),
    }


def custom(parts: list[tuple[str, Any]]) -> list[Any]:
    return [data for event, data in parts if event == "custom"]


def test_design_run_interrupt_resume_and_chat(client: TestClient) -> None:
    thread = client.post("/threads", json={"metadata": {"title": "Bedroom"}}).json()
    url = f"/threads/{thread['thread_id']}"
    assert client.get(f"{url}/state").json()["status"] == "new"
    room, events, chat = fixture("room_spec"), fixture("stream_events"), fixture("chat")

    parts = stream(client, f"{url}/runs/stream", {"input": design_input(), "config": {"configurable": {"no_critic": False}}})
    assert parts[0][0] == "metadata"
    assert custom(parts) == events["first_run"]
    assert any(event == "messages" and data[1]["langgraph_node"] == "analyze_room" for event, data in parts)
    (interrupt,) = parts[-1][1]["__interrupt__"]
    assert (parts[-1][0], interrupt["value"]) == ("updates", as_sent(ConfirmRoom, {"room": room}))
    state = client.get(f"{url}/state").json()
    assert (state["status"], state["next"], state["interrupts"]) == ("needs_input", ["confirm_room"], [interrupt])

    parts = stream(client, f"{url}/runs/stream", {"command": {"resume": room}})
    assert custom(parts) == events["resumed_run"]
    state = client.get(f"{url}/state").json()
    assert (state["status"], state["next"], state["interrupts"]) == ("done", [], [])
    assert state["values"]["layout"] == as_sent(Layout, fixture("layout"))
    assert state["values"]["scene"] == as_sent(Scene, fixture("scene"))
    assert state["values"]["cost"] == pytest.approx(sum(e.get("cost", 0) for e in events["first_run"] + events["resumed_run"]))

    pose = client.post(f"{url}/camera-pose", json=fixture("camera_pose")).json()
    assert as_sent(CameraPose, fixture("camera_pose")) in pose["cameras"]
    assert client.get(f"{url}/state").json()["values"]["scene"] == pose

    for turn in chat:  # an applied edit, then a refused one
        parts = stream(client, f"{url}/runs/stream", {"input": turn["input"]})
        assert custom(parts) == turn["events"]
        assert "".join(data[0]["content"] for event, data in parts if event == "messages") == json.dumps(turn["output"]["rationale"])
        values = client.get(f"{url}/state").json()["values"]
        assert values["layout_diff"] == as_sent(LayoutDiff, turn["output"]["layout_diff"])
        assert values["messages"][-2:] == [
            {"role": "user", "content": turn["input"]["chat_message"]},
            {"role": "assistant", "content": turn["output"]["rationale"]},
        ]
    assert values["layout"] == as_sent(Layout, chat[0]["output"]["layout"])  # the refused edit kept the first edit's layout

    rejoined = stream(client, f"{url}/runs/current/stream")
    assert custom(rejoined) == chat[-1]["events"]
    assert {"thread_id": thread["thread_id"], "status": "done"}.items() <= client.get("/threads").json()[0].items()


def test_revert_to_a_checkpoint(client: TestClient) -> None:
    url = f"/threads/{client.post('/threads', json={}).json()['thread_id']}"
    stream(client, f"{url}/runs/stream", {"input": fixture("chat")[0]["input"]})  # a chat turn on a thread with no design fails
    assert client.get(f"{url}/state").json()["status"] == "error"
    assert custom(stream(client, f"{url}/runs/stream", {"input": design_input()})) == fixture("stream_events")["first_run"]
    first = client.get(f"{url}/history").json()[-1]
    assert client.post(f"{url}/revert", json={"checkpoint_id": first["checkpoint_id"]}).json()["next"] == ["route_input"]
    assert client.post(f"{url}/revert", json={"checkpoint_id": "nope"}).status_code == 404


def test_errors(client: TestClient) -> None:
    assert client.get("/threads/nope/state").status_code == 404
    url = f"/threads/{client.post('/threads', json={}).json()['thread_id']}"
    assert client.get(f"{url}/runs/current/stream").status_code == 404
    assert client.post(f"{url}/runs/stream", json={}).status_code == 422
    assert client.post(f"{url}/runs/stream", json={"command": {"resume": fixture("room_spec")}}).status_code == 409
    assert client.post(f"{url}/camera-pose", json=fixture("camera_pose")).status_code == 409


def test_catalog_upload_and_camera_pose(client: TestClient) -> None:
    item = fixture("scene")["items"][0]["item"]
    assert client.get(f"/catalog/items/{item['id']}").json() == as_sent(CatalogItem, item)
    assert client.get("/catalog/items/nope").status_code == 404
    assert client.post("/uploads", files={"file": ("room.jpg", b"jpeg")}).json()["key"].endswith(".jpg")


def test_exported_openapi_is_current() -> None:
    assert OUT.read_text() == render(), "run `make gen`"


def test_every_node_exists() -> None:
    assert set(build_graph().get_graph().nodes) - {"__start__", "__end__"} == set(NodeName.__args__)
