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
// chips of the tools and checks it ran, in order, and why an edit was refused.
function chatTurn(run: Run, pending?: string) {
  const update = (node: string) => run.updates.find((u) => u[node])?.[node] as { mode?: string; messages?: ChatEntry[] } | undefined;
  const routed = update("route_input");
  if (routed ? routed.mode !== "chat" : !pending) return;
  const streamed = run.messages.filter((m) => m.node === "chat_edit").map((m) => m.content);
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
    refused: run.events.find((e) => e.type === "tool" && !e.ok)?.summary,
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
export function ChatPanel({ threadId, suggestions = SUGGESTIONS }: { threadId: string; suggestions?: string[] }) {
  const thread = useThread(threadId);
  const run = useRunStream(threadId);
  const [sent, setSent] = useState("");
  const [draft, setDraft] = useState("");

  const turn = chatTurn(run, run.running ? sent : undefined);
  let history = thread.data?.values.messages ?? [];
  // once the thread's state holds the turn (fetched again after the run, or on a reload that replays it), its last two entries are the turn's
  if (turn && history.at(-1)?.content === turn.text) history = history.slice(0, -2);
  const items = thread.data?.values.scene?.items ?? [];

  function send(text: string) {
    if (!text.trim() || run.running) return;
    setSent(text);
    setDraft("");
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
            {turn.refused ? (
              <li role="alert" className="self-start max-w-[85%] rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm">
                <p className="font-medium text-destructive">Edit refused</p>
                <p className="text-muted-foreground">{turn.refused.replace(/^refused: /, "")}</p>
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
            <Button
              key={node_id}
              variant="secondary"
              size="xs"
              onClick={() => setDraft((d) => `${d}${d && !d.endsWith(" ") ? " " : ""}@${node_id} `)}
            >
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
