// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useLayoutEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { RunTimeline } from "@/components/run/run-timeline";
import { historySteps, liveSteps } from "@/components/run/steps";
import type { RunCreate } from "@/lib/api";
import { useRunStream } from "@/lib/hooks/use-run-stream";
import { stubApi } from "@/lib/mocks/stub-api";

const read = (name: string) => JSON.parse(readFileSync(join(import.meta.dirname, "../../../../fixtures/small-bedroom", name), "utf8"));
const fixture = read("stream_events.json");
const room = read("room_spec.json");
const design = {
  input: { photo_keys: ["fixtures/small-bedroom/photo-1.jpg"], dimensions: room.dimensions, brief: read("brief.json") },
} satisfies RunCreate;

let api: ReturnType<typeof stubApi>;
let run: ReturnType<typeof useRunStream>;

// the page: it streams the run and shows it. `run` is the committed state: a transition may have rendered but not committed yet,
// and a test that went on from that render would click a button that is still disabled
function Page() {
  const stream = useRunStream(api.thread.thread_id);
  useLayoutEffect(() => {
    run = stream;
  });
  return <RunTimeline run={stream} />;
}

beforeEach(() => {
  api = stubApi();
  vi.stubGlobal("fetch", vi.fn(api.fetch));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

// each step's row: its name, status, duration and cost (its summary is below)
const rows = () =>
  screen
    .getAllByRole("listitem")
    .filter((li) => li.querySelector(":scope > div"))
    .map((li) => li.querySelector(":scope > div > div")?.textContent);
const ended = () => waitFor(() => expect(!!run.runId && !run.running).toBe(true), { timeout: 5000 });

describe("RunTimeline", () => {
  it("plays back the design run, with the interrupt as an action and the Critic rounds grouped", async () => {
    render(<Page />);
    await screen.findByText("No run yet.");
    run.submit(design);
    await ended();
    expect(rows()).toEqual(["Route inputdone0.01s", "Analyze roomdone9.8s$0.012", "Confirm roomwaiting for you"]);
    expect(screen.getByText("found 1 door, 1 window, 1 radiator")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Confirm room" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Confirm room" })).toBeNull());
    await ended();
    await waitFor(() => expect(rows().at(-1)).toBe("Presentdone5.5s$0.006"));
    const rounds = screen.getAllByText(/^Critic round/).map((p) => p.parentElement as HTMLElement);
    expect(rounds.map((round) => within(round).getAllByRole("listitem").length)).toEqual([5, 5]);
    expect(within(rounds[0]).getByText("1 rule fails: the desk is far from the window")).toBeTruthy();
    // the stream is now the resumed run's: the steps before it come from the history
    expect(rows().slice(0, 2)).toEqual([expect.stringMatching(/^Route inputdone/), expect.stringMatching(/^Analyze roomdone.*\$0\.012$/)]);
    expect(rows().slice(2, 4)).toEqual(["Confirm roomdone0.02s", "Designdone6.1s$0.008"]);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("rebuilds the steps of the run's first part from the history after a reload in the middle of the resumed run", async () => {
    const first = render(<Page />);
    run.submit(design);
    await ended();
    api.hold();
    fireEvent.click(screen.getByRole("button", { name: "Confirm room" }));
    await waitFor(() => expect(rows().at(-1)).toBe("Confirm roomrunning"));
    first.unmount(); // the page reloads
    api.release();

    render(<Page />);
    await ended();
    await waitFor(() => expect(rows().at(-1)).toBe("Presentdone5.5s$0.006"));
    const steps = rows();
    expect(steps[0]).toMatch(/^Route inputdone/); // from the history: no summary, its duration the time between checkpoints
    expect(steps[1]).toMatch(/^Analyze roomdone.*\$0\.012$/);
    expect(screen.queryByText("found 1 door, 1 window, 1 radiator")).toBeNull();
    expect(steps.slice(2, 4)).toEqual(["Confirm roomdone0.02s", "Designdone6.1s$0.008"]); // from the stream
    expect(screen.getAllByText(/^Critic round/)).toHaveLength(2);
  });

  it("shows the open interrupt from the history when there is no run to rejoin", async () => {
    render(<Page />);
    run.submit(design);
    await ended();
    cleanup();
    vi.mocked(fetch).mockImplementation((input, init) =>
      String(input).endsWith("/runs/current/stream") ? Promise.resolve(new Response(null, { status: 404 })) : api.fetch(String(input), init),
    ); // the server restarted
    render(<Page />);
    await screen.findByRole("button", { name: "Confirm room" });
    expect(rows().map((r) => r?.split("done")[0])).toEqual(["Route input", "Analyze room", "Confirm roomwaiting for you"]);
  });

  it("says what went wrong, and retries", async () => {
    render(<Page />);
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2)); // the run to rejoin, the history
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError("fetch failed")); // the network is down
    run.submit(design);
    expect((await screen.findByRole("alert")).textContent).toContain("the server cannot be reached");

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await ended();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("button", { name: "Confirm room" })).toBeTruthy();
  });

  it("rejoins the run when its stream broke while it ran", async () => {
    render(<Page />);
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    vi.mocked(fetch).mockImplementationOnce(async (input, init) => {
      const reader = (await api.fetch(String(input), init)).body?.getReader();
      let chunks = 0;
      const body = new ReadableStream({
        async pull(controller) {
          if (chunks++) return controller.error(new TypeError("network error")); // the connection drops after the first chunk
          controller.enqueue((await reader?.read())?.value);
        },
      });
      return new Response(body);
    });
    // Retry the moment the alert shows: the alert must already have the run's id, for Retry to rejoin the run, not start it again
    const { promise: alert, resolve } = Promise.withResolvers<string | null>();
    const observer = new MutationObserver(() => {
      const retry = screen.queryByRole("button", { name: "Retry" });
      if (!retry) return;
      observer.disconnect();
      resolve(screen.getByRole("alert").textContent);
      fireEvent.click(retry);
    });
    observer.observe(document.body, { childList: true, subtree: true });
    onTestFinished(() => observer.disconnect());
    run.submit(design);
    expect(await alert).toContain("the connection to the server was lost");
    await screen.findByRole("button", { name: "Confirm room" });
    expect(screen.queryByRole("alert")).toBeNull();
    const posts = vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === "POST");
    expect(posts).toHaveLength(1); // the run was rejoined, not started again
  });

  it("starts a run that failed on the server again", async () => {
    render(<Page />);
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    const failed = 'event: metadata\ndata: {"run_id": "failed"}\n\nevent: error\ndata: {"message": "ValueError: no photo"}\n\n';
    vi.mocked(fetch).mockResolvedValueOnce(new Response(failed, { headers: { "Content-Type": "text/event-stream" } }));
    run.submit(design);
    expect((await screen.findByRole("alert")).textContent).toContain("ValueError: no photo");

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByRole("button", { name: "Confirm room" });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("rejoins the thread's run when the request was refused with a 409", async () => {
    render(<Page />);
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    run.submit(design);
    await ended();
    const refused = Response.json({ detail: "A run is already active on this thread" }, { status: 409 });
    vi.mocked(fetch).mockResolvedValueOnce(refused); // another tab resumed the interrupt
    fireEvent.click(screen.getByRole("button", { name: "Confirm room" }));
    await screen.findByRole("alert");

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    const posts = vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === "POST");
    expect(posts).toHaveLength(2); // the run and the refused resume: the retry rejoined
  });

  it("has no retry for a resumed run that failed on the server: its interrupt is gone", async () => {
    render(<Page />);
    run.submit(design);
    await ended();
    const failed = 'event: metadata\ndata: {"run_id": "failed"}\n\nevent: error\ndata: {"message": "ValueError: no design"}\n\n';
    vi.mocked(fetch).mockResolvedValueOnce(new Response(failed, { headers: { "Content-Type": "text/event-stream" } }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm room" }));
    expect((await screen.findByRole("alert")).textContent).toContain("ValueError: no design");
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  });
});

describe("historySteps", () => {
  it("rebuilds the steps the stream had, from the checkpoints", () => {
    const key = ({ node, round }: { node: string; round?: number | null }) => `${node}${round ?? ""}`;
    const streamed = liveSteps([...fixture.first_run, ...fixture.resumed_run]);
    expect(historySteps(api.histories[2]).map(key)).toEqual(streamed.map(key));
    expect(historySteps(api.histories[2]).map((s) => s.cost ?? 0)).toEqual(streamed.map((s) => expect.closeTo(s.cost ?? 0, 6)));
  });
});
