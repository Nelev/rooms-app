import { readFileSync } from "node:fs";
import path from "node:path";
import Ajv from "ajv";
import { describe, expect, test } from "vitest";
import type { RoomSpec } from "../coords";
import { addFeature, addKept, dragTo, planReport, remove, roomIssues, setFeature, setKept } from "./room";

const read = (file: string) => JSON.parse(readFileSync(path.resolve(__dirname, "../../../../..", file), "utf8"));
// the contract the API validates `command.resume` against (backend/app/schemas/room.py, as `make gen` exports it)
const validRoomSpec = new Ajv({ strict: false }).compile(read("contracts/schemas/RoomSpec.json"));
const CASES = ["small-bedroom", "home-office", "living-room"];
const room = (name = "small-bedroom"): RoomSpec => read(`fixtures/${name}/room_spec.json`);

test.each(CASES)("%s is a valid room", (name) => {
  expect(roomIssues(room(name))).toEqual([]);
  expect(validRoomSpec(room(name))).toBe(true);
});

test.each(CASES)("%s stays schema-valid through any drags, adds, deletes and type changes", (name) => {
  let seed = 42;
  const random = () => {
    seed = (seed * 16807) % 2147483647;
    return seed / 2147483647;
  };
  let r = room(name);
  const { width, length } = r.dimensions;
  for (let i = 0; i < 300; i++) {
    const ids = [...r.features, ...r.kept_furniture].map((x) => x.id);
    const id = ids[Math.floor(random() * ids.length)];
    const op = Math.floor(random() * 6);
    if (op === 0) [r] = addFeature(r);
    else if (op === 1) [r] = addKept(r);
    else if (op === 2 && id && ids.length > 4) r = remove(r, id);
    else if (op === 3 && id && r.features.some((f) => f.id === id))
      r = setFeature(r, id, { type: (["door", "window", "outlet"] as const)[Math.floor(random() * 3)], swing: "out", hinge: "right" });
    else if (id) r = dragTo(r, id, [random() * (width + 2) - 1, random() * (length + 2) - 1]); // outside the room too
    expect(roomIssues(r)).toEqual([]);
    expect(validRoomSpec(r), JSON.stringify(validRoomSpec.errors)).toBe(true);
  }
});

describe("roomIssues", () => {
  test("reports what the API or the room cannot take", () => {
    let r = room();
    r = { ...r, dimensions: { ...r.dimensions, length: 25 } };
    r = setFeature(r, "window_1", { offset: 0.98 }); // half of it past the corner
    r = setFeature(r, "door_1", { height: 3 }); // taller than the room
    r = setKept(r, "kept_1", { x: -1, name: " " });
    r = { ...r, features: [...r.features, { ...r.features[2], swing: "in" }] }; // radiator_1 twice, and swinging
    expect(roomIssues(r)).toEqual([
      { id: "room", message: "The length must be 1–20 m" },
      { id: "radiator_1", message: "radiator_1 is used twice" },
      { id: "door_1", message: "Must fit between the floor and the ceiling" },
      { id: "window_1", message: "Must fit on wall C" },
      { id: "radiator_1", message: "Only doors swing" },
      { id: "kept_1", message: "Needs a name" },
      { id: "kept_1", message: "Its center must be inside the room" },
    ]);
  });

  test("a feature that stops being a door loses its swing and hinge", () => {
    const r = setFeature(room(), "door_1", { swing: "out", hinge: "right" });
    expect(setFeature(r, "door_1", { type: "window" }).features[0]).not.toHaveProperty("swing");
  });
});

test("the plan warns about features the analysis is unsure of, and invalid ones", () => {
  const r = setKept(room(), "kept_1", { x: 9 });
  expect(planReport(r).issues.map((i) => [i.node_ids[0], i.message])).toEqual([
    ["kept_1", "Its center must be inside the room"],
    ["radiator_1", "70% sure: check it"],
  ]);
});

describe("dragTo", () => {
  test("snaps a feature to the nearest wall, its center where the pointer is along it", () => {
    // 3.2 x 3.4 m: (3.1, 1.0) is 0.1 m from wall B, 1.0 m along it
    const window = dragTo(room(), "window_1", [3.1, 1]).features[1];
    expect(window.wall).toBe("B");
    expect(window.offset * 3.4).toBeCloseTo(1);
  });

  test("keeps the feature on its wall at the corners, and furniture in the room", () => {
    const window = dragTo(room(), "window_1", [0.1, -1]).features[1];
    expect(window.wall).toBe("A");
    expect(window.offset * 3.2).toBeCloseTo(0.5); // half its width from the corner
    expect(dragTo(room(), "kept_1", [5, -1]).kept_furniture[0]).toMatchObject({ x: 3.2, y: 0 });
  });
});
