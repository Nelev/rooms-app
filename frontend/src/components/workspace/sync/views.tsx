"use client";

import { Undo2 } from "lucide-react";
import { ChatPanel } from "@/components/chat/chat-panel";
import { Results, WithDesign } from "@/components/results/results-view";
import { LitSceneViewer } from "@/components/scene3d/look";
import { Button } from "@/components/ui/button";
import { useWorkspace } from "./store";

// The workspace's views, all from its store: a chat edit updates them together.

export function WorkspaceResults() {
  const { values, error, highlighted, reference } = useWorkspace();
  return (
    <WithDesign values={values} error={error}>
      {values && <Results values={values} highlighted={highlighted} onPick={reference} />}
    </WithDesign>
  );
}

export function WorkspaceScene() {
  const { values, error, highlighted, reference } = useWorkspace();
  return (
    <WithDesign values={values} error={error} what="3D view">
      {values?.scene && (
        <div className="h-[32rem]">
          <LitSceneViewer scene={values.scene} highlighted={highlighted} onPick={reference} />
        </div>
      )}
    </WithDesign>
  );
}

export function WorkspaceChat() {
  const { threadId, edit, undo, undoing, undoError, reverts, draft, setDraft, sent } = useWorkspace();
  return (
    <>
      {edit && (
        <div className="flex items-center justify-between gap-2 border-b px-3 py-2 text-sm">
          <span className="text-muted-foreground" aria-live="polite">
            Changed: {[...edit.added, ...edit.changed, ...edit.removed].map((id) => id.replaceAll("_", " ")).join(", ")}
          </span>
          <Button variant="outline" size="xs" onClick={undo} disabled={undoing}>
            <Undo2 aria-hidden />
            Undo
          </Button>
        </div>
      )}
      {undoError && (
        <p role="alert" className="px-3 pt-2 text-destructive text-sm">
          {undoError.message}
        </p>
      )}
      <ChatPanel key={reverts} threadId={threadId} draft={draft} onDraftChange={setDraft} onSend={sent} />
    </>
  );
}
