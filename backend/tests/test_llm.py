"""The LLM gateway, offline: the fake model stands in for get_llm(role)."""

from collections.abc import Callable

import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from app import llm
from app.graph.stub import load
from app.llm.fake import CALL_USAGE, FakeLLM, reply
from app.schemas import RoomSpec

ROOM = load("room_spec", RoomSpec)


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeLLM]:
    def install(*replies: str | AIMessage | Exception) -> FakeLLM:
        fake = FakeLLM(*replies)
        monkeypatch.setattr(llm, "get_llm", lambda role: fake)
        return fake

    return install


def test_valid_reply_and_its_cost(fake_llm: Callable[..., FakeLLM]) -> None:
    fake = fake_llm(ROOM.model_dump_json())
    room, usage = llm.ask_structured(RoomSpec, "Read the room", role="analyze_room")
    assert (room, usage, fake.calls) == (ROOM, CALL_USAGE, 1)


def test_invalid_reply_is_retried_with_a_repair_prompt(fake_llm: Callable[..., FakeLLM]) -> None:
    fake = fake_llm('{"walls": "none"}', ROOM.model_dump_json())
    room, usage = llm.ask_structured(RoomSpec, "Read the room", role="analyze_room")
    assert room == ROOM
    assert usage == llm.add_usage(CALL_USAGE, CALL_USAGE)  # both calls are paid for
    first, retry = fake.prompts
    assert retry[:1] == first and "Your previous reply was not valid" in str(retry[1].content)


def test_a_second_invalid_reply_raises_the_parse_error(fake_llm: Callable[..., FakeLLM]) -> None:
    fake = fake_llm("not json", "still not json")
    with pytest.raises(OutputParserException):
        llm.ask_structured(RoomSpec, "Read the room", role="analyze_room")
    assert fake.calls == 2


def test_a_reply_without_a_tool_call_is_retried(fake_llm: Callable[..., FakeLLM]) -> None:
    fake = fake_llm(reply("I cannot see a room"), reply("Still no room"))
    with pytest.raises(ValueError, match="holds no result"):
        llm.ask_structured(RoomSpec, "Read the room", role="analyze_room")
    assert fake.calls == 2


def test_a_reply_cut_off_at_max_tokens_fails_without_a_retry(fake_llm: Callable[..., FakeLLM]) -> None:
    fake = fake_llm(reply('{"walls": [', finish_reason="length"))
    with pytest.raises(llm.TruncatedReply):
        llm.ask_structured(RoomSpec, "Read the room", role="analyze_room")
    assert fake.calls == 1


def test_images_go_with_the_prompt(fake_llm: Callable[..., FakeLLM]) -> None:
    fake = fake_llm(ROOM.model_dump_json())
    llm.ask_structured(RoomSpec, "Read the room", role="analyze_room", images=["data:image/jpeg;base64,AAAA"])
    assert fake.prompts[0][0].content == [
        {"type": "text", "text": "Read the room"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}},
    ]


def test_a_reply_without_cost_costs_nothing() -> None:
    message = reply()
    message.response_metadata = {}
    assert llm.call_usage(message) == {**CALL_USAGE, "cost": 0.0}


def test_get_llm_is_a_cached_openrouter_model_per_role(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    llm.get_llm.cache_clear()
    model = llm.get_llm("design")
    assert isinstance(model, ChatOpenAI) and model is llm.get_llm("design") and model is not llm.get_llm("critic")
    role = llm.ROLES["design"]
    assert (model.model_name, model.max_tokens, model.request_timeout) == (role.model, role.max_tokens, role.timeout)
    assert model.openai_api_base == "https://openrouter.ai/api/v1"
    llm.get_llm.cache_clear()
