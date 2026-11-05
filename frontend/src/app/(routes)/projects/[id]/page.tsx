import type { Metadata } from "next";
import Link from "next/link";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { WorkspaceProvider } from "@/components/workspace/sync/store";
import { WorkspaceChat, WorkspaceResults, WorkspaceScene } from "@/components/workspace/sync/views";

export const metadata: Metadata = { title: "Project" };

const TABS = [
  { value: "room", label: "Room" },
  { value: "design", label: "Design" },
  { value: "3d", label: "3D" },
  { value: "photo", label: "Photo" },
];

// The project's workspace: the design, its 3D view and the chat share one store (F-13); the other tabs get their content later.
export default async function ProjectPage({ params }: PageProps<"/projects/[id]">) {
  const { id } = await params;
  return (
    <WorkspaceProvider threadId={id}>
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
            <TabsContent key={value} value={value} className="rounded-lg border p-4">
              {value === "design" ? (
                <WorkspaceResults />
              ) : value === "3d" ? (
                <WorkspaceScene />
              ) : (
                <span className="text-muted-foreground">{label} view</span>
              )}
              {value === "room" && (
                <Link href={`/projects/${id}/room`} className="ml-2 text-primary underline-offset-4 hover:underline">
                  Confirm the room
                </Link>
              )}
            </TabsContent>
          ))}
        </Tabs>
        <aside aria-label="Chat" className="flex flex-col rounded-lg border">
          <h2 className="border-b px-4 py-3 font-medium">Chat</h2>
          <WorkspaceChat />
        </aside>
      </div>
    </WorkspaceProvider>
  );
}
