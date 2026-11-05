"use client";

import { startTransition, useEffect, useRef, useState } from "react";
import { ApiError, type Interrupt, path, type RunCreate, request, type StreamEvent, type StreamPart, streamParts } from "@/lib/api";
import type { components } from "@/lib/api/generated/schema";
import { runEnded } from "@/lib/hooks/use-threads";

type Updates = components["schemas"]["UpdatesPart"]["data"];
// a model's reply so far, from its tokens
export type Message = { id: string | null; node: components["schemas"]["MessageMetadata"]["langgraph_node"]; content: string };

export type Run = {
  threadId: string;
  runId?: string;
  running: boolean;
  events: StreamEvent[]; // the nodes' progress
  messages: Message[];
  updates: Updates[]; // what each node changed, in order
  interrupt?: Interrupt; // the interrupt the run paused at: resume it with submit({ command: { resume } })
  error?: ApiError; // the stream could not be opened or read, or the run failed
};

const idle = (threadId: string): Run => ({ threadId, running: false, events: [], messages: [], updates: [] });

function reduce(run: Run, part: StreamPart): Run {
  switch (part.event) {
    case "metadata": // the first part: a rejoined run starts over from it
      return { ...idle(run.threadId), running: true, runId: part.data.run_id };
    case "custom":
      return { ...run, events: [...run.events, part.data] };
    case "updates": {
      const interrupts = part.data.__interrupt__ as Interrupt[] | undefined;
      return { ...run, updates: [...run.updates, part.data], interrupt: interrupts?.[0] ?? run.interrupt };
    }
    case "messages": {
      const [{ id, content }, { langgraph_node: node }] = part.data;
      const last = run.messages.at(-1);
      if (last && last.id === id && last.node === node)
        return { ...run, messages: [...run.messages.slice(0, -1), { ...last, content: last.content + content }] };
      return { ...run, messages: [...run.messages, { id, node, content }] };
    }
    case "error":
      return { ...run, error: new ApiError(part.data.message, "server") };
  }
}

// Reads a run's stream into the state until it ends, then has the thread's state fetched again. A stream that is aborted (another
// one started, or the page left) stops quietly; rejoining a thread that never ran (404) is not an error.
async function follow(
  threadId: string,
  open: (signal: AbortSignal) => Promise<Response>,
  signal: AbortSignal,
  set: (update: (run: Run) => Run) => void,
) {
  try {
    // tokens come often: a transition keeps the page responsive while they do
    for await (const part of streamParts(await open(signal))) startTransition(() => set((run) => reduce(run, part)));
  } catch (error) {
    if (signal.aborted) return;
    if (error instanceof ApiError && error.status === 404) return set(() => idle(threadId));
    set((run) => ({ ...run, error: error instanceof ApiError ? error : new ApiError(String(error), "server") }));
  }
  set((run) => ({ ...run, running: false }));
  runEnded(threadId);
}

// A thread's run as it streams: `submit` starts one (a new input, or the resume of the interrupt). After a reload the hook rejoins
// the thread's latest run, from its first part (a run that is over is replayed at once, with the interrupt it may have paused at:
// `running` is then true for a moment, and the thread's state is fetched again).
export function useRunStream(threadId: string) {
  const [state, setState] = useState(() => idle(threadId));
  const controller = useRef<AbortController>(null);

  // a new stream replaces the one being read; `running` from the start for a run that is being started
  function start(open: (signal: AbortSignal) => Promise<Response>, running: boolean) {
    controller.current?.abort();
    controller.current = new AbortController();
    setState({ ...idle(threadId), running });
    void follow(threadId, open, controller.current.signal, setState);
  }

  // biome-ignore lint/correctness/useExhaustiveDependencies: rejoins once per thread
  useEffect(() => {
    start((signal) => request(path("/threads/{thread_id}/runs/current/stream", { thread_id: threadId }), { signal, timeout: null }), false);
    return () => controller.current?.abort();
  }, [threadId]);

  function submit(body: RunCreate) {
    const url = path("/threads/{thread_id}/runs/stream", { thread_id: threadId });
    const init = { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), timeout: null };
    start((signal) => request(url, { ...init, signal }), true);
  }

  return { ...(state.threadId === threadId ? state : idle(threadId)), submit };
}
