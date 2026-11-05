"""Write each contract's JSON Schema to contracts/schemas/<name>.json: `uv run python -m app.schemas.export` (`make gen`)."""

import json
from pathlib import Path

from pydantic import TypeAdapter

from app.schemas import CONTRACTS

OUT = Path(__file__).resolve().parents[3] / "contracts" / "schemas"


def render() -> dict[str, str]:
    return {f"{name}.json": json.dumps({"title": name, **TypeAdapter(t).json_schema()}, indent=2) + "\n" for name, t in CONTRACTS.items()}


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for stale in OUT.glob("*.json"):
        stale.unlink()
    for name, text in render().items():
        (OUT / name).write_text(text)
