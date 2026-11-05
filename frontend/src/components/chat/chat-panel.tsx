"use client";

import { Ban, Check, SendHorizontal } from "lucide-react";
import { type FormEvent, Fragment, useState } from "react";
import { Button } from "@/components/ui/button";
import type { components } from "@/lib/api/generated/schema";
import { type Run, useRunStream } from "@/lib/hooks/use-run-stream";
import { useThread } from "@/lib/hooks/use-threads";

type ChatEntry = components["schemas"]["ChatEntry"];

// Shown under the messages while the assistant is idle: a click sends one.
const SUGGESTIONS = ["Make it cheaper", "Move the desk closer to the window", "Add a plant"];

// An item is referenced in a message as `@<node id>` (e.g. `@desk_chair`), and shown as a chip.
const REFERENCE = /@([a-z0-9_]+)/g;
const label = (nodeId: string) => nodeId.replaceAll("_", " ");
// the draft with a reference to the item appended
export const mention = (draft: string, nodeId: string) => `${draft}${draft && !draft.endsWith(" ") ? " " : ""}@${nodeId} `;

// The stub's FakeLLM (and a model asked for structured output) streams its reply as a JSON string: shown unquoted as it streams.
function unquote(text: string): string {
  if (!text.startsWith('"')) return text;
  try {
    return JSON.parse(text);
  } catch {
    return text.slice(1);
  }
}

// The chat turn the run is on, or nothing when it is not a chat run (a design run, say): the message sent (`pending` until
// route_input moves it to the history), the assistant's text as it streams (its final answer once chat_edit returns it), the
// chips of the tools and checks it ran, in order, why its edits were refused (each refused tool's reason: a turn can apply some
// edits and refuse others, its chips then show which), and how many history entries the run has added so far.
export function chatTurn(run: Run, pending?: string) {
  const update = (node: string) => run.updates.find((u) => u[node])?.[node] as { mode?: string; messages?: ChatEntry[] } | undefined;
  const routed = update("route_input");
  if (routed ? routed.mode !== "chat" : !pending) return;
  const streamed = run.messages.filter((m) => m.node === "chat_edit").map((m) => m.content);
  const added = [routed, update("chat_edit")].reduce((n, u) => n + (u?.messages?.length ?? 0), 0);
  const chips = run.events.flatMap((e) =>
    e.type === "tool"
      ? [{ summary: e.summary, ok: e.ok }]
      : e.status === "done" && !["route_input", "chat_edit"].includes(e.node)
        ? [{ summary: e.summary, ok: true }]
        : [],
  );
  return {
    user: routed?.messages?.[0]?.content ?? pending ?? "",
    text: update("chat_edit")?.messages?.[0]?.content ?? unquote(streamed.join("")),
    chips,
    refused: chips.filter((c) => !c.ok).map((c) => c.summary.replace(/^refused: /, "")),
    added,
  };
}

function Text({ content }: { content: string }) {
  return content.split(REFERENCE).map((part, i) =>
    i % 2 ? (
      // biome-ignore lint/suspicious/noArrayIndexKey: the parts of a message do not move
      <span key={i} className="rounded-md bg-background/60 px-1.5 py-0.5 font-medium text-xs ring-1 ring-border">
        {label(part)}
      </span>
    ) : (
      // biome-ignore lint/suspicious/noArrayIndexKey: the parts of a message do not move
      <Fragment key={i}>{part}</Fragment>
    ),
  );
}

function Bubble({ from, children }: { from: ChatEntry["role"]; children: React.ReactNode }) {
  const style = from === "user" ? "self-end bg-primary text-primary-foreground" : "self-start bg-muted";
  return <li className={`max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm ${style}`}>{children}</li>;
}

