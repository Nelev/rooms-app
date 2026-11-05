import { Field, FieldDescription, FieldGroup, FieldLabel, FieldLegend, FieldSet } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { fieldError, invalid, RANGES, type StepProps } from "./fields";

// The width, length and ceiling height of the room, in meters.
export function DimensionsStep(props: StepProps) {
  const { values, errors, id, set } = props;
  return (
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
              {...invalid(props, name)}
            />
            {fieldError(props, name)}
          </Field>
        ))}
      </FieldGroup>
    </FieldSet>
  );
}
