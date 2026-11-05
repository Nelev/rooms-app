"use client";

import { PerspectiveCamera } from "@react-three/drei";
import { Canvas, type RootState } from "@react-three/fiber";
import { useId, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { itemPose, type Scene, toThree } from "../core/geometry";
import { Item } from "../core/viewer";
import { Lights } from "../look/lights";
import { NEAR } from "./occlusion";

const SHADOW_OPACITY = 0.35;

// The photo with the drawn canvas over it, at the photo's own size, as a PNG data URL
export function compose(photo: HTMLImageElement, overlay: HTMLCanvasElement): string {
  const canvas = document.createElement("canvas");
  canvas.width = photo.naturalWidth;
  canvas.height = photo.naturalHeight;
  const ctx = canvas.getContext("2d") as CanvasRenderingContext2D;
  ctx.drawImage(photo, 0, 0);
  ctx.drawImage(overlay, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/png");
}

type Props = { scene: Scene; camera: number; photoUrl: string };

// The design in the user's photo: only the new furniture, rendered from the photo's matched camera (scene.cameras[camera]) on a
// transparent canvas over it. The floor only catches their shadows, and the kept furniture, already in the photo, is drawn first
// into the depth buffer alone, so whatever stands behind it is hidden. A slider wipes between the photo (before) and the composite
// (after); the export is the full composite at the photo's size.
export function Composite({ scene, camera, photoUrl }: Props) {
  const pose = scene.cameras[camera];
  const { width, length } = scene.room.dimensions;
  const [split, setSplit] = useState(50); // % of the width, from the left, that shows the photo alone
  const photo = useRef<HTMLImageElement>(null);
  const three = useRef<RootState>(null);
  const id = useId();

  function download() {
    if (!photo.current || !three.current) return;
    // Render once more at the photo's own resolution, so the furniture is as sharp as the photo, and read the canvas back in the
    // same task: the drawing buffer is not cleared before then, so it need not be preserved.
    const { gl, scene: world, camera: view, invalidate } = three.current;
    const dpr = gl.getPixelRatio();
    gl.setPixelRatio(photo.current.naturalWidth / gl.domElement.clientWidth);
    gl.render(world, view);
    const png = compose(photo.current, gl.domElement);
    gl.setPixelRatio(dpr);
    invalidate();
    const link = document.createElement("a");
    link.href = png;
    link.download = "design-in-your-photo.png";
    link.click();
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="relative w-full overflow-hidden rounded-lg bg-muted" style={{ aspectRatio: `${pose.image_width} / ${pose.image_height}` }}>
        {/* biome-ignore lint/performance/noImgElement: a user's photo, read back into the exported PNG */}
        <img ref={photo} src={photoUrl} alt="Your room" crossOrigin="anonymous" className="absolute inset-0 size-full" />
        <div className="absolute inset-0" style={{ clipPath: `inset(0 0 0 ${split}%)` }}>
          <Canvas
            onCreated={(state) => {
              three.current = state;
            }}
            frameloop="demand"
            shadows="percentage"
            aria-label="The new furniture in your photo"
          >
            <PerspectiveCamera makeDefault position={pose.position} quaternion={pose.quaternion} fov={pose.fov} near={NEAR} />
            <Lights scene={scene} />
            <mesh position={toThree(width / 2, length / 2)} rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
              <planeGeometry args={[width, length]} />
              <shadowMaterial opacity={SHADOW_OPACITY} />
            </mesh>
            {scene.items.map((item) => (
              <Item key={item.node_id} item={item} />
            ))}
            {scene.room.kept_furniture.map((kept) => (
              <group key={kept.id} {...itemPose(kept)}>
                <mesh position={[0, kept.size.height / 2, 0]} renderOrder={-1}>
                  <boxGeometry args={[kept.size.width, kept.size.height, kept.size.depth]} />
                  <meshBasicMaterial colorWrite={false} />
                </mesh>
              </group>
            ))}
          </Canvas>
        </div>
        <div className="pointer-events-none absolute inset-y-0 w-0.5 bg-white/80" style={{ left: `${split}%` }} />
      </div>
      <div className="flex items-center gap-3 text-sm">
        <span id={`${id}-split`} className="sr-only">
          Before and after
        </span>
        <span aria-hidden>Before</span>
        <Slider aria-labelledby={`${id}-split`} value={[split]} onValueChange={(v) => setSplit(Array.isArray(v) ? v[0] : v)} />
        <span aria-hidden>After</span>
        <Button size="sm" onClick={download}>
          Export PNG
        </Button>
      </div>
    </div>
  );
}
