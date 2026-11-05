import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { Thread, ThreadState } from "@/lib/api";

// The stub API (`make dev-stub`) as a fetch, for tests: it replays what the stub answered for one project (stub/, recorded by
// record.sh). Its design run streams up to the confirm_room interrupt, the resumed run to the end, then each chat run streams the
// fixture's next chat turn (chat.json: an applied edit, then a refused one). Not recorded: a revert goes back to the recorded state
// of the checkpoint, so the next chat run replays the turn after it. Like the stub, a run goes on without the client and
// can be rejoined from its first part. Streams arrive in small chunks, and stop after their first one while the test holds them
// (`hold()`, until `release()`), so a test can leave in the middle of a run.

const read = (name: string) => readFileSync(join(import.meta.dirname, "stub", name), "utf8");
const CHUNK = 200; // bytes: Server-Sent Events are cut across chunks

function answer(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

// like a real fetch, a stream ends with an error when its request is aborted
function sse(text: string, signal: AbortSignal | null | undefined, held: () => Promise<void>) {
  let at = 0;
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      signal?.addEventListener("abort", () => controller.error(signal.reason));
    },
    async pull(controller) {
      await new Promise((resolve) => setTimeout(resolve));
      if (at > 0) await held();
      if (signal?.aborted) return;
      if (at >= text.length) return controller.close();
      controller.enqueue(new TextEncoder().encode(text.slice(at, at + CHUNK)));
      at += CHUNK;
    },
  });
  return new Response(body, { headers: { "Content-Type": "text/event-stream" } });
}

export function stubApi() {
  const thread: Thread = JSON.parse(read("thread.json"));
  const states: ThreadState[] = ["state-new.json", "state-interrupt.json", "state-done.json", "state-chat-1.json", "state-chat-2.json"].map((name) =>
    JSON.parse(read(name)),
  );
  // History is recorded up to the end of the design run; the chat turns reuse the last one.
  const histories: ThreadState[][] = ["new", "interrupt", "done"].map((name) => JSON.parse(read(`history-${name}.json`)));
  const runs = ["first-run.sse", "resumed-run.sse", "chat-1.sse", "chat-2.sse"].map(read);
  let step = 0; // the runs done: the state is states[step]
  let latest: string | undefined;
  let held = Promise.resolve();
  let release = () => {};

  async function fetch(input: string | URL | Request, init?: RequestInit): Promise<Response> {
    init?.signal?.throwIfAborted();
    const { pathname } = new URL(String(input));
    const route = `${init?.method ?? "GET"} ${pathname.replace(thread.thread_id, "{thread_id}")}`;
    switch (route) {
      case "GET /threads":
        return answer([{ ...thread, status: states[step].status }]);
      case "GET /threads/{thread_id}/state":
        return answer(states[step]);
      case "GET /threads/{thread_id}/history":
        return answer(histories[Math.min(step, histories.length - 1)]);
      case "POST /threads/{thread_id}/runs/stream": {
        const resume = "command" in JSON.parse(String(init?.body));
        if (step === runs.length || resume !== (step === 1)) return answer({ detail: "The thread has no open interrupt to resume" }, 409);
        latest = runs[step++];
        return sse(latest, init?.signal, () => held);
      }
      // not recorded: the fixture's pose, whatever the points (the stub API solves them, and the placeholder photo shows too few corners)
      case "POST /threads/{thread_id}/camera-pose":
        return answer(JSON.parse(readFileSync(join(import.meta.dirname, "../../../../fixtures/small-bedroom/camera_pose.json"), "utf8")));
      // not recorded: the state of the checkpoint itself, where the real API forks a new checkpoint from it
      case "POST /threads/{thread_id}/revert": {
        const at = states.findIndex((s) => s.checkpoint_id === JSON.parse(String(init?.body)).checkpoint_id);
        if (at < 0) return answer({ detail: "Checkpoint not found" }, 404);
        step = at;
        return answer(states[step]);
      }
      case "GET /threads/{thread_id}/runs/current/stream":
        return latest ? sse(latest, init?.signal, () => held) : answer({ detail: "No run on this thread" }, 404);
    }
    return answer({ detail: "Not Found" }, 404);
  }

  function hold() {
    held = new Promise((resolve) => {
      release = resolve;
    });
  }
  return { fetch, thread, states, histories, hold, release: () => release() };
}
