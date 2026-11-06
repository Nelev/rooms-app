"""Recorded model I/O, for the E2E suite (I-01): with LLM_RECORDINGS set (a directory), get_llm's models and the catalog's embeddings
answer from recordings there, so the real graph runs offline and deterministically.

The nodes run their real code (stub.live is true); only what goes over the network is replayed. With OPENROUTER_API_KEY a call that
has no recording yet is made and recorded (record mode, one call at a time, refused once the recorded calls cost LLM_RECORD_MAX_COST);
without it, a call without a recording raises MissingRecording (replay mode, which never calls out). A chat call's recording is
<role>-<hash>.json, its reply as LangChain's message dict; the hash covers the model, the messages sent (images included) and the
bound tools. Embeddings are kept in embeddings.json by text hash, as int8 (cosine similarity, what the store ranks by, ignores scale):
record mode returns the same rounded vectors it stores, so a replayed search ranks as the recorded one did. LLM_REPLAY_DELAY (seconds)
paces each replayed chat reply, so a run lasts long enough for the E2E suite to reload the page while it runs.
"""

import base64
import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
from langchain_core.messages import BaseMessage, message_to_dict, messages_from_dict
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables.config import run_in_executor
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

LOCK = threading.Lock()  # one recording at a time: identical parallel calls (the Analyst's readings) are paid for once
EMBEDDINGS = "embeddings.json"


class MissingRecording(Exception):
    """Replay mode met a call that was never recorded: record it again (`make e2e-record`)."""


def directory() -> Path | None:
    return Path(path) if (path := os.environ.get("LLM_RECORDINGS")) else None


def recording() -> bool:
    """Whether calls missing from the recordings are made and recorded (a key is set), rather than refused."""
    return bool(os.environ.get("OPENROUTER_API_KEY"))


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]


def recorded_cost(folder: Path) -> float:
    """USD that the recorded chat calls cost when they were recorded."""
    total = 0.0
    for file in folder.glob(f"*-{'?' * 16}.json"):  # <role>-<hash>.json
        metadata = json.loads(file.read_text())["data"].get("response_metadata", {})
        total += (metadata.get("token_usage") or {}).get("cost") or 0.0
    return total


def _record_allowed(folder: Path) -> None:
    if not recording():
        raise MissingRecording(f"no recording in {folder} and no OPENROUTER_API_KEY to record it: record the E2E suite again")
    if (spent := recorded_cost(folder)) >= (cap := float(os.environ.get("LLM_RECORD_MAX_COST", "0.4"))):
        raise MissingRecording(f"the recordings cost {spent:.3f} USD, at the LLM_RECORD_MAX_COST cap of {cap} USD: not recording more")


class RecordedChatOpenAI(ChatOpenAI):
    """ChatOpenAI that answers from LLM_RECORDINGS (see the module); tools and structured output work as on ChatOpenAI."""

    role: str = ""

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        folder = directory()
        assert folder, "LLM_RECORDINGS is not set"
        sent = [
            {
                "type": m.type,
                "content": m.content,
                "tool_calls": getattr(m, "tool_calls", []),
                "tool_call_id": getattr(m, "tool_call_id", None),
            }
            for m in messages
        ]
        file = folder / f"{self.role}-{_hash({'model': self.model_name, 'messages': sent, 'stop': stop, **kwargs})}.json"
        with LOCK:
            replayed = file.exists()
            if not replayed:
                _record_allowed(folder)
                result = super()._generate(messages, stop, run_manager, **kwargs)
                reply = result.generations[0]
                # the reply's metadata as BaseChatModel completes it after _generate: OpenRouter's cost and the finish reason
                metadata = {**(result.llm_output or {}), **(reply.generation_info or {}), **reply.message.response_metadata}
                reply.message.response_metadata = metadata
                folder.mkdir(parents=True, exist_ok=True)
                file.write_text(json.dumps(message_to_dict(reply.message), indent=1, default=str) + "\n")
        if replayed:
            time.sleep(float(os.environ.get("LLM_REPLAY_DELAY", 0)))
        return ChatResult(generations=[ChatGeneration(message=messages_from_dict([json.loads(file.read_text())])[0])])

    async def _agenerate(
        self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        return await run_in_executor(None, self._generate, messages, stop, None, **kwargs)


class RecordedEmbeddings(OpenAIEmbeddings):
    """OpenAIEmbeddings that answer from LLM_RECORDINGS/embeddings.json (see the module)."""

    def embed_documents(self, texts: list[str], chunk_size: int | None = None, **kwargs: Any) -> list[list[float]]:
        folder = directory()
        assert folder, "LLM_RECORDINGS is not set"
        file, keys = folder / EMBEDDINGS, [_hash(t) for t in texts]
        with LOCK:
            stored: dict[str, str] = json.loads(file.read_text()) if file.exists() else {}
            if missing := [t for t, k in zip(texts, keys, strict=True) if k not in stored]:
                _record_allowed(folder)
                for text, vector in zip(missing, super().embed_documents(missing, chunk_size, **kwargs), strict=True):
                    v = np.asarray(vector)
                    stored[_hash(text)] = base64.b64encode(np.round(v * 127 / np.abs(v).max()).astype(np.int8).tobytes()).decode()
                folder.mkdir(parents=True, exist_ok=True)
                file.write_text(json.dumps(stored, indent=0, sort_keys=True) + "\n")
        return [(np.frombuffer(base64.b64decode(stored[k]), np.int8) / 127).tolist() for k in keys]

    def embed_query(self, text: str, **kwargs: Any) -> list[float]:
        return self.embed_documents([text])[0]

    async def aembed_documents(self, texts: list[str], chunk_size: int | None = None, **kwargs: Any) -> list[list[float]]:
        return await run_in_executor(None, self.embed_documents, texts, chunk_size, **kwargs)

    async def aembed_query(self, text: str, **kwargs: Any) -> list[float]:
        return (await self.aembed_documents([text]))[0]
