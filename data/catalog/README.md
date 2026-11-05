# Catalog

The furniture the Sourcer picks from: `<category>.json`, each a list of `CatalogItem` (`backend/app/schemas/design.py`, JSON Schema in `contracts/schemas/CatalogItem.json`). Names and products are made up; sizes (meters, the item's own frame: width, depth, height) and EUR prices are plausible real-world values. The items of the fixture scenes are here verbatim, so fixtures and catalog agree; they keep the fixtures' placeholder `license` although they have no `glb_url`.

`backend/app/catalog/loader.py` loads and validates it; `cd backend && uv run python -m app.catalog.loader` reports the items per category and per style, and `backend/tests/test_catalog.py` checks that every core category has at least 5 items.

## 3D models

Only items with a model under a verified open license have a `glb_url`; the rest render as boxes. The models come from the [Khronos glTF Sample Assets](https://github.com/KhronosGroup/glTF-Sample-Assets) (pinned to a commit), with the license and author from each model's `metadata.json`; each model's credit is in its item's `description`, which must be shown wherever a CC-BY-4.0 model is rendered.

| Item | Model | License |
| --- | --- | --- |
| `pink-velvet-sectional-sofa` | GlamVelvetSofa, Eric Chadwick / Wayfair | CC-BY-4.0 |
| `leather-wood-sofa-3` | SheenWoodLeatherSofa, Fran Calvente (CC0), improved by Eric Chadwick / DGG | CC-BY-4.0 |
| `sheen-lounge-chair` | SheenChair, Eric Chadwick / Wayfair | CC0-1.0 |
| `damask-lounge-chair` | ChairDamaskPurplegold, Eric Chadwick / Wayfair | CC-BY-4.0 |
