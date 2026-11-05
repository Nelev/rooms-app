from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    """Base for every schema: unknown fields are errors, so a typo in LLM or client JSON is not silently dropped."""

    model_config = ConfigDict(extra="forbid")
