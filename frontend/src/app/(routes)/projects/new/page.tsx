import type { Metadata } from "next";
import { Wizard } from "@/components/wizard/wizard";

export const metadata: Metadata = { title: "New project" };

export default function NewProjectPage() {
  return (
    <>
      <h1 className="font-heading text-2xl font-semibold">New project</h1>
      <Wizard />
    </>
  );
}
