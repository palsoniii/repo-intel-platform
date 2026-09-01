// Mirrors backend/app/schemas/{parser_schema,llm_result}.py shapes loosely, so
// swapping mock data for a real /analyze response in Week 2 doesn't require
// reshaping every component that consumes it.

export type ContextVariant = "raw" | "dependency_graph" | "knowledge_graph";

export const CONTEXT_VARIANTS: { value: ContextVariant; label: string }[] = [
  { value: "raw", label: "Raw code" },
  { value: "dependency_graph", label: "Dependency graph" },
  { value: "knowledge_graph", label: "Full Neo4j context" },
];

// Generators only. gemma2:9b is deliberately absent: it is the judge, and a model that
// both writes and grades inverts the representation ranking (REPORT.md 6.2).
export const MODELS = ["qwen2.5-coder:7b", "codellama:7b-instruct", "gpt-oss:20b"] as const;
export type ModelName = (typeof MODELS)[number];

export interface RepoSummary {
  overview: string;
  techStack: string[];
  services: string[];
  dependencies: string[];
  endpoints?: string[];
  components?: string[];
}

export interface ComparisonRun {
  model: ModelName;
  contextVariant: ContextVariant;
  latencyMs: number;
  inputTokens: number;
  outputTokens: number;
  hallucinationScore: number; // 0 = no unsupported claims, judged by LLM-as-judge
  estimatedCostUsd: number; // always 0 -- local models only
}

export interface RepoAnalysis {
  repoName: string;
  sourceUrl: string;
  framework: "express" | "nestjs";
  summary: RepoSummary;
  diagramMermaid: string;
  comparisonRuns: ComparisonRun[];
}
