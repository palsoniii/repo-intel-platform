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
  hallucinationScore: number | null; // null if the run failed or the judge didn't parse
  hallucinationJudged: boolean;
  totalClaims: number;
  unsupportedClaims: number;
  // Coverage (recall): how much of the parser's ground truth the summary actually
  // mentioned, vs. hallucination (precision-like): whether what it said was true.
  coverageScore: number | null; // null if the run failed or the judge didn't parse
  coverageJudged: boolean;
  totalFacts: number;
  missingFacts: number;
  judgeModel: string | null;
  selfJudged: boolean;
  // Deterministic parser-grounded scores -- no model involved, so these are present
  // on every successful run and identical between runs on the same summary.
  oracleScored: boolean;
  oracleCoverageStrict: number | null;
  oracleCoverageLenient: number | null;
  oracleFactsCovered: number;
  oracleTotalFacts: number;
  oracleUnsupportedRate: number | null;
  oracleUnsupportedIdentifiers: number;
  oracleTotalIdentifiers: number;
  // Text-overlap against this repo's reference summary -- null when no
  // reference_summaries/<repo>.json exists for it. BERTScore isn't computed live
  // (see backend ScoredResult docstring); only BLEU/ROUGE/METEOR are cheap enough
  // for an interactive comparison.
  textOverlapScored: boolean;
  bleu4: number | null;
  rougeL: number | null;
  meteor: number | null;
  // Failure taxonomy tags (fabricated_endpoint, missed_dependency, over_generic, ...)
  failureTags: string[];
}

export interface CompareResponse {
  repoName: string;
  sourceUrl: string;
  framework: string | null;
  runs: ComparisonRunResponse[];
}

// The judge must not be one of the generators. Left unset, the backend falls back to
// the provider default (qwen2.5-coder:7b), which IS a generator -- so the qwen arm
// would grade its own summaries. REPORT.md 6.1 documents that self-judging reverses
// the ranking of representations, so it is a correctness issue, not a preference.
// Must be a model that is actually pulled AND is not one of the generators, or every
// quality metric silently comes back null: an unknown tag makes the judge call fail,
// which BaseLLMProvider turns into an empty result, which the verdict parser reports as
// "not judged" -- while the run itself still says success. This previously read
// "mistral:7b-instruct", a tag no machine here has ever had. gemma2:9b is the judge the
// study uses (docs/REPORT.md 5.5.1) and is never a generator, so no arm is self-judged.
export const DEFAULT_JUDGE_MODEL = "gemma2:9b";

export async function compareModels(
  url: string,
  models?: string[],
  judgeModel: string = DEFAULT_JUDGE_MODEL,
): Promise<CompareResponse> {
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
      hallucination_score: number | null;
      hallucination_judged: boolean;
      total_claims: number;
      unsupported_claims: number;
      coverage_score: number | null;
      coverage_judged: boolean;
      total_facts: number;
      missing_facts: number;
      judge_model: string | null;
      self_judged: boolean;
      oracle_scored: boolean;
      oracle_coverage_strict: number | null;
      oracle_coverage_lenient: number | null;
      oracle_facts_covered: number;
      oracle_total_facts: number;
      oracle_unsupported_rate: number | null;
      oracle_unsupported_identifiers: number;
      oracle_total_identifiers: number;
      text_overlap_scored: boolean;
      bleu4: number | null;
      rouge_l: number | null;
      meteor: number | null;
      failure_tags: string[];
    }[];
  }>("/compare", { url, models, judge_model: judgeModel });

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
      hallucinationScore: r.hallucination_score,
      hallucinationJudged: r.hallucination_judged,
      totalClaims: r.total_claims,
      unsupportedClaims: r.unsupported_claims,
      coverageScore: r.coverage_score,
      coverageJudged: r.coverage_judged,
      totalFacts: r.total_facts,
      missingFacts: r.missing_facts,
      judgeModel: r.judge_model,
      selfJudged: r.self_judged,
      oracleScored: r.oracle_scored,
      oracleCoverageStrict: r.oracle_coverage_strict,
      oracleCoverageLenient: r.oracle_coverage_lenient,
      oracleFactsCovered: r.oracle_facts_covered,
      oracleTotalFacts: r.oracle_total_facts,
      oracleUnsupportedRate: r.oracle_unsupported_rate,
      oracleUnsupportedIdentifiers: r.oracle_unsupported_identifiers,
      oracleTotalIdentifiers: r.oracle_total_identifiers,
      textOverlapScored: r.text_overlap_scored,
      bleu4: r.bleu4,
      rougeL: r.rouge_l,
      meteor: r.meteor,
      failureTags: r.failure_tags,
    })),
  };
}
