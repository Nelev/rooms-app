"use client";

import { ImageOff, Plus, Trash2 } from "lucide-react";
import { type PointerEvent, type ReactNode, useId, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { photoUrl } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { Feature, Point, RoomSpec } from "../coords";
import { wallFrame } from "../coords";
import { FloorPlan, SCALE } from "../floor-plan";
import {
  addFeature,
  addKept,
  dragTo,
  isFeature,
  type KeptItem,
  LOW_CONFIDENCE,
  planReport,
  ROOM,
  remove,
  roomIssues,
  setFeature,
  setKept,
} from "./room";

const TYPES: Feature["type"][] = ["window", "door", "radiator", "outlet", "built_in", "column", "other"];
const WALLS: Feature["wall"][] = ["A", "B", "C", "D"];
const SELECT = "h-8 rounded-lg border border-input bg-transparent px-2 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50";
const show = (n: number) => (Number.isFinite(n) ? Math.round(n * 1000) / 1000 : ""); // an emptied field stays empty (NaN)

// A field with its label above it.
function Labeled({ label, children }: { label: string; children: (id: string) => ReactNode }) {
  const id = useId();
  return (
    <Field className="w-auto gap-1">
      <FieldLabel htmlFor={id} className="font-normal text-muted-foreground text-xs">
        {label}
      </FieldLabel>
      {children(id)}
    </Field>
  );
}

function Num({ label, value, onChange, step = 0.01 }: { label: string; value: number; onChange: (n: number) => void; step?: number }) {
  return (
    <Labeled label={label}>
      {(id) => (
        <Input
          id={id}
          type="number"
          inputMode="decimal"
          step={step}
          value={show(value)}
          onChange={(e) => onChange(e.target.valueAsNumber)}
          className="w-24"
        />
      )}
    </Labeled>
  );
}

function Choice<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: T[]; onChange: (v: T) => void }) {
  return (
    <Labeled label={label}>
      {(id) => (
        <select id={id} value={value} onChange={(e) => onChange(e.target.value as T)} className={SELECT}>
          {options.map((o) => (
            <option key={o} value={o}>
              {o.replace("_", " ")}
            </option>
          ))}
        </select>
      )}
    </Labeled>
  );
}

// A feature or kept item in the lists: its fields, and what is wrong with it.
function Entry({
  id,
  title,
  selected,
  errors,
  onSelect,
  onRemove,
  children,
}: {
  id: string;
  title: ReactNode;
  selected: boolean;
  errors: string[];
  onSelect: () => void;
  onRemove: () => void;
  children: ReactNode;
}) {
  return (
    // a field in focus highlights its feature or item on the plan
    <li
      data-entry={id}
      onFocus={onSelect}
      className={cn("flex flex-col gap-2 rounded-lg border p-3", selected && "border-primary", errors.length && "border-destructive")}
    >
      <div className="flex items-center gap-2 font-medium text-sm">
        {title}
        <Button variant="ghost" size="icon-xs" aria-label={`Delete ${id}`} onClick={onRemove} className="ml-auto">
          <Trash2 aria-hidden />
        </Button>
      </div>
      <div className="flex flex-wrap gap-2">{children}</div>
      {errors.length > 0 && <FieldError>{errors.join(". ")}</FieldError>}
    </li>
  );
}

type Props = { initial: RoomSpec; photos: string[]; sending?: boolean; onConfirm: (room: RoomSpec) => void };

