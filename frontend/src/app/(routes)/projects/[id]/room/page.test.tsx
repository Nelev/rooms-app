import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import ProjectPage from "../page";
import RoomPage from "./page";

test("/projects/[id]/room loads the room to confirm; the workspace's Room tab loads the room", async () => {
  const html = renderToStaticMarkup(await RoomPage({ params: Promise.resolve({ id: "p1" }), searchParams: Promise.resolve({}) }));
  expect(html).toContain("Confirm the room");
  expect(html).toContain('role="status"'); // until the thread's state arrives
  const workspace = renderToStaticMarkup(await ProjectPage({ params: Promise.resolve({ id: "p1" }), searchParams: Promise.resolve({}) }));
  // the Room tab links here only while confirm_room is open (components/workspace/sync/room.test.tsx), once the thread's state arrives
  expect(workspace).toContain('aria-label="Loading the room"');
});
