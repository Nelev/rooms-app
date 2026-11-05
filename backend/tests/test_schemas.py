from typing import get_args

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from app.schemas import CONTRACTS, RunInput
from app.schemas.export import OUT, render

# (contract, model) for each contract's model, or each member of an Annotated[A | B, Field(...)] union contract
CASES = [(n, m) for n, t in CONTRACTS.items() for m in ([t] if isinstance(t, type) else get_args(get_args(t)[0]))]


@pytest.mark.parametrize(("name", "model"), CASES, ids=lambda c: c if isinstance(c, str) else c.__name__)
def test_examples_round_trip(name: str, model: type[BaseModel]) -> None:
    adapter = TypeAdapter(CONTRACTS[name])  # through the union too, so a broken discriminator fails
    examples = model.model_json_schema()["examples"]
    assert examples
    for example in examples:
        assert adapter.dump_python(adapter.validate_python(example), mode="json", exclude_unset=True) == example


def test_exported_schemas_are_current() -> None:
    assert {p.name: p.read_text() for p in OUT.glob("*.json")} == render(), "run `make gen`"


@pytest.mark.parametrize(
    "data",
    [
        {
            "chat_message": "hi",
            "photo_keys": ["a.jpg"],
            "dimensions": {"width": 3, "length": 4, "height": 2.5},
            "brief": {"room_use": "office", "budget": 0},
        },
        {"chat_message": "hi", "photo_keys": ["a.jpg"]},
        {"chat_message": "hi", "brief": {"room_use": "office", "budget": 0}},
        {"chat_message": "hi", "photo_keys": []},
        {"photo_keys": [], "dimensions": {"width": 3, "length": 4, "height": 2.5}, "brief": {"room_use": "office", "budget": 0}},
        {"photo_keys": ["a.jpg"]},
        {"chat_mesage": "hi"},
        {},
    ],
)
def test_run_input_is_a_new_design_or_a_chat_message(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(RunInput).validate_python(data)
