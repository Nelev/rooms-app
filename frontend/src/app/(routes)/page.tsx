import { FolderOpen, Plus } from "lucide-react";
import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";

// Placeholder: the list of projects comes with the data layer (F-02).
export default function ProjectsPage() {
  return (
    <>
      <h1 className="font-heading text-2xl font-semibold">Projects</h1>
      <Empty className="border">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <FolderOpen aria-hidden />
          </EmptyMedia>
          <EmptyTitle>No projects yet</EmptyTitle>
          <EmptyDescription>Start a project to design a room with the assistant.</EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Link href="/projects/new" className={buttonVariants()}>
            <Plus aria-hidden />
            New project
          </Link>
        </EmptyContent>
      </Empty>
    </>
  );
}
