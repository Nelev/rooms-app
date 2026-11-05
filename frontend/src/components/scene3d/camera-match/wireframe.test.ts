import { readFileSync } from "node:fs";
import { join } from "node:path";
import { decode } from "jpeg-js";
import { describe, expect, it } from "vitest";
import type { CameraPose, RoomSpec } from "../core/geometry";
import { wireframe } from "./wireframe";

const fixtures = join(import.meta.dirname, "../../../../../fixtures");
const read = (name: string, file: string) => JSON.parse(readFileSync(join(fixtures, name, file), "utf8"));
const LABEL = [36, 176, 604, 294]; // the PLACEHOLDER box drawn over the photo (fixtures/placeholder_photos.py)

describe.each(["small-bedroom", "home-office", "living-room"])("%s", (name) => {
  const pose: CameraPose = read(name, "camera_pose.json");
  const room: RoomSpec = read(name, "room_spec.json");
  const photo = decode(readFileSync(join(fixtures, "..", pose.photo_key as string)));
  const pixel = (x: number, y: number) => {
    const i = 4 * (y * photo.width + x);
    return photo.data[i] + photo.data[i + 1] + photo.data[i + 2];
  };
  // whether the photo has a dark (edge) pixel within 1 px of there; undefined off the photo and under its label
  const dark = (x: number, y: number) => {
    [x, y] = [Math.round(x), Math.round(y)];
    if (x < 2 || y < 2 || x > photo.width - 3 || y > photo.height - 3 || (x > LABEL[0] && x < LABEL[2] && y > LABEL[1] && y < LABEL[3])) return;
    return [-1, 0, 1].some((dx) => [-1, 0, 1].some((dy) => pixel(x + dx, y + dy) < 3 * 150));
  };
  // every 5 px along each edge, shifted by (dx, dy)
  const along = (dx: number, dy: number) =>
    wireframe(room.dimensions, pose).flatMap(([[x0, y0], [x1, y1]]) => {
      const steps = Math.ceil(Math.hypot(x1 - x0, y1 - y0) / 5);
      return Array.from({ length: steps + 1 }, (_, k) => dark(x0 + ((x1 - x0) * k) / steps + dx, y0 + ((y1 - y0) * k) / steps + dy));
    });

  it("draws the room's edges where the fixture photo shows them", () => {
    expect(photo.width).toBe(pose.image_width);
    const seen = along(0, 0).filter((d) => d !== undefined);
    expect(seen.length).toBeGreaterThan(100);
    expect(seen.filter(Boolean).length / seen.length).toBeGreaterThan(0.98);
    // a few pixels off, it misses them
    const off = along(6, 6).filter((d) => d !== undefined);
    expect(off.filter(Boolean).length / off.length).toBeLessThan(0.2);
  });
});

it("cuts an edge where it passes behind the camera", () => {
  // the small bedroom's camera stands 0.3 m from corner A, which is behind it
  const pose: CameraPose = read("small-bedroom", "camera_pose.json");
  const segments = wireframe({ width: 3.2, length: 3.4, height: 2.6 }, pose);
  expect(segments.length).toBeLessThan(12);
  for (const segment of segments) for (const p of segment) expect(p.every(Number.isFinite)).toBe(true);
});
