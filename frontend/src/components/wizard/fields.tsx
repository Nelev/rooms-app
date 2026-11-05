import { FieldError } from "@/components/ui/field";

export const RANGES = { width: [1, 20], length: [1, 20], height: [2, 5] } as const; // m
export const MAX_PHOTOS = 3;

export type Values = {
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
export type Errors = Partial<Record<keyof Values, string>>;

// What a step of the wizard renders from, and how it changes the values.
export type StepProps = {
  values: Values;
  errors: Errors;
  id: string;
  set: <K extends keyof Values>(name: K, value: Values[K]) => void;
};

// The attributes of the input of a field, which point at its inline error.
export const invalid = ({ errors, id }: StepProps, name: keyof Values) => ({
  "aria-invalid": !!errors[name] || undefined,
  "aria-describedby": `${id}-${name}-error`,
});
export const fieldError = ({ errors, id }: StepProps, name: keyof Values) => <FieldError id={`${id}-${name}-error`}>{errors[name]}</FieldError>;
