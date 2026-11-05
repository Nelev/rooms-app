"""The fake model (ported from CoA's tests/conftest.py): it stands in for get_llm(role) in tests and in the stub graph, offline."""

from collections.abc import Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.utils.function_calling import convert_to_openai_tool

from app.llm import Usage

CALL_USAGE: Usage = {"cost": 0.001, "input_tokens": 10, "output_tokens": 5}  # what every fake model call reports


def reply(content: str = "", finish_reason: str = "stop", **fields: Any) -> AIMessage:
    """A chat reply carrying the usage and the OpenRouter cost of CALL_USAGE, as ChatOpenAI returns it."""
    tokens = CALL_USAGE["input_tokens"] + CALL_USAGE["output_tokens"]
    return AIMessage(
        content,
        usage_metadata={"input_tokens": CALL_USAGE["input_tokens"], "output_tokens": CALL_USAGE["output_tokens"], "total_tokens": tokens},
        response_metadata={"token_usage": {"cost": CALL_USAGE["cost"]}, "finish_reason": finish_reason},
        **fields,
    )


class FakeLLM(BaseChatModel):
    """Returns the queued replies, one per call, and records the prompts.

    A string is the reply's text (in a structured call, its tool call's JSON arguments), a message is returned as it is,
    an exception is raised.
    """

    replies: list[str | AIMessage | Exception]
    prompts: list[list[BaseMessage]] = []
    disable_streaming: bool = True  # like get_llm's model

    def __init__(self, *replies: str | AIMessage | Exception) -> None:
        super().__init__(replies=list(replies))  # type: ignore[call-arg]  # a field of this model

    @property
    def calls(self) -> int:
        return len(self.prompts)

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        self.prompts.append(messages)
        response = self.replies.pop(0)
        if isinstance(response, Exception):  # a call that fails
            raise response
        if isinstance(response, str) and (tools := kwargs.get("tools")):  # a structured call: the text is its tool call's arguments
            call = {"id": "call_0", "type": "function", "function": {"name": tools[0]["function"]["name"], "arguments": response}}
            response = reply(additional_kwargs={"tool_calls": [call]})  # as ChatOpenAI reads it: parsed into tool_calls
        elif isinstance(response, str):
            response = reply(response)
        return ChatResult(generations=[ChatGeneration(message=response)])

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Runnable[LanguageModelInput, AIMessage]:
        """Like ChatOpenAI's: so with_structured_output and tool-calling nodes run as they do on the real model."""
        return self.bind(tools=[convert_to_openai_tool(tool) for tool in tools], **kwargs)
