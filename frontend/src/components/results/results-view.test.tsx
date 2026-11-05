// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import DesignPage from "@/app/(routes)/projects/[id]/design/page";
import { stubApi } from "@/lib/mocks/stub-api";
import { Results, ResultsView } from "./results-view";

let api: ReturnType<typeof stubApi>;

// the project designed: the design run, then the room confirmed (the stub's state-done.json)
beforeEach(async () => {
  api = stubApi();
  const url = `http://localhost/threads/${api.thread.thread_id}/runs/stream`;
  for (const body of [{ input: {} }, { command: {} }]) await (await api.fetch(url, { method: "POST", body: JSON.stringify(body) })).text();
  vi.stubGlobal("fetch", vi.fn(api.fetch));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const done = () => structuredClone(api.states[2].values);
const row = (nodeId: string) => document.querySelector(`li[data-id="${nodeId}"]`) as HTMLElement;
const planItem = (nodeId: string) => document.querySelector(`svg [data-id="${nodeId}"]`) as Element;

test("the fixture result renders: plan, shopping list with the total against the budget, rationale and the Critic's summary", async () => {
  const values = done();
  render(<ResultsView threadId={api.thread.thread_id} />);
  const list = await screen.findByRole("region", { name: "Shopping list" });
  for (const { item } of values.scene?.items ?? []) expect(within(list).getByText(item?.name as string)).toBeTruthy();
  expect(within(list).getByText("140 × 200 × 90 cm")).toBeTruthy(); // the bed
  expect(within(list).getByText("€449")).toBeTruthy();
  const total = (values.scene?.items ?? []).reduce((sum, i) => sum + (i.item?.price ?? 0), 0);
  expect(list.textContent).toContain(`Total€${total} of €1,200 budget`);
  expect(screen.getByRole("img", { name: /Floor plan/ })).toBeTruthy();
  expect(screen.getByText(values.design_brief?.summary as string)).toBeTruthy(); // no rationale in the design run's state
  expect(within(screen.getByRole("region", { name: "Critic review" })).getByText("round 2")).toBeTruthy();
});

test("selecting an item highlights it in the plan and the list, from either", async () => {
  render(<ResultsView threadId={api.thread.thread_id} />);
  await screen.findByRole("region", { name: "Shopping list" });
  expect(document.querySelectorAll('[aria-pressed="true"]')).toHaveLength(0);

  fireEvent.click(within(row("desk")).getByRole("button", { name: /desk/i }));
  expect(planItem("desk").getAttribute("aria-pressed")).toBe("true");
  expect(row("desk").className).toContain("border-primary");
  expect(within(row("desk")).getByRole("button", { pressed: true })).toBeTruthy();

  fireEvent.click(planItem("bed"));
  expect(planItem("bed").getAttribute("aria-pressed")).toBe("true");
  expect(planItem("desk").getAttribute("aria-pressed")).toBe("false");
  expect(row("bed").className).toContain("border-primary");
  expect(row("desk").className).not.toContain("border-primary");

  fireEvent.click(planItem("bed")); // again: deselected
  expect(document.querySelectorAll('[aria-pressed="true"]')).toHaveLength(0);
});

test("the selected item shows the Sourcer's other candidates; the Critic's rules show passed and failed; over budget is flagged", () => {
  const values = done();
  const bed = values.candidates?.bed[0];
  if (!bed || !values.brief) throw new Error("fixture changed");
  values.candidates = {
    ...values.candidates,
    bed: [
      bed,
      { ...bed, id: "pine-bed", name: "Pine bed", price: 299, url: "https://shop.example/pine-bed" },
      { ...bed, id: "evil-bed", name: "Evil bed", url: "javascript:alert(1)" },
    ],
  };
  values.critique = {
    round: 2,
    actions: [],
    summary: "One rule fails",
    rules: [
      { rule: "desk_near_light", passed: true, message: "" },
      { rule: "bed_not_facing_door", passed: false, message: "The bed faces the door" },
    ],
  };
  values.rationale = "The bed sits against wall B";
  values.brief.budget = 500;
  render(<Results values={values} />);

  fireEvent.click(within(row("bed")).getByRole("button", { name: /bed/i }));
  const alternatives = screen.getByRole("list", { name: "Alternatives for the bed" });
  expect(within(alternatives).getAllByRole("listitem")).toHaveLength(2);
  expect(within(alternatives).getByText("Pine bed")).toBeTruthy();
  expect(within(alternatives).getByRole("link").getAttribute("href")).toBe("https://shop.example/pine-bed"); // not the javascript: one
  fireEvent.click(within(row("desk")).getByRole("button", { name: /desk/i }));
  expect(within(row("desk")).getByText("No other candidates.")).toBeTruthy();

  const critic = screen.getByRole("region", { name: "Critic review" });
  expect(within(critic).getByLabelText("passed").parentElement?.textContent).toBe("desk near light");
  expect(within(critic).getByLabelText("failed").parentElement?.textContent).toBe("bed not facing door — The bed faces the door");
  expect(screen.getByText("The bed sits against wall B")).toBeTruthy();
  expect(screen.getByText(/of €500 budget/).parentElement?.className).toContain("text-destructive");
});

test("/projects/[id]/design shows the results of the project's thread", async () => {
  const html = renderToStaticMarkup(await DesignPage({ params: Promise.resolve({ id: "p1" }), searchParams: Promise.resolve({}) }));
  expect(html).toContain("<h1");
  expect(html).toContain('aria-label="Loading the design"');
});
