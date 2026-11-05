Coordinate convention:
{coords}
A scene graph places objects by relations only; a solver turns the relations into positions. Never give coordinates.
Each edge `{{"source": ..., "relation": ..., "target": ...}}` places its source relative to its target. The relations, and only these:
- `against_wall`: the source stands flush against the target wall (`wall_A` to `wall_D`), its back to the wall.
- `in_corner`: the source stands in a corner at one end of the target wall.
- `left_of` / `right_of`: the source stands beside the target, on its left / right as seen facing the target's front.
- `in_front` / `behind`: the source stands in front of / behind the target. `in_front` of a window or door means near it, leaving it clear.
- `on`: the source stands on top of the target.
- `adjacent`: the source stands next to the target, on either side, nothing between them.
- `facing`: the source's front is turned toward the target. It only turns the source, it does not place it.

Rules:
- The walls, doors and windows are fixed: never use one as an edge's source, only as a target.
- Place every object: give it at least one edge other than `facing` whose source it is, leading through other objects to a wall, door or window.
- Give every object exactly one `facing` edge whose source it is, toward a wall, a door, a window or another object (e.g. a bed against a wall faces the opposite wall, a sofa faces the TV, a desk chair faces its desk).
- No loops: never place A relative to B and B relative to A, directly or through other objects.
- Keep doors and windows clear, keep what is placed against a wall shorter than the wall, and do not crowd several objects along one side of a smaller object. The kept furniture in the room stays where it is and takes up its space.
- Use only the node ids listed; never invent nodes.
