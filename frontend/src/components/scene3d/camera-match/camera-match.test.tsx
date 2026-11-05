// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { stubApi } from "@/lib/mocks/stub-api";
import { CameraMatch } from "./camera-match";
import { wireframe } from "./wireframe";

const read = (file: string) => JSON.parse(readFileSync(join(import.meta.dirname, "../../../../../fixtures/small-bedroom", file), "utf8"));
const pose = read("camera_pose.json");
const room = read("room_spec.json").dimensions;
const photo = { key: pose.photo_key, url: "/photo-1.jpg" };

let api: ReturnType<typeof stubApi>;
const fetch = vi.fn((...args: Parameters<typeof globalThis.fetch>) => api.fetch(...args));

beforeEach(() => {
  api = stubApi();
  vi.stubGlobal("fetch", fetch);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  fetch.mockClear();
});

// the photo loads at 640 x 480 and is shown at half its size
function load(onConfirm = () => {}) {
  const { container } = render(<CameraMatch threadId={api.thread.thread_id} photo={photo} room={room} onConfirm={onConfirm} />);
  const img = screen.getByRole("img", { name: "Your room" }) as HTMLImageElement;
  Object.defineProperties(img, { naturalWidth: { value: 640 }, naturalHeight: { value: 480 } });
  fireEvent.load(img);
  const overlay = screen.getByRole("img", { name: /^Photo overlay/ });
  overlay.getBoundingClientRect = () => ({ left: 10, top: 20, width: 320, height: 240 }) as DOMRect;
  return { container, overlay };
}

const button = (name: string) => screen.getByRole("button", { name }) as HTMLButtonElement;

it("places the picked corners, matches the camera and draws the room from the returned pose over the photo", async () => {
  const onConfirm = vi.fn();
  const { container, overlay } = load(onConfirm);
  // the corners are placed in turn, from Floor A; a picked corner is placed again where it is clicked
  for (const [x, y] of [
    [10, 20],
    [100, 120],
    [170, 120],
  ])
    fireEvent.click(overlay, { clientX: x, clientY: y });
  fireEvent.click(button("Ceiling A"));
  fireEvent.click(overlay, { clientX: 170, clientY: 60 });
  expect(button("Match camera").disabled).toBe(false);
  fireEvent.click(button("Floor A ✓"));
  fireEvent.click(overlay, { clientX: 30, clientY: 220 });

  fireEvent.click(button("Match camera"));
  await screen.findByText(/2\.8 px off/);
  const [url, init] = fetch.mock.calls[0];
  expect(String(url)).toMatch(new RegExp(`/threads/${api.thread.thread_id}/camera-pose$`));
  expect(JSON.parse(String(init?.body))).toEqual({
    photo_key: pose.photo_key,
    image_width: 640,
    image_height: 480,
    points: [
      { corner: "B", ceiling: false, x: 180, y: 200 },
      { corner: "C", ceiling: false, x: 320, y: 200 },
      { corner: "A", ceiling: true, x: 320, y: 80 },
      { corner: "A", ceiling: false, x: 40, y: 400 },
    ],
  });

  // the fixture pose's wireframe, which lines up with the fixture photo (wireframe.test.ts), in the photo's pixels
  const lines = [...container.querySelectorAll("line")].map((l) => ["x1", "y1", "x2", "y2"].map((a) => Number(l.getAttribute(a))));
  expect(lines).toEqual(wireframe(room, pose).map((s) => s.flat()));
  expect(container.querySelector("svg")?.getAttribute("viewBox")).toBe("0 0 640 480");

  fireEvent.click(button("Confirm"));
  expect(onConfirm).toHaveBeenCalledWith(pose);
});

it("shows why no camera fits, then lets the user redo the corners", async () => {
  fetch.mockImplementationOnce(
    async () => new Response(JSON.stringify({ detail: "The points are 40 px off the best camera pose" }), { status: 400 }),
  );
  const { container, overlay } = load();
  for (let i = 0; i < 4; i++) fireEvent.click(overlay, { clientX: 20 + 40 * i, clientY: 100 });
  expect(container.querySelectorAll("circle")).toHaveLength(4);
  fireEvent.click(button("Match camera"));
  expect((await screen.findByRole("alert")).textContent).toBe("The points are 40 px off the best camera pose");
  expect(container.querySelectorAll("line")).toHaveLength(0);

  // Clear drops the corners and the stale error
  fireEvent.click(button("Clear"));
  expect(screen.queryByRole("alert")).toBeNull();
  expect(container.querySelectorAll("circle")).toHaveLength(0);

  // the stub answers the fixture pose; Redo starts over
  for (let i = 0; i < 4; i++) fireEvent.click(overlay, { clientX: 20 + 40 * i, clientY: 100 });
  fireEvent.click(button("Match camera"));
  await screen.findByText(/2\.8 px off/);
  fireEvent.click(button("Redo"));
  expect(container.querySelectorAll("circle, line")).toHaveLength(0);
  expect(button("Match camera").disabled).toBe(true);
  expect(button("Floor A").getAttribute("aria-pressed")).toBe("true");
});
