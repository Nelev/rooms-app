import type { Metadata } from "next";

export const metadata: Metadata = { title: "New project" };

// Placeholder for the new-project wizard.
export default function NewProjectPage() {
  return (
    <>
      <h1 className="font-heading text-2xl font-semibold">New project</h1>
      <p className="text-muted-foreground">The wizard to describe your room goes here.</p>
    </>
  );
}
