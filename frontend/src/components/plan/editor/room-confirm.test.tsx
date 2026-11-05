// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import Ajv from "ajv";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { stubApi } from "@/lib/mocks/stub-api";
import { RoomConfirm } from "./room-confirm";

const read = (name: string) => JSON.parse(readFileSync(join(import.meta.dirname, "../../../../../fixtures/small-bedroom", name), "utf8"));
const room = read("room_spec.json");
const validRoomSpec = new Ajv({ strict: false }).compile(read("../../contracts/schemas/RoomSpec.json")); // what the API checks the resume against
const design = { input: { photo_keys: ["fixtures/small-bedroom/photo-1.jpg"], dimensions: room.dimensions, brief: read("brief.json") } };

let api: ReturnType<typeof stubApi>;
const url = (path: string) => `http://localhost:8000${path.replace("{thread_id}", api.thread.thread_id)}`;

beforeEach(() => {
  api = stubApi();
  vi.stubGlobal("fetch", vi.fn(api.fetch));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

// the stub's design run, played to its confirm_room interrupt
async function analyzed() {
  await (await api.fetch(url("/threads/{thread_id}/runs/stream"), { method: "POST", body: JSON.stringify(design) })).text();
  render(<RoomConfirm threadId={api.thread.thread_id} />);
  return (await screen.findByRole("button", { name: "Confirm room" })) as HTMLButtonElement;
}
const entry = (id: string) => document.querySelector(`[data-entry="${id}"]`) as HTMLElement;
const field = (id: string, label: string) => within(entry(id)).getByLabelText(label) as HTMLInputElement;

test("without an open interrupt there is nothing to confirm", async () => {
  render(<RoomConfirm threadId={api.thread.thread_id} />);
  expect(await screen.findByText("Nothing to confirm")).toBeTruthy();
});

test("shows the detected features, the unsure ones highlighted, next to the photos and the plan", async () => {
  await analyzed();
  const photo = screen.getByRole("img", { name: "Your room, view 1" }) as HTMLImageElement; // no overlays yet: the photo stands in
  expect(photo.src).toBe("http://localhost:8000/uploads/fixtures/small-bedroom/photo-1.jpg");
  expect(within(entry("radiator_1")).getByText("70% sure: check it")).toBeTruthy();
  expect(within(entry("door_1")).getByText("95% sure")).toBeTruthy();
  expect(document.querySelector('svg [data-id="radiator_1"] .fill-amber-500\\/30')).not.toBeNull();
  expect(document.querySelector('svg [data-id="door_1"] .fill-amber-500\\/30')).toBeNull();
});

test("a feature dragged on the plan moves to the nearest wall", async () => {
  await analyzed();
  const svg = document.querySelector('svg[role="img"]') as SVGSVGElement;
  // one pixel per viewBox unit: the room (3.2 x 3.4 m) starts 40 px in, a meter is 100 px, y points down
  const [, , w, h] = (svg.getAttribute("viewBox") as string).split(" ").map(Number);
  svg.getBoundingClientRect = () => ({ left: 0, top: 0, width: w, height: h }) as DOMRect;
  const window = document.querySelector('svg [data-id="window_1"] line') as Element;
  fireEvent.pointerDown(window, { clientX: 200, clientY: 40, pointerId: 1 });
  fireEvent.pointerMove(window, { clientX: 350, clientY: 40 + 340 - 100, pointerId: 1 }); // (3.1, 1.0) m: 0.1 m from wall B
  fireEvent.pointerUp(window, { pointerId: 1 });
  expect(field("window_1", "Wall").value).toBe("B");
  expect(field("window_1", "Center from wall start (m)").value).toBe("1");
});

test("the room can only be confirmed while it is valid", async () => {
  const confirm = await analyzed();
  fireEvent.change(screen.getByLabelText("Width, walls A and C (m)"), { target: { value: "" } });
  // the width, and without it no feature fits on walls A and C nor is the wardrobe in the room
  expect(screen.getByText("Fix 5 problems to confirm")).toBeTruthy();
  expect(confirm.disabled).toBe(true);
  fireEvent.change(screen.getByLabelText("Width, walls A and C (m)"), { target: { value: "3.5" } });
  fireEvent.change(field("window_1", "Width (m)"), { target: { value: "4" } });
  expect(within(entry("window_1")).getByText("Must fit on wall C")).toBeTruthy();
  fireEvent.change(field("window_1", "Width (m)"), { target: { value: "1.2" } });
  expect(confirm.disabled).toBe(false);
});

test("edits resume the run with the corrected, schema-valid room", async () => {
  const confirm = await analyzed();
  fireEvent.click(screen.getByRole("button", { name: "Delete radiator_1" }));
  fireEvent.click(screen.getByRole("button", { name: /Add feature/ }));
  fireEvent.change(field("feature_1", "Type"), { target: { value: "door" } });
  fireEvent.change(field("feature_1", "Wall"), { target: { value: "D" } });
  fireEvent.change(field("feature_1", "Hinge"), { target: { value: "right" } });
  fireEvent.click(screen.getByRole("button", { name: /Add furniture/ }));
  fireEvent.change(field("kept_2", "Name"), { target: { value: "desk" } });
  fireEvent.change(field("kept_1", "Rotation (°)"), { target: { value: "90" } });
  fireEvent.change(screen.getByLabelText("Ceiling height (m)"), { target: { value: "2.7" } });
  fireEvent.click(confirm);

  expect(await screen.findByText("Room confirmed")).toBeTruthy();
  const [, init] = vi.mocked(fetch).mock.calls.find(([, init]) => init?.method === "POST") as [string, RequestInit];
  const resumed = JSON.parse(String(init.body)).command.resume;
  expect(validRoomSpec(resumed), JSON.stringify(validRoomSpec.errors)).toBe(true);
  expect(resumed.dimensions.height).toBe(2.7);
  expect(resumed.features.map((f: { id: string }) => f.id)).toEqual(["door_1", "window_1", "feature_1"]);
  expect(resumed.features[2]).toMatchObject({ type: "door", wall: "D", hinge: "right", confidence: 1 });
  expect(resumed.kept_furniture).toMatchObject([
    { id: "kept_1", rotation: 90 },
    { id: "kept_2", name: "desk", x: 1.6, y: 1.7 },
  ]);
  // the stub accepted the resume (it answers a 409 when there is no interrupt to resume)
  expect((await (await api.fetch(url("/threads/{thread_id}/state"))).json()).status).toBe("done");
  expect(screen.queryByRole("alert")).toBeNull();
});

test("a resume that fails keeps the user's edits", async () => {
  const confirm = await analyzed();
  fireEvent.change(screen.getByLabelText("Ceiling height (m)"), { target: { value: "2.7" } });
  vi.mocked(fetch).mockRejectedValueOnce(new TypeError("Failed to fetch")); // the resume cannot be sent
  fireEvent.click(confirm);

  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(screen.queryByText("Room confirmed")).toBeNull();
  expect((screen.getByLabelText("Ceiling height (m)") as HTMLInputElement).value).toBe("2.7");
  expect((screen.getByRole("button", { name: "Confirm room" }) as HTMLButtonElement).disabled).toBe(false);
});
