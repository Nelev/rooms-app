// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { photoUrl } from "@/lib/api";
import { stubApi } from "@/lib/mocks/stub-api";
import { WorkspaceProvider } from "./store";
import { WorkspaceRoom } from "./views";

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
  render(
    <WorkspaceProvider threadId={api.thread.thread_id}>
      <WorkspaceRoom />
    </WorkspaceProvider>,
  );

  const photo = (await screen.findByRole("img", { name: "Your room, view 1" })) as HTMLImageElement;
  expect(photo.src).toBe(photoUrl("fixtures/small-bedroom/photo-1.jpg"));
  expect(screen.getByRole("img", { name: /Floor plan/ })).toBeTruthy();
  // the timeline, once the rejoined run has replayed
  const timeline = screen.getByRole("region", { name: "Run progress" });
  await waitFor(() => expect(within(timeline).getByText("Analyze room")).toBeTruthy());
  if (confirm) {
    const link = await screen.findByRole("link", { name: "Confirm the room" });
    expect(link.getAttribute("href")).toBe(`/projects/${api.thread.thread_id}/room`);
  } else {
    await within(timeline).findByText("Present");
    await waitFor(() => expect(within(timeline).queryByText("running")).toBeNull()); // the replay is over: the link would show by now
    expect(screen.queryByRole("link", { name: "Confirm the room" })).toBeNull();
  }
});
