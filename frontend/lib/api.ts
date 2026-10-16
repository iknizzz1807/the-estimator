/**
 * Typed API client for the frozen contract in docs/API.md.
 *
 * - Real API is the default path (NEXT_PUBLIC_API_URL, default http://localhost:8000).
 * - NEXT_PUBLIC_USE_MOCK=1 forces bundled mock payloads (lib/mock.ts).
 * - When a request fails at the network level (backend not running) the client
 *   transparently falls back to mock data and flips a global flag so the UI can
 *   show the "backend offline — demo data" banner. HTTP errors (4xx/5xx) are
 *   NOT masked: they surface to the user as guided error states.
 *
 * SSE note: POST /api/estimate/stream cannot use EventSource, so we POST via
 * fetch and parse the text/event-stream body manually.
 */

import {
  mockAb,
  mockEstimate,
  mockEstimatePackages,
  mockEstimateStream,
  mockHealth,
  mockImport,
  mockLoadScenario,
  mockProjects,
  mockReplay,
  mockReset,
  mockScenarios,
  mockSubmitActual,
} from "./mock";
import type {
  ABResponse,
  ActualUpdateResponse,
  AnswersMap,
  EstimateResponse,
  Health,
  ImportResponse,
  PackagesResponse,
  ProjectRow,
  ReplayResponse,
  ResetResponse,
  Scenario,
  StreamEvent,
} from "./types";

const API_URL = (
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
).replace(/\/+$/, "");

const FORCED_MOCK =
  process.env.NEXT_PUBLIC_USE_MOCK === "1" ||
  process.env.NEXT_PUBLIC_USE_MOCK === "true";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

/* ------------------------------------------------------------------ */
/* Mock-state store (offline banner + health badge subscribe to it).   */
/* ------------------------------------------------------------------ */

export interface MockState {
  active: boolean;
  forced: boolean;
}

let mockState: MockState = { active: FORCED_MOCK, forced: FORCED_MOCK };
const mockListeners = new Set<(state: MockState) => void>();

export function getMockState(): MockState {
  return mockState;
}

export function subscribeMockState(
  listener: (state: MockState) => void
): () => void {
  mockListeners.add(listener);
  return () => mockListeners.delete(listener);
}

function setMockActive(active: boolean) {
  if (mockState.active === active) return;
  mockState = { ...mockState, active };
  mockListeners.forEach((listener) => listener(mockState));
}

/* ------------------------------------------------------------------ */
/* Core request helpers                                                */
/* ------------------------------------------------------------------ */

function jsonInit(body: unknown): RequestInit {
  return { method: "POST", body: JSON.stringify(body) };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isForm = init?.body instanceof FormData;
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body && !isForm ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers as Record<string, string> | undefined),
    },
  });
  if (!res.ok) {
    let detail = `Request failed (HTTP ${res.status})`;
    try {
      const body: unknown = await res.json();
      if (body && typeof body === "object" && "detail" in body) {
        const d = (body as { detail: unknown }).detail;
        if (typeof d === "string") detail = d;
        else if (Array.isArray(d)) {
          detail = d
            .map((item) =>
              item && typeof item === "object" && "msg" in item
                ? String((item as { msg: unknown }).msg)
                : JSON.stringify(item)
            )
            .join("; ");
        }
      }
    } catch {
      // keep the default message
    }
    throw new ApiError(res.status, detail);
  }
  const data = (await res.json()) as T;
  setMockActive(false);
  return data;
}

async function apiCall<T>(
  path: string,
  init?: RequestInit,
  mockFactory?: () => T | Promise<T>
): Promise<T> {
  if (FORCED_MOCK) {
    if (!mockFactory) throw new ApiError(0, "No mock available for this route");
    return mockFactory();
  }
  try {
    return await request<T>(path, init);
  } catch (err) {
    if (err instanceof ApiError) throw err; // HTTP error: real error state
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    if (mockFactory) {
      setMockActive(true);
      return mockFactory();
    }
    throw err;
  }
}

/* ------------------------------------------------------------------ */
/* SSE stream parsing (POST /api/estimate/stream)                      */
/* ------------------------------------------------------------------ */

function toStreamEvent(eventName: string, payload: unknown): StreamEvent {
  const obj =
    payload && typeof payload === "object"
      ? (payload as Record<string, unknown>)
      : undefined;
  const type = (eventName || String(obj?.type ?? "")).toLowerCase();

  // Final result: `event: result` (payload is the estimate) or a payload
  // carrying a `result` field.
  const candidate =
    obj && obj.result && typeof obj.result === "object"
      ? (obj.result as EstimateResponse)
      : obj && "estimate" in obj
        ? (payload as EstimateResponse)
        : undefined;
  if (type === "result" || candidate) {
    if (candidate && candidate.estimate) return { type: "result", result: candidate };
  }

  if (type === "error") {
    const message =
      String(obj?.detail ?? obj?.message ?? "") ||
      (typeof payload === "string" ? payload : "") ||
      "Estimation failed — please retry";
    return { type: "error", message };
  }

  // Step event: name comes from the JSON payload, the `event:` field, or raw data.
  const raw =
    obj?.step ??
    obj?.name ??
    obj?.status ??
    (eventName && eventName.toLowerCase() !== "step"
      ? eventName
      : typeof payload === "string"
        ? payload
        : "");
  const step = String(raw).trim().toLowerCase();
  if (!step && !type) return { type: "step", step: "extracting" };
  return { type: "step", step: step || type };
}

