import { Camera, ImagePlus, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Button, buttonVariants } from "@/components/ui/button";
import { FieldDescription, FieldLegend, FieldSet } from "@/components/ui/field";
import { fieldError, invalid, type StepProps } from "./fields";

const TIPS = [
  "Shoot from a corner, with the phone level at chest height.",
  "Get at least two walls and some floor in each photo.",
  "Turn the lights on and open the curtains.",
  "Use the normal lens, not the wide-angle one.",
];

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

// The photos of the room, by drag and drop or camera, with their previews and the capture tips.
export function PhotosStep(props: StepProps) {
  const { values, set } = props;
  const addPhotos = (files: FileList | null) => files?.length && set("photos", [...values.photos, ...files]);
  return (
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
          {...invalid(props, "photos")}
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
      {fieldError(props, "photos")}
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
  );
}
