// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ChatPanel, chatTurn } from "@/components/chat/chat-panel";
import { stubApi } from "@/lib/mocks/stub-api";

// the stub's chat turns: an applied edit, then a refused one
const chat = JSON.parse(readFileSync(join(import.meta.dirname, "../../../../fixtures/small-bedroom/chat.json"), "utf8"));

let api: ReturnType<typeof stubApi>;

// the project designed (the design run, then the room confirmed), as the chat panel finds it
beforeEach(async () => {
  api = stubApi();
  const url = `http://localhost/threads/${api.thread.thread_id}/runs/stream`;
  for (const body of [{ input: {} }, { command: {} }]) await (await api.fetch(url, { method: "POST", body: JSON.stringify(body) })).text();
  vi.stubGlobal("fetch", vi.fn(api.fetch));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const log = () => screen.getByRole("log", { name: "Messages" });
// once the run being read is over (the design run the panel rejoins, say)
async function send(text: string, then = () => {}) {
  fireEvent.change(screen.getByRole("textbox", { name: "Message" }), { target: { value: text } });
  const button = screen.getByRole("button", { name: "Send" }) as HTMLButtonElement;
  await waitFor(() => expect(button.disabled).toBe(false), { timeout: 5000 });
  then();
  fireEvent.click(button);
}
const stateFetches = () => vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith("/state")).length;

it("plays the fixture conversation: an applied edit with its step chips, then a refused one with its reason", async () => {
  render(<ChatPanel threadId={api.thread.thread_id} />);
  await screen.findByRole("button", { name: "desk chair" }); // the design's items, to mention
  expect(within(log()).queryAllByRole("listitem")).toHaveLength(0); // the design run it rejoined is not a chat turn

  await send(chat[0].input.chat_message);
  await within(log()).findByText(chat[0].output.rationale);
  await waitFor(() => expect(within(log()).getByLabelText("Steps").textContent).toContain("updated design"));
  for (const chip of ["swapped desk chair", "re-validated"]) expect(within(log()).getByText(chip)).toBeTruthy();
  await screen.findByLabelText("Suggested replies"); // the run is over

  const fetches = stateFetches();
  await send(chat[1].input.chat_message);
  const refusal = await within(log()).findByRole("alert");
  expect(refusal.textContent).toContain("Edit refused");
  expect(refusal.textContent).toContain("the bed would block the door");
  await waitFor(() => expect(refusal.textContent).toContain(chat[1].output.rationale));

  // once the thread's state is fetched again, the earlier turn comes from its history, each message once
  await waitFor(() => expect(stateFetches()).toBe(fetches + 1));
  await waitFor(() => {
    const text = log().textContent ?? "";
    for (const turn of chat) {
      expect(text.split(turn.input.chat_message)).toHaveLength(2);
      expect(text.split(turn.output.rationale)).toHaveLength(2);
    }
  });
  expect(within(log()).queryByText("swapped desk chair")).toBeNull(); // the chips are the latest run's
}, 15_000);

it("inserts an item reference, shown as a chip, and sends a suggested reply", async () => {
  render(<ChatPanel threadId={api.thread.thread_id} suggestions={["Make it cheaper"]} />);
  fireEvent.click(await screen.findByRole("button", { name: "desk chair" }));
  const input = screen.getByRole("textbox", { name: "Message" }) as HTMLInputElement;
  expect(input.value).toBe("@desk_chair ");

  await send("Swap @desk_chair for a cheaper one", api.hold); // the run stops after its first chunk: the message is the one sent
  const sent = await within(log()).findByText("desk chair");
  expect(sent.tagName).toBe("SPAN");
  expect(sent.parentElement?.textContent).toBe("Swap desk chair for a cheaper one");
  expect(JSON.parse(String(vi.mocked(fetch).mock.calls.at(-1)?.[1]?.body))).toEqual({
    input: { chat_message: "Swap @desk_chair for a cheaper one" },
  });
  expect(screen.queryByLabelText("Suggested replies")).toBeNull(); // not while the assistant answers
  api.release();

  await within(log()).findByText(chat[0].output.rationale);
  fireEvent.click(await screen.findByRole("button", { name: "Make it cheaper" }));
  await within(log()).findByRole("alert"); // the stub's next turn: the refused edit
}, 15_000);

it("lists each refusal of a turn that applies some edits and refuses others, and counts the entries the run added", () => {
  const turn = chatTurn({
    threadId: "t",
    running: false,
    messages: [],
    updates: [
      { route_input: { mode: "chat", messages: [{ role: "user", content: "Move the desk and the bed" }] } },
      { chat_edit: { messages: [{ role: "assistant", content: "Moved the desk; the bed stays." }] } },
    ],
    events: [
      { type: "tool", tool: "move_item", summary: "moved desk", ok: true },
      { type: "tool", tool: "move_item", summary: "refused: the bed would block the door", ok: false },
      { type: "tool", tool: "remove_item", summary: "refused: the wardrobe is required", ok: false },
    ],
  });
  expect(turn?.chips.map((c) => c.ok)).toEqual([true, false, false]);
  expect(turn?.refused).toEqual(["the bed would block the door", "the wardrobe is required"]);
  expect(turn?.added).toBe(2);
});
