import { RANGES } from "@/components/wizard/fields";
import { type Feature, type Point, type RoomSpec, type ValidationReport, type Wall, wallFrame } from "../coords";

export type KeptItem = RoomSpec["kept_furniture"][number];

// A detection below this confidence is highlighted for the user to check.
export const LOW_CONFIDENCE = 0.8;
export const ROOM = "room"; // what an issue of the dimensions is about

const EPS = 1e-6;
const round = (n: number) => Math.round(n * 1000) / 1000; // to the millimeter
const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n));

export const isFeature = (room: RoomSpec, id: string) => room.features.some((f) => f.id === id);

// What is wrong with the room, by the id of the feature or kept item (or ROOM) it is about: the schema's ranges (backend/app/schemas/room.py)
// plus what makes a room impossible (a feature off its wall or above the ceiling, furniture outside the room). An empty list is a room
// the API accepts.
export function roomIssues(room: RoomSpec): { id: string; message: string }[] {
  const issues: { id: string; message: string }[] = [];
  const check = (id: string, ok: boolean, message: string) => ok || issues.push({ id, message });
  const { dimensions: dims } = room;
  for (const name of ["width", "length", "height"] as const) {
    const [lo, hi] = RANGES[name];
    check(ROOM, dims[name] >= lo && dims[name] <= hi, `The ${name === "height" ? "ceiling height" : name} must be ${lo}–${hi} m`);
  }
  const ids = [...room.features, ...room.kept_furniture].map((x) => x.id);
  for (const id of new Set(ids.filter((id, i) => ids.indexOf(id) !== i))) check(id, false, `${id} is used twice`);

  for (const f of room.features) {
    const wall = wallFrame(dims, f.wall).length;
    const center = f.offset * wall;
    check(f.id, f.width > 0 && f.height > 0, "Width and height must be over 0 m");
    check(f.id, f.offset >= 0 && f.offset <= 1 && center - f.width / 2 >= -EPS && center + f.width / 2 <= wall + EPS, `Must fit on wall ${f.wall}`);
    const sill = f.sill_height ?? 0; // a default may be left out of the JSON (as in fixtures/)
    check(f.id, sill >= 0 && sill + f.height <= dims.height + EPS, "Must fit between the floor and the ceiling");
    check(f.id, f.type === "door" || (!f.swing && !f.hinge), "Only doors swing");
  }
  for (const k of room.kept_furniture) {
    check(k.id, k.name.trim() !== "", "Needs a name");
    check(k.id, k.size.width > 0 && k.size.depth > 0 && k.size.height > 0, "Width, depth and height must be over 0 m");
    check(k.id, k.x >= 0 && k.x <= dims.width && k.y >= 0 && k.y <= dims.length, "Its center must be inside the room");
    check(k.id, (k.rotation ?? 0) >= 0 && (k.rotation ?? 0) < 360, "Rotation must be 0–359°");
  }
  // NaN (an emptied field) fails every comparison above, so it is reported too
  return issues;
}

// What the floor plan draws in its warning color: the room's issues and the features to check.
export function planReport(room: RoomSpec, issues = roomIssues(room)): ValidationReport {
  return {
    issues: [
      ...issues.map(({ id, message }) => ({ code: "invalid", message, severity: "error" as const, node_ids: [id] })),
      ...room.features
        .filter((f) => (f.confidence ?? 1) < LOW_CONFIDENCE)
        .map((f) => ({
          code: "low_confidence",
          message: `${Math.round(f.confidence * 100)}% sure: check it`,
          severity: "warning" as const,
          node_ids: [f.id],
        })),
    ],
  };
}

export function setFeature(room: RoomSpec, id: string, patch: Partial<Feature>): RoomSpec {
  return {
    ...room,
    features: room.features.map((f) => {
      if (f.id !== id) return f;
      const next = { ...f, ...patch };
      if (next.type !== "door") {
        delete next.swing; // the schema refuses them on anything else
        delete next.hinge;
      }
      return next;
    }),
  };
}

export function setKept(room: RoomSpec, id: string, patch: Partial<KeptItem>): RoomSpec {
  return { ...room, kept_furniture: room.kept_furniture.map((k) => (k.id === id ? { ...k, ...patch } : k)) };
}

export function remove(room: RoomSpec, id: string): RoomSpec {
  return { ...room, features: room.features.filter((f) => f.id !== id), kept_furniture: room.kept_furniture.filter((k) => k.id !== id) };
}

function nextId(room: RoomSpec, prefix: string) {
  const ids = new Set([...room.features, ...room.kept_furniture].map((x) => x.id));
  let n = 1;
  while (ids.has(`${prefix}_${n}`)) n++;
  return `${prefix}_${n}`;
}

// A window in the middle of wall A, the user's own (confidence 1).
export function addFeature(room: RoomSpec): [RoomSpec, string] {
  const id = nextId(room, "feature");
  const width = Math.min(0.8, wallFrame(room.dimensions, "A").length);
  const height = Math.min(1.2, room.dimensions.height - 0.9); // fits under the lowest ceiling allowed (2 m)
  const feature: Feature = { id, type: "window", wall: "A", offset: 0.5, width, height, sill_height: 0.9, confidence: 1 };
  return [{ ...room, features: [...room.features, feature] }, id];
}

// A piece of furniture in the middle of the room.
export function addKept(room: RoomSpec): [RoomSpec, string] {
  const id = nextId(room, "kept");
  const { width, length } = room.dimensions;
  const item: KeptItem = {
    id,
    name: "furniture",
    x: round(width / 2),
    y: round(length / 2),
    rotation: 0,
    size: { width: 0.8, depth: 0.6, height: 0.8 },
  };
  return [{ ...room, kept_furniture: [...room.kept_furniture, item] }, id];
}

// Drags a feature or kept item to a point of the room: a feature to the nearest wall, as far along it as fits; an item's center, kept
// inside the room (its position rounded to the millimeter).
export function dragTo(room: RoomSpec, id: string, [x, y]: Point): RoomSpec {
  const { width, length } = room.dimensions;
  const feature = room.features.find((f) => f.id === id);
  if (!feature) return setKept(room, id, { x: round(clamp(x, 0, width)), y: round(clamp(y, 0, length)) });
  // the distance to each wall, and how far along it (from its start corner) the point is: see coords.ts
  const walls: [Wall, number, number][] = [
    ["A", y, x],
    ["B", width - x, y],
    ["C", length - y, width - x],
    ["D", x, length - y],
  ];
  const [wall, , along] = walls.reduce((best, w) => (w[1] < best[1] ? w : best));
  const wallLength = wallFrame(room.dimensions, wall).length;
  const half = Math.min(feature.width / 2, wallLength / 2);
  return setFeature(room, id, { wall, offset: clamp(along, half, wallLength - half) / wallLength });
}
