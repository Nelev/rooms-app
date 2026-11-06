"use client";

import { Check, ExternalLink, ImageOff, X } from "lucide-react";
import { type ReactNode, useState } from "react";
import { FloorPlan } from "@/components/plan/floor-plan";
import { Empty, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import type { ApiError } from "@/lib/api";
import type { components } from "@/lib/api/generated/schema";
import { useThread } from "@/lib/hooks/use-threads";
import { cn } from "@/lib/utils";

type Schemas = components["schemas"];
type RunState = Schemas["RunState"];
type CatalogItem = Schemas["CatalogItem"];

const eur = new Intl.NumberFormat("en", { style: "currency", currency: "EUR", minimumFractionDigits: 0, maximumFractionDigits: 2 });
const cm = (m: number) => Math.round(m * 100);
const dimensions = ({ width, depth, height }: CatalogItem["size"]) => `${cm(width)} × ${cm(depth)} × ${cm(height)} cm`;
const label = (nodeId: string) => nodeId.replaceAll("_", " ");

function Thumbnail({ item }: { item: CatalogItem }) {
  return item.image_url ? (
    // biome-ignore lint/performance/noImgElement: catalog images come from any host, next/image would need each one configured
    <img src={item.image_url} alt="" className="size-12 shrink-0 rounded-md object-cover" />
  ) : (
    <span className="flex size-12 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
      <ImageOff aria-hidden className="size-4" />
    </span>
  );
}

function Link({ item }: { item: CatalogItem }) {
  if (!item.url || !/^https?:\/\//i.test(item.url)) return null; // catalog URLs are untrusted: never render javascript: and co.
  return (
    <a
      href={item.url}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={`Shop ${item.name}`}
      className="inline-flex items-center gap-1 text-primary text-xs hover:underline"
    >
      Shop <ExternalLink aria-hidden className="size-3" />
    </a>
  );
}

// A project's finished design: the plan and the shopping list, where selecting an item in one highlights it in both, with the
// Sourcer's other candidates for the selected item, the total against the budget, the rationale and the Critic's rules.
// F-13: `highlighted` items (a chat edit just changed them) stand out, and clicking an item in the plan also calls `onPick` with its id.
export function Results({ values, highlighted = [], onPick }: { values: RunState; highlighted?: string[]; onPick?: (id: string) => void }) {
  const [selectedId, setSelectedId] = useState<string>();
  const room = values.scene?.room ?? values.room_spec;
  const items = (values.scene?.items ?? []).filter((i): i is typeof i & { item: CatalogItem } => !!i.item);
  const total = items.reduce((sum, i) => sum + i.item.price, 0);
  const budget = values.brief?.budget;
  // the Presenter sets the rationale; an older thread without one falls back to the design brief's summary
  const rationale = values.rationale ?? values.design_brief?.summary;
  const critique = values.critique;
  const select = (id: string) => setSelectedId((current) => (current === id ? undefined : id));

  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_24rem]">
      <div className="flex flex-col gap-5">
        {rationale && (
          <section aria-labelledby="rationale" className="flex flex-col gap-1">
            <h2 id="rationale" className="font-medium">
              Why this design
            </h2>
            <p className="text-muted-foreground text-sm">{rationale}</p>
          </section>
        )}
        {room && (
          <FloorPlan
            room={room}
            layout={values.layout}
            report={values.validation}
            selectedId={selectedId}
            onSelect={(id) => {
              select(id);
              onPick?.(id);
            }}
            highlighted={highlighted}
            className="rounded-lg border"
          />
        )}
        {critique && (
          <section aria-labelledby="critique" className="flex flex-col gap-2">
            <h2 id="critique" className="font-medium">
              Critic review
            </h2>
            <p className="text-muted-foreground text-sm">{critique.summary}</p>
            {critique.rules.length > 0 && (
              <ul className="flex flex-col gap-1 text-sm">
                {critique.rules.map((r) => (
                  <li key={r.rule} className="flex gap-2">
                    {r.passed ? (
                      <Check aria-label="passed" className="size-4 shrink-0 text-emerald-600" />
                    ) : (
                      <X aria-label="failed" className="size-4 shrink-0 text-destructive" />
                    )}
                    <span>
                      {label(r.rule)}
                      {r.message && <span className="text-muted-foreground"> — {r.message}</span>}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}
      </div>

      <section aria-labelledby="shopping-list" className="flex flex-col gap-3">
        <h2 id="shopping-list" className="font-medium">
          Shopping list
        </h2>
        <ul className="flex flex-col gap-2">
          {items.map(({ node_id, item }) => {
            const selected = node_id === selectedId;
            const changed = highlighted.includes(node_id);
            const alternatives = (values.candidates?.[node_id] ?? []).filter((c) => c.id !== item.id);
            return (
              <li
                key={node_id}
                data-id={node_id}
                data-highlighted={changed || undefined}
                className={cn("rounded-lg border p-2", changed && "bg-primary/10", selected && "border-primary ring-2 ring-primary/30")}
              >
                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    aria-pressed={selected}
                    onClick={() => select(node_id)}
                    className="flex min-w-0 flex-1 items-center gap-3 rounded-md text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <Thumbnail item={item} />
                    <span className="flex min-w-0 flex-col">
                      <span className="truncate font-medium text-sm">{item.name}</span>
                      <span className="text-muted-foreground text-xs">{dimensions(item.size)}</span>
                    </span>
                  </button>
                  <span className="flex flex-col items-end gap-1">
                    <span className="font-medium text-sm tabular-nums">{eur.format(item.price)}</span>
                    <Link item={item} />
                  </span>
                </div>
                {selected && (
                  <div className="mt-2 border-t pt-2">
                    <h3 className="text-muted-foreground text-xs">Alternatives for the {label(node_id)}</h3>
                    {alternatives.length ? (
                      <ul aria-label={`Alternatives for the ${label(node_id)}`} className="mt-1 flex flex-col gap-1">
                        {alternatives.map((alt) => (
                          <li key={alt.id} className="flex items-center gap-3 text-sm">
                            <Thumbnail item={alt} />
                            <span className="flex min-w-0 flex-1 flex-col">
                              <span className="truncate">{alt.name}</span>
                              <span className="text-muted-foreground text-xs">{dimensions(alt.size)}</span>
                            </span>
                            <span className="flex flex-col items-end gap-1">
                              <span className="tabular-nums">{eur.format(alt.price)}</span>
                              <Link item={alt} />
                            </span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="mt-1 text-sm">No other candidates.</p>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
        <p className="flex justify-between border-t pt-2 font-medium text-sm">
          <span>Total</span>
          <span className={cn("tabular-nums", budget !== undefined && total > budget && "text-destructive")}>
            {eur.format(total)}
            {budget !== undefined && <span className="font-normal text-muted-foreground"> of {eur.format(budget)} budget</span>}
          </span>
        </p>
      </section>
    </div>
  );
}

// The thread's design once its state is loaded, or else its error, a placeholder while it loads, or that there is none yet.
export function WithDesign({
  values,
  error,
  what = "design",
  children,
}: {
  values?: RunState;
  error?: ApiError;
  what?: string;
  children: ReactNode;
}) {
  if (error && !values)
    return (
      <p role="alert" className="text-destructive text-sm">
        {error.message}
      </p>
    );
  if (!values) return <Skeleton role="status" aria-label={`Loading the ${what}`} className="h-96 w-full" />;
  if (!values.scene)
    return (
      <Empty>
        <EmptyHeader>
          <EmptyTitle>No design yet.</EmptyTitle>
        </EmptyHeader>
      </Empty>
    );
  return children;
}

// The results of the project's thread, once its state is loaded.
export function ResultsView({ threadId }: { threadId: string }) {
  const { data, error } = useThread(threadId);
  return (
    <WithDesign values={data?.values} error={error}>
      {data && <Results values={data.values} />}
    </WithDesign>
  );
}
