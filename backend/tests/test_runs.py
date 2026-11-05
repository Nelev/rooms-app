"""The thread API over HTTP, in memory and on Postgres (TEST_DATABASE_URL, else skipped): a run streamed to its interrupt, resumed,
left and rejoined, refused a second concurrent run, cut off by a restart and continued, and a revert."""

import json
import os
import uuid
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from httpx import Response
from psycopg.conninfo import make_conninfo
from psycopg.sql import SQL, Identifier

from app import runs
from app.graph import stub
from app.graph.stub import fixture
from app.main import app
from app.schemas import Layout
from tests.test_api import as_sent, custom, design_input, one_round, replayed, stream, stub_cost

Part = tuple[str, Any]


@pytest.fixture(params=["memory", "postgres"])
def database(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[str | None]:
    """The DATABASE_URL the app starts with: none (in memory), or a schema of its own on TEST_DATABASE_URL."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "")  # the catalog store stays in memory: these tests need no catalog
    monkeypatch.setattr(stub, "PACE", 0.05)  # a resumed design run takes ~2 s: long enough to leave it, rejoin it and collide with it
    if request.param == "memory":
        monkeypatch.delenv("DATABASE_URL", raising=False)
        yield None
        return
    base = os.getenv("TEST_DATABASE_URL") or pytest.skip("TEST_DATABASE_URL is not set")
    schema = f"test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(SQL("CREATE SCHEMA {}").format(Identifier(schema)))
    dsn = make_conninfo(base, options=f"-csearch_path={schema}")
    monkeypatch.setenv("DATABASE_URL", dsn)
    yield dsn
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(SQL("DROP SCHEMA {} CASCADE").format(Identifier(schema)))


def parts_until(response: Response, stop: Callable[[Part], bool]) -> list[Part]:
    """The stream's parts up to the first that `stop` matches (all of them if none does)."""
    assert response.status_code == 200, response.read()
    parts: list[Part] = []
    event = None
    for line in response.iter_lines():
        if line.startswith("event: "):
            event = line.removeprefix("event: ")
        elif line.startswith("data: "):
            parts.append((str(event), json.loads(line.removeprefix("data: "))))
            if stop(parts[-1]):
                break
    return parts


def started(node: str) -> Callable[[Part], bool]:
    return lambda part: part[0] == "custom" and part[1]["node"] == node and part[1]["status"] == "started"


def test_stream_resume_rejoin_conflict_restart_and_revert(database: str | None) -> None:
    events = fixture("stream_events")
    with ExitStack() as stack:
        client = stack.enter_context(TestClient(app))
        thread_id = client.post("/threads", json={"metadata": {"title": "Bedroom"}}).json()["thread_id"]
        url = f"/threads/{thread_id}"

        # to the interrupt
        assert custom(stream(client, f"{url}/runs/stream", {"input": design_input()})) == events["first_run"]
        assert client.get(f"{url}/state").json()["status"] == "needs_input"

        # resume it, and leave the stream while the run goes on
        with client.stream("POST", f"{url}/runs/stream", json={"command": {"resume": fixture("room_spec")}}) as response:
            left = parts_until(response, started("design"))
        assert client.get(f"{url}/state").json()["status"] == "running"
        assert client.post(f"{url}/runs/stream", json={"input": fixture("chat")[0]["input"]}).status_code == 409
        assert client.post(f"{url}/runs/stream", json={"input": None}).status_code == 409

        # rejoin it: the same run, from its first part
        with client.stream("GET", f"{url}/runs/current/stream") as response:
            rejoined = parts_until(response, started("architect"))  # its longest step: the restart lands in it
        assert rejoined[: len(left)] == left and len(rejoined) > len(left)

        # a restart cuts it off: the runs are lost, the checkpoints kept
        if database:  # a real restart: the lifespan closes and opens Postgres again
            stack.close()
            client = stack.enter_context(TestClient(app))
        else:  # in memory the checkpoints would go too: lose only the runs, as the lifespan's shutdown does
            client.portal.call(runs.shutdown)  # type: ignore[union-attr]
        state = client.get(f"{url}/state").json()
        assert (state["status"], state["next"]) == ("error", ["architect"])
        assert client.get(f"{url}/runs/current/stream").status_code == 404

        # input null continues it from the last checkpoint: the cut-off node again, then the rest
        continued = custom(stream(client, f"{url}/runs/stream", {"input": None}))
        resumed = one_round(events["resumed_run"])
        assert replayed(continued) == replayed(resumed[resumed.index(continued[0]) :]) and started("architect")(("custom", continued[0]))
        state = client.get(f"{url}/state").json()
        assert (state["status"], state["next"]) == ("done", [])
        assert client.post(f"{url}/runs/stream", json={"input": None}).status_code == 409  # nothing left to continue
        designed = state["values"]["layout"]
        assert [i["node_id"] for i in state["values"]["scene"]["items"]] == [p["node_id"] for p in designed["placements"]]
        assert state["values"]["cost"] == pytest.approx(stub_cost(events["first_run"] + resumed))
        assert client.get("/threads").json()[0] | {"thread_id": thread_id, "status": "done"} == client.get("/threads").json()[0]

        # a chat edit, then revert to the design before it
        chat = fixture("chat")[0]
        stream(client, f"{url}/runs/stream", {"input": chat["input"]})
        assert client.get(f"{url}/state").json()["values"]["layout"] == as_sent(Layout, chat["output"]["layout"])
        history = client.get(f"{url}/history").json()
        before = next(h for h in history if not h["next"] and h["values"].get("layout") == designed)
        state = client.post(f"{url}/revert", json={"checkpoint_id": before["checkpoint_id"]}).json()
        assert (state["status"], state["values"]["layout"]) == ("done", designed)
        assert client.get(f"{url}/history").json()[0]["checkpoint_id"] == state["checkpoint_id"]  # a new checkpoint, the history kept


def test_finished_runs_are_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the newest MAX_FINISHED finished runs stay rejoinable; an active run is never dropped."""
    monkeypatch.setattr(runs, "MAX_FINISHED", 2)
    active = runs.Run()
    monkeypatch.setattr(runs, "RUNS", {"active": active, **{f"t{i}": runs.Run(done=True) for i in range(4)}})
    runs._evict_finished()
    assert runs.RUNS == {"active": active, "t2": runs.RUNS["t2"], "t3": runs.RUNS["t3"]}
