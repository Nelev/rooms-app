import { EventSourceParserStream } from "eventsource-parser/stream";
import type { components, paths } from "@/lib/api/generated/schema";

// `make dev-stub` serves the stub graph here: in development the hooks run against real endpoints, with fixture data
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const TIMEOUT_MS = 15_000;

type Schemas = components["schemas"];
export type Thread = Schemas["Thread"];
export type ThreadState = Schemas["ThreadState"];
export type Interrupt = Schemas["Interrupt"];
export type RunCreate = Schemas["RunCreate"];
export type StreamEvent = Schemas["CustomPart"]["data"];
export type StreamPart = Schemas["MetadataPart"] | Schemas["UpdatesPart"] | Schemas["CustomPart"] | Schemas["MessagesPart"] | Schemas["ErrorPart"];

// The API's paths, with `{thread_id}` and the like in them: `path("/threads/{thread_id}/state", { thread_id })` fills them in.
export type Path = keyof paths;
// what a GET of the path answers
export type Answer<P extends Path> = paths[P] extends { get: { responses: { 200: { content: { "application/json": infer T } } } } } ? T : never;

export function path(template: Path, params: Record<string, string> = {}): string {
  return template.replace(/\{(\w+)\}/g, (_, name: string) => encodeURIComponent(params[name]));
}

// Where a photo is read, by its key (an upload's or a fixture's): the API serves it or redirects to a signed URL of it. An <img> sends no
// Authorization header: once there is sign-in (A-01), this route needs another way to know the person (a cookie or a token in the query).
export function photoUrl(key: string): string {
  return API_URL + path("/uploads/{key}", { key });
}

// The access token of the signed-in person, once there is sign-in (A-01): until then requests go without one.
export const session = {
  accessToken: async (): Promise<string | undefined> => undefined,
  forgetAccessToken: () => {},
};

// auth: the API refused the session even with a new token; network: no answer; server: an answer that is an error
export type ErrorKind = "auth" | "network" | "server";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly kind: ErrorKind,
    readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// ms; the default is short, for what a page loads. null: none, for a run's stream, which ends with the run.
type Options = RequestInit & { timeout?: number | null };

// Every request carries the access token, and gives up after `timeout` (or when the caller aborts its `signal`). A token that could not
// be fetched counts as the network: the cause is not known, so the caller keeps trying.
async function send(url: string, { timeout = TIMEOUT_MS, signal, ...init }: Options): Promise<Response> {
  const token = await session.accessToken().catch(() => {
    throw new ApiError("the session could not be refreshed, reload the page to sign in again", "network");
  });
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const signals = [signal, timeout === null ? null : AbortSignal.timeout(timeout)].filter((s): s is AbortSignal => !!s);
  return fetch(`${API_URL}${url}`, { ...init, headers, signal: AbortSignal.any(signals) }).catch((error) => {
    throw new ApiError(error?.name === "TimeoutError" ? "the server did not answer in time" : "the server cannot be reached", "network");
  });
}

// A 401 means the token went stale: it is asked for again, once. An error says what the server said (its `detail`), or at least its status.
export async function request(url: string, options: Options = {}): Promise<Response> {
  let response = await send(url, options);
  if (response.status === 401) {
    session.forgetAccessToken();
    response = await send(url, options);
  }
  if (!response.ok) {
    const detail = await response.json().then(
      (body) => body.detail,
      () => undefined,
    );
    const message = typeof detail === "string" ? detail : `the server answered ${response.status}`;
    throw new ApiError(message, response.status === 401 ? "auth" : "server", response.status);
  }
  return response;
}

// The body of an answer as JSON. A 200 that is not JSON (a gateway's page, say) is an error of the server, not a parser's message.
export async function json<T>(response: Response): Promise<T> {
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError("the server sent an answer that could not be read", "server");
  }
}

// The parts of a run's stream (Server-Sent Events, the data JSON) as they arrive. A connection that drops counts as the network.
export async function* streamParts(response: Response): AsyncGenerator<StreamPart> {
  if (!response.body) throw new ApiError("the server sent an answer that could not be read", "server");
  const reader = response.body.pipeThrough(new TextDecoderStream()).pipeThrough(new EventSourceParserStream()).getReader();
  while (true) {
    const { done, value } = await reader.read().catch((error) => {
      if (error?.name === "AbortError") throw error;
      throw new ApiError("the connection to the server was lost", "network");
    });
    if (done) return;
    yield { event: value.event, data: JSON.parse(value.data) } as StreamPart;
  }
}
