import type { ReactNode } from "react";
import { Field, FieldDescription, FieldGroup, FieldLabel, FieldLegend, FieldSet } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";
import { fieldError, invalid, type StepProps } from "./fields";

const ROOM_USES = ["bedroom", "living room", "home office", "kids room", "dining room", "studio"];
const STYLES = ["scandinavian", "modern", "minimalist", "japandi", "industrial", "mid-century", "boho", "classic"];
const BUDGET = { min: 0, max: 10_000, step: 100 }; // EUR
const eur = new Intl.NumberFormat("en", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });

type ChipProps = { type: "radio" | "checkbox"; name: string; checked: boolean; onChange: () => void; children: ReactNode };
function Chip({ type, name, checked, onChange, children }: ChipProps) {
  return (
    <label className="cursor-pointer rounded-full border px-3 py-1 text-sm capitalize has-checked:border-primary has-checked:bg-primary has-checked:text-primary-foreground has-focus-visible:ring-3 has-focus-visible:ring-ring/50">
      <input type={type} name={name} checked={checked} onChange={onChange} className="sr-only" />
      {children}
    </label>
  );
}

// The brief: room use, styles, budget, and the items the design must have, keep or remove.
export function BriefStep(props: StepProps) {
  const { values, id, set } = props;
  const toggleStyle = (style: string) =>
    set("styles", values.styles.includes(style) ? values.styles.filter((s) => s !== style) : [...values.styles, style]);
  return (
    <FieldGroup>
      <FieldSet>
        <FieldLegend variant="label">What is the room for?</FieldLegend>
        <div role="radiogroup" className="flex flex-wrap gap-2" {...invalid(props, "room_use")}>
          {ROOM_USES.map((use) => (
            <Chip key={use} type="radio" name={`${id}-room_use`} checked={values.room_use === use} onChange={() => set("room_use", use)}>
              {use}
            </Chip>
          ))}
        </div>
        {fieldError(props, "room_use")}
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
  );
}
