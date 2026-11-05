// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RunCreate } from "@/lib/api";
import { useRunStream } from "@/lib/hooks/use-run-stream";
import { useProjects, useThread } from "@/lib/hooks/use-threads";
import { stubApi } from "@/lib/mocks/stub-api";

// what the stub graph replays: the S-04 fixture's progress events
const read = (name: string) => JSON.parse(readFileSync(join(import.meta.dirname, "../../../../fixtures/small-bedroom", name), "utf8"));
const fixture = read("stream_events.json");
const room = read("room_spec.json");
const design = {
  input: { photo_keys: ["fixtures/small-bedroom/photo-1.jpg"], dimensions: room.dimensions, brief: read("brief.json") },
} satisfies RunCreate;

let api: ReturnType<typeof stubApi>;
const id = () => api.thread.thread_id;

beforeEach(() => {
  api = stubApi();
  vi.stubGlobal("fetch", vi.fn(api.fetch));
});
afterEach(() => vi.unstubAllGlobals());

// the run started and has ended
async function finished(run: () => { running: boolean; runId?: string }) {
  await waitFor(() => expect(!!run().runId && !run().running).toBe(true), { timeout: 5000 });
}

describe("useRunStream", () => {
  it("streams the design run to the interrupt, then the resumed run to the end", async () => {
    const { result } = renderHook(() => useRunStream(id()));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1)); // it looked for a run to rejoin: there is none
    expect(result.current).toMatchObject({ running: false, events: [] });
    expect(result.current.error).toBeUndefined();

    result.current.submit(design);
    await finished(() => result.current);
    expect(result.current.events).toEqual(fixture.first_run);
    expect(result.current.messages.map((m) => m.node)).toEqual(["analyze_room"]);
    expect(JSON.parse(result.current.messages[0].content).dimensions).toEqual(room.dimensions); // the tokens, put together
    expect(result.current.interrupt).toEqual(api.states[1].interrupts[0]);

    const runId = result.current.runId;
    result.current.submit({ command: { resume: room } }); // the room confirmed as it is
    await waitFor(() => expect(result.current.runId).not.toBe(runId));
    await finished(() => result.current);
    expect(result.current.events).toEqual(fixture.resumed_run);
    expect(result.current.interrupt).toBeUndefined();
    expect(result.current.updates.some((update) => "present" in update)).toBe(true);
    expect(result.current.error).toBeUndefined();
  });

  it("rejoins the run after a reload, from its first part", async () => {
    const first = renderHook(() => useRunStream(id()));
    api.hold();
    first.result.current.submit(design);
    await waitFor(() => expect(first.result.current.events).toEqual(fixture.first_run.slice(0, 1)));
    expect(first.result.current.running).toBe(true);
    first.unmount(); // the page reloads in the middle of the run
    api.release();

    const { result } = renderHook(() => useRunStream(id()));
    await finished(() => result.current);
    expect(result.current.events).toEqual(fixture.first_run);
    expect(result.current.interrupt).toEqual(api.states[1].interrupts[0]);
    expect(vi.mocked(fetch).mock.calls.at(-1)?.[0]).toMatch(/\/runs\/current\/stream$/);
  });

  it("says why the server refused a run", async () => {
    const { result } = renderHook(() => useRunStream(id()));
    result.current.submit({ command: { resume: room } }); // nothing to resume yet
    await waitFor(() => expect(result.current.error?.status).toBe(409));
    expect(result.current).toMatchObject({ running: false, events: [] });
  });
});

describe("useThread and useProjects", () => {
  it("load, and load again when a run ends", async () => {
    const { result } = renderHook(() => ({ thread: useThread(id()), projects: useProjects(), run: useRunStream(id()) }));
    await waitFor(() => expect(result.current.thread.data?.status).toBe("new"));
    expect(result.current.projects.data).toEqual([api.thread]);

    result.current.run.submit(design);
    await finished(() => result.current.run);
    await waitFor(() => expect(result.current.thread.data?.status).toBe("needs_input"));
    expect(result.current.thread.data?.interrupts).toEqual(api.states[1].interrupts);
    expect(result.current.projects.data?.[0].status).toBe("needs_input");
  });

  it("report an error", async () => {
    const { result } = renderHook(() => useThread("unknown"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error?.status).toBe(404);
  });
});
