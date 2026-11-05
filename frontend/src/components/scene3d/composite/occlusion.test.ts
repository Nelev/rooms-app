import { readFileSync } from "node:fs";
import { join } from "node:path";
import { Euler, Quaternion } from "three";
import { expect, it } from "vitest";
import type { CameraPose, Scene } from "../core/geometry";
import { visibility } from "./occlusion";

const scene: Scene = JSON.parse(readFileSync(join(import.meta.dirname, "../../../../../fixtures/small-bedroom/scene.json"), "utf8"));
const pose = scene.cameras[0];
const DEG = Math.PI / 180;
// the fixture camera raised above the wardrobe's top (2 m) and turned 25 degrees down
const raised: CameraPose = {
  ...pose,
  position: [0.3, 2.3, -0.3],
  quaternion: new Quaternion().setFromEuler(new Euler(-25 * DEG, -45 * DEG, 0, "YXZ")).toArray() as CameraPose["quaternion"],
};

it("from the fixture camera, the kept wardrobe hides every new item in the photo", () => {
  // the camera stands in corner A at 1.5 m, 10 cm from the side of the 2 m wardrobe (x 0 to 0.6, y 0.4 to 1.4), looking past it
  // into the room: the wardrobe fills the photo, and the desk, against wall D, is out of it
  expect(visibility(scene, pose)).toEqual({ bed: "hidden", nightstand: "hidden", desk: "out of view", desk_chair: "hidden" });
});

it("from above the wardrobe, it hides what stands behind it and the near corner of the bed", () => {
  expect(visibility(scene, raised)).toEqual({ bed: "partly hidden", nightstand: "visible", desk: "hidden", desk_chair: "hidden" });
  // without kept furniture, nothing is hidden
  const empty = { ...scene, room: { ...scene.room, kept_furniture: [] } };
  expect(visibility(empty, raised)).toEqual({ bed: "visible", nightstand: "visible", desk: "visible", desk_chair: "visible" });
});
