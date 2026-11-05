"use client";

import { TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";

// Error boundary of every route; retry() re-fetches and re-renders the segment.
export default function ErrorPage({ retry }: { error: Error & { digest?: string }; retry: () => void }) {
  return (
    <Empty role="alert" className="border">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <TriangleAlert aria-hidden />
        </EmptyMedia>
        <EmptyTitle>Something went wrong</EmptyTitle>
        <EmptyDescription>Try again, or come back later.</EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button onClick={() => retry()}>Try again</Button>
      </EmptyContent>
    </Empty>
  );
}
