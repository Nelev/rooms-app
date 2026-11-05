// The pure math of the 3D viewer, kept apart from react-three-fiber so it can be tested without WebGL.
// Room coordinates (backend/app/schemas/coords.py): meters, z up, rotation counterclockwise about z, front at 0 facing +y.
// three.js is y-up: room (x, y, z) is three.js (x, z, -y), so a counterclockwise turn about room z is the same turn about three.js +y.
import type { components } from "@/lib/api/generated/schema";

type Schemas = components["schemas"];
export type Scene = Schemas["Scene"];
export type RoomSpec = Schemas["RoomSpec"];
export type CameraPose = Schemas["CameraPose"];
export type Front = Schemas["CatalogItem"]["front"];
export type Vec3 = [number, number, number];
type Size = Schemas["Size"];
type Wall = Schemas["Feature"]["wall"];

export const EYE_HEIGHT = 1.6;
export const WALL_THICKNESS = 0.1;
const DEG = Math.PI / 180;

export const toThree = (x: number, y: number, z = 0): Vec3 => [x, z, -y];
export const toRoom = ([x, y, z]: Vec3): Vec3 => [x, -z, y];

// A scene item or a kept item; z and rotation have defaults, so fixtures may leave them out.
type Placed = { x: number; y: number; z?: number; rotation?: number; size: Size };

// The item's group: at its footprint center on its base, turned about the vertical. In it, width runs along x,
// height along y and depth along z, with the front facing -z (room +y at rotation 0).
export function itemPose({ x, y, z = 0, rotation = 0 }: Placed): { position: Vec3; rotation: Vec3 } {
  return { position: toThree(x, y, z), rotation: [0, rotation * DEG, 0] };
}

// The turn about y that makes a GLB's front axis face -z.
const FRONT_TURN: Record<Front, number> = { "-z": 0, "+z": Math.PI, "+x": Math.PI / 2, "-x": -Math.PI / 2 };

// How to fit a GLB with bounds `min`..`max` (its own frame) in an item's group: turn its front to -z, scale each axis
// to the catalog size, center its footprint on the origin and put its bottom at 0. Apply the result to a group
// around the model: rotation and scale on the group, `offset` as the model's position inside it.
export function glbFit(front: Front, min: Vec3, max: Vec3, size: Size): { rotation: Vec3; scale: Vec3; offset: Vec3 } {
  const sideways = front === "+x" || front === "-x"; // the model's x axis then runs front to back
  const [w, d] = sideways ? [size.depth, size.width] : [size.width, size.depth];
  const extent = (i: number) => max[i] - min[i] || 1;
  return {
    rotation: [0, FRONT_TURN[front], 0],
    scale: [w / extent(0), size.height / extent(1), d / extent(2)],
    offset: [-(min[0] + max[0]) / 2, -min[1], -(min[2] + max[2]) / 2],
  };
}

// A wall's frame in room coordinates: start corner, unit direction and length (walls go counterclockwise).
function wallFrame({ width, length }: RoomSpec["dimensions"], wall: Wall) {
  const frames: Record<Wall, { start: [number, number]; dir: [number, number]; length: number }> = {
    A: { start: [0, 0], dir: [1, 0], length: width },
    B: { start: [width, 0], dir: [0, 1], length },
    C: { start: [width, length], dir: [-1, 0], length: width },
    D: { start: [0, length], dir: [0, -1], length },
  };
  return frames[wall];
}

export type WallMesh = {
  wall: Wall;
  outline: [number, number][]; // (along the wall, height), doors cut into its bottom edge
  holes: [number, number][][]; // windows
  position: Vec3;
  rotation: Vec3;
};

// Each wall as a shape in its own plane: x along the wall from its start corner, y up. The mesh puts that plane on the
// room's edge, extruded outward (+z) by WALL_THICKNESS; each wall runs on by that much past its end corner to close the corner.
export function wallMeshes(room: RoomSpec): WallMesh[] {
  const height = room.dimensions.height;
  return (["A", "B", "C", "D"] as const).map((wall) => {
    const { start, dir, length } = wallFrame(room.dimensions, wall);
    // clamped to the wall, so an opening that reaches past a corner still gives a valid outline
    const span = (f: RoomSpec["features"][number]): [number, number] => [
      Math.max(0, f.offset * length - f.width / 2),
      Math.min(length, f.offset * length + f.width / 2),
    ];
    const features = room.features.filter((f) => f.wall === wall);
    const doors = features.filter((f) => f.type === "door").sort((a, b) => a.offset - b.offset);
    const outline: [number, number][] = [[0, 0]];
    let end = 0; // overlapping doors would fold the outline back on itself: each starts where the last one ends
    for (const door of doors) {
      const [a, b] = [Math.max(end, span(door)[0]), span(door)[1]];
      if (b <= a) continue;
      outline.push([a, 0], [a, door.height], [b, door.height], [b, 0]);
      end = b;
    }
    outline.push([length + WALL_THICKNESS, 0], [length + WALL_THICKNESS, height], [0, height]);
    const holes = features
      .filter((f) => f.type === "window")
      .map((f): [number, number][] => {
        const [a, b] = span(f);
        const [bottom, top] = [f.sill_height ?? 0, (f.sill_height ?? 0) + f.height];
        return [
          [a, bottom],
          [b, bottom],
          [b, top],
          [a, top],
        ];
      });
    return { wall, outline, holes, position: toThree(start[0], start[1]), rotation: [0, Math.atan2(dir[1], dir[0]), 0] };
  });
}

export type Viewpoint = { position: Vec3; target: Vec3 };

// The orbit camera looks at the room's center from above a corner. The eye-level one stands just inside wall A's
// start corner at EYE_HEIGHT, facing the room's center; its target is 1 cm ahead so orbit controls turn it in place.
export function viewpoints({ width, length, height }: RoomSpec["dimensions"]): { orbit: Viewpoint; eye: Viewpoint } {
  const reach = Math.max(width, length);
  const [ex, ey] = [0.3, 0.3];
  const [dx, dy] = [width / 2 - ex, length / 2 - ey];
  const step = 0.01 / Math.hypot(dx, dy);
  return {
    orbit: { position: toThree(width + reach * 0.6, -reach * 0.6, height + reach), target: toThree(width / 2, length / 2, 0) },
    eye: { position: toThree(ex, ey, EYE_HEIGHT), target: toThree(ex + dx * step, ey + dy * step, EYE_HEIGHT) },
  };
}
