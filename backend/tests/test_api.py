"""The stub API end to end: a thread's design run to the confirm_room interrupt, its resume and chat runs, all on fixtures."""

import io
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pillow_heif
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import TypeAdapter

from app.api.export import OUT, render
from app.api.models import StreamPart
from app.api.uploads import MAX_UPLOAD_BYTES
from app.graph.graph import build_graph
from app.graph.stub import fixture
from app.main import app
from app.schemas import CatalogItem, ConfirmRoom, Layout, LayoutDiff, Scene
from app.schemas.run import NodeName
from app.storage import local_path

PARTS = TypeAdapter(list[StreamPart])


def as_sent(type_: Any, data: Any) -> Any:
    """`data` as the API sends it: through the model, with its defaults."""
    adapter = TypeAdapter(type_)
    return adapter.dump_python(adapter.validate_python(data), mode="json")


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))  # uploads without object storage, never in the developer's backend/.uploads
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


REAL = ("solve", "critic", "present")  # deterministic nodes that run for real in the stub graph and stream their own step events


def one_round(events: list[Any]) -> list[Any]:
    """The fixture events a stub design run replays: the real critic accepts the fixture design in one round, not the fixture's 2."""
    return [e for e in events if e.get("round", 1) == 1]


def replayed(events: list[Any]) -> list[Any]:
    """The events of the stub nodes, and only the steps of the real ones (their summaries and durations are their own)."""
    return [{k: e[k] for k in ("node", "status", "round") if k in e} if e["node"] in REAL else e for e in events]


def stub_cost(events: list[Any]) -> float:
    """The usage of a stub run streaming `events`: the fixture costs of its stub steps (the real nodes call no model)."""
    return sum(e.get("cost", 0) for e in events if e["node"] not in REAL)


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
    paused = f"{url}/runs/{parts[0][1]['run_id']}/result"
    assert client.get(paused).status_code == 409  # paused at confirm_room
    state = client.get(f"{url}/state").json()
    assert (state["status"], state["next"], state["interrupts"]) == ("needs_input", ["confirm_room"], [interrupt])

    parts = stream(client, f"{url}/runs/stream", {"command": {"resume": room}})
    resumed = one_round(events["resumed_run"])
    assert replayed(custom(parts)) == replayed(resumed)
    state = client.get(f"{url}/state").json()
    assert (state["status"], state["next"], state["interrupts"]) == ("done", [], [])
    values = state["values"]
    assert (values["critique"]["round"], values["critique"]["actions"], values["fallback"]["changes"]) == (1, [], [])
    assert [i["node_id"] for i in values["scene"]["items"]] == [p["node_id"] for p in values["layout"]["placements"]] != []
    assert values["scene"]["room"] == as_sent(Scene, fixture("scene"))["room"]
    assert values["cost"] == pytest.approx(stub_cost(events["first_run"] + resumed))
    result = client.get(f"{url}/runs/{parts[0][1]['run_id']}/result").json()
    assert {k: result[k] for k in ("scene", "layout", "critique", "rationale")} == {
        k: values[k] for k in ("scene", "layout", "critique", "rationale")
    }
    assert (result["total"], result["budget"]) == (806, 1200) and "€806, within the €1,200 budget" in result["rationale"]
    assert client.get(f"{url}/runs/nope/result").status_code == 404
    assert client.get(paused).status_code == 409

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
    result = client.get(f"{url}/runs/{parts[0][1]['run_id']}/result").json()
    assert (result["rationale"], result["layout_diff"]) == (chat[-1]["output"]["rationale"], values["layout_diff"])

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


def test_catalog_and_upload(client: TestClient) -> None:
    item = fixture("scene")["items"][0]["item"]
    assert client.get(f"/catalog/items/{item['id']}").json() == as_sent(CatalogItem, item)
    assert client.get("/catalog/items/nope").status_code == 404
    assert client.post("/uploads", files={"file": ("room.jpg", b"jpeg", "image/jpeg")}).json()["key"].endswith(".jpg")
    assert client.post("/uploads", files={"file": ("notes.txt", b"text", "text/plain")}).status_code == 415
    too_big = b"0" * (MAX_UPLOAD_BYTES + 1)
    assert client.post("/uploads", files={"file": ("room.jpg", too_big, "image/jpeg")}).status_code == 413


