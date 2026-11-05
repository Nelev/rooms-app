import { PerspectiveCamera, Vector3 } from "three";
import { type CameraPose, type RoomSpec, toThree } from "../core/geometry";

export type Pixel = [number, number];
export type Segment = [Pixel, Pixel];

const NEAR = 0.05; // m: the part of an edge closer to the camera's plane than this is cut off

// The room's 12 edges (floor, ceiling, corners) as the pose's camera sees them, in pixels of its photo; an edge is cut where it
// passes behind the camera, and may run past the photo's borders.
export function wireframe({ width, length, height }: RoomSpec["dimensions"], pose: CameraPose): Segment[] {
  const camera = new PerspectiveCamera(pose.fov, pose.image_width / pose.image_height, NEAR);
  camera.position.set(...pose.position);
  camera.quaternion.set(...pose.quaternion);
  camera.updateMatrixWorld();
  const floor = [
    [0, 0],
    [width, 0],
    [width, length],
    [0, length],
  ];
  // in the camera's frame, which looks down -z
  const corner = (i: number, z: number) => new Vector3(...toThree(floor[i % 4][0], floor[i % 4][1], z)).applyMatrix4(camera.matrixWorldInverse);
  const pixel = (p: Vector3): Pixel => {
    const { x, y } = p.clone().applyMatrix4(camera.projectionMatrix);
    return [((x + 1) / 2) * pose.image_width, ((1 - y) / 2) * pose.image_height];
  };
  const cut = (p: Vector3, q: Vector3) => (p.z > -NEAR ? p.clone().lerp(q, (p.z + NEAR) / (p.z - q.z)) : p);
  return [0, 1, 2, 3]
    .flatMap((i) => [
      [corner(i, 0), corner(i + 1, 0)],
      [corner(i, height), corner(i + 1, height)],
      [corner(i, 0), corner(i, height)],
    ])
    .filter(([a, b]) => Math.min(a.z, b.z) <= -NEAR)
    .map(([a, b]): Segment => [pixel(cut(a, b)), pixel(cut(b, a))]);
}