function parseSseBlock(block: string): StreamEvent | null {
  let eventName = "";
  const dataLines: string[] = [];
  for (const line of block.split(/\r?\n/)) {
    if (!line || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") eventName = value.trim();
    else if (field === "data") dataLines.push(value);
  }
  if (!eventName && dataLines.length === 0) return null;
  const raw = dataLines.join("\n").trim();
  let payload: unknown = undefined;
  if (raw) {
    try {
      payload = JSON.parse(raw);
    } catch {
      payload = raw;
    }
  }
  return toStreamEvent(eventName, payload);
}

async function readSseStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: StreamEvent) => void
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let index = buffer.indexOf("\n\n");
    while (index >= 0) {
      const block = buffer.slice(0, index);
      buffer = buffer.slice(index + 2);
      const event = parseSseBlock(block);
      if (event) onEvent(event);
      index = buffer.indexOf("\n\n");
    }
  }
  if (buffer.trim()) {
    const event = parseSseBlock(buffer);
    if (event) onEvent(event);
  }
}

export async function estimateStream(
  emailText: string,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  if (FORCED_MOCK) {
    return mockEstimateStream(emailText, onEvent, signal);
  }
  try {
    const res = await fetch(`${API_URL}/api/estimate/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify({ email_text: emailText }),
      signal,
    });
    if (!res.ok) {
      let detail = `Estimation failed (HTTP ${res.status})`;
      try {
        const body: unknown = await res.json();
        if (body && typeof body === "object" && "detail" in body) {
          detail = String((body as { detail: unknown }).detail);
        }
      } catch {
        // keep default
      }
      throw new ApiError(res.status, detail);
    }
    if (!res.body) throw new ApiError(0, "Streaming not supported by browser");
    setMockActive(false);
    await readSseStream(res.body, onEvent);
  } catch (err) {
    if (signal?.aborted) return;
    if (err instanceof ApiError) throw err;
    if (err instanceof DOMException && err.name === "AbortError") return;
    // Network-level failure: fall back to the mock stream during development.
    setMockActive(true);
    return mockEstimateStream(emailText, onEvent, signal);
  }
}

/* ------------------------------------------------------------------ */
/* Endpoint bindings                                                   */
/* ------------------------------------------------------------------ */

export const api = {
  baseUrl: API_URL,

  health: () => apiCall<Health>("/api/health", undefined, mockHealth),

  scenarios: () => apiCall<Scenario[]>("/api/scenarios", undefined, mockScenarios),

  loadScenario: (id: string) =>
    apiCall<EstimateResponse>(
      `/api/scenarios/${encodeURIComponent(id)}/load`,
      { method: "POST" },
      () => mockLoadScenario(id)
    ),

  estimate: (emailText: string, answers?: AnswersMap) =>
    apiCall<EstimateResponse>(
      "/api/estimate",
      jsonInit({
        email_text: emailText,
        // Answer-refinement calls carry accumulated yes/no answers and are
        // side-effect free (contract v0.2); no answers → a normal estimate.
        ...(answers && Object.keys(answers).length > 0 ? { answers } : {}),
      }),
      () => mockEstimate(emailText, answers)
    ),

  estimatePackages: (emailText: string, budgetDays: number) =>
    apiCall<PackagesResponse>(
      "/api/packages",
      jsonInit({ email_text: emailText, budget_days: budgetDays }),
      () => mockEstimatePackages(emailText, budgetDays)
    ),

  resetDemo: () =>
    apiCall<ResetResponse>("/api/reset", { method: "POST" }, mockReset),

  projects: () =>
    apiCall<ProjectRow[]>("/api/projects", undefined, mockProjects),

  submitActual: (projectId: string, actualDays: number) =>
    apiCall<ActualUpdateResponse>(
      `/api/projects/${encodeURIComponent(projectId)}/actual`,
      jsonInit({ actual_days: actualDays }),
      () => mockSubmitActual(projectId, actualDays)
    ),

  replay: (minTrain = 10) =>
    apiCall<ReplayResponse>(
      `/api/replay?min_train=${minTrain}`,
      undefined,
      mockReplay
    ),

  ab: (emailText: string, n = 10) =>
    apiCall<ABResponse>(
      "/api/ab",
      jsonInit({ email_text: emailText, n }),
      () => mockAb(emailText, n)
    ),

  importCsv: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return apiCall<ImportResponse>(
      "/api/import",
      { method: "POST", body: form },
      () => mockImport(file)
    );
  },
};
