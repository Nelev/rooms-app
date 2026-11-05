"use client";

import { useEffect, useState } from "react";
import { type Answer, type ApiError, json, type Path, path, request } from "@/lib/api";

// Tells the hooks that read a thread that one of its runs ended (its state, and the project's status, changed).
const runs = new EventTarget();

export function runEnded(threadId: string) {
  runs.dispatchEvent(new CustomEvent("end", { detail: threadId }));
}

type Result<T> = { url: string; data?: T; error?: ApiError };

// What a GET of the path answers, fetched again when a run ends: any run, or only those of `threadId`. A refetch keeps the
// data it had while it loads, so `loading` is only true until the first answer.
function useGet<P extends Path>(template: P, params: Record<string, string>, threadId?: string) {
  const url = path(template, params);
  const [result, setResult] = useState<Result<Answer<P>>>();
  const [version, setVersion] = useState(0);
  const refetch = () => setVersion((v) => v + 1);

  useEffect(() => {
    const onEnd = (event: Event) => (!threadId || (event as CustomEvent<string>).detail === threadId) && setVersion((v) => v + 1);
    runs.addEventListener("end", onEnd);
    return () => runs.removeEventListener("end", onEnd);
  }, [threadId]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: a new version fetches again
  useEffect(() => {
    const controller = new AbortController();
    request(url, { signal: controller.signal })
      .then((response) => json<Answer<P>>(response))
      .then(
        (data) => setResult({ url, data }),
        (error: ApiError) => controller.signal.aborted || setResult((r) => ({ url, data: r?.url === url ? r.data : undefined, error })),
      );
    return () => controller.abort();
  }, [url, version]);

  const current = result?.url === url ? result : undefined;
  return { data: current?.data, error: current?.error, loading: !current, refetch };
}

// The caller's projects, newest first.
export function useProjects() {
  return useGet("/threads", {});
}

// A project's state: its design, the open interrupt, its status.
export function useThread(threadId: string) {
  return useGet("/threads/{thread_id}/state", { thread_id: threadId }, threadId);
}