PHOTO = Path(__file__).parents[2] / "fixtures" / "small-bedroom" / "photo-1.jpg"


def test_uploaded_photo_is_served_back_without_object_storage(client: TestClient, tmp_path: Path) -> None:
    key = client.post("/uploads", files={"file": ("Room.JPG", PHOTO.read_bytes(), "image/jpeg")}).json()["key"]
    assert key.startswith("uploads/") and key.endswith(".jpg")
    assert (tmp_path / key).read_bytes() == PHOTO.read_bytes()
    response = client.get(f"/uploads/{key}")
    assert response.status_code == 200
    assert (response.content, response.headers["content-type"]) == (PHOTO.read_bytes(), "image/jpeg")

    heic = io.BytesIO()
    pillow_heif.from_pillow(Image.open(PHOTO)).save(heic, quality=50)
    key = client.post("/uploads", files={"file": ("IMG_0001.HEIC", heic.getvalue(), "image/heic")}).json()["key"]
    assert key.endswith(".jpg")  # as object storage stores it
    assert Image.open(io.BytesIO(client.get(f"/uploads/{key}").content)).format == "JPEG"
    key = client.post("/uploads", files={"file": ("blob", b"png", "image/png")}).json()["key"]  # no extension: the type's
    assert key.endswith(".png") and client.get(f"/uploads/{key}").content == b"png"


def test_fixture_photos_are_served_and_other_keys_are_not(client: TestClient) -> None:
    response = client.get("/uploads/fixtures/small-bedroom/photo-1.jpg")  # the stub runs' photo keys
    assert (response.status_code, response.content) == (200, PHOTO.read_bytes())
    for key in (
        "uploads/nope.jpg",  # not uploaded
        "fixtures/small-bedroom/room_spec.json",  # not an image
        "backend/pyproject.toml",
        "renders/x.png",  # not a photo's directory
        "uploads/%2e%2e/%2e%2e/fixtures/small-bedroom/photo-1.jpg",  # out of its directory (httpx would collapse a plain ..)
        "uploads/%00.jpg",
    ):
        assert client.get(f"/uploads/{key}").status_code == 404, key
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    assert client.post("/uploads", files={"file": ("x.svg", svg, "image/svg+xml")}).status_code == 415  # active content
    assert client.post("/uploads", files={"file": ("x.txt", b"png", "image/png")}).status_code == 415


@pytest.mark.parametrize(
    "key",
    [
        "uploads/../../fixtures/small-bedroom/photo-1.jpg",
        "uploads/../x.jpg",
        "fixtures/../backend/x.jpg",
        "fixtures//etc/passwd.jpg",
        "uploads//etc/x.jpg",
        "uploads/x.svg",
        "uploads/x\0.jpg",
        "renders/x.png",
    ],
)
def test_local_path_rejects_keys_out_of_photo_directories(key: str) -> None:
    assert local_path(key) is None


def test_uploaded_photo_redirects_to_a_signed_url_with_object_storage(client: TestClient) -> None:
    storage = Mock()
    storage.put.side_effect = lambda key, data, content_type: key
    storage.url.side_effect = lambda key: f"https://storage.example/{key}?X-Amz-Signature=s"
    app.state.storage = storage  # the client's app started without one; the next client's starts again from the env
    key = client.post("/uploads", files={"file": ("room.jpg", b"jpeg", "image/jpeg")}).json()["key"]
    response = client.get(f"/uploads/{key}", follow_redirects=False)
    assert (response.status_code, response.headers["location"]) == (307, f"https://storage.example/{key}?X-Amz-Signature=s")
    assert client.get("/uploads/uploads/x.svg", follow_redirects=False).status_code == 404  # checked before the redirect
    assert client.get("/uploads/fixtures/small-bedroom/photo-1.jpg").content == PHOTO.read_bytes()  # fixtures are not in the bucket


def test_exported_openapi_is_current() -> None:
    assert OUT.read_text() == render(), "run `make gen`"


def test_every_node_exists() -> None:
    assert set(build_graph().get_graph().nodes) - {"__start__", "__end__"} == set(NodeName.__args__)
