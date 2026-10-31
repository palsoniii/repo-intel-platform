// Client for the dashboard API (backend/app/product/router.py, mounted at /api).
// Field names are kept in the backend's snake_case: these types are only used inside
// the dashboard, and mapping every view's payload would be churn with no reader.

import { useEffect, useState } from "react";
import { API_BASE_URL, ApiError } from "./api";

export type AnalysisStatus = "queued" | "running" | "ready" | "failed";
export type Stage =
  | "queued" | "cloning" | "parsing" | "indexing" | "graph" | "summarizing" | "done" | "failed";
export type SummaryStatus = "pending" | "running" | "done" | "failed" | "skipped";

export interface Stats {
  files: number;
  classes: number;
  functions: number;
  endpoints: number;
  entities: number;
  internal_imports: number;
  external_dependencies: number;
  lines_of_code: number;
}

export interface RepoSummary {
  overview?: string;
  tech_stack?: string[];
  services?: string[];
  dependencies?: string[];
  endpoints?: string[];
  components?: string[];
}

export interface AnalysisBrief {
  id: string;
  url: string;
  owner: string;
  repo_name: string;
  commit_sha: string | null;
  framework: string | null;
  status: AnalysisStatus;
  stage: Stage;
  error: string | null;
  summary_status: SummaryStatus;
  summary_error: string | null;
  summary_model: string | null;
  graph_status: "pending" | "stored" | "unavailable" | "disabled";
  created_at: string;
  updated_at: string;
  timings: Record<string, number>;
  stats: Stats | null;
  reused?: boolean;
}

export interface Analysis extends AnalysisBrief {
  summary: {
    summary: RepoSummary | null;
    valid: boolean;
    raw_text: string;
    model: string;
    provider?: Provider; // absent on summaries written before Groq support (local)
    latency_ms: number;
    input_tokens: number;
    output_tokens: number;
  } | null;
  metadata?: {
    name: string;
    detected_language: string;
    detected_framework: string | null;
    framework_version: string | null;
    files_scanned: number;
    parse_warnings: string[];
  };
  layers?: { layer: string; label: string; files: number }[];
  hotspots?: { id: string; path: string; imported_by: number }[];
  suggested_questions?: string[];
}

export type NodeKind = "file" | "class" | "function" | "endpoint" | "entity";

export interface GraphElements {
  nodes: { data: { id: string; kind: NodeKind; label: string; path?: string; layer?: string; method?: string; orm?: string } }[];
  edges: { data: { id: string; source: string; target: string; kind: string } }[];
}

export interface Architecture {
  layered: {
    mermaid: string;
    grouped: boolean;
    node_count: number;
    edge_count: number;
    graph: {
      nodes: { id: string; label: string; layer: string; files: number; path: string | null; title: string }[];
      links: { source: string; target: string; count: number }[];
    };
  };
  nest_modules: { mermaid: string; modules: number; edges: number } | null;
}

export interface TraceStep {
  kind: "endpoint" | "handler" | "middleware" | "service" | "data" | "entity";
  label: string;
  file?: string | null;
  depth: number;
}

export interface Endpoint {
  id: string;
  method: string;
  path: string;
  handler: string | null;
  controller: string | null;
  file: string | null;
  line: number | null;
  annotation: string | null;
  trace: TraceStep[];
}

export interface Entity {
  name: string;
  orm: string;
  source_path: string;
  line: number;
  module_id: string | null;
  fields: { name: string; type: string }[];
  relations: { target: string; kind: "one" | "many"; field: string }[];
}

export interface Dependency {
  name: string;
  version: string | null;
  dep_type: "runtime" | "dev" | "unknown";
  category: string;
  description: string | null;
}

export interface FileEntry {
  id: string;
  path: string;
  layer: string;
  size: number;
  imports: number;
  imported_by: number;
  classes: string[];
}

export type Provider = "groq" | "ollama";

