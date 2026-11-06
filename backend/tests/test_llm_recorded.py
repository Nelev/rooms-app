"""Recorded model I/O (LLM_RECORDINGS, app/llm/recorded.py), offline: ChatOpenAI's and OpenAIEmbeddings' network calls are faked."""

import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app import llm
from app.catalog.embed import get_embeddings
from app.graph import stub
from app.graph.stub import load
from app.llm.fake import CALL_USAGE, FakeLLM
from app.llm.recorded import MissingRecording, recorded_cost
from app.schemas import RoomSpec
from app.schemas.room import Dimensions

ROOM = load("room_spec", RoomSpec)


@pytest.fixture
def recordings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Record mode (a key and LLM_RECORDINGS); the test drops the key to replay."""
    monkeypatch.setenv("LLM_RECORDINGS", str(tmp_path))
    monkeypatch.setenv("OPENROUTER_API_KEY", os.environ.get("OPENROUTER_API_KEY") or "test")  # the real one in a live test
    llm.get_llm.cache_clear()
    get_embeddings.cache_clear()
    yield tmp_path
    llm.get_llm.cache_clear()
    get_embeddings.cache_clear()


@pytest.fixture
def network(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeLLM]:
    """Fake what ChatOpenAI would get from OpenRouter: the queued replies, one per call."""

    def install(*replies: str) -> FakeLLM:
        fake = FakeLLM(*replies)

        def generate(self: ChatOpenAI, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
            """As ChatOpenAI returns it: the cost and the finish reason outside the message, which BaseChatModel merges in later."""
            reply = fake._generate(messages, stop, **kwargs).generations[0].message
            usage, reply.response_metadata = reply.response_metadata, {}
            generation = ChatGeneration(message=reply, generation_info={"finish_reason": usage["finish_reason"]})
            return ChatResult(generations=[generation], llm_output={"token_usage": usage["token_usage"]})

        monkeypatch.setattr(ChatOpenAI, "_generate", generate)
        return fake

    return install


def test_records_then_replays_offline(recordings: Path, network: Callable[..., FakeLLM], monkeypatch: pytest.MonkeyPatch) -> None:
    fake = network(ROOM.model_dump_json())
    assert llm.ask_structured(RoomSpec, "Read the room", role="analyze_room", images=["data:image/jpeg;base64,AA=="]) == (ROOM, CALL_USAGE)
    assert [p.name.split("-")[0] for p in recordings.iterdir()] == ["analyze_room"]
    assert llm.ask_structured(RoomSpec, "Read the room", role="analyze_room", images=["data:image/jpeg;base64,AA=="])[0] == ROOM
    assert fake.calls == 1  # recorded once

    monkeypatch.setenv("OPENROUTER_API_KEY", "")  # as docker compose passes an unset one
    llm.get_llm.cache_clear()
    assert llm.ask_structured(RoomSpec, "Read the room", role="analyze_room", images=["data:image/jpeg;base64,AA=="]) == (ROOM, CALL_USAGE)
    assert fake.calls == 1
    with pytest.raises(MissingRecording):  # another photo
        llm.ask_structured(RoomSpec, "Read the room", role="analyze_room", images=["data:image/jpeg;base64,AB=="])
    with pytest.raises(MissingRecording):  # another role, the same prompt
        llm.ask_structured(RoomSpec, "Read the room", role="design", images=["data:image/jpeg;base64,AA=="])


def test_record_mode_stops_at_the_cost_cap(recordings: Path, network: Callable[..., FakeLLM], monkeypatch: pytest.MonkeyPatch) -> None:
    fake = network(ROOM.model_dump_json(), ROOM.model_dump_json())
    llm.ask_structured(RoomSpec, "Read the room", role="analyze_room")
    monkeypatch.setenv("LLM_RECORD_MAX_COST", str(CALL_USAGE["cost"]))
    with pytest.raises(MissingRecording, match="cap"):
        llm.ask_structured(RoomSpec, "Read another room", role="analyze_room")
    assert fake.calls == 1


def test_tool_calls_replay(recordings: Path, network: Callable[..., FakeLLM], monkeypatch: pytest.MonkeyPatch) -> None:
    """What chat_edit does: a model with tools bound, its tool call replayed with the same id."""
    network('{"width": 3, "length": 4, "height": 2.5}')
    model = llm.get_llm("chat_edit").bind_tools([Dimensions])
    first = model.invoke("Make it bigger")
    monkeypatch.delenv("OPENROUTER_API_KEY")
    llm.get_llm.cache_clear()
    again = llm.get_llm("chat_edit").bind_tools([Dimensions]).invoke("Make it bigger")
    assert again.tool_calls == first.tool_calls and again.tool_calls[0]["args"] == {"width": 3, "length": 4, "height": 2.5}
    with pytest.raises(MissingRecording):  # other tools
        llm.get_llm("chat_edit").bind_tools([RoomSpec]).invoke("Make it bigger")


def test_embeddings_record_and_replay(recordings: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[list[str]] = []

    def embed(self: OpenAIEmbeddings, texts: list[str], chunk_size: Any = None, **kwargs: Any) -> list[list[float]]:
        sent.append(texts)
        return [[float(len(t)), 0.5, -1.0] for t in texts]

    monkeypatch.setattr(OpenAIEmbeddings, "embed_documents", embed)
    docs = get_embeddings().embed_documents(["bed", "oak desk"])
    assert docs == [[1.0, 21 / 127, -42 / 127], [1.0, 8 / 127, -16 / 127]]  # int8, scaled to the largest component
    assert get_embeddings().embed_query("bed") == docs[0] and sent == [["bed", "oak desk"]]  # only new texts are sent

    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    get_embeddings.cache_clear()
    assert get_embeddings().embed_documents(["oak desk", "bed"]) == docs[::-1]
    with pytest.raises(MissingRecording):
        get_embeddings().embed_query("sofa")


def test_nodes_run_live_on_recordings(monkeypatch: pytest.MonkeyPatch) -> None:
    assert not stub.live("design")
    monkeypatch.setenv("LLM_RECORDINGS", "/nowhere")
    assert stub.live("design")


@pytest.mark.live
def test_records_a_real_call_with_its_cost(recordings: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """One real call (the cheap design model), recorded with the cost OpenRouter charged, then replayed without the key."""
    prompt = "The room is 3 m wide, 4 m long and 2.5 m high."
    dimensions, usage = llm.ask_structured(Dimensions, prompt, role="design")
    assert usage["cost"] > 0 and recorded_cost(recordings) == pytest.approx(usage["cost"])
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    llm.get_llm.cache_clear()
    assert llm.ask_structured(Dimensions, prompt, role="design") == (dimensions, usage)
