import type { Metadata } from "next";
import { PhotoView } from "./photo-view";

export const metadata: Metadata = { title: "In your photo" };

// The project's design in the user's photo, from the camera matched to it (F-10).
export default async function PhotoPage({ params }: PageProps<"/projects/[id]/photo">) {
  const { id } = await params;
  return (
    <>
      <h1 className="font-heading text-2xl font-semibold">In your photo</h1>
      <PhotoView threadId={id} />
    </>
  );
}
