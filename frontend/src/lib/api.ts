// Thin client for the real backend (backend/app/main.py). Only /summarize is wired
// up so far -- Diagram and Comparison pages still use mockData.ts until Phase 5 /
// Week 3's ablation work exist on the backend.

const API_BASE_URL = "http://localhost:8000";

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

export class SummarizeError extends Error {}

// snake_case (backend/Python) -> camelCase (frontend), kept in one place so the
// rest of the app never has to think about the boundary.
function fromApiShape(data: {
  repo_name: string;
  source_url: string;
  framework: string | null;
  summary: SummarizeResponse["summary"];
  summary_raw_text: string;
  status: SummarizeResponse["status"];
  error: string | null;
}): SummarizeResponse {
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

export async function summarizeRepository(url: string): Promise<SummarizeResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/summarize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
  } catch {
    throw new SummarizeError(
      `Couldn't reach the backend at ${API_BASE_URL}. Is it running (uvicorn app.main:app --reload)?`,
    );
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // response body wasn't JSON -- fall back to statusText above
    }
    throw new SummarizeError(detail);
  }

  return fromApiShape(await response.json());
}
