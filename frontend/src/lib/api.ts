// Thin client for the real backend (backend/app/main.py).

import type { ContextVariant } from "./types";

const API_BASE_URL = "http://localhost:8000";

export class ApiError extends Error {}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError(
      `Couldn't reach the backend at ${API_BASE_URL}. Is it running (uvicorn app.main:app --reload)?`,
    );
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const errorBody = await response.json();
      detail = errorBody.detail ?? detail;
    } catch {
      // response body wasn't JSON -- fall back to statusText above
    }
    throw new ApiError(detail);
  }

  return response.json();
}

export interface SummarizeResponse {
  repoName: string;
  sourceUrl: string;
  framework: string | null;
  summary: {
    overview: string;
    tech_stack: string[];
    services: string[];
    dependencies: string[];
  } | null;
  summaryRawText: string;
  status: "success" | "partial" | "failed";
  error: string | null;
}

export async function summarizeRepository(url: string): Promise<SummarizeResponse> {
  const data = await postJson<{
    repo_name: string;
    source_url: string;
    framework: string | null;
    summary: SummarizeResponse["summary"];
    summary_raw_text: string;
    status: SummarizeResponse["status"];
    error: string | null;
  }>("/summarize", { url });

  return {
    repoName: data.repo_name,
    sourceUrl: data.source_url,
    framework: data.framework,
    summary: data.summary,
    summaryRawText: data.summary_raw_text,
    status: data.status,
    error: data.error,
  };
}

export interface DiagramResponse {
  repoName: string;
  sourceUrl: string;
  framework: string | null;
  diagramMermaid: string;
}

export async function getArchitectureDiagram(url: string): Promise<DiagramResponse> {
  const data = await postJson<{
    repo_name: string;
    source_url: string;
    framework: string | null;
    diagram_mermaid: string;
  }>("/diagram", { url });

  return {
    repoName: data.repo_name,
    sourceUrl: data.source_url,
    framework: data.framework,
    diagramMermaid: data.diagram_mermaid,
  };
}

export interface ComparisonRunResponse {
  model: string;
  contextVariant: ContextVariant;
  latencyMs: number;
  inputTokens: number;
  outputTokens: number;
  estimatedCostUsd: number;
  status: "success" | "partial" | "failed";
  error: string | null;
}

export interface CompareResponse {
  repoName: string;
  sourceUrl: string;
  framework: string | null;
  runs: ComparisonRunResponse[];
}

export async function compareModels(url: string, models?: string[]): Promise<CompareResponse> {
  const data = await postJson<{
    repo_name: string;
    source_url: string;
    framework: string | null;
    runs: {
      model: string;
      context_variant: ContextVariant;
      latency_ms: number;
      input_tokens: number;
      output_tokens: number;
      estimated_cost_usd: number;
      status: ComparisonRunResponse["status"];
      error: string | null;
    }[];
  }>("/compare", { url, models });

  return {
    repoName: data.repo_name,
    sourceUrl: data.source_url,
    framework: data.framework,
    runs: data.runs.map((r) => ({
      model: r.model,
      contextVariant: r.context_variant,
      latencyMs: r.latency_ms,
      inputTokens: r.input_tokens,
      outputTokens: r.output_tokens,
      estimatedCostUsd: r.estimated_cost_usd,
      status: r.status,
      error: r.error,
    })),
  };
}
