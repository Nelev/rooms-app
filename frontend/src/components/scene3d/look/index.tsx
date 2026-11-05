"use client";

import dynamic from "next/dynamic";
import type { ComponentProps } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import type { Viewer as CoreViewer } from "../core/viewer";

// The 3D viewer with its materials and lights: core's viewer, client only, in its own chunk with three.js
export const LitSceneViewer = dynamic(
  async () => {
    const [{ Viewer }, { FloorMaterial }, { Lights }] = await Promise.all([import("../core/viewer"), import("./floor"), import("./lights")]);
    return function LitViewer(props: Omit<ComponentProps<typeof CoreViewer>, "floor" | "lights">) {
      return <Viewer {...props} floor={<FloorMaterial room={props.scene.room} />} lights={<Lights scene={props.scene} />} />;
    };
  },
  { ssr: false, loading: () => <Skeleton className="size-full min-h-80" /> },
);
