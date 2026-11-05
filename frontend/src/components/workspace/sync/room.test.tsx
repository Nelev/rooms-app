// @vitest-environment jsdom
import { act, cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { photoUrl } from "@/lib/api";
import { runEnded } from "@/lib/hooks/use-threads";
import { stubApi } from "@/lib/mocks/stub-api";
import { WorkspaceProvider } from "./store";
import { WorkspaceRoom } from "./views";

// the stream hook calls runEnded once it has read the whole run: the test waits for that, not for a timeout, however slow the replay.
// The mock replaces runEnded, so the refetch after a run is skipped: the state fetched during the replay is already final.
vi.mock("@/lib/hooks/use-threads", { spy: true });

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

// the project after its design run (paused at confirm_room), then after the room was confirmed (done)
it.each([
  { state: "interrupt", runs: [{ input: {} }], confirm: true },
  { state: "done", runs: [{ input: {} }, { command: {} }], confirm: false },
])("shows the run, the photo and the room plan, $state", async ({ runs, confirm }) => {
  const api = stubApi();
  const url = `http://localhost/threads/${api.thread.thread_id}/runs/stream`;
  for (const body of runs) await (await api.fetch(url, { method: "POST", body: JSON.stringify(body) })).text();
  vi.stubGlobal("fetch", vi.fn(api.fetch));
  const replayed = new Promise<void>((resolve) => vi.mocked(runEnded).mockImplementationOnce(() => resolve()));
  render(
    <WorkspaceProvider threadId={api.thread.thread_id}>
      <WorkspaceRoom />
    </WorkspaceProvider>,
  );
  // within act, React keeps every update of the replay until it is over, then renders them all: the assertions below see the
  // end of the run, however slow the machine. The thread's state and history GETs settle in microtasks, long before the replay's
  // many setTimeout-paced chunks end: an event-loop order, not a timing.
  await act(() => replayed);

  const photo = screen.getByRole("img", { name: "Your room, view 1" }) as HTMLImageElement;
  expect(photo.src).toBe(photoUrl("fixtures/small-bedroom/photo-1.jpg"));
  expect(screen.getByRole("img", { name: /Floor plan/ })).toBeTruthy();
  // the timeline of the rejoined run
  const timeline = screen.getByRole("region", { name: "Run progress" });
  expect(within(timeline).getByText("Analyze room")).toBeTruthy();
  expect(within(timeline).queryByText("running")).toBeNull();
  const link = screen.queryByRole("link", { name: "Confirm the room" });
  if (confirm) expect(link?.getAttribute("href")).toBe(`/projects/${api.thread.thread_id}/room`);
  else {
    expect(within(timeline).getByText("Present")).toBeTruthy();
    expect(link).toBeNull();
  }
});
