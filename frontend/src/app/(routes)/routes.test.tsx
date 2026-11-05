import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import ErrorPage from "./error";
import RoutesLayout from "./layout";
import Loading from "./loading";
import ProjectsPage from "./page";
import ProjectPage from "./projects/[id]/page";
import NewProjectPage from "./projects/new/page";

test("the shell has a skip link, a theme toggle and the main landmark", () => {
  const html = renderToStaticMarkup(<RoutesLayout params={Promise.resolve({})}>child</RoutesLayout>);
  expect(html).toContain('href="#main"');
  expect(html).toContain('aria-label="Toggle dark mode"');
  expect(html).toMatch(/<main id="main"[^>]*>child<\/main>/);
});

test("/ shows the empty projects list with a link to the wizard", () => {
  const html = renderToStaticMarkup(<ProjectsPage />);
  expect(html).toContain("No projects yet");
  expect(html).toContain('href="/projects/new"');
});

test("/projects/new shows the wizard at its photos step", () => {
  const html = renderToStaticMarkup(<NewProjectPage />);
  expect(html).toContain("New project");
  expect(html).toContain("Photos of the room");
});

test("/projects/[id] shows the four tabs and the chat panel", async () => {
  const html = renderToStaticMarkup(await ProjectPage({ params: Promise.resolve({ id: "p1" }), searchParams: Promise.resolve({}) }));
  expect(html).toContain("Project p1");
  for (const tab of ["Room", "Design", "3D", "Photo"]) expect(html).toMatch(new RegExp(`role="tab"[^>]*>${tab}<`));
  expect(html).toContain('<aside aria-label="Chat"');
});

test("loading and error states are announced", () => {
  expect(renderToStaticMarkup(<Loading />)).toContain('role="status"');
  const html = renderToStaticMarkup(<ErrorPage error={new Error("x")} retry={() => {}} />);
  expect(html).toContain('role="alert"');
  expect(html).toContain("Try again");
});
