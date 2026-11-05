"use client";

import { Clone, OrbitControls, PerspectiveCamera, useGLTF } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";
import { Component, type ReactNode, Suspense, useState } from "react";
import { Box3, Shape, Vector2 } from "three";
import { Button } from "@/components/ui/button";
import { type CameraPose, type Front, glbFit, itemPose, type Scene, toThree, viewpoints, WALL_THICKNESS, wallMeshes } from "./geometry";

type Size = Scene["items"][number]["size"];
type View = "orbit" | "eye" | number; // a number is the index of a photo's camera in scene.cameras

const WALL_COLOR = "#f2efe9";
const FLOOR_COLOR = "#c8b49a";
const ITEM_COLOR = "#a8a29e";

const shape = (points: [number, number][]) => points.map(([u, v]) => new Vector2(u, v));

function Room({ room }: { room: Scene["room"] }) {
  const { width, length, height } = room.dimensions;
  const center = toThree(width / 2, length / 2);
  return (
    <>
      {wallMeshes(room).map((wall) => {
        const outline = new Shape(shape(wall.outline));
        outline.holes = wall.holes.map((hole) => new Shape(shape(hole)));
        return (
          <mesh key={wall.wall} position={wall.position} rotation={wall.rotation}>
            <extrudeGeometry args={[outline, { depth: WALL_THICKNESS, bevelEnabled: false }]} />
            <meshStandardMaterial color={room.walls.find((w) => w.wall === wall.wall)?.color ?? WALL_COLOR} />
          </mesh>
        );
      })}
      <mesh position={center} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[width, length]} />
        <meshStandardMaterial color={FLOOR_COLOR} />
      </mesh>
      {/* faces down, so it hides nothing from the orbit camera above */}
      <mesh position={[center[0], height, center[2]]} rotation={[Math.PI / 2, 0, 0]}>
        <planeGeometry args={[width, length]} />
        <meshStandardMaterial color={WALL_COLOR} />
      </mesh>
    </>
  );
}

function Box({ size }: { size: Size }) {
  return (
    <mesh position={[0, size.height / 2, 0]}>
      <boxGeometry args={[size.width, size.height, size.depth]} />
      <meshStandardMaterial color={ITEM_COLOR} />
    </mesh>
  );
}

function Model({ url, front, size }: { url: string; front: Front; size: Size }) {
  const { scene } = useGLTF(url);
  const { min, max } = new Box3().setFromObject(scene);
  const fit = glbFit(front, min.toArray(), max.toArray(), size);
  return (
    <group rotation={fit.rotation} scale={fit.scale}>
      <group position={fit.offset}>
        <Clone object={scene} />
      </group>
    </group>
  );
}

// a model that cannot be loaded renders as its box
class Fallback extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

function Item({ item }: { item: Scene["items"][number] }) {
  const { position, rotation } = itemPose(item);
  const box = <Box size={item.size} />;
  const url = item.item?.glb_url;
  return (
    <group position={position} rotation={rotation}>
      {url ? (
        <Fallback fallback={box}>
          <Suspense fallback={box}>
            <Model url={url} front={item.item?.front ?? "+z"} size={item.size} />
          </Suspense>
        </Fallback>
      ) : (
        box
      )}
    </group>
  );
}

function Camera({ view, scene }: { view: View; scene: Scene }) {
  if (typeof view === "number") {
    const pose: CameraPose = scene.cameras[view];
    return <PerspectiveCamera key={view} makeDefault position={pose.position} quaternion={pose.quaternion} fov={pose.fov} near={0.05} />;
  }
  const { position, target } = viewpoints(scene.room.dimensions)[view];
  const eye = view === "eye";
  return (
    <>
      <PerspectiveCamera key={view} makeDefault position={position} fov={eye ? 65 : 45} near={0.05} />
      <OrbitControls
        key={`${view}-controls`}
        makeDefault
        target={target}
        // at eye level the camera only turns in place, at 1.6 m
        {...(eye && { minPolarAngle: Math.PI / 2, maxPolarAngle: Math.PI / 2, enableZoom: false, enablePan: false })}
      />
    </>
  );
}

// The design in 3D: the room with its openings and every item, a GLB where the catalog has one and a box otherwise.
// Renders on demand only. Load it through `SceneViewer` (index.tsx), which skips server rendering.
export function Viewer({ scene }: { scene: Scene }) {
  const [view, setView] = useState<View>("orbit");
  const credits = scene.items.flatMap(({ item }) => (item?.glb_url ? [`${item.name}: ${item.description}`] : []));
  return (
    <div className="relative size-full min-h-80">
      <Canvas frameloop="demand" aria-label="3D view of the design">
        <Camera view={view} scene={scene} />
        <hemisphereLight args={["#ffffff", "#b5a48c", 1.5]} />
        <directionalLight position={toThree(scene.room.dimensions.width, -scene.room.dimensions.length, 6)} intensity={1.5} />
        <Room room={scene.room} />
        {scene.items.map((item) => (
          <Item key={item.node_id} item={item} />
        ))}
        {scene.room.kept_furniture.map((kept) => (
          <group key={kept.id} {...itemPose(kept)}>
            <Box size={kept.size} />
          </group>
        ))}
      </Canvas>
      <div className="absolute top-2 left-2 flex flex-wrap gap-1">
        {(["orbit", "eye", ...scene.cameras.map((_, i) => i)] as View[]).map((v) => (
          <Button key={v} size="sm" variant={v === view ? "default" : "outline"} aria-pressed={v === view} onClick={() => setView(v)}>
            {v === "orbit" ? "Orbit" : v === "eye" ? "Eye level" : `Photo ${v + 1}`}
          </Button>
        ))}
      </div>
      {credits.length > 0 ? <p className="absolute bottom-2 left-2 max-w-prose text-muted-foreground text-xs">{credits.join(" · ")}</p> : null}
    </div>
  );
}
