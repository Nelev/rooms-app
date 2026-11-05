import { Skeleton } from "@/components/ui/skeleton";

// Shown while a route segment loads.
export default function Loading() {
  return (
    <div role="status" aria-label="Loading" className="flex flex-col gap-3">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-40 w-full" />
    </div>
  );
}
