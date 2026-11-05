// Which new items the photo's kept furniture hides, as the composite draws them: the pure part, testable without WebGL.
import { BoxGeometry, Frustum, Group, Matrix4, Mesh, PerspectiveCamera, Raycaster, Vector3 } from "three";
import { type CameraPose, itemPose, type Scene } from "../core/geometry";

export type Visibility = "visible" | "partly hidden" | "hidden" | "out of view";

type Placed = Scene["room"]["kept_furniture"][number] | Scene["items"][number];

export const NEAR = 0.05; // m, the composite camera's near plane
const INSET = 0.98; // samples sit just inside the box, so one that only grazes an occluder's edge counts as seen

// The pose's camera, as the composite renders it
function poseCamera(pose: CameraPose): PerspectiveCamera {
  const camera = new PerspectiveCamera(pose.fov, pose.image_width / pose.image_height, NEAR);
  camera.position.set(...pose.position);
  camera.quaternion.set(...pose.quaternion);
  camera.updateMatrixWorld();
  return camera;
}

// The item's box where the viewer puts it (its group, the box on its base)
function box({ size, ...placed }: Placed): Mesh {
  const mesh = new Mesh(new BoxGeometry(size.width, size.height, size.depth));
  mesh.position.y = size.height / 2;
  const group = new Group();
  const { position, rotation } = itemPose({ ...placed, size });
  group.position.set(...position);
  group.rotation.set(...rotation);
  group.add(mesh);
  group.updateMatrixWorld(true);
  return mesh;
}

// Each new item's box seen from the pose: its 8 corners and center, each out of the photo, behind a kept item's box or seen.
// An item is hidden when every sample in the photo is behind kept furniture, partly hidden when some are.
export function visibility(scene: Scene, pose: CameraPose): Record<string, Visibility> {
  const camera = poseCamera(pose);
  const frustum = new Frustum().setFromProjectionMatrix(new Matrix4().multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse));
  const kept = scene.room.kept_furniture.map(box);
  const raycaster = new Raycaster();
  return Object.fromEntries(
    scene.items.map((item) => {
      const mesh = box(item);
      const { width, height, depth } = item.size;
      const corners = [-1, 1].flatMap((x) => [-1, 1].flatMap((y) => [-1, 1].map((z) => new Vector3(x * width, y * height, z * depth))));
      const samples = [new Vector3(), ...corners]
        .map((p) => p.multiplyScalar(INSET / 2).applyMatrix4(mesh.matrixWorld))
        .filter((p) => frustum.containsPoint(p));
      const hidden = samples.filter((p) => {
        const distance = p.distanceTo(camera.position);
        raycaster.set(camera.position, p.clone().sub(camera.position).normalize());
        raycaster.far = distance;
        return raycaster.intersectObjects(kept, false).length > 0;
      }).length;
      const seen: Visibility = !samples.length ? "out of view" : hidden === samples.length ? "hidden" : hidden ? "partly hidden" : "visible";
      return [item.node_id, seen];
    }),
  );
}
