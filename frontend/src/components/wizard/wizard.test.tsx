// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Wizard } from "@/components/wizard/wizard";
import { stubApi } from "@/lib/mocks/stub-api";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const photo = (name: string, type = "image/jpeg") => new File(["jpeg"], name, { type });

// the stub API, with the two endpoints the wizard calls before the run
let api: ReturnType<typeof stubApi>;
let uploads: (file: File) => Response;
let runs: (() => Response) | undefined; // replaces the stub's run stream when set
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

beforeEach(() => {
  api = stubApi();
  uploads = (file) => json({ key: `uploads/${file.name}` });
  runs = undefined;
  push.mockReset();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const route = `${init?.method ?? "GET"} ${new URL(input).pathname}`;
      if (route === "POST /uploads") return uploads((init?.body as FormData | undefined)?.get("file") as File);
      if (route === "POST /threads") return json(api.thread);
      if (runs && route.endsWith("/runs/stream")) return runs();
      return api.fetch(input, init);
    }),
  );
  Object.assign(URL, { createObjectURL: (file: File) => `blob:${file.name}`, revokeObjectURL: () => {} });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const next = () => fireEvent.click(screen.getByRole("button", { name: "Next" }));
const fileInputs = () => document.querySelectorAll<HTMLInputElement>('input[type="file"]');
const dropZone = () => screen.getByText(/Drop photos here/).closest("label") as HTMLElement;
const meters = (label: RegExp, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const calls = (route: string) =>
  vi.mocked(fetch).mock.calls.filter(([url, init]) => `${init?.method ?? "GET"} ${new URL(String(url)).pathname}` === route);

async function fillUpToBrief() {
  fireEvent.drop(dropZone(), { dataTransfer: { files: [photo("photo-1.jpg")] } });
  next();
  meters(/^width/i, "3.2");
  meters(/^length/i, "3.4");
  meters(/^ceiling height/i, "2.6");
  next();
  await screen.findByText("What is the room for?");
}

describe("Wizard", () => {
  it("shows inline errors for invalid input, step by step", async () => {
    render(<Wizard />);
    next();
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Add 1 to 3 photos of the room");
    expect(fileInputs()[0].getAttribute("aria-invalid")).toBe("true");

    fireEvent.change(fileInputs()[0], { target: { files: [photo("a.jpg"), photo("b.jpg"), photo("c.jpg"), photo("d.jpg")] } });
    next();
    expect(screen.getByRole("alert").textContent).toBe("Add 1 to 3 photos of the room");
    expect(screen.getAllByRole("img")).toHaveLength(4);
    fireEvent.click(screen.getByRole("button", { name: "Remove d.jpg" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove c.jpg" }));
    fireEvent.change(fileInputs()[1], { target: { files: [photo("notes.pdf", "application/pdf")] } }); // the camera input
    next();
    expect(screen.getByRole("alert").textContent).toBe("Photos must be images");
    fireEvent.click(screen.getByRole("button", { name: "Remove notes.pdf" }));
    next();

    meters(/^width/i, "0.5");
    meters(/^length/i, "abc");
    meters(/^ceiling height/i, "2.5");
    next();
    expect(screen.getAllByRole("alert").map((a) => a.textContent)).toEqual(["Enter a number from 1 to 20 m", "Enter a number from 1 to 20 m"]);
    expect(screen.getByLabelText(/^width/i).getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByLabelText(/^ceiling height/i).getAttribute("aria-invalid")).toBeNull();
    meters(/^width/i, "3");
    meters(/^length/i, "4");
    meters(/^ceiling height/i, "6");
    next();
    expect(screen.getByRole("alert").textContent).toBe("Enter a number from 2 to 5 m");
    meters(/^ceiling height/i, "2.7");
    next();

    fireEvent.click(await screen.findByRole("button", { name: "Design my room" }));
    expect(screen.getByRole("alert").textContent).toBe("Choose what the room is for");
    expect(fetch).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByLabelText(/^ceiling height/i)).toHaveProperty("value", "2.7"); // the values are kept
  });

  it("uploads the photos, creates the project, starts the design run and opens the workspace", async () => {
    render(<Wizard />);
    await fillUpToBrief();
    fireEvent.click(screen.getByLabelText("bedroom"));
    fireEvent.click(screen.getByLabelText("scandinavian"));
    // hidden until the thumb is measured, which jsdom does not do
    fireEvent.keyDown(screen.getByRole("slider", { hidden: true }), { key: "ArrowRight" }); // one step: 1600
    expect(screen.getByText("€1,600")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Must-have items"), { target: { value: "double bed, desk ," } });
    fireEvent.change(screen.getByLabelText("Items to keep"), { target: { value: "wardrobe" } });
    fireEvent.click(screen.getByRole("button", { name: "Design my room" }));

    await waitFor(() => expect(push).toHaveBeenCalledWith(`/projects/${api.thread.thread_id}`), { timeout: 5000 });
    expect(calls("POST /uploads")).toHaveLength(1);
    expect(JSON.parse(String(calls("POST /threads")[0][1]?.body))).toEqual({ metadata: { title: "bedroom" } });
    expect(JSON.parse(String(calls(`POST /threads/${api.thread.thread_id}/runs/stream`)[0][1]?.body))).toEqual({
      input: {
        photo_keys: ["uploads/photo-1.jpg"],
        dimensions: { width: 3.2, length: 3.4, height: 2.6 },
        brief: {
          room_use: "bedroom",
          styles: ["scandinavian"],
          budget: 1600,
          must_haves: ["double bed", "desk"],
          keep: ["wardrobe"],
          remove: [],
          notes: "",
        },
      },
    });
  });

  it("says why the project could not be started, and can be submitted again", async () => {
    uploads = () => json({ detail: "Upload an image" }, 415);
    render(<Wizard />);
    await fillUpToBrief();
    fireEvent.click(screen.getByLabelText("bedroom"));
    fireEvent.click(screen.getByRole("button", { name: "Design my room" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Could not start the design: Upload an image");
    expect(calls("POST /threads")).toHaveLength(0);

    uploads = (file) => json({ key: `uploads/${file.name}` });
    fireEvent.click(screen.getByRole("button", { name: "Design my room" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith(`/projects/${api.thread.thread_id}`), { timeout: 5000 });
  });

  it("reuses the project when its run failed to start", async () => {
    runs = () => json({ detail: "Run failed" }, 500);
    render(<Wizard />);
    await fillUpToBrief();
    fireEvent.click(screen.getByLabelText("bedroom"));
    fireEvent.click(screen.getByRole("button", { name: "Design my room" }));
    expect((await screen.findByRole("alert", {}, { timeout: 5000 })).textContent).toMatch(/^Could not start the design/);

    runs = undefined;
    fireEvent.click(screen.getByRole("button", { name: "Design my room" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith(`/projects/${api.thread.thread_id}`), { timeout: 5000 });
    expect(calls("POST /threads")).toHaveLength(1);
  });
});
