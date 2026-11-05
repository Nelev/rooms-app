import type { StreamEvent, ThreadState } from "@/lib/api";
import type { components } from "@/lib/api/generated/schema";

// One row of the run timeline: an agent step, as the run's StepEvents describe it
export type Step = Omit<components["schemas"]["StepEvent"], "type">;

const LOOP = new Set<Step["node"]>(["architect", "refine", "source", "solve", "critic"]); // the nodes of the Critic rounds

const same = (a: Step, b: Step) => a.node === b.node && (a.round ?? null) === (b.round ?? null);

// The steps of a run, from its stream's events: a step's later events update its row, and a node that starts again before it
// ended (confirm_room, resumed after the interrupt) keeps its row. Tool events are the chat's.
export function liveSteps(events: StreamEvent[]): Step[] {
  const steps: Step[] = [];
  for (const event of events) {
    if (event.type !== "step") continue;
    const { type, ...step } = event;
    const at = steps.findLastIndex((s) => same(s, step));
    if (at >= 0 && (step.status !== "started" || steps[at].status === "started")) steps[at] = { ...steps[at], ...step };
    else steps.push(step);
  }
  return steps;
}

// The steps of the thread's latest run, from its checkpoints (newest first): a checkpoint's `next` nodes ran when a later one
// follows it. Checkpoints have no summary; the duration is the time between them, unknown while a step waited for the user.
export function historySteps(history: ThreadState[]): Step[] {
  const states = history.toReversed();
  const from = Math.max(
    0,
    states.findLastIndex((s) => s.next.includes("__start__")),
  ); // the run's input
  return states.slice(from, -1).flatMap((state, i) => {
    const after = states[from + i + 1];
    const duration = Date.parse(after.created_at ?? "") - Date.parse(state.created_at ?? "");
    return state.next
      .filter((node) => node !== "__start__")
      .map((node) => ({
        node,
        status: "done" as const,
        summary: "",
        round: LOOP.has(node) && state.values.mode === "design" ? state.values.round : undefined,
        duration_s: state.interrupts.length || Number.isNaN(duration) ? undefined : duration / 1000,
        cost: (after.values.cost ?? 0) - (state.values.cost ?? 0) || undefined,
      }));
  });
}

// The latest run's steps. The stream of a rejoined run starts with its own first step: a new run (route_input) replaces what the
// history has, a resumed one follows the history's steps before it.
export function timelineSteps(history: ThreadState[], events: StreamEvent[]): Step[] {
  const past = historySteps(history);
  const live = liveSteps(events);
  if (!live.length) return past;
  const at = live[0].node === "route_input" ? 0 : past.findIndex((s) => same(s, live[0]));
  return [...past.slice(0, at < 0 ? past.length : at), ...live];
}