// The project's chat: its history, the turn in progress as it streams, and a composer with suggested replies and the design's items
// to reference. Earlier turns come from the thread's state; the step chips and a refusal are those of the latest run.
// F-13: the workspace keeps the composer's text (`draft`, `onDraftChange`: it inserts the references of items clicked in its views)
// and is told when a message is sent (`onSend`).
export function ChatPanel({
  threadId,
  suggestions = SUGGESTIONS,
  draft: shared,
  onDraftChange,
  onSend,
}: {
  threadId: string;
  suggestions?: string[];
  draft?: string;
  onDraftChange?: (draft: string) => void;
  onSend?: () => void;
}) {
  const thread = useThread(threadId);
  const run = useRunStream(threadId);
  const [sent, setSent] = useState("");
  const [base, setBase] = useState<number>(); // the history's length when the turn was sent
  const [own, setOwn] = useState("");
  const draft = shared ?? own;
  const setDraft = onDraftChange ?? setOwn;

  let turn = chatTurn(run, run.running ? sent : undefined);
  let history = thread.data?.values.messages ?? [];
  // a run rejoined on a reload, already over, whose turn is no longer the history's last (it was undone): not shown
  if (turn && base === undefined && !run.running && thread.data && history.at(-turn.added)?.content !== turn.user) turn = undefined;
  // the history without the turn shown below it, whether or not the thread's state has been fetched again since: a turn sent here
  // follows the history it was sent after; a run rejoined on a reload, already over, added its entries at the end
  if (turn) history = history.slice(0, base ?? Math.max(0, history.length - turn.added));
  const items = thread.data?.values.scene?.items ?? [];

  function send(text: string) {
    if (!text.trim() || run.running) return;
    setSent(text);
    setBase(history.length + (turn?.added ?? 0)); // the entries shown: the latest run's may not be in the thread's state yet
    setDraft("");
    onSend?.();
    run.submit({ input: { chat_message: text } });
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    send(draft);
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 p-3">
      <ol role="log" aria-label="Messages" className="flex flex-1 flex-col gap-2 overflow-y-auto">
        {history.map((entry, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: the history only grows
          <Bubble key={i} from={entry.role}>
            <Text content={entry.content} />
          </Bubble>
        ))}
        {turn && (
          <>
            <Bubble from="user">
              <Text content={turn.user} />
            </Bubble>
            {turn.chips.length > 0 && (
              <li className="flex flex-wrap gap-1.5" aria-label="Steps">
                {turn.chips.map((chip, i) => (
                  <span
                    // biome-ignore lint/suspicious/noArrayIndexKey: the run's events only grow
                    key={i}
                    className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs ${chip.ok ? "text-muted-foreground" : "border-destructive/40 text-destructive"}`}
                  >
                    {chip.ok ? <Check aria-hidden className="size-3" /> : <Ban aria-hidden className="size-3" />}
                    {chip.summary}
                  </span>
                ))}
              </li>
            )}
            {turn.refused.length > 0 ? (
              <li role="alert" className="self-start max-w-[85%] rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm">
                <p className="font-medium text-destructive">Edit refused</p>
                {turn.refused.map((reason) => (
                  <p key={reason} className="text-muted-foreground">
                    {reason}
                  </p>
                ))}
                {turn.text && <p className="mt-1">{turn.text}</p>}
              </li>
            ) : turn.text ? (
              <Bubble from="assistant">{turn.text}</Bubble>
            ) : (
              run.running && <li className="self-start animate-pulse text-muted-foreground text-sm">Thinking…</li>
            )}
          </>
        )}
      </ol>
      {[thread.error, run.error].map(
        (error) =>
          error && (
            <p key={error.message} role="alert" className="text-destructive text-sm">
              {error.message}
            </p>
          ),
      )}
      {!run.running && suggestions.length > 0 && (
        <fieldset className="flex flex-wrap gap-1.5" aria-label="Suggested replies">
          {suggestions.map((text) => (
            <Button key={text} variant="outline" size="xs" onClick={() => send(text)}>
              {text}
            </Button>
          ))}
        </fieldset>
      )}
      {items.length > 0 && (
        <fieldset className="flex flex-wrap items-center gap-1.5 text-muted-foreground text-xs" aria-label="Items">
          Mention
          {items.map(({ node_id }) => (
            <Button key={node_id} variant="secondary" size="xs" onClick={() => setDraft(mention(draft, node_id))}>
              {label(node_id)}
            </Button>
          ))}
        </fieldset>
      )}
      <form onSubmit={onSubmit} className="flex gap-2">
        <input
          aria-label="Message"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Ask for a change…"
          className="h-8 min-w-0 flex-1 rounded-lg border bg-background px-2.5 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        />
        <Button type="submit" size="icon" aria-label="Send" disabled={run.running || !draft.trim()}>
          <SendHorizontal aria-hidden />
        </Button>
      </form>
    </div>
  );
}
