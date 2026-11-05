"""Write the API's OpenAPI schema to contracts/openapi.json: `uv run python -m app.api.export` (`make gen`)."""

import json
from pathlib import Path

from app.main import app

OUT = Path(__file__).resolve().parents[3] / "contracts" / "openapi.json"


def render() -> str:
    return json.dumps(app.openapi(), indent=2) + "\n"


if __name__ == "__main__":
    OUT.write_text(render())
