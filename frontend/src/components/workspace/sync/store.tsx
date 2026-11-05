"use client";

import { createContext, type ReactNode, use, useEffect, useState } from "react";
import { mention } from "@/components/chat/chat-panel";
import { ApiError, path, request, type ThreadState } from "@/lib/api";
import type { components } from "@/lib/api/generated/schema";
import { runEnded, useThread } from "@/lib/hooks/use-threads";

export const HIGHLIGHT_MS = 4000; // how long the items a chat edit changed stay highlighted

type LayoutDiff = components["schemas"]["LayoutDiff"];

// The layout diff of a chat turn that changed the design, going from one state of the thread to the next; nothing when the change is
// not a chat edit: a design run or an undo (neither adds to the chat's history), or a refused edit (an empty diff).
export function chatEdit(before: ThreadState, after: ThreadState): LayoutDiff | undefined {
  const diff = after.values.layout_diff;
  if ((after.values.messages?.length ?? 0) <= (before.values.messages?.length ?? 0)) return;
  if (diff && diff.added.length + diff.changed.length + diff.removed.length) return diff;
}

type Sync = {
  seen?: ThreadState; // the thread's state the views show
  edit?: { diff: LayoutDiff; undoTo: string }; // the latest chat edit, and the checkpoint before it
  highlight: boolean; // its added and changed items stand out
};

function useWorkspaceStore(threadId: string) {
  const thread = useThread(threadId); // fetched again when a run on the thread ends: a chat turn sent from the chat panel, say
  const [sync, setSync] = useState<Sync>({ highlight: false });
  const [draft, setDraft] = useState("");
  const [reverts, setReverts] = useState(0);
  const [undoing, setUndoing] = useState(false);
  const [undoError, setUndoError] = useState<ApiError>();

  // a new state of the thread: a chat edit can be undone, and its items are highlighted
  const state = thread.data;
  if (state && state.checkpoint_id !== sync.seen?.checkpoint_id) {
    const diff = sync.seen && chatEdit(sync.seen, state);
    const undoTo = sync.seen?.checkpoint_id;
    setSync({ seen: state, edit: diff && undoTo ? { diff, undoTo } : undefined, highlight: !!diff });
  }

  useEffect(() => {
    if (!sync.edit) return;
    const timer = setTimeout(() => setSync((s) => ({ ...s, highlight: false })), HIGHLIGHT_MS);
    return () => clearTimeout(timer);
  }, [sync.edit]);

  // back to the checkpoint before the chat edit; every view of the thread then reads its state again
  async function undo(checkpoint_id: string) {
    setUndoing(true);
    setUndoError(undefined);
    try {
      const body: components["schemas"]["Revert"] = { checkpoint_id };
      const init = { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
      await request(path("/threads/{thread_id}/revert", { thread_id: threadId }), init);
      runEnded(threadId);
      setReverts((r) => r + 1);
    } catch (error) {
      setUndoError(error instanceof ApiError ? error : new ApiError(String(error), "server"));
    } finally {
      setUndoing(false);
    }
  }

  const { edit } = sync;
  return {
    threadId,
    values: sync.seen?.values,
    error: thread.error,
    edit: edit?.diff,
    highlighted: edit && sync.highlight ? [...edit.diff.added, ...edit.diff.changed] : [],
    undo: edit && (() => undo(edit.undoTo)),
    undoing,
    undoError,
    reverts, // how many times the chat was undone: the chat panel starts over, without the undone turn
    draft, // the chat composer's text
    setDraft,
    sent: () => setSync((s) => ({ ...s, edit: undefined, highlight: false })), // a chat message was sent: no undo while it runs
    reference: (nodeId: string) => setDraft((d) => mention(d, nodeId)), // an item clicked in a view, referenced in the chat
  };
}

export type Workspace = ReturnType<typeof useWorkspaceStore>;

const WorkspaceContext = createContext<Workspace | null>(null);

// One store for a project's workspace: the thread's state the plan, the results and the 3D view show, the latest chat edit with the
// items it changed and its undo, and the chat's draft.
export function WorkspaceProvider({ threadId, children }: { threadId: string; children: ReactNode }) {
  return <WorkspaceContext value={useWorkspaceStore(threadId)}>{children}</WorkspaceContext>;
}

export function useWorkspace(): Workspace {
  const workspace = use(WorkspaceContext);
  if (!workspace) throw new Error("useWorkspace needs a WorkspaceProvider");
  return workspace;
}
