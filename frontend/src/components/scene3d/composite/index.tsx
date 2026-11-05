"use client";

import dynamic from "next/dynamic";
import { Skeleton } from "@/components/ui/skeleton";

// three.js needs the browser: the composite loads on the client only, in its own chunk
export const PhotoComposite = dynamic(() => import("./composite").then((m) => m.Composite), {
  ssr: false,
  loading: () => <Skeleton className="aspect-4/3 w-full" />,
});
