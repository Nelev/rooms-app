"use client";

import { Camera, ImagePlus, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { type ReactNode, useEffect, useEffectEvent, useId, useRef, useState } from "react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel, FieldLegend, FieldSet } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";
import { ApiError, json, request, type Thread } from "@/lib/api";
import type { components } from "@/lib/api/generated/schema";
import { useRunStream } from "@/lib/hooks/use-run-stream";

type NewDesign = components["schemas"]["NewDesign"];
type Upload = components["schemas"]["Upload"];

const STEPS = ["Photos", "Dimensions", "Brief"];
const ROOM_USES = ["bedroom", "living room", "home office", "kids room", "dining room", "studio"];
const STYLES = ["scandinavian", "modern", "minimalist", "japandi", "industrial", "mid-century", "boho", "classic"];
const RANGES = { width: [1, 20], length: [1, 20], height: [2, 5] } as const; // m
const MAX_PHOTOS = 3;
const MAX_PHOTO_BYTES = 20 * 1024 * 1024; // the API's limit
const BUDGET = { min: 0, max: 10_000, step: 100 }; // EUR
const TIPS = [
  "Shoot from a corner, with the phone level at chest height.",
  "Get at least two walls and some floor in each photo.",
  "Turn the lights on and open the curtains.",
  "Use the normal lens, not the wide-angle one.",
];
const eur = new Intl.NumberFormat("en", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });

type Values = {
  photos: File[];
  width: string;
  length: string;
  height: string;
  room_use: string;
  styles: string[];
  budget: number;
  must_haves: string;
  keep: string;
  remove: string;
};
type Errors = Partial<Record<keyof Values, string>>;
const FIELDS: (keyof Values)[][] = [["photos"], ["width", "length", "height"], ["room_use"]];

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
  return Object.fromEntries(Object.entries(errors).filter(([name]) => FIELDS[step].includes(name as keyof Values)));
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

type ChipProps = { type: "radio" | "checkbox"; name: string; checked: boolean; onChange: () => void; children: ReactNode };
function Chip({ type, name, checked, onChange, children }: ChipProps) {
  return (
    <label className="cursor-pointer rounded-full border px-3 py-1 text-sm capitalize has-checked:border-primary has-checked:bg-primary has-checked:text-primary-foreground has-focus-visible:ring-3 has-focus-visible:ring-ring/50">
      <input type={type} name={name} checked={checked} onChange={onChange} className="sr-only" />
      {children}
    </label>
  );
}

