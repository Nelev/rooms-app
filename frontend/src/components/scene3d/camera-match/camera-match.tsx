"use client";

import { type MouseEvent, useState } from "react";
import { Button } from "@/components/ui/button";
import { type ApiError, json, path, request } from "@/lib/api";
import type { components } from "@/lib/api/generated/schema";
import type { CameraPose, RoomSpec } from "../core/geometry";
import { wireframe } from "./wireframe";

type CornerPoint = components["schemas"]["CornerPoint"];
type Corner = Pick<CornerPoint, "corner" | "ceiling">;

// the floor corners first, as they are the ones a photo shows most; walls start at their corner (A at (0, 0), then counterclockwise)
const CORNERS: Corner[] = [false, true].flatMap((ceiling) => (["A", "B", "C", "D"] as const).map((corner) => ({ corner, ceiling })));
const MIN_POINTS = 4;
const label = ({ corner, ceiling }: Corner) => `${ceiling ? "Ceiling" : "Floor"} ${corner}`;
const same = (a: Corner, b: Corner) => a.corner === b.corner && a.ceiling === b.ceiling;

type Props = {
  threadId: string;
  photo: { key: string; url: string };
  room: RoomSpec["dimensions"];
  onConfirm?: (pose: CameraPose) => void;
};

// Matches a photo to the room: the user picks a room corner, clicks where the photo shows it, and so on for at least 4 corners. The API
// solves the camera and saves it in the scene right away (a new match for the same photo replaces it), then the room's edges are drawn
// from it over the photo, with the reprojection error, for the user to confirm or redo.
export function CameraMatch({ threadId, photo, room, onConfirm }: Props) {
  const [size, setSize] = useState<{ width: number; height: number }>();
  const [points, setPoints] = useState<CornerPoint[]>([]);
  const [active, setActive] = useState<Corner>(CORNERS[0]);
  const [pose, setPose] = useState<CameraPose>();
  const [error, setError] = useState<string>();
  const [solving, setSolving] = useState(false);

  // in the photo's pixels; the next corner to place is the first one not placed yet
  function place(event: MouseEvent<SVGSVGElement>) {
    if (!size || pose) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const point = {
      ...active,
      x: ((event.clientX - rect.left) / rect.width) * size.width,
      y: ((event.clientY - rect.top) / rect.height) * size.height,
    };
    const placed = [...points.filter((p) => !same(p, active)), point];
    setPoints(placed);
    setActive(CORNERS.find((c) => !placed.some((p) => same(p, c))) ?? active);
  }

  async function solve() {
    if (!size) return;
    setSolving(true);
    setError(undefined);
    const body = { photo_key: photo.key, image_width: size.width, image_height: size.height, points };
    const init = { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
    try {
      setPose(await json<CameraPose>(await request(path("/threads/{thread_id}/camera-pose", { thread_id: threadId }), init)));
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setSolving(false);
    }
  }

  function redo() {
    setPose(undefined);
    setPoints([]);
    setActive(CORNERS[0]);
    setError(undefined);
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="relative w-fit max-w-full">
        {/* biome-ignore lint/performance/noImgElement: a user's photo at its own size, under an overlay in its pixels */}
        <img
          src={photo.url}
          alt="Your room"
          className="block h-auto max-w-full"
          onLoad={(e) => setSize({ width: e.currentTarget.naturalWidth, height: e.currentTarget.naturalHeight })}
        />
        {size ? (
          // biome-ignore lint/a11y/useKeyWithClickEvents: placing a corner is pointing at a pixel; the corner buttons say which corners are placed
          <svg
            className="absolute inset-0 size-full cursor-crosshair"
            viewBox={`0 0 ${size.width} ${size.height}`}
            aria-label="Photo overlay: click where the photo shows the selected corner"
            role="img"
            onClick={place}
          >
            {pose
              ? wireframe(room, pose).map(([[x1, y1], [x2, y2]]) => (
                  <line
                    key={`${x1},${y1},${x2},${y2}`}
                    x1={x1}
                    y1={y1}
                    x2={x2}
                    y2={y2}
                    stroke="#16a34a"
                    strokeWidth={2}
                    vectorEffect="non-scaling-stroke"
                  />
                ))
              : null}
            {points.map((p) => (
              <g key={label(p)}>
                <circle cx={p.x} cy={p.y} r={size.width / 120} fill="#2563eb" stroke="white" vectorEffect="non-scaling-stroke" />
                <text x={p.x} y={p.y} dx={size.width / 80} fontSize={size.width / 40} fill="#2563eb" stroke="white" strokeWidth={0.5}>
                  {label(p)}
                </text>
              </g>
            ))}
          </svg>
        ) : null}
      </div>
      {pose ? (
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm">
            The room's edges from the matched camera
            {pose.reprojection_error != null ? `: the corners are ${pose.reprojection_error.toFixed(1)} px off on average.` : "."} Do they line up
            with the photo?
          </p>
          <Button size="sm" onClick={() => onConfirm?.(pose)}>
            Confirm
          </Button>
          <Button size="sm" variant="outline" onClick={redo}>
            Redo
          </Button>
        </div>
      ) : (
        <>
          <p className="text-muted-foreground text-sm">
            Pick a corner, then click where the photo shows it. Match at least {MIN_POINTS} corners: corner A is where wall A starts, the others
            follow counterclockwise.
          </p>
          <fieldset className="flex flex-wrap gap-1">
            <legend className="sr-only">Room corners</legend>
            {CORNERS.map((c) => (
              <Button
                key={label(c)}
                size="sm"
                variant={same(c, active) ? "default" : "outline"}
                aria-pressed={same(c, active)}
                onClick={() => setActive(c)}
              >
                {label(c)}
                {points.some((p) => same(p, c)) ? " ✓" : ""}
              </Button>
            ))}
          </fieldset>
          <div className="flex gap-2">
            <Button size="sm" disabled={points.length < MIN_POINTS || solving} onClick={solve}>
              {solving ? "Matching…" : "Match camera"}
            </Button>
            <Button size="sm" variant="outline" disabled={points.length === 0} onClick={redo}>
              Clear
            </Button>
          </div>
        </>
      )}
      {error ? (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      ) : null}
    </div>
  );
}
