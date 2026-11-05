"""The Designer: the brief and the confirmed room in, a DesignBrief (zones, palette, the objects to add) out.

The model plans the design; code then makes sure that every must-have of the brief is in it and that it does not overfill the room,
I-Design's main failure: objects other than the must-haves are dropped until the objects fit the free floor area.
"""

import os
import re
from functools import cache
from pathlib import Path
from typing import Any

from app import llm
from app.catalog.loader import load_catalog
from app.graph.state import RunState
from app.graph.stub import ask, load, stub_node
from app.schemas import Brief, DesignBrief, RoomSpec, coords
from app.schemas.design import DesignObject

PROMPT = (Path(__file__).resolve().parents[2] / "prompts" / "designer" / "design.md").read_text()
MAX_FILL = 0.4  # the share of the free floor area the objects' footprints may cover (the fixture designs cover up to 0.35)
AREA_PER_OBJECT = 1.5  # m2 of free floor area per object
FLAT = {"rug"}  # categories that lie on the floor without taking it up


def limits(room: RoomSpec) -> tuple[float, float, int]:
    """The room's free floor area (m2, kept furniture excluded), the objects' maximum total footprint and maximum count."""
    dims = room.dimensions
    free = dims.width * dims.length - sum(k.size.width * k.size.depth for k in room.kept_furniture)
    return free, MAX_FILL * free, max(1, int(free / AREA_PER_OBJECT))


def footprint(objects: list[DesignObject]) -> float:
    return sum(o.size.width * o.size.depth * o.quantity for o in objects if o.category not in FLAT)


def prompt(brief: Brief, room: RoomSpec) -> str:
    free, max_footprint, max_count = limits(room)
    return PROMPT.format(
        coords=coords.__doc__,
        categories=", ".join(categories()),
        free_area=free,
        max_footprint=max_footprint,
        max_count=max_count,
        room=room.model_dump_json(),
        brief=brief.model_dump_json(),
    )


@cache
def categories() -> list[str]:
    return sorted({i.category for i in load_catalog().values()})


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


@cache
def category_of(name: str) -> str:
    """The catalog category a name ends with ("desk chair": chair, "bookshelf": shelf, "dining table for six": table), the
    longest when several end on the same word ("armchair": armchair), "other" when it names none."""
    words = _words(name)

    def end(category: str) -> int:  # the last word of the name that ends the category, -1 if none
        *head, last = category.split("_")
        return max((i for i in range(len(head), len(words)) if words[i].endswith(last) and words[i - len(head) : i] == head), default=-1)

    best = max(categories(), key=lambda c: (end(c), len(c)))
    return best if end(best) >= 0 else "other"


def covers(obj: DesignObject, must_have: str) -> bool:
    """Whether the object is the must-have: its name has all the must-have's words and it is of the must-have's category (a
    "desk lamp" is no "desk")."""
    return set(_words(must_have)) <= set(_words(obj.name)) and category_of(must_have) in (obj.category, "other")


def _must_object(must_have: str, brief: Brief, ids: set[str]) -> DesignObject:
    """An object for a must-have the model left out: of the must-have's category, with the size of that category's median catalog
    item (of the whole catalog's for "other")."""
    catalog = list(load_catalog().values())
    category = category_of(must_have)
    items = sorted([i for i in catalog if i.category == category] or catalog, key=lambda i: i.size.width * i.size.depth)
    id_ = base = "_".join(_words(must_have)) or "object"
    n = 1
    while id_ in ids:
        n += 1
        id_ = f"{base}_{n}"
    style = brief.styles[0] if brief.styles else ""
    return DesignObject(
        id=id_, name=must_have, category=category, style=style, material="", size=items[len(items) // 2].size, quantity=1, priority="must"
    )


def add_must_haves(design: DesignBrief, brief: Brief) -> DesignBrief:
    """The design with every must-have of the brief as a must object: a nice object that is one becomes must, a missing one is added."""
    objects = list(design.objects)
    for must_have in brief.must_haves:
        matches = [i for i, o in enumerate(objects) if covers(o, must_have)]
        if not matches:
            objects.append(_must_object(must_have, brief, {o.id for o in objects}))
        elif all(objects[i].priority == "nice" for i in matches):
            objects[matches[0]] = objects[matches[0]].model_copy(update={"priority": "must"})
    return design.model_copy(update={"objects": objects})


def fit(design: DesignBrief, brief: Brief, room: RoomSpec) -> DesignBrief:
    """The design without the objects that overfill the room, one unit at a time: the nice ones first, then the ones the model made
    must that are no must-have of the brief, the least important (the last) first. The brief's must-haves always stay."""
    _, max_footprint, max_count = limits(room)
    objects = list(design.objects)
    while sum(o.quantity for o in objects) > max_count or footprint(objects) > max_footprint:
        optional = [i for i, o in enumerate(objects) if not any(covers(o, m) for m in brief.must_haves)]
        if not optional:  # the must-haves alone overfill the room: later steps report it
            break
        i = max(optional, key=lambda i: (objects[i].priority == "nice", i))
        if objects[i].quantity > 1:
            objects[i] = objects[i].model_copy(update={"quantity": objects[i].quantity - 1})
        else:
            del objects[i]
    return design.model_copy(update={"objects": objects})


def plan(brief: Brief, room: RoomSpec) -> tuple[DesignBrief, llm.Usage]:
    """The model's design for the brief and room, with every must-have and fit to the room, and the usage of its calls."""
    design, usage = llm.ask_structured(DesignBrief, prompt(brief, room), role="design")
    return fit(add_must_haves(design, brief), brief, room), usage


@stub_node
def design(state: RunState) -> dict[str, Any]:
    if not os.environ.get("OPENROUTER_API_KEY"):  # the stub graph (`make dev-stub`, the graph and API tests): the fixture's design
        return {"design_brief": ask(DesignBrief, load("design_brief", DesignBrief)), "round": 1}
    design_brief, usage = plan(Brief.model_validate(state["brief"]), state["room_spec"])  # a graph input may be plain JSON
    return {"design_brief": design_brief, "round": 1, **usage}
