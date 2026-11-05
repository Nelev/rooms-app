"use client";

import { type Corner, SceneViewer } from "@/components/scene3d/core";
import { useThread } from "@/lib/hooks/use-threads";

export function RenderScene({ runId, corner }: { runId: string; corner: Corner }) {
  const { data, error, loading } = useThread(runId);
  const scene = data?.values.scene;
  if (scene) return <SceneViewer scene={scene} corner={corner} />;
  if (loading) return null;
  return <p role="alert">{error ? `The run could not be loaded: ${error.message}` : "The run has no scene yet."}</p>;
}
