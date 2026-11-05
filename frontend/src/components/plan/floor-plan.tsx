import type { KeyboardEvent } from "react";
import { cn } from "@/lib/utils";
import { type Feature, featureRect, type Layout, onWall, type Point, type RoomSpec, type ValidationReport, type Wall, wallFrame } from "./coords";

export const SCALE = 100; // viewBox units per meter
const PAD = 0.4; // meters around the room for the wall letters, more if a door opens out
// as backend/app/geometry/room.py: assumed depths and the strip in front of a window or radiator that must stay clear
const RADIATOR_DEPTH = 0.1;
const FIXTURE_DEPTH = 0.3;
const FRONT_ZONE = 0.3;

const WARNING = "fill-amber-500/30 stroke-amber-600";
const CLEARANCE = "fill-sky-500/10 stroke-sky-500 [stroke-dasharray:4_3]";

type Props = {
  room: RoomSpec;
  layout?: Layout;
  report?: ValidationReport;
  selectedId?: string;
  onSelect?: (id: string) => void;
  highlighted?: string[]; // items a chat edit just changed (F-13)
  className?: string;
};

// The room seen from above, read-only: walls, openings and door swings, clearance zones, kept furniture and the layout's items,
// with whatever the report names (items or features) in a warning color.
export function FloorPlan({ room, layout, report, selectedId, onSelect, highlighted = [], className }: Props) {
  const dims = room.dimensions;
  const pad = Math.max(PAD, ...room.features.map((f) => (f.type === "door" && f.swing === "out" ? f.width + 0.1 : 0)));
  const px = (m: number) => Math.round(m * SCALE * 10) / 10;
  const svg = ([x, y]: Point): Point => [px(pad + x), px(pad + dims.length - y)]; // SVG's y points down
  const points = (ps: Point[]) => ps.map((p) => svg(p).join(",")).join(" ");
  const problems = new Map<string, string[]>();
  for (const issue of report?.issues ?? []) for (const id of issue.node_ids) problems.set(id, [...(problems.get(id) ?? []), issue.message]);
  const title = (id: string, name: string) => <title>{[name, ...(problems.get(id) ?? [])].join("\n")}</title>;

  const items = [
    ...room.kept_furniture.map((k) => ({ ...k, label: k.name, kept: true })),
    ...(layout?.placements ?? []).map((p) => ({ ...p, id: p.node_id, label: p.node_id.replaceAll("_", " "), kept: false })),
  ];

  return (
    <svg
      viewBox={`0 0 ${px(dims.width + 2 * pad)} ${px(dims.length + 2 * pad)}`}
      role="img"
      aria-label={`Floor plan, ${dims.width} by ${dims.length} m`}
      className={cn("h-auto w-full select-none", className)}
      fontSize={12}
      textAnchor="middle"
      dominantBaseline="central"
    >
      <rect {...rect(svg([0, dims.length]), px(dims.width), px(dims.length))} className="fill-muted stroke-foreground" strokeWidth={6} />
      {(["A", "B", "C", "D"] as Wall[]).map((w) => {
        const [x, y] = svg(onWall(dims, w, wallFrame(dims, w).length / 2, -PAD / 2));
        return (
          <text key={w} x={x} y={y} className="fill-muted-foreground">
            {w}
          </text>
        );
      })}
      {room.features.map((f) => (
        <g key={f.id} data-id={f.id}>
          {title(f.id, f.id)}
          {featureShape(f)}
        </g>
      ))}
      {items.map((item) => {
        const [x, y] = svg([item.x, item.y]);
        const [w, d] = [px(item.size.width), px(item.size.depth)];
        const select = onSelect && (() => onSelect(item.id));
        return (
          <g
            key={item.id}
            data-id={item.id}
            data-highlighted={highlighted.includes(item.id) || undefined}
            {...(select && {
              role: "button",
              tabIndex: 0,
              "aria-pressed": item.id === selectedId,
              onClick: select,
              onKeyDown: (e: KeyboardEvent) => {
                if (e.key !== "Enter" && e.key !== " ") return;
                e.preventDefault(); // Space would scroll the page
                select();
              },
            })}
            className={select && "group cursor-pointer outline-none"}
          >
            {title(item.id, item.label)}
            <g transform={`translate(${x} ${y}) rotate(${-(item.rotation ?? 0)})`}>
              <rect
                {...rect([-w / 2, -d / 2], w, d)}
                strokeWidth={item.id === selectedId ? 3 : 1.5}
                className={cn(
                  "fill-background stroke-foreground",
                  item.kept && "[stroke-dasharray:6_3]",
                  problems.has(item.id) && WARNING,
                  highlighted.includes(item.id) && "animate-pulse fill-primary/20 stroke-primary",
                  select && "group-focus-visible:stroke-primary",
                  item.id === selectedId && "stroke-primary",
                )}
              />
              {/* the front edge (+y in the item's frame is up the screen) */}
              <line x1={-w / 2} y1={-d / 2} x2={w / 2} y2={-d / 2} strokeWidth={4} className="stroke-current" />
            </g>
            <text x={x} y={y} className="fill-foreground">
              {item.label}
            </text>
          </g>
        );
      })}
    </svg>
  );

  function featureShape(f: Feature) {
    const warn = problems.has(f.id) && WARNING;
    const along = f.offset * wallFrame(dims, f.wall).length;
    const [a, b] = [svg(onWall(dims, f.wall, along - f.width / 2)), svg(onWall(dims, f.wall, along + f.width / 2))];
    const zone = (from: number, depth: number, className = CLEARANCE) => (
      <polygon points={points(featureRect(dims, f, from, depth))} strokeWidth={1} className={cn(className, warn)} />
    );
    const opening = <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} strokeWidth={8} className="stroke-background" />;
    switch (f.type) {
      case "door": {
        // seen from inside, a left hinge is at the end further along the wall's direction (as geometry/room.py)
        const left = f.hinge !== "right";
        const side = f.swing === "out" ? -1 : 1;
        const hinge = svg(onWall(dims, f.wall, along + (left ? 1 : -1) * (f.width / 2)));
        const tip = svg(onWall(dims, f.wall, along + (left ? 1 : -1) * (f.width / 2), side * f.width));
        const shut = left ? a : b;
        const r = px(f.width);
        const sweep = (shut[0] - hinge[0]) * (tip[1] - hinge[1]) - (shut[1] - hinge[1]) * (tip[0] - hinge[0]) > 0 ? 1 : 0;
        return (
          <>
            {opening}
            {f.swing === "out" && zone(0, f.width)}
            <path
              d={`M${hinge} L${shut} A${r} ${r} 0 0 ${sweep} ${tip} Z`}
              strokeWidth={1}
              className={cn(f.swing === "out" ? "fill-none stroke-muted-foreground" : CLEARANCE, warn)}
            />
            <line x1={hinge[0]} y1={hinge[1]} x2={tip[0]} y2={tip[1]} strokeWidth={2} className={cn("stroke-foreground", warn)} />
          </>
        );
      }
      case "window":
        return (
          <>
            {opening}
            <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} strokeWidth={3} className={cn("stroke-sky-500", warn)} />
            {zone(0, FRONT_ZONE)}
          </>
        );
      case "radiator":
        return (
          <>
            {zone(0, RADIATOR_DEPTH, "fill-muted-foreground stroke-foreground")}
            {zone(RADIATOR_DEPTH, FRONT_ZONE)}
          </>
        );
      case "column":
      case "built_in":
        return zone(0, FIXTURE_DEPTH, "fill-muted-foreground/50 stroke-foreground");
      default: {
        const [x, y] = svg(onWall(dims, f.wall, along, 0.05));
        return <circle cx={x} cy={y} r={4} strokeWidth={1} className={cn("fill-background stroke-foreground", warn)} />;
      }
    }
  }
}

function rect([x, y]: Point, width: number, height: number) {
  return { x, y, width, height };
}
