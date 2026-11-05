import type { Metadata } from "next";
import { RoomConfirm } from "@/components/plan/editor/room-confirm";

export const metadata: Metadata = { title: "Confirm the room" };

export default async function RoomPage({ params }: PageProps<"/projects/[id]/room">) {
  const { id } = await params;
  return (
    <>
      <h1 className="font-heading text-2xl font-semibold">Confirm the room</h1>
      <p className="text-muted-foreground text-sm">Check what was found in your photos and fix anything that is off before the design starts.</p>
      <RoomConfirm threadId={id} />
    </>
  );
}
