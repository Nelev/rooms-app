"use client";

import { Check, House } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { useRunStream } from "@/lib/hooks/use-run-stream";
import { useThread } from "@/lib/hooks/use-threads";
import { RoomEditor } from "./room-editor";

function Note({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <Empty>
      <EmptyHeader>
        <EmptyMedia variant="icon">{icon}</EmptyMedia>
        <EmptyTitle>{title}</EmptyTitle>
        <EmptyDescription>{children}</EmptyDescription>
      </EmptyHeader>
    </Empty>
  );
}

// The project's open confirm_room interrupt, in the room editor: confirming resumes the run with the corrected room.
export function RoomConfirm({ threadId }: { threadId: string }) {
  const thread = useThread(threadId);
  const run = useRunStream(threadId);
  const [sent, setSent] = useState(false);
  // the stream has the interrupt as soon as the run pauses, before the thread's state is fetched again
  const interrupt = run.interrupt ?? thread.data?.interrupts[0];
  // a project is its thread (the contract's Thread and GraphState; the wizard routes to /projects/{thread_id}), so the ids are the same
  const back = <Link href={`/projects/${threadId}`}>Back to the project</Link>;
  const error = run.error ?? thread.error;

  // until the resumed run has started the editor stays, with the user's edits: a resume that fails (a 409, the network) can be sent again
  if (sent && run.runId && !run.error)
    return (
      <Note icon={<Check aria-hidden />} title="Room confirmed">
        The design is on its way. {back}
      </Note>
    );
  return (
    <>
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {error.message}
        </p>
      )}
      {interrupt ? (
        <RoomEditor
          key={interrupt.id}
          initial={interrupt.value.room}
          photos={interrupt.value.overlay_keys.length ? interrupt.value.overlay_keys : (thread.data?.values.photo_keys ?? [])}
          sending={sent && !run.error}
          onConfirm={(room) => {
            setSent(true);
            run.submit({ command: { resume: room } });
          }}
        />
      ) : thread.loading || run.running ? (
        <p role="status" className="text-muted-foreground text-sm">
          Loading the room…
        </p>
      ) : (
        <Note icon={<House aria-hidden />} title="Nothing to confirm">
          The room is shown here once its photos are analyzed. {back}
        </Note>
      )}
    </>
  );
}