// The room as analyzed, to correct before the design starts: the photos next to the editable plan, the detected features (the ones the
// analysis is unsure of highlighted) and the kept furniture. Features are dragged along the walls on the plan and kept items around it;
// every field can be typed in. The room can only be confirmed while it is valid (see roomIssues).
export function RoomEditor({ initial, photos, sending, onConfirm }: Props) {
  const [room, setRoom] = useState(initial);
  const [selected, setSelected] = useState<string>();
  const dragging = useRef<string>(null);
  const issues = roomIssues(room);
  const errorsOf = (id: string) => issues.filter((i) => i.id === id).map((i) => i.message);
  const dims = room.dimensions;

  // the pointer in room meters, from the plan's viewBox (FloorPlan pads the room by the same margin on every side)
  function toRoom(e: PointerEvent<HTMLDivElement>): Point | undefined {
    const svg = e.currentTarget.querySelector("svg");
    const [, , w, h] = (svg?.getAttribute("viewBox") ?? "").split(" ").map(Number);
    const box = svg?.getBoundingClientRect();
    if (!box?.width || !box.height) return;
    const pad = w / SCALE / 2 - dims.width / 2;
    const x = (((e.clientX - box.left) / box.width) * w) / SCALE - pad;
    const y = (((e.clientY - box.top) / box.height) * h) / SCALE - pad;
    return [x, dims.length - y]; // SVG's y points down
  }

  function onPointerDown(e: PointerEvent<HTMLDivElement>) {
    const id = (e.target as Element).closest("[data-id]")?.getAttribute("data-id");
    if (!id || !(isFeature(room, id) || room.kept_furniture.some((k) => k.id === id))) return;
    dragging.current = id;
    setSelected(id);
    e.currentTarget.setPointerCapture?.(e.pointerId);
  }

  function onPointerMove(e: PointerEvent<HTMLDivElement>) {
    const id = dragging.current;
    const point = id && toRoom(e);
    if (id && point) setRoom((r) => dragTo(r, id, point));
  }

  const add = ([next, id]: [RoomSpec, string]) => {
    setRoom(next);
    setSelected(id);
  };
  const feature = (f: Feature) => (patch: Partial<Feature>) => setRoom((r) => setFeature(r, f.id, patch));
  const kept = (k: KeptItem) => (patch: Partial<KeptItem>) => setRoom((r) => setKept(r, k.id, patch));
  const setDims = (name: keyof RoomSpec["dimensions"]) => (n: number) => setRoom((r) => ({ ...r, dimensions: { ...r.dimensions, [name]: n } }));

  return (
    <div className="flex flex-col gap-5">
      <div className="grid gap-4 lg:grid-cols-2">
        <figure className="flex flex-col gap-2">
          {photos.length ? (
            photos.map((key, i) => (
              // biome-ignore lint/performance/noImgElement: a user's photo from the API or a signed URL, nothing for next/image to optimize
              <img key={key} src={photoUrl(key)} alt={`Your room, view ${i + 1}`} className="w-full rounded-lg border bg-muted" />
            ))
          ) : (
            <div className="flex aspect-[4/3] flex-col items-center justify-center gap-2 rounded-lg border bg-muted p-4 text-center text-muted-foreground text-sm">
              <ImageOff aria-hidden />
              No photos
            </div>
          )}
          {photos.length ? <figcaption className="break-all text-muted-foreground text-xs">{photos.join(", ")}</figcaption> : null}
        </figure>
        <div
          className="touch-none"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={() => {
            dragging.current = null;
          }}
          onPointerCancel={() => {
            dragging.current = null;
          }}
        >
          <FloorPlan room={room} report={planReport(room, issues)} selectedId={selected} onSelect={setSelected} className="cursor-grab" />
          <p className="mt-1 text-muted-foreground text-xs">Drag features along the walls and furniture around the room.</p>
        </div>
      </div>

      {room.warnings.length > 0 && (
        <ul className="list-disc pl-5 text-amber-700 text-sm dark:text-amber-400">
          {room.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}

      <section aria-labelledby="dimensions" className="flex flex-col gap-2">
        <h2 id="dimensions" className="font-medium">
          Dimensions
        </h2>
        <div className="flex flex-wrap gap-2">
          <Num label="Width, walls A and C (m)" value={dims.width} onChange={setDims("width")} />
          <Num label="Length, walls B and D (m)" value={dims.length} onChange={setDims("length")} />
          <Num label="Ceiling height (m)" value={dims.height} onChange={setDims("height")} />
        </div>
        {errorsOf(ROOM).length > 0 && <FieldError>{errorsOf(ROOM).join(". ")}</FieldError>}
      </section>

      <section aria-labelledby="features" className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <h2 id="features" className="font-medium">
            Features
          </h2>
          <Button variant="outline" size="sm" onClick={() => add(addFeature(room))}>
            <Plus aria-hidden /> Add feature
          </Button>
        </div>
        <ul className="flex flex-col gap-2">
          {room.features.map((f) => {
            const set = feature(f);
            const wall = wallFrame(dims, f.wall).length;
            const confidence = f.confidence ?? 1;
            const low = confidence < LOW_CONFIDENCE;
            return (
              <Entry
                key={f.id}
                id={f.id}
                selected={f.id === selected}
                errors={errorsOf(f.id)}
                onSelect={() => setSelected(f.id)}
                onRemove={() => setRoom((r) => remove(r, f.id))}
                title={
                  <>
                    {f.id}
                    <span
                      className={cn(
                        "rounded-full px-2 py-0.5 font-normal text-xs",
                        low ? "bg-amber-500/20 text-amber-800 dark:text-amber-300" : "bg-muted text-muted-foreground",
                      )}
                    >
                      {Math.round(confidence * 100)}% sure{low && ": check it"}
                    </span>
                  </>
                }
              >
                <Choice label="Type" value={f.type} options={TYPES} onChange={(type) => set({ type })} />
                <Choice label="Wall" value={f.wall} options={WALLS} onChange={(w) => set({ wall: w })} />
                <Num label="Center from wall start (m)" value={f.offset * wall} onChange={(m) => set({ offset: m / wall })} />
                <Num label="Width (m)" value={f.width} onChange={(width) => set({ width })} />
                <Num label="Height (m)" value={f.height} onChange={(height) => set({ height })} />
                <Num label="Above floor (m)" value={f.sill_height ?? 0} onChange={(sill_height) => set({ sill_height })} />
                {f.type === "door" && (
                  <>
                    <Choice label="Opens" value={f.swing ?? "in"} options={["in", "out"]} onChange={(swing) => set({ swing })} />
                    <Choice label="Hinge" value={f.hinge ?? "left"} options={["left", "right"]} onChange={(hinge) => set({ hinge })} />
                  </>
                )}
              </Entry>
            );
          })}
        </ul>
      </section>

      <section aria-labelledby="kept" className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <h2 id="kept" className="font-medium">
            Furniture you keep
          </h2>
          <Button variant="outline" size="sm" onClick={() => add(addKept(room))}>
            <Plus aria-hidden /> Add furniture
          </Button>
        </div>
        <ul className="flex flex-col gap-2">
          {room.kept_furniture.map((k) => {
            const set = kept(k);
            return (
              <Entry
                key={k.id}
                id={k.id}
                selected={k.id === selected}
                errors={errorsOf(k.id)}
                onSelect={() => setSelected(k.id)}
                onRemove={() => setRoom((r) => remove(r, k.id))}
                title={k.id}
              >
                <Labeled label="Name">
                  {(id) => <Input id={id} value={k.name} onChange={(e) => set({ name: e.target.value })} className="w-36" />}
                </Labeled>
                <Num label="Center x (m)" value={k.x} onChange={(x) => set({ x })} />
                <Num label="Center y (m)" value={k.y} onChange={(y) => set({ y })} />
                <Num label="Rotation (°)" value={k.rotation ?? 0} step={90} onChange={(rotation) => set({ rotation })} />
                <Num label="Width (m)" value={k.size.width} onChange={(width) => set({ size: { ...k.size, width } })} />
                <Num label="Depth (m)" value={k.size.depth} onChange={(depth) => set({ size: { ...k.size, depth } })} />
                <Num label="Height (m)" value={k.size.height} onChange={(height) => set({ size: { ...k.size, height } })} />
              </Entry>
            );
          })}
        </ul>
      </section>

      <div className="flex items-center justify-end gap-3">
        {issues.length > 0 && (
          <p className="text-destructive text-sm">
            Fix {issues.length} problem{issues.length > 1 && "s"} to confirm
          </p>
        )}
        <Button disabled={sending || issues.length > 0} onClick={() => onConfirm(room)}>
          Confirm room
        </Button>
      </div>
    </div>
  );
}
