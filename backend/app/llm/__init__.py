"""The LLM gateway: every model call goes through this module (ported from CoA's react_agent/tools.py).

get_llm(role) is a role's model on OpenRouter (its recorded replies with LLM_RECORDINGS: recorded.py). ask_structured asks it for a
schema's result and returns the result with the call's usage, which the node adds to its state update (RunState's reducers sum cost
and tokens). Tests put a FakeLLM (fake.py) in get_llm's place.
"""

import os
from collections.abc import Sequence
from functools import cache
from typing import Any, Literal, NamedTuple, TypedDict, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.llm import recorded

Role = Literal["analyze_room", "design", "architect", "critic", "chat_edit"]  # the nodes that call a model


class RoleModel(NamedTuple):
    model: str  # an OpenRouter model id
    max_tokens: int  # per call, reasoning included: a guard against a runaway call
    timeout: float  # seconds per request


ROLES: dict[Role, RoleModel] = {
    "analyze_room": RoleModel("openai/gpt-6.1-sol", 16_000, 180),  # reads the photos
    "design": RoleModel("openai/gpt-5-mini", 8_000, 90),
    "architect": RoleModel("openai/gpt-6.1-sol", 16_000, 180),
    "critic": RoleModel("openai/gpt-6.1-sol", 16_000, 180),  # reads the renders
    "chat_edit": RoleModel("openai/gpt-5-mini", 8_000, 90),
}

REPAIR_PROMPT = "Your previous reply was not valid:\n{error}\n\nReply again with the whole result, fixed."


class Usage(TypedDict):
    """What model calls used; the keys are RunState's usage keys."""

    cost: float  # USD, as OpenRouter charged it
    input_tokens: int
    output_tokens: int


class TruncatedReply(Exception):
    """The reply hit max_tokens (finish_reason "length"): it is cut off, so the call fails."""


@cache
def get_llm(role: Role) -> BaseChatModel:
    config = ROLES[role]
    settings: dict[str, Any] = {
        "model": config.model,
        "base_url": "https://openrouter.ai/api/v1",
        "max_tokens": config.max_tokens,  # an alias of max_completion_tokens
        "timeout": config.timeout,
        # a streamed reply carries no OpenRouter cost; LangGraph's "messages" stream still gets the whole reply
        "disable_streaming": True,
    }
    if recorded.directory():  # recorded calls: replaying needs no key; with one, the calls not recorded yet are made and recorded
        return recorded.RecordedChatOpenAI(role=role, api_key=os.environ.get("OPENROUTER_API_KEY") or "replay", **settings)  # type: ignore[arg-type]  # a str is accepted and kept as a SecretStr
    return ChatOpenAI(api_key=os.environ["OPENROUTER_API_KEY"], **settings)  # type: ignore[arg-type]


def call_usage(message: AIMessage) -> Usage:
    """What one model call used: its tokens, and the cost OpenRouter charged for it (0 when the provider does not say)."""
    tokens: dict[str, Any] = dict(message.usage_metadata or {})
    cost = (message.response_metadata.get("token_usage") or {}).get("cost") or 0.0
    return {"cost": cost, "input_tokens": tokens.get("input_tokens", 0), "output_tokens": tokens.get("output_tokens", 0)}


def add_usage(a: Usage, b: Usage) -> Usage:
    """The usage of two calls together."""
    return {
        "cost": a["cost"] + b["cost"],
        "input_tokens": a["input_tokens"] + b["input_tokens"],
        "output_tokens": a["output_tokens"] + b["output_tokens"],
    }


def user_message(text: str, images: Sequence[str] = ()) -> HumanMessage:
    """A prompt, with images given as URLs (an https URL, or a data: URL of the image's base64)."""
    if not images:
        return HumanMessage(text)
    return HumanMessage([{"type": "text", "text": text}, *({"type": "image_url", "image_url": {"url": url}} for url in images)])


def ask_structured[T: BaseModel](schema: type[T], prompt: str, *, role: Role, images: Sequence[str] = ()) -> tuple[T, Usage]:
    """Ask `role`'s model for a `schema` result; returns it with the usage of the calls.

    An invalid reply is retried once, with a prompt saying what was wrong; a second one raises its parse error. A reply cut off at
    max_tokens raises TruncatedReply.
    """
    # function calling, not json_schema: ChatOpenAI raises json_schema's validation errors without the reply, so its usage is lost
    llm = get_llm(role).with_structured_output(schema, method="function_calling", include_raw=True)
    messages: list[BaseMessage] = [user_message(prompt, images)]
    usage: Usage = {"cost": 0.0, "input_tokens": 0, "output_tokens": 0}
    for _ in range(2):
        out = cast(dict[str, Any], llm.invoke(messages))
        raw: AIMessage = out["raw"]
        usage = add_usage(usage, call_usage(raw))
        if raw.response_metadata.get("finish_reason") == "length":
            raise TruncatedReply(f"the {role} model's reply hit max_tokens ({ROLES[role].max_tokens})")
        if out["parsed"] is not None:
            return cast(T, out["parsed"]), usage
        error: Exception = out["parsing_error"] or ValueError("the reply holds no result")
        messages.append(HumanMessage(REPAIR_PROMPT.format(error=error)))
    raise error
