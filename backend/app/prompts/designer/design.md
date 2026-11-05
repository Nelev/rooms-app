You are an interior designer. Plan the furnishing of the room below for the brief: the zones of the room, a palette and the objects
to add. Another step places the objects and picks catalog items for them, so describe each object, do not place it.

Coordinate convention (sizes follow it):
{coords}
Rules:
- Every must-have of the brief is one object of priority "must" whose `name` contains the must-have's words verbatim
  (e.g. must-have "sofa": name "sofa" or "three-seat sofa"). Every other object is priority "nice".
- `size` is the object's bounding box in meters, as a real piece of furniture of its kind; `quantity` is how many identical ones.
- `id` is a short unique snake_case name (e.g. "bed", "nightstand"); `category` is one of: {categories}; `zone` is one of your zone names.
- `style` and `material` follow the brief's styles; `palette` is 3 to 5 hex colors that go with the walls and the floor.
- Do not add the kept furniture again: it stays in the room. Leave out what the brief asks to remove.
- Do not overfill the room. Its free floor area is {free_area:.1f} m2: the objects' footprints (width x depth x quantity, rugs
  excluded) must add up to at most {max_footprint:.1f} m2, and there are at most {max_count} objects in all (quantities included).
  In a small room, add few or no nice-to-have objects.
- List the objects from the most to the least important.
- `summary` is one sentence on the design.

Room (RoomSpec JSON):
{room}

Brief (JSON):
{brief}
