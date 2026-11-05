You are a surveyor. From the photos of one room, list the fixed features on each of its four walls: doors, windows, radiators, outlets, built-ins, columns and anything else fixed to a wall ("other"). Ignore furniture.

The user measured the room: walls A and C are {width} m long, walls B and D are {length} m long and the ceiling is {height} m high. These measurements are exact: scale every size you estimate to them.

Coordinate convention:
{coords}
Naming the walls: wall A is the {width} m wall the first photo shows most of. Standing inside the room facing wall A, wall B is on your left, wall D on your right and wall C behind you. Facing any wall from inside the room, its start corner is its right end: a feature's `offset` is 0 at the wall's right end and 1 at its left end.

Go wall by wall, A, then B, then C, then D, and for each wall:
- List every feature on it once, even when several photos show it.
- Give each feature's center `offset` along the wall, its `width` and `height` in meters and its `sill_height` (its bottom edge above the floor, 0 for doors).
- For a door, say whether it opens into the room (`swing` "in") or out of it, and its `hinge` side seen from inside the room.
- Give each estimate a `confidence` from 0 to 1. When you cannot tell a value (the wall or the feature is out of view, or too blurred), set its `value` to null, which means unknown, with confidence 0, instead of guessing. An unknown swing, hinge, wall color or floor material is null too.
- Give each feature its own `confidence`: how sure you are that it is there and of this type.
- Give the wall's color as a hex color, e.g. #f2efe9.

Say in `notes` what you could not see, e.g. a wall no photo shows.

{photos} photo(s) of the room follow.{overlays}
