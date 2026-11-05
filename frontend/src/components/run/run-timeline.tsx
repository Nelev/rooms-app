"use client";

import { CircleAlert, CircleCheck, CirclePause, CircleX, LoaderCircle, RotateCw } from "lucide-react";
import { type Step, timelineSteps } from "@/components/run/steps";
import { Button } from "@/components/ui/button";
import type { useRunStream } from "@/lib/hooks/use-run-stream";
import { useHistory } from "@/lib/hooks/use-threads";

type RunStream = ReturnType<typeof useRunStream>;

const seconds = new Intl.NumberFormat("en", { style: "unit", unit: "second", unitDisplay: "narrow", maximumSignificantDigits: 2 });
const usd = new Intl.NumberFormat("en", { style: "currency", currency: "USD", maximumSignificantDigits: 2 });

const name = ({ node }: Step) => node[0].toUpperCase() + node.slice(1).replaceAll("_", " ");

// The run of a thread as a timeline: one row per agent step, the Critic rounds grouped, the confirm_room interrupt as an action.
// It shows the run of `useRunStream` (the page's, shared with the chat); after a reload, the steps the stream no longer has come
// from the thread's history.
export function RunTimeline({ run }: { run: RunStream }) {
  const history = useHistory(run.threadId);
  const interrupt = run.interrupt ?? (run.running || run.events.length ? undefined : history.data?.[0]?.interrupts[0]);
  const steps = timelineSteps(history.data ?? [], run.events);
  const last = steps.at(-1);
  if (interrupt && !(last?.node === "confirm_room" && last.status === "started"))
    steps.push({ node: "confirm_room", status: "started", summary: "" }); // the history has no row for a step that has not ended
  const error = run.error ?? history.error;
  const retry = run.error ? run.retry : undefined; // none for a resumed run that failed

  // consecutive steps of the same Critic round in one group; `at` is the first step's index, a stable key
  const groups: { at: number; round?: number | null; steps: Step[] }[] = [];
  steps.forEach((step, at) => {
    const group = groups.at(-1);
    if (step.round != null && group?.round === step.round) group.steps.push(step);
    else groups.push({ at, round: step.round, steps: [step] });
  });

  function row(step: Step, i: number) {
    const waiting = !!interrupt && step.node === "confirm_room" && step.status === "started";
    const [Icon, label, className] =
      step.status === "done"
        ? ([CircleCheck, "done", "text-primary"] as const)
        : step.status === "error"
          ? ([CircleX, "failed", "text-destructive"] as const)
          : waiting
            ? ([CirclePause, "waiting for you", "text-primary"] as const)
            : run.running
              ? ([LoaderCircle, "running", "animate-spin text-muted-foreground"] as const)
              : ([CircleX, "stopped", "text-muted-foreground"] as const);
    return (
      <li key={`${step.node}-${i}`} className="flex items-start gap-2 py-1.5 text-sm">
        <Icon aria-hidden className={`mt-0.5 size-4 shrink-0 ${className}`} />
        <div className="min-w-0 flex-1">
          <div className="flex gap-2">
            <span className="font-medium">{name(step)}</span>
            <span className="sr-only">{label}</span>
            <span className="ml-auto flex gap-2 text-muted-foreground tabular-nums">
              {step.duration_s != null && <span>{seconds.format(step.duration_s)}</span>}
              {step.cost != null && <span>{usd.format(step.cost)}</span>}
            </span>
          </div>
          {step.summary && <p className="truncate text-muted-foreground">{step.summary}</p>}
          {waiting && interrupt && (
            <div className="mt-1.5 flex items-center gap-2">
              <span className="text-muted-foreground">Check the room before the design starts.</span>
              <Button size="sm" disabled={run.running} onClick={() => run.submit({ command: { resume: interrupt.value.room } })}>
                Confirm room
              </Button>
            </div>
          )}
        </div>
      </li>
    );
  }

  return (
    <section aria-label="Run progress" className="flex flex-col gap-2">
      {!steps.length && !error && <p className="text-sm text-muted-foreground">No run yet.</p>}
      <ol>
        {groups.map(({ at, round, steps }) =>
          round == null ? (
            steps.map((step, i) => row(step, at + i))
          ) : (
            <li key={`round-${at}`} className="my-1 rounded-lg border px-3 py-1">
              <p className="pt-1 text-xs font-medium text-muted-foreground">Critic round {round}</p>
              <ol>{steps.map((step, i) => row(step, at + i))}</ol>
            </li>
          ),
        )}
      </ol>
      {error && (
        <div role="alert" className="flex items-center gap-2 rounded-lg bg-destructive/10 p-3 text-sm text-destructive">
          <CircleAlert aria-hidden className="size-4 shrink-0" />
          <span className="flex-1">{error.message}</span>
          {(retry || !run.error) && (
            <Button size="sm" variant="outline" onClick={retry ?? history.refetch}>
              <RotateCw aria-hidden />
              Retry
            </Button>
          )}
        </div>
      )}
    </section>
  );
}