export interface SystemStatus {
  provider: Provider;
  model: string;
  label: string;
  llm: { reachable: boolean; model_available?: boolean; models?: string[]; error?: string };
  public: boolean;
  neo4j: { enabled: boolean; reachable?: boolean; error?: string };
}

export function modelLabel(provider: Provider | undefined, model: string): string {
  return `${provider === "groq" ? "Groq" : "Local"} · ${model}`;
}

// Fetched once per page load and shared: several components word themselves by
// which model is configured.
let systemRequest: Promise<SystemStatus> | null = null;

export function useSystem(): SystemStatus | null {
  const [system, setSystem] = useState<SystemStatus | null>(null);
  useEffect(() => {
    systemRequest ??= api.system();
    systemRequest.then(setSystem).catch(() => {
      systemRequest = null;
    });
  }, []);
  return system;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(
      `Couldn't reach the backend at ${API_BASE_URL}. Is it running (uvicorn app.main:app)?`,
    );
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : detail;
    } catch {
      // not JSON
    }
    throw new ApiError(detail);
  }
  return response.json();
}

const get = <T,>(path: string) => request<T>(path);
const post = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  createAnalysis: (url: string, force = false) => post<AnalysisBrief>("/api/analyses", { url, force }),
  listAnalyses: () => get<AnalysisBrief[]>("/api/analyses"),
  analysis: (id: string) => get<Analysis>(`/api/analyses/${id}`),
  deleteAnalysis: (id: string) => request<unknown>(`/api/analyses/${id}`, { method: "DELETE" }),
  graph: (id: string) => get<GraphElements>(`/api/analyses/${id}/graph`),
  architecture: (id: string, includeTests: boolean) =>
    get<Architecture>(`/api/analyses/${id}/architecture?include_tests=${includeTests}`),
  endpoints: (id: string) => get<Endpoint[]>(`/api/analyses/${id}/endpoints`),
  models: (id: string) => get<{ mermaid: string | null; entities: Entity[] }>(`/api/analyses/${id}/models`),
  dependencies: (id: string) => get<Dependency[]>(`/api/analyses/${id}/dependencies`),
  files: (id: string) => get<FileEntry[]>(`/api/analyses/${id}/files`),
  file: (id: string, path: string) =>
    get<{ path: string; content: string }>(`/api/analyses/${id}/file?path=${encodeURIComponent(path)}`),
  regenerateSummary: (id: string) => post<unknown>(`/api/analyses/${id}/summary`, {}),
  system: () => get<SystemStatus>("/api/system"),
  primeAsk: (id: string) => post<unknown>(`/api/analyses/${id}/ask/prime`, {}),
};

export type AskEvent =
  | { type: "sources"; sources: { path: string; score: number }[]; model: string; provider?: Provider; cached?: boolean }
  | { type: "token"; text: string }
  | {
      type: "done";
      input_tokens?: number;
      output_tokens?: number;
      duration_ms?: number;
      cached?: boolean;
      model?: string;
      provider?: Provider;
    }
  | { type: "error"; message: string };

// Streams an answer as NDJSON events. The local model writes ~15-25 tokens/s on the
// demo Mac, so streaming is what makes a 20-second answer feel responsive.
export async function askRepo(
  id: string,
  question: string,
  history: { role: "user" | "assistant"; content: string }[],
  onEvent: (e: AskEvent) => void,
  signal?: AbortSignal,
  fresh = false,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/analyses/${id}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, history, fresh }),
      signal,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") return;
    throw new ApiError(`Couldn't reach the backend at ${API_BASE_URL}.`);
  }
  if (!response.ok || !response.body) {
    throw new ApiError(`Ask failed (${response.status}).`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let nl: number;
    while ((nl = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, nl).trim();
      buffer = buffer.slice(nl + 1);
      if (line) onEvent(JSON.parse(line) as AskEvent);
    }
  }
}
