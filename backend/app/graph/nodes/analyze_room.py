"""The Room Analyst: the vision model reads the room's walls and features from the photos into a RoomSpec.

The model goes wall by wall (A to D), with feature positions as fractions of the wall length, a confidence per estimate and null for
unknown. It reads the room RUNS times; a feature is kept when MIN_VOTES runs found it. The typed dimensions are the room's.
Without OPENROUTER_API_KEY the node replays its fixture, like the other stub nodes (the stub/offline switch), and logs a warning.
"""

import base64
import logging
import mimetypes
import os
import statistics
import time
from collections import Counter
from collections.abc import Iterable, Sequence
from functools import reduce
from pathlib import Path
from typing import Any, Literal, get_args

from botocore.exceptions import ClientError
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import get_executor_for_config
from langgraph.config import get_stream_writer
from pydantic import Field

from app import llm
from app.graph import stub
from app.graph.routing import flags
from app.graph.state import RunState
from app.graph.stub import ask, load, stub_node
from app.schemas import RoomSpec, coords
from app.schemas.base import Model
from app.schemas.coords import Fraction, Wall
from app.schemas.room import Dimensions, Feature, FeatureType, WallSpec
from app.storage import Storage, local_path

logger = logging.getLogger(__name__)

PROMPT = (Path(__file__).resolve().parents[2] / "prompts" / "analyst" / "room.md").read_text()
RUNS, MIN_VOTES = 3, 2
TOLERANCE = 0.5  # m along the wall: two features of a type on a wall closer than this are the same feature
# what an unknown size is assumed to be, per type: width, height (None: the ceiling's), sill height, in m
DEFAULT_SIZE: dict[FeatureType, tuple[float, float | None, float]] = {
    "door": (0.8, 2.1, 0),
    "window": (1.2, 1.2, 0.9),
    "radiator": (0.8, 0.6, 0.1),
    "outlet": (0.08, 0.08, 0.3),
    "built_in": (1.0, None, 0),
    "column": (0.4, None, 0),
    "other": (0.5, 0.5, 0),
}


class Estimate(Model):
    value: float | None = Field(description="null when unknown")
    confidence: Fraction


class SeenFeature(Model):
    type: FeatureType
    offset: Estimate = Field(description="Center as a fraction of the wall length from the wall's start corner (its right end)")
    width: Estimate = Field(description="m")
    height: Estimate = Field(description="m")
    sill_height: Estimate = Field(description="m from the floor to the feature's bottom edge; 0 for doors")
    swing: Literal["in", "out"] | None = Field(None, description="Doors only; null when unknown")
    hinge: Literal["left", "right"] | None = Field(None, description="Doors only, seen from inside the room; null when unknown")
    confidence: Fraction = Field(description="That the feature is there and of this type")


class WallReading(Model):
    wall: Wall
    color: str | None = Field(description="Hex color; null when unknown")
    features: list[SeenFeature]


class RoomReading(Model):
    """What the model reads from the photos, wall by wall."""

    walls: list[WallReading] = Field(description="Walls A, B, C and D, in this order")
    floor_material: str | None = Field(description="e.g. oak, tiles, carpet; null when unknown")
    notes: list[str] = Field(description="What could not be seen or is uncertain")


def wall_length(wall: Wall, dimensions: Dimensions) -> float:
    return dimensions.width if wall in "AC" else dimensions.length


def to_feature(seen: SeenFeature, wall: Wall, dimensions: Dimensions, warnings: list[str]) -> Feature:
    """A feature the model saw, its unknown estimates replaced by the type's default (and a warning); its confidence its least known one."""
    width, height, sill = DEFAULT_SIZE[seen.type]
    defaults = {"offset": 0.5, "width": width, "height": height or dimensions.height, "sill_height": sill}
    values: dict[str, float] = {}
    for name, default in defaults.items():
        estimate: Estimate = getattr(seen, name)
        values[name] = default if estimate.value is None else estimate.value
        if estimate.value is None:
            warnings.append(
                f"The {name.replace('_', ' ')} of the {seen.type.replace('_', ' ')} on wall {wall} is unknown: assumed {default}"
            )
    known = (e.confidence for e in (getattr(seen, name) for name in defaults) if e.value is not None)
    confidence = min(seen.confidence, *known)  # an assumed size is a warning, not doubt that the feature is there
    values["offset"] = min(max(values["offset"], 0), 1)
    door = {"swing": seen.swing, "hinge": seen.hinge} if seen.type == "door" else {}  # a model may give them to any feature
    return Feature.model_validate({**values, **door, "id": "", "type": seen.type, "wall": wall, "confidence": confidence})


