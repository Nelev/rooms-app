"""Tag each run for LangSmith: one trace per run, its nodes nested in it, with the model calls' tokens and cost.

LangChain traces to LangSmith on its own when LANGSMITH_TRACING=true and LANGSMITH_API_KEY are set (LANGSMITH_PROJECT
picks the project). The eval runner reads cost and latency from these traces.
"""

from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.outputs import LLMResult
from langchain_core.runnables import RunnableConfig

from app.api.models import RunConfigurable


class ProviderCost(BaseCallbackHandler):
    """Give the traced model call the cost the provider reports (OpenRouter's `token_usage.cost`) as `total_cost`.

    The LangSmith tracer copies a model call's usage metadata (its tokens) to its run's `usage_metadata`, where LangSmith
    also takes a `total_cost` and sums it up the trace to each node and to the run
    (https://docs.langchain.com/langsmith/cost-tracking). This swaps, in the callbacks' copy of the result only, each
    reply for a copy with the cost added: the reply the graph gets back, and so its state and the API, keeps the schema's
    keys. Inline, before the tracer reads it.

    A reply without `token_usage.cost` (e.g. streamed: ChatOpenAI keeps only the tokens of the final usage chunk) gets no
    `total_cost`; LangSmith then prices it from its model price table, if it has the model.
    """

    run_inline = True

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        for gens in response.generations:
            for i, gen in enumerate(gens):
                message = getattr(gen, "message", None)
                if not isinstance(message, AIMessage) or message.usage_metadata is None:
                    continue
                if (cost := (message.response_metadata.get("token_usage") or {}).get("cost")) is not None:
                    usage = {**message.usage_metadata, "total_cost": cost}
                    gens[i] = gen.model_copy(update={"message": message.model_copy(update={"usage_metadata": usage})})


def traced(config: RunnableConfig, run_id: UUID) -> RunnableConfig:
    """`config` tagged for its trace: the thread (the user's design project) it runs on and the variant flags.

    `run_id` becomes the trace's root run ID, so the API's run ID finds its trace."""
    configurable = config.get("configurable", {})
    flags = {name: bool(configurable.get(name, False)) for name in RunConfigurable.model_fields}
    metadata = {"thread_id": configurable["thread_id"], **flags}
    return {
        **config,
        "run_id": run_id,
        "tags": [*config.get("tags", []), *(name for name, on in flags.items() if on)],
        "metadata": {**config.get("metadata", {}), **metadata},
        "callbacks": [ProviderCost(), *(config.get("callbacks") or [])],  # type: ignore[misc]
    }
