import { expect, test } from "vitest";
import { cn } from "@/lib/utils";

test("cn merges conflicting Tailwind classes", () => {
  expect(cn("px-2", "px-4")).toBe("px-4");
});
