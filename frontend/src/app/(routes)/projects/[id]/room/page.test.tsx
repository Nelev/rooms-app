import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import ProjectPage from "../page";
import RoomPage from "./page";

test("/projects/[id]/room loads the room to confirm, linked from the workspace's Room tab", async () => {
  const html = renderToStaticMarkup(await RoomPage({ params: Promise.resolve({ id: "p1" }), searchParams: Promise.resolve({}) }));
  expect(html).toContain("Confirm the room");
  expect(html).toContain('role="status"'); // until the thread's state arrives
  const workspace = renderToStaticMarkup(await ProjectPage({ params: Promise.resolve({ id: "p1" }), searchParams: Promise.resolve({}) }));
  expect(workspace).toContain('href="/projects/p1/room"');
});
