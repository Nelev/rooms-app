"""The single-LLM baseline (LayoutGPT-style): one model call places the furniture directly, as absolute positions, from the room, the
brief and a catalog subset. It returns the same `Layout` as the agent, so every metric applies unchanged.

Run from backend/ (eval/ shares its environment), with OPENROUTER_API_KEY set:
`PYTHONPATH=.:../eval uv run python -m baselines.single_llm [OUT_DIR]` writes `<OUT_DIR>/<case>.json` (the layout and the call's usage,
or the error) for every case of the dataset; OUT_DIR defaults to eval/results/single_llm.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

from dataset import Case, load_cases

from app import llm
from app.catalog.loader import load_catalog
from app.schemas import Brief, CatalogItem, Layout, RoomSpec, coords

PER_CATEGORY = 6  # catalog items offered per category: the brief's styles first, then the cheapest
OUT = Path(__file__).resolve().parents[1] / "results" / "single_llm"

PROMPT = """You are an interior designer. Furnish the room below for the brief: choose items from the catalog and place each one, \
in one answer.

Coordinate convention (all positions and sizes follow it):
{coords}
Rules:
- One placement per item; `node_id` is a short unique name (e.g. "bed", "nightstand_2"), `item_id` is the catalog id and `size` is \
the item's catalog size.
- Keep every item inside the room, without overlapping another item or the kept furniture, and keep doors and windows clear.
- Do not place the kept furniture again: it stays where it is. Leave out what the brief asks to remove.
- Include every must-have, stay within the budget (EUR, the sum of the chosen items' prices) and follow the styles.

Room (RoomSpec JSON):
{room}

Brief (JSON):
{brief}

Catalog (one JSON item per line):
{catalog}
"""


def catalog_subset(brief: Brief) -> list[CatalogItem]:
    """Up to PER_CATEGORY items per category: those sharing a style with the brief first, then the cheapest."""
    by_category: dict[str, list[CatalogItem]] = defaultdict(list)
    for item in load_catalog().values():
        by_category[item.category].append(item)
    styles = set(brief.styles)
    return [
        item
        for items in by_category.values()
        for item in sorted(items, key=lambda i: (not styles & set(i.style_tags), i.price))[:PER_CATEGORY]
    ]


def prompt(room: RoomSpec, brief: Brief) -> str:
    fields = {"id", "name", "category", "size", "price", "style_tags", "color"}
    catalog = "\n".join(item.model_dump_json(include=fields) for item in catalog_subset(brief))
    return PROMPT.format(coords=coords.__doc__, room=room.model_dump_json(), brief=brief.model_dump_json(), catalog=catalog)


def predict(case: Case) -> tuple[Layout, llm.Usage]:
    """The baseline's layout for a case, from its hand-labeled room (so only the layout is compared), and the call's usage."""
    return llm.ask_structured(Layout, prompt(case.room_spec, case.brief), role="architect")


def run(cases: dict[str, Case], out: Path) -> dict[str, Layout | Exception]:
    """Predict every case and write `<out>/<case>.json`; a failed case is recorded and the run goes on."""
    out.mkdir(parents=True, exist_ok=True)
    results: dict[str, Layout | Exception] = {}
    for name, case in cases.items():
        record: dict[str, object]
        try:
            layout, usage = predict(case)
        except Exception as error:  # a model failure (invalid twice, truncated, network) must not stop the run
            results[name] = error
            record = {"error": repr(error)}
        else:
            results[name] = layout
            record = {"layout": layout.model_dump(mode="json"), "usage": usage}
        (out / f"{name}.json").write_text(json.dumps(record, indent=2) + "\n")
    return results


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT
    llm.get_llm("architect")  # fail fast on a setup error (e.g. no OPENROUTER_API_KEY) instead of recording it for every case
    results = run(load_cases(), out)
    failed = [name for name, result in results.items() if isinstance(result, Exception)]
    print(f"{len(results) - len(failed)}/{len(results)} cases laid out in {out}" + (f"; failed: {failed}" if failed else ""))
