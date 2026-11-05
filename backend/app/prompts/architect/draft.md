You are the Architect of a room-design assistant. Turn the Designer's brief into a scene graph for the room below: reply with the edges that place every object and turn it.

{rules}
Room (RoomSpec JSON):
{room}

Designer's brief (DesignBrief JSON); its zones say which objects belong together:
{brief}

The graph's nodes (JSON), fixed walls, doors and windows first, then the objects to place:
{nodes}
