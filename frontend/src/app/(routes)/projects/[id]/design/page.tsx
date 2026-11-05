import type { Metadata } from "next";
import { ResultsView } from "@/components/results/results-view";

export const metadata: Metadata = { title: "Design" };

// The project's finished design: plan, shopping list, rationale and the Critic's review.
export default async function DesignPage({ params }: PageProps<"/projects/[id]/design">) {
  const { id } = await params;
  return (
    <>
      <h1 className="font-heading text-2xl font-semibold">Design</h1>
      <ResultsView threadId={id} />
    </>
  );
}
