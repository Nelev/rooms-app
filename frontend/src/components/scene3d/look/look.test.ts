import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { type Scene, toThree } from "../core/geometry";
import { floorLook, floorRepeat, sunPosition, windowLights } from "./look";

const read = (name: string): Scene => JSON.parse(readFileSync(join(import.meta.dirname, "../../../../../fixtures", name, "scene.json"), "utf8"));
const close = (a: number[], b: number[]) => a.forEach((v, i) => void expect(v).toBeCloseTo(b[i], 6));

describe("floorLook", () => {
  it.each([
    ["walnut", "planks", "#6b4a33"],
    ["oak", "planks", "#b48a5e"],
    ["grey carpet", "carpet", "#8d8c88"],
    ["white marble tiles", "tiles", "#e8e6e1"],
    ["Ceramic tile", "tiles", "#d6d2cb"],
    ["terracotta tiles", "tiles", "#d6d2cb"],
    ["wool rugs", "carpet", "#a8a39b"],
    [null, "planks", "#b48a5e"],
    ["something unknown", "planks", "#b48a5e"],
  ])("reads %s as %s in %s", (material, pattern, color) => {
    expect(floorLook(material)).toMatchObject({ pattern, color });
  });

  it("tiles the texture at its real-world size", () => {
    const { tile } = floorLook("oak");
    expect(floorRepeat({ width: 4.5, length: 5.0 }, tile)).toEqual([4.5 / tile, 5.0 / tile]);
  });
});

describe("windowLights", () => {
  it("puts one light in each fixture window, facing into the room", () => {
    // living-room: window_1 on wall B (x = 4.5), centered, 1.6 x 1.5 m at a 0.6 m sill
    const [living] = windowLights(read("living-room"));
    expect(living).toMatchObject({ id: "window_1", width: expect.closeTo(1.6), height: expect.closeTo(1.5), intensity: 5, sun: 3 });
    close(living.center, toThree(4.5, 2.5, 1.35));
    close(living.inward, [-1, 0, 0]);
    // small-bedroom: window on wall C (y = 3.4), which faces -y in the room, +z in three.js
    const bedroom = read("small-bedroom");
    const [window] = windowLights(bedroom);
    const f = bedroom.room.features.find((x) => x.id === "window_1") as Scene["room"]["features"][number];
    close(window.center, toThree(bedroom.room.dimensions.width * (1 - f.offset), 3.4, (f.sill_height ?? 0) + f.height / 2));
    close(window.inward, [0, 0, 1]);
  });

  it("makes the largest window the main one unless Scene.lights names directional ones", () => {
    const scene = read("living-room");
    const small = {
      ...scene.room.features.find((f) => f.id === "window_1"),
      id: "window_2",
      wall: "A",
      width: 0.6,
    } as Scene["room"]["features"][number];
    scene.room.features.push(small);
    expect(windowLights(scene).map((l) => [l.id, l.sun])).toEqual([
      ["window_1", 3],
      ["window_2", null],
    ]);
    scene.lights = [{ kind: "directional", window_id: "window_2", intensity: 2 }];
    expect(windowLights(scene).map((l) => [l.id, l.sun, l.intensity])).toEqual([
      ["window_1", null, 5],
      ["window_2", 2, 5],
    ]);
  });

  it("gives a windowless room no window lights", () => {
    const scene = read("living-room");
    scene.room.features = scene.room.features.filter((f) => f.type !== "window");
    expect(windowLights(scene)).toEqual([]);
  });

  it("places the sun outside and above the window", () => {
    const [light] = windowLights(read("living-room"));
    const [x, y] = sunPosition(light, 10);
    expect(x).toBeGreaterThan(4.5);
    expect(y).toBeGreaterThan(light.center[1]);
  });
});
