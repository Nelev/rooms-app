"use client";

import dynamic from "next/dynamic";
import { Skeleton } from "@/components/ui/skeleton";
import type { Scene } from "../core/geometry";
import type { Corner } from "../core/viewer";

// The 3D viewer with its materials and lights: core's viewer, client only, in its own chunk with three.js
export const LitSceneViewer = dynamic(
  async () => {
    const [{ Viewer }, { FloorMaterial }, { Lights }] = await Promise.all([import("../core/viewer"), import("./floor"), import("./lights")]);
    return function LitViewer({ scene, corner }: { scene: Scene; corner?: Corner }) {
      return <Viewer scene={scene} corner={corner} floor={<FloorMaterial room={scene.room} />} lights={<Lights scene={scene} />} />;
    };
  },
  { ssr: false, loading: () => <Skeleton className="size-full min-h-80" /> },
);
