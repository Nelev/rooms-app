import { readFileSync } from "node:fs";
import { join } from "node:path";
import { Box3, BoxGeometry, ExtrudeGeometry, Group, Mesh, Object3D, Shape, Vector2, Vector3 } from "three";
import { describe, expect, it } from "vitest";
import { type Front, glbFit, itemPose, type Scene, toRoom, toThree, type Vec3, viewpoints, WALL_THICKNESS, wallMeshes } from "./geometry";

const CM = 0.01;
const cases = ["small-bedroom", "home-office", "living-room"];
const read = (name: string, file: string) => JSON.parse(readFileSync(join(import.meta.dirname, "../../../../../fixtures", name, file), "utf8"));

type Placement = { node_id: string; x: number; y: number; z?: number; rotation?: number; size: { width: number; depth: number; height: number } };

// The room-frame bounds (min, max) of an object, as the viewer would place it.
function roomBounds(object: Object3D): { min: Vec3; max: Vec3 } {
  object.updateMatrixWorld(true);
  const box = new Box3().setFromObject(object);
  const [a, b] = [toRoom(box.min.toArray()), toRoom(box.max.toArray())];
  return { min: [Math.min(a[0], b[0]), Math.min(a[1], b[1]), a[2]], max: [Math.max(a[0], b[0]), Math.max(a[1], b[1]), b[2]] };
}

// The item's group as the viewer builds it, with `model` inside
function placed(item: Placement, model: Object3D): Group {
  const group = new Group();
  const { position, rotation } = itemPose(item);
  group.position.set(...position);
  group.rotation.set(...rotation);
  group.add(model);
  return group;
}

// The footprint's axis-aligned bounds; the fixture layouts turn items by multiples of 90 degrees
function expectFootprint(bounds: { min: Vec3; max: Vec3 }, p: Placement) {
  const turned = Math.round((p.rotation ?? 0) / 90) % 2 === 1;
  const [w, d] = turned ? [p.size.depth, p.size.width] : [p.size.width, p.size.depth];
  const z = p.z ?? 0;
  const expected = { min: [p.x - w / 2, p.y - d / 2, z], max: [p.x + w / 2, p.y + d / 2, z + p.size.height] };
  for (const k of ["min", "max"] as const) bounds[k].forEach((v, i) => void expect(Math.abs(v - expected[k][i])).toBeLessThan(CM));
}

describe.each(cases)("%s", (name) => {
  const scene: Scene = read(name, "scene.json");
  const layout: { placements: Placement[] } = read(name, "layout.json");

  it("projects each item's 3D position back to its Layout placement within 1 cm", () => {
    expect(scene.items.map((i) => i.node_id).sort()).toEqual(layout.placements.map((p) => p.node_id).sort());
    for (const item of scene.items) {
      const p = layout.placements.find((q) => q.node_id === item.node_id) as Placement;
      const [x, y, z] = toRoom(itemPose(item).position);
      expect(Math.hypot(x - p.x, y - p.y, z - (p.z ?? 0))).toBeLessThan(CM);
      const box = new Mesh(new BoxGeometry(item.size.width, item.size.height, item.size.depth));
      box.position.y = item.size.height / 2;
      expectFootprint(roomBounds(placed(item, box)), p);
    }
  });

  it("puts each window hole and door gap where the RoomSpec has it", () => {
    for (const mesh of wallMeshes(scene.room)) {
      const wall = new Mesh(
        new ExtrudeGeometry(new Shape(mesh.outline.map(([u, v]) => new Vector2(u, v))), { depth: WALL_THICKNESS, bevelEnabled: false }),
      );
      wall.position.set(...mesh.position);
      wall.rotation.set(...mesh.rotation);
      wall.updateMatrixWorld(true);
      const features = scene.room.features.filter((f) => f.wall === mesh.wall && (f.type === "window" || f.type === "door"));
      const openings = [...mesh.holes, ...features.filter((f) => f.type === "door").map((_, i) => mesh.outline.slice(1 + 4 * i, 5 + 4 * i))];
      expect(openings).toHaveLength(features.length);
      for (const f of features) {
        const [ox, oy] = { A: [f.offset, 0], B: [1, f.offset], C: [1 - f.offset, 1], D: [0, 1 - f.offset] }[f.wall];
        const center: Vec3 = [ox * scene.room.dimensions.width, oy * scene.room.dimensions.length, (f.sill_height ?? 0) + f.height / 2];
        // some opening's center, on the wall's inner face, is the feature's center
        const found = openings.some((o) => {
          const u = (Math.min(...o.map((q) => q[0])) + Math.max(...o.map((q) => q[0]))) / 2;
          const v = (Math.min(...o.map((q) => q[1])) + Math.max(...o.map((q) => q[1]))) / 2;
          const at = toRoom(wall.localToWorld(new Vector3(u, v, 0)).toArray());
          return Math.hypot(...at.map((c, i) => c - center[i])) < CM;
        });
        expect(found, f.id).toBe(true);
      }
      // the inner face lies on the room's edge, the wall outside it
      const { min, max } = roomBounds(wall);
      const { width, length } = scene.room.dimensions;
      const inside = { A: max[1] < CM, B: min[0] > width - CM, C: min[1] > length - CM, D: max[0] < CM }[mesh.wall];
      expect(inside, mesh.wall).toBe(true);
    }
  });

  it("starts the eye-level camera at 1.6 m inside the room, turning in place", () => {
    const { position, target } = viewpoints(scene.room.dimensions).eye;
    const [x, y, z] = toRoom(position);
    expect(z).toBeCloseTo(1.6);
    // orbit controls circle the target, so a target 1 cm away keeps the camera where it stands
    expect(Math.hypot(...position.map((p, i) => p - target[i]))).toBeCloseTo(0.01);
    expect(x > 0 && x < scene.room.dimensions.width && y > 0 && y < scene.room.dimensions.length).toBe(true);
  });
});

