import type { RepoAnalysis, ComparisonRun, ModelName, ContextVariant } from "./types";
import { MODELS, CONTEXT_VARIANTS } from "./types";

// Placeholder data for the dashboard shell (Week 1). Real data replaces this in
// Week 2 once GitHub URL -> parser -> Neo4j -> context -> Ollama -> summary is wired up.

function mockRun(model: ModelName, contextVariant: ContextVariant): ComparisonRun {
  // Deterministic-looking fake numbers so the UI has visible variation without
  // being random on every render.
  const modelIndex = MODELS.indexOf(model);
  const variantIndex = CONTEXT_VARIANTS.findIndex((v) => v.value === contextVariant);
  const richness = variantIndex + 1; // raw=1, dependency_graph=2, knowledge_graph=3

  return {
    model,
    contextVariant,
    latencyMs: 1800 + modelIndex * 650 - richness * 80,
    inputTokens: 400 * richness + modelIndex * 50,
    outputTokens: 180 + modelIndex * 20,
    hallucinationScore: Math.max(0, 0.35 - richness * 0.1 - modelIndex * 0.02),
    estimatedCostUsd: 0,
  };
}

export const mockAnalysis: RepoAnalysis = {
  repoName: "node-js-getting-started",
  sourceUrl: "https://github.com/heroku/node-js-getting-started",
  framework: "express",
  summary: {
    overview:
      "[Placeholder] A minimal Express.js application demonstrating routing, static " +
      "file serving, and view rendering. This text is fake -- Phase 5 (summary " +
      "generation) will replace it with real Ollama output.",
    techStack: ["Express.js", "Node.js", "Pug (views)"],
    services: ["HTTP server (index.js)", "Static asset serving"],
    dependencies: ["express", "pug"],
  },
  diagramMermaid: [
    "graph TD",
    "  Client -->|HTTP GET /| Server[Express Server]",
    "  Server --> Router[Route Handlers]",
    "  Router --> Views[Pug Views]",
    "  Server --> Static[Static Assets]",
  ].join("\n"),
  comparisonRuns: MODELS.flatMap((model) =>
    CONTEXT_VARIANTS.map((v) => mockRun(model, v.value)),
  ),
};

export const HELD_BACK_REPO_NAMES = ["surprise-repo-1", "surprise-repo-2"];
