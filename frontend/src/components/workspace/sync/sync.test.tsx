// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { stubApi } from "@/lib/mocks/stub-api";
import { chatEdit, HIGHLIGHT_MS, WorkspaceProvider } from "./store";
import { WorkspaceChat, WorkspaceResults, WorkspaceScene } from "./views";

// three.js needs WebGL: the 3D view shows the data it was given, and its items can be clicked
vi.mock("@/components/scene3d/look", () => ({
  LitSceneViewer: ({
    scene,
    highlighted,
    onPick,
  }: {
    scene: { items: { node_id: string; item_id: string }[] };
    highlighted: string[];
    onPick: (id: string) => void;
  }) => (
    <ul aria-label="3D view">
      {scene.items.map(({ node_id, item_id }) => (
        <li key={node_id} data-highlighted={highlighted.includes(node_id) || undefined}>
          <button type="button" onClick={() => onPick(node_id)}>
            3D {node_id}: {item_id}
          </button>
        </li>
      ))}
    </ul>
  ),
}));

const chat = JSON.parse(readFileSync(join(import.meta.dirname, "../../../../../fixtures/small-bedroom/chat.json"), "utf8"));

let api: ReturnType<typeof stubApi>;

// the project designed (the design run, then the room confirmed); timers are fake, to end the highlight, but run on with real time
beforeEach(async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true, advanceTimeDelta: 1, toFake: ["setTimeout", "clearTimeout"] });
  api = stubApi();
  const url = `http://localhost/threads/${api.thread.thread_id}/runs/stream`;
  for (const body of [{ input: {} }, { command: {} }]) await (await api.fetch(url, { method: "POST", body: JSON.stringify(body) })).text();
  vi.stubGlobal("fetch", vi.fn(api.fetch));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

function renderWorkspace() {
  render(
    <WorkspaceProvider threadId={api.thread.thread_id}>
      <WorkspaceResults />
      <WorkspaceScene />
      <WorkspaceChat />
    </WorkspaceProvider>,
  );
}

const shoppingList = () => within(screen.getByRole("heading", { name: "Shopping list" }).parentElement as HTMLElement).getAllByRole("listitem");
const highlighted = () =>
  [...document.querySelectorAll("[data-highlighted]")].map((e) => (e.closest("svg") ? "plan" : e.closest("[aria-label='3D view']") ? "3D" : "list"));
const input = () => screen.getByRole("textbox", { name: "Message" }) as HTMLInputElement;

it("tells a chat edit from a design run and an undo", () => {
  const [done, edited, refused] = [2, 3, 4].map((i) => api.states[i]);
  expect(chatEdit(done, edited)).toMatchObject({ changed: ["desk_chair"] });
  expect(chatEdit(edited, refused)).toBeUndefined(); // a refused edit changes nothing: nothing to undo
  expect(chatEdit(edited, done)).toBeUndefined(); // the undo
  expect(chatEdit(api.states[1], done)).toBeUndefined(); // the design run
});

it("updates the plan, the results and the 3D view together from the fixture diff, highlights it for a while, and undoes it", async () => {
  renderWorkspace();
  await screen.findByText("3D desk_chair: grey-desk-chair");
  expect(shoppingList().filter((li) => li.dataset.id)).toHaveLength(4);
  expect(screen.queryByRole("button", { name: "Undo" })).toBeNull();

  // once the design run the chat panel rejoins is over (the store and the chat panel then read the state again)
  const stateFetches = () => vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith("/state")).length;
  await waitFor(() => expect(stateFetches()).toBe(4), { timeout: 5000 });
  fireEvent.change(input(), { target: { value: chat[0].input.chat_message } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  expect(screen.queryByRole("button", { name: "Undo" })).toBeNull();

  // the run ended and the state was read again: every view shows the edit, with the changed item highlighted
  await screen.findByText("3D desk_chair: white-desk-chair", {}, { timeout: 5000 });
  expect(screen.getByText(chat[0].output.rationale, { selector: "section p" })).toBeTruthy(); // the results' rationale
  expect(shoppingList().filter((li) => li.dataset.id)).toHaveLength(3); // the stub swaps the desk chair for one it does not look up
  expect(highlighted().sort()).toEqual(["3D", "plan"]);
  expect(document.querySelector('svg [data-highlighted][data-id="desk_chair"]')).toBeTruthy();
  expect(screen.getByText("Changed: desk chair")).toBeTruthy();

  // the highlight expires, the undo stays
  await act(async () => {}); // the highlight's timer starts
  expect(highlighted()).toHaveLength(2);
  act(() => vi.advanceTimersByTime(HIGHLIGHT_MS));
  expect(highlighted()).toEqual([]);
  const undo = screen.getByRole("button", { name: "Undo" });

  fireEvent.click(undo);
  await screen.findByText("3D desk_chair: grey-desk-chair");
  const [, init] = vi.mocked(fetch).mock.calls.find(([url]) => String(url).endsWith("/revert")) as [string, RequestInit];
  expect(JSON.parse(String(init.body))).toEqual({ checkpoint_id: api.states[2].checkpoint_id }); // the checkpoint before the chat turn
  expect(shoppingList().filter((li) => li.dataset.id)).toHaveLength(4);
  expect(screen.queryByRole("button", { name: "Undo" })).toBeNull();
  // the chat starts over without the undone turn, and the next one shows once
  await waitFor(() => expect(within(screen.getByRole("log")).queryAllByRole("listitem")).toEqual([]));
  fireEvent.change(input(), { target: { value: chat[0].input.chat_message } });
  await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toHaveProperty("disabled", false)); // the rejoined run replayed
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  await screen.findByText("3D desk_chair: white-desk-chair", {}, { timeout: 5000 });
  await waitFor(() => expect(screen.getByRole("button", { name: "Undo" })).toBeTruthy());
  expect(within(screen.getByRole("log")).getAllByText(chat[0].input.chat_message)).toHaveLength(1);
}, 15_000);

it("inserts a reference to an item clicked in the plan or the 3D view into the chat input", async () => {
  renderWorkspace();
  const plan = await screen.findByRole("img", { name: /Floor plan/ });
  fireEvent.click(plan.querySelector('[data-id="bed"]') as Element);
  expect(input().value).toBe("@bed ");
  fireEvent.click(screen.getByText("3D desk: birch-desk-100"));
  expect(input().value).toBe("@bed @desk ");
});
