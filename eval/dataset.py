"""The eval dataset: one `eval/data/<case>/case.json` per case, see eval/data/README.md.

Run from backend/ (eval/ shares its environment): `PYTHONPATH=. uv run python ../eval/dataset.py` validates every case and prints a summary.
"""

import json
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import Field, JsonValue, field_validator

from app.schemas import RoomSpec
from app.schemas.run import NewDesign

REPO = Path(__file__).resolve().parents[1]
DATA = Path(__file__).resolve().parent / "data"

# I-Design's four brief categories
Category = Literal["functionality", "layout", "color_scheme", "atmosphere"]


class Case(NewDesign):
    """The run input (photos as paths from the repo root, typed dimensions, brief), the hand-labeled room and what a correct run does.

    `room_spec` and `brief` may be a path from the repo root to a JSON file instead, to reuse the fixtures.
    """

    room_spec: RoomSpec = Field(description="The room as a person labeled it from the photos")
    category: Category = Field(description="What the brief mainly asks for")
    expected: str | None = Field(None, description="Hard cases only: what a correct run does instead of a plain design")
    photos_match_room: bool = Field(
        True, description="False when the photos show another room than `room_spec`: photo-analysis scoring must skip the case"
    )

    @field_validator("room_spec", "brief", mode="before")
    @classmethod
    def _load_path(cls, value: JsonValue) -> JsonValue:
        return json.loads((REPO / value).read_text()) if isinstance(value, str) else value

    @field_validator("photo_keys")
    @classmethod
    def _photos_exist(cls, keys: list[str]) -> list[str]:
        missing = [k for k in keys if not (REPO / k).is_file()]
        if missing:
            raise ValueError(f"missing photos: {missing}")
        return keys


def load_cases(data: Path = DATA) -> dict[str, Case]:
    """Every case by name (its folder), validated; raises on the first invalid one."""
    return {p.parent.name: Case.model_validate_json(p.read_bytes()) for p in sorted(data.glob("*/case.json"))}


if __name__ == "__main__":
    cases = load_cases()
    print(f"{len(cases)} cases, {sum(c.expected is not None for c in cases.values())} hard")
    for category, n in sorted(Counter(c.category for c in cases.values()).items()):
        print(f"  {category}: {n}")
