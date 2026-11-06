// Records the demo video (docs/demo/demo.webm) and the screenshots (docs/img/*.png): the whole user flow, wizard -> confirm room ->
// design -> 3D -> photo -> chat edit, driven with Playwright against a running app.
//
//   BASE_URL=http://localhost:3000 pnpm --dir frontend exec node ../docs/demo/record.ts   (Node >= 22.18: built-in type stripping)
//
// Run it against `make dev-stub` (fixture replay and the fake model: no model calls, free). The stub replays fixtures/small-bedroom,
// so the wizard enters that room. Needs Playwright's Chromium: `pnpm --dir frontend exec playwright install chromium`.
import { mkdirSync, readFileSync, renameSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";

const ROOT = join(import.meta.dirname, "../..");
const FRONTEND = join(ROOT, "frontend");
const VIDEO = join(ROOT, "docs/demo");
const IMG = join(ROOT, "docs/img");
const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";
const SIZE = { width: 1280, height: 800 };

// Playwright is a dev dependency of the frontend, outside this folder's module resolution
const { chromium } = createRequire(join(FRONTEND, "package.json"))("playwright") as typeof import("playwright");
type Locator = import("playwright").Locator;

// The fixture photos show fewer than the 4 corners camera matching needs (fixtures/README.md). This placeholder is fixtures/
// small-bedroom/photo-1.jpg's room seen by the same camera (camera_pose.json) on a sensor twice as wide, so 3 corners are in it:
// its edges are fixtures/placeholder_photos.py's, moved by (320, 240) on a 1280 x 960 canvas (saved at 800 x 600), and CORNERS are
// where it shows the room's corners, on that canvas. Regenerate these numbers if fixtures/small-bedroom/camera_pose.json changes.
const EDGES = [
  [831.6, 579.1, 306.1, 387],
  [831.6, -8.7, 306.1, 132.2],
  [831.6, 579.1, 831.6, -8.7],
  [306.1, 387, -184.8, 555],
  [306.1, 132.2, -184.8, 9],
  [306.1, 387, 306.1, 132.2],
  [-184.8, 555, -184.8, 9],
  [831.6, 579.1, 4262.7, 12710.8],
  [831.6, -8.7, 4262.7, -8905.2],
  [-184.8, 555, -3623.2, 12710.8],
  [-184.8, 9, -3623.2, -8905.2],
].map((e) => e.map((v, i) => v + (i % 2 ? 240 : 320)));
const CORNERS: [string, number, number][] = [
  ["Floor B", 1151.6, 819.1],
  ["Floor C", 626.1, 627],
  ["Floor D", 135.2, 795],
  ["Ceiling B", 1151.6, 231.3],
  ["Ceiling C", 626.1, 372.2],
  ["Ceiling D", 135.2, 249],
];
const PHOTO_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600" viewBox="0 0 1280 960" style="display:block;background:#e9e4dc">
  <polygon points="${[EDGES[7].slice(2), EDGES[0], EDGES[3], EDGES[9].slice(2)].flat().join(" ")}" fill="#c8b49a"/>
  ${EDGES.map(([x1, y1, x2, y2]) => `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#555" stroke-width="4"/>`).join("")}
  <rect x="340" y="60" width="600" height="90" fill="#fff" stroke="#c00" stroke-width="4"/>
  <text x="640" y="100" font-family="sans-serif" font-size="30" fill="#c00" text-anchor="middle">PLACEHOLDER - small bedroom</text>
  <text x="640" y="134" font-family="sans-serif" font-size="20" fill="#333" text-anchor="middle">synthetic image, replace with a real photo</text>
</svg>`;

// A caption at the bottom of the page, for a silent video
const CAPTION = `
  window.caption = (text) => {
    let el = document.getElementById("demo-caption");
    if (!el) {
      el = Object.assign(document.createElement("div"), { id: "demo-caption" });
      el.style.cssText = "position:fixed;left:50%;bottom:24px;transform:translateX(-50%);z-index:99999;max-width:80%;padding:10px 18px;" +
        "border-radius:10px;background:rgba(17,17,17,.85);color:#fff;font:500 18px/1.4 system-ui,sans-serif;text-align:center;pointer-events:none";
      document.body.append(el);
    }
    el.textContent = text;
  };`;

mkdirSync(IMG, { recursive: true });
const browser = await chromium.launch({ args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] }); // software WebGL
const context = await browser.newContext({ viewport: SIZE, colorScheme: "light", recordVideo: { dir: join(VIDEO, "raw"), size: SIZE } });
// the Next.js dev tools badge is not part of the app
await context.addInitScript(`addEventListener("DOMContentLoaded", () => {
  document.head.append(Object.assign(document.createElement("style"), { textContent: "nextjs-portal{display:none!important}" }));
  ${CAPTION}
});`);
const page = await context.newPage();

const pause = (s: number) => page.waitForTimeout(s * 1000);
const say = async (text: string, seconds = 2.5) => {
  await page.evaluate((t) => (window as unknown as { caption: (t: string) => void }).caption(t), text);
  await pause(seconds);
};
// a screenshot of the page scrolled to the top, or of one element, without the caption
const shot = async (name: string, target: "page" | "full" | Locator = "page") => {
  const selector = typeof target === "string" ? "#demo-caption" : "#demo-caption, header"; // the sticky header covers a scrolled element
  const hide = (v: string) =>
    page.evaluate(
      ([selector, v]) => {
        for (const el of document.querySelectorAll<HTMLElement>(selector)) el.style.visibility = v;
      },
      [selector, v],
    );
  await hide("hidden");
  const path = join(IMG, `${name}.png`);
  if (typeof target === "string") {
    await page.evaluate(() => scrollTo(0, 0));
    await page.screenshot({ path, fullPage: target === "full" });
  } else await target.screenshot({ path });
  await hide("");
};

// the photo, drawn by the browser
const photoPage = await browser.newPage({ viewport: { width: 800, height: 600 } });
await photoPage.setContent(PHOTO_SVG);
const photo = await photoPage.screenshot({ type: "jpeg", quality: 80 });
await photoPage.close();

let recorded = false; // keep the committed demo.webm if the flow fails partway
try {
  await page.goto(BASE_URL);
  await say("rooms-app: photos of a room in, a furnished design out", 3);
  await page.getByRole("link", { name: "New project" }).click();

  // the wizard
  await page.waitForURL(/projects\/new/);
  await say("1. Photos of the room (placeholders here: the stub replays a fixture room)");
  await page.locator("input[type=file][multiple]").setInputFiles([
    { name: "bedroom-corner.jpg", mimeType: "image/jpeg", buffer: photo },
    { name: "bedroom-door.jpg", mimeType: "image/jpeg", buffer: readFileSync(join(ROOT, "fixtures/small-bedroom/photo-2.jpg")) },
  ]);
  await pause(1.5);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await say("2. Its dimensions, wall to wall", 1);
  await page.getByLabel("Width (m)").pressSequentially("3.2", { delay: 80 });
  await page.getByLabel("Length (m)").pressSequentially("3.4", { delay: 80 });
  await page.getByLabel("Ceiling height (m)").pressSequentially("2.6", { delay: 80 });
  await pause(1);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await say("3. The brief: use, style, budget, must-haves", 1);
  await page.getByText("bedroom", { exact: true }).click();
  await page.getByText("scandinavian", { exact: true }).click();
  await page.getByText("japandi", { exact: true }).click();
  await page.getByLabel("Must-have items").pressSequentially("double bed, desk", { delay: 50 });
  await pause(1);
  await shot("wizard-brief");
  await page.getByRole("button", { name: "Design my room" }).click();

  // the Room Analyst reads the photos, then the run waits for the user
  await page.waitForURL(/projects\/(?!new)[^/]+$/);
  await say("The Room Analyst reads walls, doors and windows from the photos");
  await page.getByRole("link", { name: "Confirm the room" }).waitFor({ timeout: 60_000 });
  await pause(1);
  await page.getByRole("link", { name: "Confirm the room" }).click();
  await page.getByRole("heading", { name: "Confirm the room" }).waitFor();
  await say("Human in the loop: check and correct the room before the design starts", 3);
  await shot("room-confirm");
  // the fixture's kept wardrobe stands right in front of the photo's camera, where it would hide the new furniture in the photo
  await say("Fix what the analyst got wrong: there is no wardrobe in this room", 1.5);
  await page.getByRole("button", { name: "Delete kept_1" }).scrollIntoViewIfNeeded();
  await pause(1);
  await page.getByRole("button", { name: "Delete kept_1" }).click();
  await pause(1.5);
  await page.getByRole("button", { name: "Confirm room", exact: true }).click();
  await page.getByRole("link", { name: "Back to the project" }).click();

  // the design run: Designer, Architect, Refiner, Sourcer, solver and Critic
  await say("Designer -> Architect -> Refiner -> Sourcer -> solver -> Critic, live", 2);
  await page.getByText("Present", { exact: true }).waitFor({ timeout: 120_000 });
  await page.getByRole("tab", { name: "Design" }).waitFor({ timeout: 120_000 });
  await pause(1);
  await shot("run-timeline");
  await page.getByRole("tab", { name: "Design" }).click();
  await say("The design: why, the floor plan, the Critic's review and the shopping list", 3);
  await shot("design", "full");
  await page.mouse.wheel(0, 700);
  await pause(2);
  await page.mouse.wheel(0, -700);

  // 3D
  await page.getByRole("tab", { name: "3D" }).click();
  await say("The room in 3D (box models: most catalog items have no 3D model yet)", 2);
  const canvas = page.locator("canvas").first();
  const box = await canvas.boundingBox();
  if (box) {
    const [x, y] = [box.x + box.width / 2, box.y + box.height / 2];
    await page.mouse.move(x, y);
    await page.mouse.down();
    await page.mouse.move(x - 200, y + 20, { steps: 40 });
    await page.mouse.up();
  }
  await pause(1);
  await shot("3d-orbit");
  await page.getByRole("button", { name: "Eye level" }).click();
  await say("Eye level", 2);

  // the photo: match its camera, then see the design in it
  await page.getByRole("tab", { name: "Photo" }).click();
  await page.getByRole("link", { name: "See it in your photo" }).click();
  await page.getByRole("heading", { name: "In your photo" }).waitFor();
  await say("Match the photo's camera: click the room's corners on it", 2);
  const overlay = page.getByRole("img", { name: /Photo overlay/ });
  for (const [corner, x, y] of CORNERS) {
    await page.getByRole("button", { name: corner, exact: true }).click();
    const o = await overlay.boundingBox();
    if (o) await page.mouse.click(o.x + (x / 1280) * o.width, o.y + (y / 960) * o.height);
    await pause(0.5);
  }
  await page.getByRole("button", { name: "Match camera" }).click();
  await page.getByRole("button", { name: "Confirm", exact: true }).waitFor();
  await say("The room's edges from the matched camera", 2.5);
  await shot("camera-match");
  await page.getByRole("button", { name: "Confirm", exact: true }).click();
  await page.getByRole("slider").waitFor();
  await pause(3);
  await shot("photo-composite", page.getByRole("img", { name: "Your room" }).locator(".."));
  await page.getByRole("slider").scrollIntoViewIfNeeded();
  await say("The design drawn into the photo: wipe between before and after", 1);
  await page.getByRole("slider").focus();
  for (const key of ["ArrowLeft", "ArrowRight"])
    for (let i = 0; i < 40; i++) {
      await page.keyboard.press(key);
      await pause(0.04);
    }
  await pause(1.5);

  // chat edit
  await page.goBack();
  await page.getByRole("tab", { name: "Design" }).click();
  await say("Chat to edit the design: the edit is re-validated by the solver", 2);
  await page.getByRole("textbox", { name: "Message" }).pressSequentially("Swap the desk chair for a cheaper one", { delay: 40 });
  await page.getByRole("button", { name: "Send" }).click();
  await page.getByRole("button", { name: "Undo" }).waitFor({ timeout: 60_000 });
  await pause(2);
  await shot("chat-edit");
  await say("Changed: the desk chair, €70 cheaper; one click undoes it", 3);
  recorded = true;
} finally {
  const video = page.video();
  await context.close();
  await browser.close();
  if (video && recorded) renameSync(await video.path(), join(VIDEO, "demo.webm"));
  rmSync(join(VIDEO, "raw"), { recursive: true, force: true });
}
