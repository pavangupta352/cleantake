export interface Alignment {
  offset_seconds: number;
  drift_ppm: number;
  confidence: number;
  anchors: number;
  residual_ms: number;
  status: "aligned" | "uncertain" | "manual" | "reference";
  polarity: number;
}
export interface Source {
  id: string;
  name: string;
  original_filename: string;
  sha256: string;
  speaker: string | null;
  imported_at: string;
  alignment: Alignment;
  audio: {
    frames: number;
    sample_rate: number;
    source_sample_rate: number;
    source_channels: number;
    selected_channel: number | null;
    selected_stream: number;
    channel_mode: string;
    source_duration_seconds: number;
    codec_name: string;
  };
}
export interface Repair {
  id: string;
  start_frame: number;
  end_frame: number;
  source_id: string | null;
  kind: "dropout" | "clipping" | "noise" | "manual";
  status: "proposed" | "accepted" | "rejected" | "unresolved";
  confidence: number;
  reason: string;
  gain_db: number;
  fade_ms: number;
  alternatives: { source_id?: string; reason?: string; score?: number }[];
}
export interface Transcript {
  id: string;
  source_id: string;
  warnings: string[];
  turns: {
    text: string;
    speaker?: string;
    start_ms: number | null;
    end_ms: number | null;
    time_estimated: boolean;
  }[];
}
export interface Project {
  id: string;
  name: string;
  revision: number;
  sample_rate: number;
  primary_source_id: string | null;
  duration_frames: number;
  sources: Source[];
  repairs: Repair[];
  transcripts: Transcript[];
  warnings: string[];
  status: string;
  error: string | null;
  can_undo?: boolean;
  can_redo?: boolean;
}
export interface Summary {
  id: string;
  name: string;
  updated_at: string;
  status: string;
  duration_frames: number;
  source_count: number;
  repair_count: number;
  revision: number;
}
export interface ExportResult {
  export_id: string;
  revision: number;
  artifacts: { name: string; size: number; media_type: string }[];
  warnings?: string[];
}
export interface Job {
  id: string;
  project_id: string;
  operation: string;
  status:
    | "queued"
    | "running"
    | "completed"
    | "failed"
    | "cancelled"
    | "interrupted";
  progress: number | null;
  message: string;
  error: string | null;
  result: (ExportResult & { project_id?: string }) | null;
}
export interface Peaks {
  source_id?: string;
  start_frame: number;
  end_frame: number;
  sample_rate: number;
  min: number[];
  max: number[];
  coverage: [number, number];
  revision: number;
  aligned?: boolean;
}
export type AudioMode = "original" | "repaired" | "source";

const TOKEN_KEY = "cleantake-session";
const fragment = new URLSearchParams(window.location.hash.slice(1));
const supplied = fragment.get("token");
if (supplied) {
  sessionStorage.setItem(TOKEN_KEY, supplied);
  history.replaceState(
    null,
    "",
    window.location.pathname + window.location.search,
  );
}
export const hasSession = () => Boolean(sessionStorage.getItem(TOKEN_KEY));
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}
export async function request(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("X-CleanTake-Token", sessionStorage.getItem(TOKEN_KEY) || "");
  if (init.body && !(init.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      ...init,
      headers,
      referrerPolicy: "no-referrer",
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new ApiError(
      0,
      "disconnected",
      "The local studio is not responding. Keep the CleanTake process running, then retry.",
    );
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new ApiError(
      response.status,
      payload?.error?.code || "request_failed",
      payload?.error?.message ||
        `The request could not be completed (${response.status}). Try again.`,
    );
  }
  return response;
}
export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await request(path, {
    method,
    body:
      body instanceof FormData
        ? body
        : body === undefined
          ? undefined
          : JSON.stringify(body),
    signal,
  });
  return response.status === 204 ? (undefined as T) : response.json();
}
export const projectPath = (id: string) =>
  `/projects/${encodeURIComponent(id)}`;
export const time = (frames: number, rate = 48000, precise = false) => {
  const seconds = Math.max(0, frames / rate);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor(seconds / 60) % 60;
  const sec = precise
    ? (seconds % 60).toFixed(3).padStart(6, "0")
    : Math.floor(seconds % 60)
        .toString()
        .padStart(2, "0");
  return `${hours ? `${hours}:` : ""}${String(minutes).padStart(2, "0")}:${sec}`;
};
