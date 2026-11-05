// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { stubApi } from "@/lib/mocks/stub-api";
import { PhotoView } from "./photo-view";

// the composite needs WebGL: it shows what it is given
vi.mock("@/components/scene3d/composite", () => ({
  PhotoComposite: ({ scene, camera, photoUrl }: { scene: { items: unknown[] }; camera: number; photoUrl: string }) => (
    <div data-testid="composite">{`${scene.items.length} items, camera ${camera}, ${photoUrl}`}</div>
  ),
}));

let api: ReturnType<typeof stubApi>;
let step = 2; // the stub's state: 2 is the finished design, 0 a new project

beforeEach(() => {
  api = stubApi();
  vi.stubGlobal("fetch", (input: string, init?: RequestInit) =>
    String(input).endsWith("/state") ? Promise.resolve(new Response(JSON.stringify(api.states[step]))) : api.fetch(input, init),
  );
  Object.assign(URL, { createObjectURL: () => "blob:photo-1", revokeObjectURL: () => {} }); // jsdom has neither
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  step = 2;
});

it("composes the design over the photo the user opens", async () => {
  render(<PhotoView threadId={api.thread.thread_id} />);
  const input = await screen.findByLabelText("Open the photo photo-1.jpg");
  expect(screen.queryByTestId("composite")).toBeNull();
  fireEvent.change(input, { target: { files: [new File(["jpg"], "photo-1.jpg", { type: "image/jpeg" })] } });
  expect(screen.getByTestId("composite").textContent).toBe("4 items, camera 0, blob:photo-1");
});

it("waits for a design", async () => {
  step = 0;
  render(<PhotoView threadId={api.thread.thread_id} />);
  expect(await screen.findByText("No design yet.")).toBeTruthy();
});
