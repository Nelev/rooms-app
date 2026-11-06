"""The catalog in data/catalog/ validates, covers the core categories and agrees with the fixtures."""

import json
import re
from collections import Counter
from pathlib import Path

import pytest

from app.catalog.loader import CATALOG_DIR, CORE_CATEGORIES, load_catalog
from app.schemas import Scene

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def test_catalog_validates_and_covers_core_categories() -> None:
    catalog = load_catalog()
    assert 150 <= len(catalog) <= 300
    counts = Counter(i.category for i in catalog.values())
    assert {c: counts[c] for c in CORE_CATEGORIES if counts[c] < 5} == {}
    for path in CATALOG_DIR.glob("*.json"):  # one file per category
        assert {i["category"] for i in json.loads(path.read_text())} == {path.stem}
    assert all(i.style_tags for i in catalog.values())
    assert all(i.license for i in catalog.values() if i.glb_url), "a GLB needs a license"
    assert all("CC-BY" in (i.description or "") for i in catalog.values() if i.license == "CC-BY-4.0"), "CC-BY needs attribution"


def test_catalog_agrees_with_fixtures() -> None:
    catalog = load_catalog()
    scenes = [Scene.model_validate_json(p.read_bytes()) for p in FIXTURES.glob("*/scene.json")]
    scene_items = {i.item.id: i.item for s in scenes for i in s.items if i.item}
    assert {id_: catalog.get(id_) for id_ in scene_items} == scene_items
    item_ids = {m for p in FIXTURES.glob("*/*.json") for m in re.findall(r'"item_id": "([^"]+)"', p.read_text())}
    assert item_ids - catalog.keys() == set()


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    item = json.loads((CATALOG_DIR / "bed.json").read_text())[0]
    (tmp_path / "a.json").write_text(json.dumps([item]))
    (tmp_path / "b.json").write_text(json.dumps([item]))
    with pytest.raises(ValueError, match="Duplicate"):
        load_catalog(tmp_path)


def test_empty_catalog_dir_fails(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_catalog(tmp_path / "missing")
