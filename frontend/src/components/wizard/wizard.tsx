"use client";

import { useRouter } from "next/navigation";
import { useEffect, useEffectEvent, useId, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { ApiError, json, request, type Thread } from "@/lib/api";
import type { components } from "@/lib/api/generated/schema";
import { useRunStream } from "@/lib/hooks/use-run-stream";
import { BriefStep } from "./brief-step";
import { DimensionsStep } from "./dimensions-step";
import { type Errors, MAX_PHOTOS, RANGES, type StepProps, type Values } from "./fields";
import { PhotosStep } from "./photos-step";

type NewDesign = components["schemas"]["NewDesign"];
type Upload = components["schemas"]["Upload"];

const STEPS = [
  { name: "Photos", Step: PhotosStep, fields: ["photos"] },
  { name: "Dimensions", Step: DimensionsStep, fields: ["width", "length", "height"] },
  { name: "Brief", Step: BriefStep, fields: ["room_use"] },
] satisfies { name: string; Step: (props: StepProps) => React.ReactNode; fields: (keyof Values)[] }[];
const MAX_PHOTO_BYTES = 20 * 1024 * 1024; // the API's limit

const EMPTY: Values = { photos: [], width: "", length: "", height: "", room_use: "", styles: [], budget: 1500, must_haves: "", keep: "", remove: "" };

// What is wrong with the values of the given step, by field: earlier steps have passed already.
function check(values: Values, step: number): Errors {
  const errors: Errors = {};
  const { photos } = values;
  if (photos.length < 1 || photos.length > MAX_PHOTOS) errors.photos = `Add 1 to ${MAX_PHOTOS} photos of the room`;
  else if (photos.some((file) => !file.type.startsWith("image/"))) errors.photos = "Photos must be images";
  else if (photos.some((file) => file.size > MAX_PHOTO_BYTES)) errors.photos = "Each photo must be under 20 MB";
  for (const [name, [min, max]] of Object.entries(RANGES) as [keyof typeof RANGES, readonly [number, number]][]) {
    const meters = Number(values[name]);
    if (!values[name].trim() || !(meters >= min && meters <= max)) errors[name] = `Enter a number from ${min} to ${max} m`;
  }
  if (!values.room_use) errors.room_use = "Choose what the room is for";
  const fields: (keyof Values)[] = STEPS[step].fields;
  return Object.fromEntries(Object.entries(errors).filter(([name]) => fields.includes(name as keyof Values)));
}

const list = (text: string) =>
  text
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

// The run input of the values, once the photos are uploaded.
function newDesign(values: Values, photo_keys: string[]): NewDesign {
  const { width, length, height, room_use, styles, budget, must_haves, keep, remove } = values;
  return {
    photo_keys,
    dimensions: { width: Number(width), length: Number(length), height: Number(height) },
    brief: { room_use, styles, budget, must_haves: list(must_haves), keep: list(keep), remove: list(remove), notes: "" },
  };
}

async function upload(file: File): Promise<string> {
  const body = new FormData();
  body.append("file", file);
  return (await json<Upload>(await request("/uploads", { method: "POST", body, timeout: 120_000 }))).key;
}

async function createProject(title: string): Promise<Thread> {
  const init = { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ metadata: { title } }) };
  return json<Thread>(await request("/threads", init));
}

// Starts the design run, and goes to the workspace once the run has started: the run goes on without this page.
function StartRun({ threadId, input, onError }: { threadId: string; input: NewDesign; onError: (message: string) => void }) {
  const router = useRouter();
  const { submit, runId, error } = useRunStream(threadId);
  const start = useEffectEvent(() => submit({ input }));
  const fail = useEffectEvent(onError);
  useEffect(() => start(), []); // in Strict Mode the first submit is aborted before it is sent
  useEffect(() => {
    if (runId) router.push(`/projects/${threadId}`);
  }, [runId, router, threadId]);
  useEffect(() => {
    if (error) fail(error.message);
  }, [error]);
  return null;
}

// The new-project wizard: photos, dimensions, brief. Each step is checked before the next; submitting uploads the photos, creates
// the project and starts its design run.
export function Wizard() {
  const [step, setStep] = useState(0);
  const [values, setValues] = useState(EMPTY);
  const [errors, setErrors] = useState<Errors>({});
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<string>();
  const [started, setStarted] = useState<{ threadId: string; input: NewDesign }>();
  const id = useId();
  // made by an earlier attempt that failed later on: a retry reuses them, the uploads as long as the photos are the same
  const uploaded = useRef<{ photos: File[]; keys: string[] }>(undefined);
  const project = useRef<string>(undefined);

  const set: StepProps["set"] = (name, value) => setValues((v) => ({ ...v, [name]: value }));
  const { Step } = STEPS[step];

  const fail = (message: string) => {
    setFailure(message);
    setStarted(undefined);
    setPending(false);
  };

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    const found = check(values, step);
    setErrors(found);
    if (Object.keys(found).length) return;
    if (step < STEPS.length - 1) return setStep(step + 1);
    setPending(true);
    setFailure(undefined);
    try {
      const { photos } = values;
      if (uploaded.current?.photos !== photos) uploaded.current = { photos, keys: await Promise.all(photos.map(upload)) };
      project.current ??= (await createProject(values.room_use)).thread_id;
      setStarted({ threadId: project.current, input: newDesign(values, uploaded.current.keys) });
    } catch (e) {
      fail(e instanceof ApiError ? e.message : String(e));
    }
  }

  return (
    // a drop that misses the drop zone does nothing, instead of the browser opening the photo and leaving the wizard
    <form
      noValidate
      onSubmit={onSubmit}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => e.preventDefault()}
      className="flex max-w-2xl flex-col gap-6"
    >
      <ol className="flex gap-4 text-sm">
        {STEPS.map(({ name }, i) => (
          <li key={name} aria-current={i === step ? "step" : undefined} className={i === step ? "font-medium" : "text-muted-foreground"}>
            {i + 1}. {name}
          </li>
        ))}
      </ol>

      <Step values={values} errors={errors} id={id} set={set} />

      {failure && (
        <p role="alert" className="text-sm text-destructive">
          Could not start the design: {failure}
        </p>
      )}
      <div className="flex gap-2">
        {step > 0 && (
          <Button type="button" variant="outline" disabled={pending} onClick={() => setStep(step - 1)}>
            Back
          </Button>
        )}
        <Button type="submit" disabled={pending}>
          {step < STEPS.length - 1 ? "Next" : pending ? "Starting…" : "Design my room"}
        </Button>
      </div>
      {started && <StartRun threadId={started.threadId} input={started.input} onError={fail} />}
    </form>
  );
}
