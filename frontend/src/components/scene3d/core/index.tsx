"use client";

import dynamic from "next/dynamic";
import { Skeleton } from "@/components/ui/skeleton";

export type { Scene } from "./geometry";
export type { Corner } from "./viewer";

// three.js needs the browser: the viewer loads on the client only, in its own chunk
export const SceneViewer = dynamic(() => import("./viewer").then((m) => m.Viewer), {
  ssr: false,
  loading: () => <Skeleton className="size-full min-h-80" />,
});
