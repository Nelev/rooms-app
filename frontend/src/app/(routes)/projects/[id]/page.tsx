import { MessageSquare } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export const metadata: Metadata = { title: "Project" };

const TABS = [
  { value: "room", label: "Room" },
  { value: "design", label: "Design" },
  { value: "3d", label: "3D" },
  { value: "photo", label: "Photo" },
];

// Tabs whose full view lives on its own route (F-05 room confirm, F-07 results).
const LINKS: Record<string, string> = { room: "Confirm the room", design: "Open the design" };

// Placeholder workspace: the tabs and the chat panel get their content from later tasks.
export default async function ProjectPage({ params }: PageProps<"/projects/[id]">) {
  const { id } = await params;
  return (
    <>
      <h1 className="font-heading text-2xl font-semibold">Project {id}</h1>
      <div className="grid flex-1 gap-5 lg:grid-cols-[1fr_22rem]">
        <Tabs defaultValue="room">
          <TabsList>
            {TABS.map(({ value, label }) => (
              <TabsTrigger key={value} value={value}>
                {label}
              </TabsTrigger>
            ))}
          </TabsList>
          {TABS.map(({ value, label }) => (
            <TabsContent key={value} value={value} className="rounded-lg border p-4 text-muted-foreground">
              {label} view
              {value in LINKS && (
                <Link href={`/projects/${id}/${value}`} className="ml-2 text-primary underline-offset-4 hover:underline">
                  {LINKS[value]}
                </Link>
              )}
            </TabsContent>
          ))}
        </Tabs>
        <aside aria-label="Chat" className="flex flex-col rounded-lg border">
          <h2 className="border-b px-4 py-3 font-medium">Chat</h2>
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <MessageSquare aria-hidden />
              </EmptyMedia>
              <EmptyTitle>No messages yet</EmptyTitle>
              <EmptyDescription>Ask the assistant about your room.</EmptyDescription>
            </EmptyHeader>
          </Empty>
        </aside>
      </div>
    </>
  );
}
