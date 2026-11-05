import type { Metadata } from "next";
import { notFound } from "next/navigation";
import type { Corner } from "@/components/scene3d/core";
import { RenderScene } from "./render-scene";

export const metadata: Metadata = { title: "Render", robots: { index: false } };

const CORNERS: Corner[] = ["cornerA", "cornerC"];

// A run's design from one fixed corner, with no app chrome, for screenshots (eval/scripts/capture.ts, the VLM judge).
// The run is a thread: its scene is the thread state's. ?view=cornerA (default) or cornerC, the opposite corner.
export default async function RenderPage({ params, searchParams }: PageProps<"/render/[runId]">) {
  const [{ runId }, { view = "cornerA" }] = await Promise.all([params, searchParams]);
  if (!CORNERS.includes(view as Corner)) notFound();
  return (
    <main className="h-svh w-svw">
      <RenderScene runId={runId} corner={view as Corner} />
    </main>
  );
}