describe("glbFit", () => {
  const size = { width: 2, depth: 0.8, height: 0.9 };
  // a model whose bounds and front differ from the catalog's: a box off its origin, with a marker on its front face
  const fronts: Record<Front, Vec3> = { "+z": [0, 0, 1], "-z": [0, 0, -1], "+x": [1, 0, 0], "-x": [-1, 0, 0] };

  it.each(Object.keys(fronts) as Front[])("scales a %s-facing model to the catalog size, front to the item's front", (front) => {
    const n = fronts[front];
    const sideways = n[0] !== 0;
    const [sx, sy, sz] = sideways ? [3, 5, 7] : [7, 5, 3]; // 7 units wide, 3 deep, in the model's frame
    const [cx, by, cz] = [10, -2, 4];
    const model = new Mesh(new BoxGeometry(sx, sy, sz));
    model.position.set(cx, by + sy / 2, cz);
    const marker = new Object3D();
    marker.position.set(cx + (n[0] * sx) / 2, by + sy / 2, cz + (n[2] * sz) / 2);
    const root = new Group().add(model, marker);
    const fit = glbFit(front, [cx - sx / 2, by, cz - sz / 2], [cx + sx / 2, by + sy, cz + sz / 2], size);
    const fitted = new Group().add(root);
    fitted.rotation.set(...fit.rotation);
    fitted.scale.set(...fit.scale);
    root.position.set(...fit.offset);

    const item = { node_id: "sofa", x: 1.5, y: 2, rotation: 90, size };
    const group = placed(item, fitted);
    expectFootprint(roomBounds(group), item);
    // at 90 degrees the front faces -x in the room
    const [fx, fy] = toRoom(marker.getWorldPosition(new Vector3()).toArray());
    expect(Math.hypot(fx - (item.x - size.depth / 2), fy - item.y)).toBeLessThan(CM);
  });
});

it("maps room coordinates to three.js and back", () => {
  expect(toThree(1, 2, 3)).toEqual([1, 3, -2]);
  expect(toRoom(toThree(1, 2, 3))).toEqual([1, 2, 3]);
});

it("keeps a wall outline going forward when doors overlap", () => {
  const { room }: Scene = read("small-bedroom", "scene.json");
  const door = room.features.find((f) => f.type === "door") as Scene["room"]["features"][number];
  const features = [door, { ...door, id: "door_2", offset: door.offset + 0.05 }, { ...door, id: "door_3", width: 0.2 }];
  const outline = wallMeshes({ ...room, features }).find((m) => m.wall === door.wall)?.outline ?? [];
  // door_3 lies inside door_1 and is dropped; door_2 starts where door_1 ends
  expect(outline).toHaveLength(1 + 4 * 2 + 3);
  // along the bottom edge, up to the far top corner
  outline.slice(1, -1).forEach(([u], i) => void expect(u).toBeGreaterThanOrEqual(outline[i][0]));
});