def match(found: Sequence[Feature], labeled: Sequence[Feature], dimensions: Dimensions) -> list[tuple[Feature, Feature]]:
    """Pairs of the same feature: same type and wall, centers within TOLERANCE, the closest pairs first; each feature in one pair."""

    def distance(a: Feature, b: Feature) -> float:
        return abs(a.offset - b.offset) * wall_length(a.wall, dimensions)

    candidates = sorted(
        (distance(a, b), i, j) for i, a in enumerate(found) for j, b in enumerate(labeled) if (a.type, a.wall) == (b.type, b.wall)
    )
    pairs: list[tuple[Feature, Feature]] = []
    used_a: set[int] = set()
    used_b: set[int] = set()
    for d, i, j in candidates:
        if d <= TOLERANCE and i not in used_a and j not in used_b:
            pairs.append((found[i], labeled[j]))
            used_a.add(i)
            used_b.add(j)
    return pairs


def most_common[T](values: Iterable[T | None]) -> T | None:
    """The most common known value; None when every one is unknown."""
    known = Counter(v for v in values if v is not None)
    return known.most_common(1)[0][0] if known else None


def vote(runs: Sequence[list[Feature]], dimensions: Dimensions, min_votes: int) -> tuple[list[Feature], int]:
    """The features found in at least `min_votes` runs, each the median of its sightings, with ids by type (door_1, ...); and how many
    features were left out."""
    groups: list[list[Feature]] = []
    for features in runs:
        seeds = {id(a): b for a, b in match(features, [g[0] for g in groups], dimensions)}
        for feature in features:
            if (seed := seeds.get(id(feature))) is not None:
                next(g for g in groups if g[0] is seed).append(feature)
            else:
                groups.append([feature])
    kept, ids = [], Counter[str]()
    for group in (g for g in groups if len(g) >= min_votes):
        first = group[0]
        ids[first.type] += 1
        update: dict[str, Any] = {
            name: statistics.median(getattr(f, name) for f in group) for name in ("offset", "width", "height", "sill_height")
        }
        update |= {side: most_common(getattr(f, side) for f in group) for side in ("swing", "hinge")}
        update |= {
            "id": f"{first.type}_{ids[first.type]}",
            "confidence": statistics.mean(f.confidence for f in group) * len(group) / len(runs),
        }
        kept.append(first.model_copy(update=update))
    return kept, len(groups) - len(kept)


def analyze(
    dimensions: Dimensions, photos: Sequence[str], overlays: Sequence[str] = (), runs: int = RUNS, config: RunnableConfig | None = None
) -> tuple[RoomSpec, llm.Usage]:
    """The room in `photos` (image URLs), read `runs` times in parallel, and the usage of the calls.

    `overlays` are detection overlay images of the photos (B-06), shown to the model after them. The typed `dimensions` are the room's.
    """
    note = (
        f"\nThen {len(overlays)} detection overlay(s) of the photos, in the same order: boxes a detector drew around features."
        if overlays
        else ""
    )
    prompt = PROMPT.format(**dimensions.model_dump(), coords=coords.__doc__, photos=len(photos), overlays=note)
    images = [*photos, *overlays]
    with get_executor_for_config(config) as executor:  # copies the run's context, so the calls stream and trace under the node
        replies = list(executor.map(lambda _: llm.ask_structured(RoomReading, prompt, role="analyze_room", images=images), range(runs)))
    readings = [reading for reading, _ in replies]
    warnings: list[str] = []
    found = [[to_feature(f, w.wall, dimensions, warnings) for w in r.walls for f in w.features] for r in readings]
    features, dropped = vote(found, dimensions, min(MIN_VOTES, runs))
    if dropped:
        warnings.append(f"{dropped} feature(s) seen in fewer than {MIN_VOTES} of {runs} readings of the photos were left out")
    room = RoomSpec(
        dimensions=dimensions,  # the typed dimensions always win
        walls=[WallSpec(wall=w, color=most_common(x.color for r in readings for x in r.walls if x.wall == w)) for w in get_args(Wall)],
        floor_material=most_common(r.floor_material for r in readings),
        features=features,
        warnings=list(dict.fromkeys([*warnings, *(n for r in readings for n in r.notes)])),  # deduplicated, in order
    )
    return room, reduce(llm.add_usage, (usage for _, usage in replies))


