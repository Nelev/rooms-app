import { defineConfig, devices } from "@playwright/test";

// Against the running stack (`make e2e` starts it): BASE_URL is the frontend. E2E_RECORD=1 while recording (`make e2e-record`):
// the real models take minutes per step. A failed test is not retried: a flaky one should show, and a retry would pay again.
const recording = !!process.env.E2E_RECORD;

export default defineConfig({
  testDir: "tests",
  timeout: (recording ? 30 : 5) * 60_000,
  expect: { timeout: (recording ? 10 : 1) * 60_000 },
  workers: 1, // one recording at a time
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: process.env.BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    launchOptions: { args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] }, // WebGL in software, as eval/scripts/capture.ts
  },
});
