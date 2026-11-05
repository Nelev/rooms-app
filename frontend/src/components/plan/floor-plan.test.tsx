// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import path from "node:path";
import { fireEvent, render } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, test, vi } from "vitest";
import type { ValidationReport } from "./coords";
import { FloorPlan } from "./floor-plan";

const fixture = (name: string) => JSON.parse(readFileSync(path.resolve(__dirname, "../../../../fixtures", name), "utf8"));
const CASES = ["small-bedroom", "home-office", "living-room"];

test.each(CASES)("%s renders its room and layout", (name) => {
  const html = renderToStaticMarkup(<FloorPlan room={fixture(`${name}/room_spec.json`)} layout={fixture(`${name}/layout.json`)} />);
  expect(html).toMatchSnapshot();
});

test.each(CASES)("%s renders the room alone", (name) => {
  expect(renderToStaticMarkup(<FloorPlan room={fixture(`${name}/room_spec.json`)} />)).toMatchSnapshot();
});

test("doors opening out, right hinges, columns, built-ins and outlets render", () => {
  const room = fixture("small-bedroom/room_spec.json");
  room.features = [
    { id: "door_out", type: "door", wall: "B", offset: 0.3, width: 0.8, height: 2.1, swing: "out", hinge: "right" },
    { id: "door_right", type: "door", wall: "C", offset: 0.7, width: 0.9, height: 2.1, hinge: "right" },
    { id: "column_1", type: "column", wall: "D", offset: 0.2, width: 0.4, height: 2.6 },
    { id: "built_in_1", type: "built_in", wall: "D", offset: 0.7, width: 0.8, height: 2.0 },
    { id: "outlet_1", type: "outlet", wall: "A", offset: 0.3, width: 0.1, height: 0.1, sill_height: 0.3 },
  ];
  expect(renderToStaticMarkup(<FloorPlan room={room} />)).toMatchSnapshot();
});

test("the report's violations are drawn in the warning color with their messages", () => {
  const report: ValidationReport = {
    issues: [
      { code: "blocks_opening", message: "desk blocks the door swing of door_1", severity: "error", node_ids: ["desk", "door_1"] },
      { code: "clearance", message: "nightstand cannot be reached through a 0.6 m walkway", severity: "warning", node_ids: ["nightstand"] },
    ],
  };
  const html = renderToStaticMarkup(
    <FloorPlan room={fixture("small-bedroom/room_spec.json")} layout={fixture("small-bedroom/layout.json")} report={report} selectedId="bed" />,
  );
  expect(html).toMatchSnapshot();
  const { container } = render(
    <FloorPlan room={fixture("small-bedroom/room_spec.json")} layout={fixture("small-bedroom/layout.json")} report={report} />,
  );
  for (const id of ["desk", "door_1", "nightstand"]) expect(container.querySelector(`[data-id="${id}"] .fill-amber-500\\/30`)).not.toBeNull();
  for (const id of ["bed", "window_1"]) expect(container.querySelector(`[data-id="${id}"] .fill-amber-500\\/30`)).toBeNull();
  expect(container.querySelector('[data-id="desk"] title')?.textContent).toBe("desk\ndesk blocks the door swing of door_1");
});

test("an item is drawn at its position and rotation, with y up", () => {
  const room = { dimensions: { width: 4, length: 3, height: 2.5 }, walls: [], features: [], kept_furniture: [], warnings: [] };
  const layout = { placements: [{ node_id: "bed", x: 1, y: 0.5, z: 0, rotation: 90, size: { width: 1.4, depth: 2, height: 0.9 } }] };
  const { container } = render(<FloorPlan room={room} layout={layout} />);
  expect(container.querySelector("svg")?.getAttribute("viewBox")).toBe("0 0 480 380");
  // (1, 0.5) m is 40 + 100 across and 40 + 300 - 50 down; a counterclockwise turn is a negative SVG angle, since SVG's y points down
  expect(container.querySelector('[data-id="bed"] g')?.getAttribute("transform")).toBe("translate(140 290) rotate(-90)");
});

test("items are selectable when onSelect is given", () => {
  const onSelect = vi.fn();
  const room = fixture("home-office/room_spec.json");
  const { container, getAllByRole } = render(
    <FloorPlan room={room} layout={fixture("home-office/layout.json")} selectedId="desk" onSelect={onSelect} />,
  );
  const desk = container.querySelector('[data-id="desk"]') as Element;
  expect(desk.getAttribute("aria-pressed")).toBe("true");
  fireEvent.click(desk);
  fireEvent.keyDown(container.querySelector(`[data-id="${room.kept_furniture[0].id}"]`) as Element, { key: "Enter" });
  expect(onSelect.mock.calls).toEqual([["desk"], [room.kept_furniture[0].id]]);
  expect(getAllByRole("button").length).toBeGreaterThan(1);
  expect(render(<FloorPlan room={room} />).container.querySelector('[role="button"]')).toBeNull();
});
