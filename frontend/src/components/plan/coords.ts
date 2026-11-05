import type { components } from "@/lib/api/generated/schema";

type Schemas = components["schemas"];
export type RoomSpec = Schemas["RoomSpec"];
export type Feature = Schemas["Feature"];
export type Layout = Schemas["Layout"];
export type ValidationReport = Schemas["ValidationReport"];
export type Wall = Feature["wall"];
export type Point = [number, number];

// The convention of backend/app/schemas/coords.py: meters, origin at the floor corner of walls A and D, x along wall A,
// y along wall D into the room, walls counterclockwise, rotation counterclockwise with 0 facing +y.
export function wallFrame({ width, length }: RoomSpec["dimensions"], wall: Wall): { start: Point; dir: Point; length: number } {
  return {
    A: { start: [0, 0], dir: [1, 0], length: width },
    B: { start: [width, 0], dir: [0, 1], length },
    C: { start: [width, length], dir: [-1, 0], length: width },
    D: { start: [0, length], dir: [0, -1], length },
  }[wall] as { start: Point; dir: Point; length: number };
}

// The point `along` meters from the wall's start corner and `inward` meters into the room (the direction turned counterclockwise).
export function onWall(dims: RoomSpec["dimensions"], wall: Wall, along: number, inward = 0): Point {
  const { start, dir } = wallFrame(dims, wall);
  return [start[0] + dir[0] * along - dir[1] * inward, start[1] + dir[1] * along + dir[0] * inward];
}

// A feature's rectangle (as geometry/room.py `_along`): its width centered on it, from `from` to `from + depth` meters into the room.
export function featureRect(dims: RoomSpec["dimensions"], f: Feature, from: number, depth: number): Point[] {
  const center = f.offset * wallFrame(dims, f.wall).length;
  return [
    [-1, from],
    [1, from],
    [1, from + depth],
    [-1, from + depth],
  ].map(([s, n]) => onWall(dims, f.wall, center + (s * f.width) / 2, n));
}