def image_urls(keys: Sequence[str]) -> list[str]:
    """Photos as data: URLs, read from object storage when it is configured, else from the local files of their keys (local_path:
    uploads/ keys from UPLOAD_DIR, the fixtures' photo keys from fixtures/).

    A key that is not an image, outside fixtures/ and uploads/ without storage, or unreadable raises a ValueError naming it; the run's
    error event carries it.
    """
    storage = Storage.from_env() if os.environ.get("STORAGE_ENDPOINT_URL") else None
    urls = []
    for key in keys:
        mimetype = mimetypes.guess_type(key)[0] or ""
        if not mimetype.startswith("image/"):
            raise ValueError(f"photo key is not an image: {key}")
        try:
            if storage:
                data = storage.get(key)
            elif path := local_path(key):
                data = path.read_bytes()
            else:
                raise ValueError(
                    f"photo key outside fixtures/ and uploads/ and object storage is not configured (STORAGE_ENDPOINT_URL): {key}"
                )
        except (OSError, ClientError) as e:
            raise ValueError(f"photo {key} could not be read: {e}") from e
        urls.append(f"data:{mimetype};base64,{base64.b64encode(data).decode()}")
    return urls


def summary(room: RoomSpec) -> str:
    counts = Counter(f.type.replace("_", " ") for f in room.features)
    return "found " + ", ".join(f"{n} {t}" for t, n in counts.items()) if counts else "found no features"


def _replay(state: RunState) -> dict[str, Any]:
    return {"room_spec": ask(RoomSpec, load("room_spec", RoomSpec))}


_replay.__name__ = "analyze_room"  # stub_node replays the fixture step of the node it is named after
replay = stub_node(_replay)


def analyze_room(state: RunState, config: RunnableConfig) -> dict[str, Any]:
    """Read the room from the photos: RUNS readings voted, or one when the run has `analyst_mode` (the single-pass ablation)."""
    if not stub.live("analyze_room"):
        logger.warning("OPENROUTER_API_KEY is not set: analyze_room replays the fixture room")
        return replay(state)  # the stub graph: the fixture room
    write, start = get_stream_writer(), time.monotonic()
    write({"type": "step", "node": "analyze_room", "status": "started"})
    photos = image_urls(state["photo_keys"])
    room, usage = analyze(
        Dimensions.model_validate(state["dimensions"]), photos, runs=1 if flags(config).analyst_mode else RUNS, config=config
    )
    duration = round(time.monotonic() - start, 2)
    write(
        {"type": "step", "node": "analyze_room", "status": "done", "summary": summary(room), "duration_s": duration, "cost": usage["cost"]}
    )
    return {"room_spec": room, **usage}


def feature_scores(rooms: Iterable[tuple[RoomSpec, RoomSpec]]) -> dict[str, tuple[float, float]]:
    """Feature precision and recall, per type and over all features ("all"), of (found, labeled) rooms; 0 when undefined."""
    hits, found, labeled = Counter[str](), Counter[str](), Counter[str]()
    for room, label in rooms:
        hits.update(f.type for f, _ in match(room.features, label.features, label.dimensions))
        found.update(f.type for f in room.features)
        labeled.update(f.type for f in label.features)
    for counts in (hits, found, labeled):
        counts["all"] = counts.total()
    return {t: (hits[t] / found[t] if found[t] else 0.0, hits[t] / labeled[t] if labeled[t] else 0.0) for t in sorted(found | labeled)}
