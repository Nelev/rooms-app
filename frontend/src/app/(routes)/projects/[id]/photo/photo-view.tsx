"use client";

import { useEffect, useState } from "react";
import { CameraMatch } from "@/components/scene3d/camera-match/camera-match";
import { PhotoComposite } from "@/components/scene3d/composite";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { photoUrl } from "@/lib/api";
import { useThread } from "@/lib/hooks/use-threads";

// The composite of the thread's design over one of its photos with a matched camera: the camera's photo (else the thread's first) as
// the API serves it, or one the user opens from their device.
export function PhotoView({ threadId }: { threadId: string }) {
  const thread = useThread(threadId);
  const [camera, setCamera] = useState(0);
  const [opened, setOpened] = useState<string>(); // a photo opened from the device
  useEffect(() => () => (opened ? URL.revokeObjectURL(opened) : undefined), [opened]);

  if (thread.error && !thread.data)
    return (
      <p role="alert" className="text-destructive text-sm">
        {thread.error.message}
      </p>
    );
  if (!thread.data) return <Skeleton role="status" aria-label="Loading the design" className="aspect-4/3 w-full" />;
  const scene = thread.data.values.scene;
  const first = thread.data.values.photo_keys?.[0];
  if (scene && !scene.cameras.length && first)
    return (
      <div className="flex flex-col gap-3">
        <p className="text-muted-foreground text-sm">
          The design is shown in a photo once the photo's camera is matched to the room: click the room's corners on it.
        </p>
        <CameraMatch
          threadId={threadId}
          photo={{ key: first, url: photoUrl(first) }}
          room={scene.room.dimensions}
          onConfirm={() => thread.refetch()}
        />
      </div>
    );
  if (!scene?.cameras.length)
    return (
      <Empty>
        <EmptyHeader>
          <EmptyTitle>{scene ? "No photo is matched to the room yet." : "No design yet."}</EmptyTitle>
          <EmptyDescription>The design is shown in a photo once the photo's camera is matched to the room.</EmptyDescription>
        </EmptyHeader>
      </Empty>
    );

  const pose = scene.cameras[camera];
  const key = pose.photo_key ?? thread.data.values.photo_keys?.[0];
  const photo = opened ?? (key ? photoUrl(key) : undefined);
  return (
    <div className="flex flex-col gap-3">
      {scene.cameras.length > 1 ? (
        <div className="flex flex-wrap gap-1">
          {scene.cameras.map((c, i) => (
            <Button
              key={c.photo_key}
              size="sm"
              variant={i === camera ? "default" : "outline"}
              aria-pressed={i === camera}
              onClick={() => {
                setCamera(i);
                setOpened(undefined);
              }}
            >
              Photo {i + 1}
            </Button>
          ))}
        </div>
      ) : null}
      <label htmlFor={`${threadId}-photo`} className="text-sm">
        Or open the photo {key?.split("/").at(-1)} from your device
      </label>
      <Input
        key={camera} // a new camera starts with no file, so the same file can be opened again
        id={`${threadId}-photo`}
        type="file"
        accept="image/*"
        onChange={(e) => {
          const file = e.target.files?.[0];
          setOpened(file ? URL.createObjectURL(file) : undefined);
        }}
      />
      {photo ? <PhotoComposite key={photo} scene={scene} camera={camera} photoUrl={photo} /> : null}
    </div>
  );
}
