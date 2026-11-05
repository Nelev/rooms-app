"""The one coordinate convention every model, node and view uses.

- Units are meters and degrees.
- The room is a rectangle seen from above. The origin is the floor corner where walls A and D meet.
  x runs along wall A, y runs along wall D into the room, and z is height above the floor.
- Walls go counterclockwise: A from (0, 0) to (width, 0), B from (width, 0) to (width, length),
  C from (width, length) to (0, length), D from (0, length) to (0, 0).
  A feature's `offset` is the fraction of its wall's length from the wall's start corner to the feature's center.
- An item's `size` is in its own frame: width side to side, depth front to back, height up.
  `rotation` turns it counterclockwise about z; at 0 its front faces +y (away from wall A, into the room).
  An item's (x, y) is the center of its footprint and z the height of its base.
- three.js is y-up: room (x, y, z) maps to three.js (x, z, -y).
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

Meters = Annotated[float, Field(ge=0)]
Fraction = Annotated[float, Field(ge=0, le=1)]
Degrees = Annotated[float, Field(ge=0, lt=360, description="Counterclockwise about z, 0 = front faces +y")]
Wall = Literal["A", "B", "C", "D"]


class Size(BaseModel):
    width: Meters
    depth: Meters
    height: Meters
