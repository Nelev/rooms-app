"use client";

import { Undo2 } from "lucide-react";
import Link from "next/link";
import { ChatPanel } from "@/components/chat/chat-panel";
import { FloorPlan } from "@/components/plan/floor-plan";
import { Results, WithDesign } from "@/components/results/results-view";
import { RunTimeline } from "@/components/run/run-timeline";
import { LitSceneViewer } from "@/components/scene3d/look";
import { Button, buttonVariants } from "@/components/ui/button";
import { Empty, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { photoUrl } from "@/lib/api";
import { useWorkspace } from "./store";

// The workspace's views, all from its store: a chat edit updates them together.

// The run's progress, then the room: its photos and its plan once analyzed, and the way to confirm it while the run waits for that.
export function WorkspaceRoom() {
  const { threadId, values, status, error, run } = useWorkspace();
  const room = values?.room_spec;
  return (
    <div className="flex flex-col gap-4">
      <RunTimeline run={run} />
      {status === "needs_input" && !run.running && (
        <Link href={`/projects/${threadId}/room`} className={buttonVariants({ className: "self-start" })}>
          Confirm the room
        </Link>
      )}
      {error && !values ? (
        <p role="alert" className="text-destructive text-sm">
          {error.message}
        </p>
      ) : !values ? (
        <Skeleton role="status" aria-label="Loading the room" className="h-96 w-full" />
      ) : (
        <>
          {!!values.photo_keys?.length && (
            <div className="flex flex-wrap gap-2">
              {values.photo_keys.map((key, i) => (
                // biome-ignore lint/performance/noImgElement: a user's photo from the API or a signed URL, nothing for next/image to optimize
                <img key={key} src={photoUrl(key)} alt={`Your room, view ${i + 1}`} className="h-40 rounded-lg border object-cover" />
              ))}
            </div>
          )}
          {room ? (
            <FloorPlan room={room} className="max-h-96" />
          ) : (
            <Empty>
              <EmptyHeader>
                <EmptyTitle>The room is not analyzed yet.</EmptyTitle>
              </EmptyHeader>
            </Empty>
          )}
        </>
      )}
    </div>
  );
}

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
  const { threadId, run, edit, undo, undoing, undoError, reverts, draft, setDraft, sent } = useWorkspace();
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
      <ChatPanel key={reverts} threadId={threadId} run={run} draft={draft} onDraftChange={setDraft} onSend={sent} />
    </>
  );
}
