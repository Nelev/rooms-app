// The pure part of the viewer's look (materials and lights), kept apart from react-three-fiber so it can be tested without WebGL.
import { Euler, Vector3 } from "three";
import { type RoomSpec, type Scene, type Vec3, type WallMesh, wallMeshes } from "../core/geometry";

export type Pattern = "planks" | "tiles" | "carpet";
// `tile` is the real-world size in meters that one copy of the pattern's texture covers
export type FloorLook = { pattern: Pattern; color: string; roughness: number; tile: number };

const PATTERNS: Record<Pattern, { words: string[]; color: string; roughness: number; tile: number }> = {
  planks: {
    words: ["wood", "parquet", "laminate", "plank", "oak", "walnut", "pine", "maple", "ash", "birch", "cherry"],
    color: "#b48a5e",
    roughness: 0.55,
    tile: 1.2,
  },
  tiles: {
    words: ["tile", "ceramic", "porcelain", "stone", "marble", "slate", "terrazzo", "concrete"],
    color: "#d6d2cb",
    roughness: 0.35,
    tile: 0.6,
  },
  carpet: { words: ["carpet", "rug", "wool", "sisal"], color: "#a8a39b", roughness: 1, tile: 0.5 },
};

// A word in the material name overrides the pattern's default color
const COLORS: Record<string, string> = {
  walnut: "#6b4a33",
  oak: "#b48a5e",
  cherry: "#8e4f34",
  pine: "#cfa874",
  maple: "#d8b88a",
  birch: "#dcc39b",
  ash: "#cdb48f",
  white: "#e8e6e1",
  black: "#2e2d2b",
  grey: "#8d8c88",
  gray: "#8d8c88",
  beige: "#cdbb9c",
  brown: "#7a5a40",
  marble: "#e6e3de",
  slate: "#5d6168",
  concrete: "#a19e99",
};

// RoomSpec.floor_material is free text ("walnut", "grey carpet"): read its pattern and color from known words, wood otherwise
export function floorLook(material: string | null | undefined): FloorLook {
  const words = (material ?? "")
    .toLowerCase()
    .split(/[^a-z]+/)
    .map((w) => w.replace(/s$/, "")); // "tiles" reads as "tile"
  const pattern = (Object.keys(PATTERNS) as Pattern[]).find((p) => PATTERNS[p].words.some((w) => words.includes(w))) ?? "planks";
  const { color, roughness, tile } = PATTERNS[pattern];
  return { pattern, color: COLORS[words.find((w) => w in COLORS) ?? ""] ?? color, roughness, tile };
}

// How many copies of the floor texture cover the room, so it keeps its real-world size
export const floorRepeat = ({ width, length }: Pick<RoomSpec["dimensions"], "width" | "length">, tile: number): [number, number] => [
  width / tile,
  length / tile,
];

export type WindowLight = {
  id: string;
  center: Vec3; // the window's center, in the wall's inner face
  inward: Vec3; // unit normal from the window into the room
  rotation: Vec3; // turns a RectAreaLight (which shines along -z) to shine into the room
  width: number;
  height: number;
  intensity: number;
  sun: number | null; // a main window's sun intensity: a shadow-casting DirectionalLight through it
};

const AREA_INTENSITY = 5;
const SUN_INTENSITY = 3;
// Each sun renders the scene once more into its shadow map, so the cost grows with them: at most this many
export const MAX_SUNS = 2;

// One light per window, with Scene.lights' intensities. The main windows, with a sun, are those with a directional light
// in Scene.lights (the MAX_SUNS brightest), or the largest window when it has none.
export function windowLights(scene: Scene): WindowLight[] {
  const lights = scene.lights ?? [];
  const named = lights.filter((l) => l.kind === "directional");
  const suns = named.toSorted((a, b) => b.intensity - a.intensity).slice(0, MAX_SUNS);
  const windows = scene.room.features.filter((f) => f.type === "window");
  const largest = windows.reduce<(typeof windows)[number] | undefined>((a, f) => (a && a.width * a.height >= f.width * f.height ? a : f), undefined);
  return windows.map((f) => {
    // core's wall mesh for a room with only this window: its one hole is this window's, whatever the features' order
    const wall = wallMeshes({ ...scene.room, features: [f] }).find((w) => w.wall === f.wall) as WallMesh;
    const turn = new Euler(...wall.rotation);
    const hole = wall.holes[0];
    const [u, v] = [(hole[0][0] + hole[2][0]) / 2, (hole[0][1] + hole[2][1]) / 2];
    const center = new Vector3(u, v, 0).applyEuler(turn).add(new Vector3(...wall.position));
    return {
      id: f.id,
      center: center.toArray(),
      inward: new Vector3(0, 0, -1).applyEuler(turn).toArray(),
      rotation: wall.rotation,
      width: hole[1][0] - hole[0][0],
      height: hole[2][1] - hole[0][1],
      intensity: lights.find((l) => l.kind === "area" && l.window_id === f.id)?.intensity ?? AREA_INTENSITY,
      sun: named.length ? (suns.find((l) => l.window_id === f.id)?.intensity ?? null) : f === largest ? SUN_INTENSITY : null,
    };
  });
}

const SUN_ELEVATION = 40 * (Math.PI / 180);

// Where a main window's sun sits: outside the window, `distance` away and SUN_ELEVATION up, shining in through its center
export function sunPosition({ center, inward }: WindowLight, distance: number): Vec3 {
  const out = new Vector3(...inward).multiplyScalar(-Math.cos(SUN_ELEVATION) * distance);
  return new Vector3(...center)
    .add(out)
    .add(new Vector3(0, Math.sin(SUN_ELEVATION) * distance, 0))
    .toArray();
}
