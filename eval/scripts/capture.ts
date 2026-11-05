// The two corner renders of each run for the VLM judge (E-04), after I-Design's protocol: the design seen from two opposite
// corners of the room. Writes eval/results/renders/<run>/cornerA.png and cornerC.png (the /render/[runId] route, F-14).
//
//   pnpm --dir frontend exec node ../eval/scripts/capture.ts [runId ...]   (Node >= 22.18: built-in type stripping)
//
// A run id is a thread id, whose scene the frontend fetches from the API, or a fixture case (fixtures/<case>/scene.json, the
// default: all of them), whose scene this script serves in place of the API. Without BASE_URL (a running frontend) it starts
// `next dev` on a free port. Needs Playwright's Chromium: `pnpm --dir frontend exec playwright install chromium`.
import { type ChildProcess, spawn } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { createServer } from "node:net";
import { join } from "node:path";

const ROOT = join(import.meta.dirname, "../..");
const FRONTEND = join(ROOT, "frontend");
const FIXTURES = join(ROOT, "fixtures");
const OUT = join(ROOT, "eval/results/renders");
const CORNERS = ["cornerA", "cornerC"];

// Playwright is a dev dependency of the frontend, outside this folder's module resolution
const { chromium } = createRequire(join(FRONTEND, "package.json"))("playwright") as typeof import("playwright");

const fixtureScene = (id: string) => join(FIXTURES, id, "scene.json");
const runs = process.argv.slice(2);
if (runs.length === 0) runs.push(...readdirSync(FIXTURES).filter((id) => existsSync(fixtureScene(id))));

async function freePort(): Promise<number> {
  const server = createServer().listen(0);
  await new Promise((resolve) => server.once("listening", resolve));
  const { port } = server.address() as { port: number };
  await new Promise((resolve) => server.close(resolve));
  return port;
}

async function startFrontend(): Promise<{ url: string; dev?: ChildProcess }> {
  if (process.env.BASE_URL) return { url: process.env.BASE_URL };
  const port = await freePort();
  const dev = spawn(join(FRONTEND, "node_modules/.bin/next"), ["dev", "--port", String(port)], { cwd: FRONTEND, stdio: "inherit" });
  const url = `http://localhost:${port}`;
  for (let i = 0; i < 120; i++) {
    const up = await fetch(url)
      .then((r) => r.status < 500)
      .catch(() => false);
    if (up) return { url, dev };
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  dev.kill();
  throw new Error(`next dev did not start on ${url}`);
}

const { url, dev } = await startFrontend();
// headless Chromium draws WebGL in software
const browser = await chromium.launch({ args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
try {
  const page = await browser.newPage({ viewport: { width: 1024, height: 768 }, colorScheme: "light" });
  await page.route("**/threads/*/state", (route) => {
    const id = decodeURIComponent(new URL(route.request().url()).pathname.split("/").at(-2) ?? "");
    if (!runs.includes(id) || !existsSync(fixtureScene(id))) return route.continue();
    const values = { scene: JSON.parse(readFileSync(fixtureScene(id), "utf8")) };
    return route.fulfill({ json: { values, next: [], interrupts: [], status: "done" }, headers: { "Access-Control-Allow-Origin": "*" } });
  });
  for (const run of runs) {
    for (const corner of CORNERS) {
      await page.goto(`${url}/render/${encodeURIComponent(run)}?view=${corner}`, { waitUntil: "networkidle" });
      const shown = page.locator("canvas, [role=alert]").first();
      await shown.waitFor();
      if ((await shown.getAttribute("role")) === "alert") throw new Error(`${run}: ${await shown.textContent()}`);
      await page.waitForLoadState("networkidle"); // models still loading
      await page.addStyleTag({ content: "nextjs-portal { display: none !important; }" }); // next dev's indicator
      await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      mkdirSync(join(OUT, run), { recursive: true });
      const file = join(OUT, run, `${corner}.png`);
      await page.screenshot({ path: file });
      console.log(file);
    }
  }
} finally {
  await browser.close();
  dev?.kill();
}