function Preview({ file, onRemove }: { file: File; onRemove: () => void }) {
  const [url, setUrl] = useState<string>();
  useEffect(() => {
    const objectUrl = URL.createObjectURL(file);
    setUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [file]);
  return (
    <li className="relative">
      {/* biome-ignore lint/performance/noImgElement: a local blob preview, nothing for next/image to optimize */}
      {url && <img src={url} alt={file.name} className="aspect-4/3 w-full rounded-lg border object-cover" />}
      <Button
        type="button"
        size="icon-xs"
        variant="secondary"
        className="absolute top-1 right-1"
        aria-label={`Remove ${file.name}`}
        onClick={onRemove}
      >
        <X aria-hidden />
      </Button>
    </li>
  );
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
  const project = useRef<string>(undefined); // created by an earlier attempt whose run failed to start: a retry reuses it

  const set = <K extends keyof Values>(name: K, value: Values[K]) => setValues((v) => ({ ...v, [name]: value }));
  const addPhotos = (files: FileList | null) => files?.length && set("photos", [...values.photos, ...files]);
  const toggleStyle = (style: string) =>
    set("styles", values.styles.includes(style) ? values.styles.filter((s) => s !== style) : [...values.styles, style]);
  const invalid = (name: keyof Values) => ({ "aria-invalid": !!errors[name] || undefined, "aria-describedby": `${id}-${name}-error` });
  const error = (name: keyof Values) => <FieldError id={`${id}-${name}-error`}>{errors[name]}</FieldError>;

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
      const keys = await Promise.all(values.photos.map(upload));
      project.current ??= (await createProject(values.room_use)).thread_id;
      setStarted({ threadId: project.current, input: newDesign(values, keys) });
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
        {STEPS.map((name, i) => (
          <li key={name} aria-current={i === step ? "step" : undefined} className={i === step ? "font-medium" : "text-muted-foreground"}>
            {i + 1}. {name}
          </li>
        ))}
      </ol>

      {step === 0 && (
        <FieldSet>
          <FieldLegend>Photos of the room</FieldLegend>
          <FieldDescription>Add 1 to 3 photos, from different corners.</FieldDescription>
          <label
            className="flex cursor-pointer flex-col items-center gap-2 rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground has-focus-visible:ring-3 has-focus-visible:ring-ring/50 has-aria-invalid:border-destructive"
            onDrop={(e) => {
              e.preventDefault();
              addPhotos(e.dataTransfer.files);
            }}
          >
            <ImagePlus aria-hidden className="size-6" />
            <span>
              Drop photos here or <span className="text-foreground underline">choose files</span>
            </span>
            <input
              type="file"
              accept="image/*"
              multiple
              className="sr-only"
              {...invalid("photos")}
              onChange={(e) => {
                addPhotos(e.target.files);
                e.target.value = "";
              }}
            />
          </label>
          <label
            className={buttonVariants({
              variant: "outline",
              className: "w-fit cursor-pointer has-focus-visible:ring-3 has-focus-visible:ring-ring/50",
            })}
          >
            <Camera aria-hidden />
            Take a photo
            <input
              type="file"
              accept="image/*"
              capture="environment"
              className="sr-only"
              onChange={(e) => {
                addPhotos(e.target.files);
                e.target.value = "";
              }}
            />
          </label>
          {error("photos")}
          {values.photos.length > 0 && (
            <ul className="grid grid-cols-3 gap-3">
              {values.photos.map((file, i) => (
                <Preview
                  // biome-ignore lint/suspicious/noArrayIndexKey: files have no id and may repeat; a preview follows its file prop
                  key={i}
                  file={file}
                  onRemove={() =>
                    set(
                      "photos",
                      values.photos.filter((_, j) => j !== i),
                    )
                  }
                />
              ))}
            </ul>
          )}
          <div className="text-sm">
            <p className="font-medium">Capture tips</p>
            <ul className="list-disc pl-5 text-muted-foreground">
              {TIPS.map((tip) => (
                <li key={tip}>{tip}</li>
              ))}
            </ul>
          </div>
        </FieldSet>
      )}

      {step === 1 && (
        <FieldSet>
          <FieldLegend>Room dimensions</FieldLegend>
          <FieldDescription>In meters, measured wall to wall.</FieldDescription>
          <FieldGroup className="grid sm:grid-cols-3">
            {(Object.keys(RANGES) as (keyof typeof RANGES)[]).map((name) => (
              <Field key={name} data-invalid={!!errors[name] || undefined}>
                <FieldLabel htmlFor={`${id}-${name}`} className="capitalize">
                  {name === "height" ? "Ceiling height" : name} (m)
                </FieldLabel>
                <Input
                  id={`${id}-${name}`}
                  type="number"
                  inputMode="decimal"
                  step="0.01"
                  min={RANGES[name][0]}
                  max={RANGES[name][1]}
                  value={values[name]}
                  onChange={(e) => set(name, e.target.value)}
                  {...invalid(name)}
                />
                {error(name)}
              </Field>
            ))}
          </FieldGroup>
        </FieldSet>
      )}

      {step === 2 && (
        <FieldGroup>
          <FieldSet>
            <FieldLegend variant="label">What is the room for?</FieldLegend>
            <div role="radiogroup" className="flex flex-wrap gap-2" {...invalid("room_use")}>
              {ROOM_USES.map((use) => (
                <Chip key={use} type="radio" name={`${id}-room_use`} checked={values.room_use === use} onChange={() => set("room_use", use)}>
                  {use}
                </Chip>
              ))}
            </div>
            {error("room_use")}
          </FieldSet>
          <FieldSet>
            <FieldLegend variant="label">Style</FieldLegend>
            <div className="flex flex-wrap gap-2">
              {STYLES.map((style) => (
                <Chip key={style} type="checkbox" name={`${id}-styles`} checked={values.styles.includes(style)} onChange={() => toggleStyle(style)}>
                  {style}
                </Chip>
              ))}
            </div>
          </FieldSet>
          <Field>
            <FieldLabel>
              <span id={`${id}-budget`}>Budget</span> <output className="ml-auto font-normal">{eur.format(values.budget)}</output>
            </FieldLabel>
            <Slider
              aria-labelledby={`${id}-budget`}
              {...BUDGET}
              value={[values.budget]}
              onValueChange={(value) => set("budget", Array.isArray(value) ? value[0] : (value as number))}
            />
          </Field>
          {(
            [
              ["must_haves", "Must-have items", "double bed, desk"],
              ["keep", "Items to keep", "wardrobe"],
              ["remove", "Items to remove", "old armchair"],
            ] as const
          ).map(([name, label, example]) => (
            <Field key={name}>
              <FieldLabel htmlFor={`${id}-${name}`}>{label}</FieldLabel>
              <Input id={`${id}-${name}`} placeholder={`e.g. ${example}`} value={values[name]} onChange={(e) => set(name, e.target.value)} />
              <FieldDescription>Separate items with commas.</FieldDescription>
            </Field>
          ))}
        </FieldGroup>
      )}

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
