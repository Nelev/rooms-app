// @vitest-environment jsdom

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { cleanup, render, screen } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import RenderPage from "./page";
import { RenderScene } from "./render-scene";

// three.js needs WebGL: the viewer shows what it was given
vi.mock("@/components/scene3d/core", () => ({
  SceneViewer: ({ scene, corner }: { scene: { items: unknown[] }; corner: string }) => (
    <p>
      {corner}: {scene.items.length} items
    </p>
  ),
}));
vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("not found");
  },
}));

// the stub API's answers for a project before its first run and after its design run
const state = (name: string) => readFileSync(join(import.meta.dirname, "../../../lib/mocks/stub", name), "utf8");
const answer = (name: string) => vi.mocked(fetch).mockResolvedValue(new Response(state(name), { headers: { "Content-Type": "application/json" } }));

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const page = (view?: string) => RenderPage({ params: Promise.resolve({ runId: "t1" }), searchParams: Promise.resolve(view ? { view } : {}) });

test("/render/[runId] has no app chrome and takes only the two corners", async () => {
  const html = renderToStaticMarkup(await page());
  expect(html).not.toMatch(/<(header|nav|button)/); // the scene loads on the client
  await expect(page("cornerC")).resolves.toBeTruthy();
  await expect(page("orbit")).rejects.toThrow("not found");
});

test("the scene is the run's thread state", async () => {
  answer("state-done.json");
  render(<RenderScene runId="t1" corner="cornerC" />);
  const { items } = JSON.parse(state("state-done.json")).values.scene;
  expect(await screen.findByText(`cornerC: ${items.length} items`)).toBeTruthy();
  expect(new URL(String(vi.mocked(fetch).mock.calls[0][0])).pathname).toBe("/threads/t1/state");
});

test("a run without a scene says so", async () => {
  answer("state-new.json");
  render(<RenderScene runId="t1" corner="cornerA" />);
  expect((await screen.findByRole("alert")).textContent).toBe("The run has no scene yet.");
});
