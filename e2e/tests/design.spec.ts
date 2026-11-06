import { join } from "node:path";
import { expect, type Page, test } from "@playwright/test";

// The whole flow on the docker compose stack, the real graph answered from the recorded model calls (e2e/compose.yml). Every test
// sends the same photo, dimensions, brief and chat message: the model calls they make are the recorded ones.

const PHOTO = join(import.meta.dirname, "../../fixtures/small-bedroom/photo-1.jpg"); // 640 x 480
const ROOM = { width: "3.2", length: "3.4", height: "2.6" };
// Where the photo would show the room's corners from a known camera (backend/tests/test_camera.py's third camera, at 640 x 480,
// in this room): what a person clicks to match the camera. The placeholder photo does not show them; the composite needs a match.
const CORNERS = [
  { corner: "Floor B", x: 578, y: 389 },
  { corner: "Ceiling B", x: 609, y: 80 },
  { corner: "Floor C", x: 314, y: 299 },
  { corner: "Ceiling C", x: 314, y: 157 },
  { corner: "Floor D", x: 69, y: 378 },
  { corner: "Ceiling D", x: 41, y: 89 },
];

const workspace = (page: Page) => page.getByRole("heading", { name: /^Project / });

// The wizard: a project with the fixture photo, the room's dimensions and a brief; it goes to the project's workspace once its run starts.
async function createProject(page: Page) {
  await page.goto("/");
  await page.getByRole("link", { name: "New project" }).click();
  await page.getByLabel("Drop photos here or choose files").setInputFiles(PHOTO);
  await expect(page.getByRole("img", { name: "photo-1.jpg" })).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByLabel("Width (m)").fill(ROOM.width);
  await page.getByLabel("Length (m)").fill(ROOM.length);
  await page.getByLabel("Ceiling height (m)").fill(ROOM.height);
  await page.getByRole("button", { name: "Next" }).click();
  // the chips' labels cover their (visually hidden) inputs
  await page.getByText("bedroom", { exact: true }).click();
  await expect(page.getByRole("radio", { name: "bedroom", exact: true })).toBeChecked();
  await page.getByText("scandinavian", { exact: true }).click();
  await page.getByLabel("Must-have items").fill("double bed, desk");
  await page.getByRole("button", { name: "Design my room" }).click();
  await expect(workspace(page)).toBeVisible();
}

// The room as analyzed, confirmed in the editor; the design run then goes on.
async function confirmRoom(page: Page) {
  await page.getByRole("link", { name: "Confirm the room" }).click();
  await expect(page.getByRole("heading", { name: "Confirm the room" })).toBeVisible();
  await page.getByRole("button", { name: "Confirm room" }).click();
  await expect(page.getByText("Room confirmed")).toBeVisible();
  await page.getByRole("link", { name: "Back to the project" }).click();
  await expect(workspace(page)).toBeVisible();
}

const shoppingList = (page: Page) => page.getByRole("region", { name: "Shopping list" });

test("create a project, confirm the room, then see, edit, view in 3D and in the photo its design", async ({ page }) => {
  await createProject(page);
  await confirmRoom(page);

  // results: the Design tab once the run has finished
  await page.getByRole("tab", { name: "Design" }).click();
  await expect(shoppingList(page).getByRole("listitem").first()).toBeVisible();
  await expect(page.getByRole("region", { name: "Why this design" })).toBeVisible();

  // a chat edit: applied, the items it changed highlighted, then undone
  const chat = page.getByRole("complementary", { name: "Chat" });
  await chat.getByRole("group", { name: "Items" }).getByRole("button").first().click();
  const message = chat.getByRole("textbox", { name: "Message" });
  await message.fill(`${await message.inputValue()}swap it for a smaller one`);
  await chat.getByRole("button", { name: "Send" }).click();
  await expect(chat.getByText(/^Changed: /)).toBeVisible();
  await expect(shoppingList(page).locator("li[data-highlighted]").first()).toBeVisible();
  await chat.getByRole("button", { name: "Undo" }).click();
  await expect(chat.getByText(/^Changed: /)).toBeHidden();

  // the 3D view
  await page.getByRole("tab", { name: "3D" }).click();
  await expect(page.getByRole("tabpanel").locator("canvas")).toBeVisible();

  // the design in the photo: the camera matched from the corners clicked on it, then the composite
  await page.getByRole("tab", { name: "Photo" }).click();
  await page.getByRole("link", { name: "See it in your photo" }).click();
  const overlay = page.getByRole("img", { name: /^Photo overlay/ });
  await expect(overlay).toBeVisible();
  const box = await overlay.boundingBox();
  if (!box) throw new Error("the photo overlay has no size");
  for (const { corner, x, y } of CORNERS) {
    await page.getByRole("button", { name: corner, exact: true }).click();
    await overlay.click({ position: { x: (x / 640) * box.width, y: (y / 480) * box.height } });
  }
  await page.getByRole("button", { name: "Match camera" }).click();
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByLabel("The new furniture in your photo").locator("canvas")).toBeVisible();
  // the photo under it, read with CORS (the export draws it into a canvas): from the API's redirect to a signed object storage URL
  const photo = page.getByRole("img", { name: "Your room" });
  await expect.poll(() => photo.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBe(640);
});

// The page is reloaded while a step of the run runs (each replayed model reply takes LLM_REPLAY_DELAY, e2e/compose.yml): in the design
// run (analyzing the room), then in the run resumed with the room. The page must rejoin the run and follow it to its end.
test("a reload while the design runs rejoins the run, which finishes", async ({ page }) => {
  const progress = page.getByRole("region", { name: "Run progress" }); // the Room tab's
  const running = progress.getByText("running", { exact: true });
  await createProject(page);
  await expect(running).toBeVisible();
  await page.reload();
  await confirmRoom(page);
  await expect(running).toBeVisible();
  await page.reload();
  await expect(progress.getByText("Present", { exact: true })).toBeVisible();
  await expect(progress.getByText(/^(failed|stopped|running)$/)).toHaveCount(0);
  await page.getByRole("tab", { name: "Design" }).click();
  await expect(shoppingList(page).getByRole("listitem").first()).toBeVisible();
});
