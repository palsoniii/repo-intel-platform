"""
FastAPI entrypoint. Real endpoints get added as each module (parser, graph, context,
providers, evaluation) is built out; /summarize is the first one that runs the full
GitHub URL -> parser -> Neo4j -> context -> Ollama -> summary pipeline, no mocks.
"""

import logging
import re

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.pipeline import (
    AnalysisError,
    PipelineInfrastructureError,
    analyze_repository,
    generate_repository_diagram,
    generate_repository_summary,
    run_scored_ablation,
)
from app.schemas.llm_result import ContextVariant, LLMMetrics, RunStatus
from app.schemas.parser_schema import ParsedRepository

# .env has been documented and depended on since Phase 0 (NEO4J_PASSWORD,
# OLLAMA_HOST, ...) but nothing actually loaded it -- neo4j_client.get_driver() and
# OllamaProvider.__init__ both read os.environ lazily at call time, not at import
# time, so this just needs to run before the first request, not before the imports
# above. Found by restarting the server without inline env vars and getting a Neo4j
# auth error that only made sense once this gap was noticed.
load_dotenv()

logger = logging.getLogger(__name__)

# Dev-only: the dashboard (Vite) calls this API directly from the browser. Vite's
# default port (5173) may be taken by another local project, so it can land on any
# port -- matched here via regex rather than a hardcoded origin. Tighten this to the
# deployed frontend's real origin before Week 4's public/live demo. Shared between
# CORSMiddleware and unhandled_exception_handler below -- see that handler's
# docstring for why both need it.
DEV_CORS_ORIGIN_REGEX = re.compile(r"^http://(localhost|127\.0\.0\.1):\d+$")

app = FastAPI(
    title="Repository Intelligence Platform",
    description="Static-analysis-driven repository understanding + multi-LLM comparison",
    version="0.3.0-phase2-4",
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=DEV_CORS_ORIGIN_REGEX.pattern,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Safety net for genuinely unexpected exceptions. Specific, anticipated
    failures (bad URL, Neo4j unreachable) are raised as HTTPException from the
    route instead, which IS covered by CORSMiddleware correctly -- this handler
    exists only for the rest.

    The CORS header below is set manually, NOT inherited from CORSMiddleware:
    Starlette special-cases handlers registered for `Exception`/500, routing them
    to ServerErrorMiddleware, which wraps CORSMiddleware from the outside. So a
    response built here never passes back through CORSMiddleware to pick up
    Access-Control-Allow-Origin -- confirmed by testing this exact handler with
    TestClient(raise_server_exceptions=False) and inspecting the response headers.
    Without this, an unexpected backend error looks like an opaque network/CORS
    failure in the browser instead of a readable one."""
    logger.exception("Unhandled exception in %s %s", request.method, request.url.path)
    response = JSONResponse(status_code=500, content={"detail": f"Internal error: {exc}"})
    origin = request.headers.get("origin")
    if origin and DEV_CORS_ORIGIN_REGEX.match(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
    return response


class AnalyzeRequest(BaseModel):
    url: str
    max_size_mb: int = 200


class SummarizeRequest(BaseModel):
    url: str
    model: str | None = None
    max_size_mb: int = 200


class SummarizeResponse(BaseModel):
    repo_name: str
    source_url: str
    framework: str | None
    summary: dict | None  # None if the model's output didn't parse as valid JSON
    summary_raw_text: str
    metrics: LLMMetrics
    status: RunStatus
    error: str | None = None


class DiagramRequest(BaseModel):
    url: str
    max_size_mb: int = 200


class DiagramResponse(BaseModel):
    repo_name: str
    source_url: str
    framework: str | None
    diagram_mermaid: str


class CompareRequest(BaseModel):
    url: str
    models: list[str] | None = None  # defaults to the 3 comparison models (.env)
    judge_model: str | None = None  # defaults to the provider's default model
    max_size_mb: int = 200


class ComparisonRun(BaseModel):
    model: str
    context_variant: ContextVariant
    latency_ms: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    status: RunStatus
    error: str | None = None
    # Quality metrics -- null when the run failed or the judge's own output didn't parse.
    # Hallucination = precision-like (are the claims it made true); coverage =
    # recall-like (how much of the parser's ground truth did it actually mention).
    # Neither alone is "quality": a summary can hit 0 hallucination by saying almost
    # nothing, which is exactly what low coverage would reveal.
    hallucination_score: float | None = None
    hallucination_judged: bool = False
    total_claims: int = 0
    unsupported_claims: int = 0
    coverage_score: float | None = None
    coverage_judged: bool = False
    total_facts: int = 0
    missing_facts: int = 0
    judge_model: str | None = None
    self_judged: bool = False  # generator == judge (exclude when analysing)
    # Deterministic parser-grounded scores for the same summary -- no model involved,
    # so unlike the judge fields above these are never null on a successful run and
    # never vary between runs. Reported alongside the judge, not instead of it: the
    # oracle matches identifiers and so cannot credit paraphrase, while the judge can
    # but is unreliable in both directions. `oracle_coverage_strict` is the headline
    # figure in docs/REPORT.md 5.7; the lenient tier bounds surface-form variation.
    oracle_scored: bool = False
    oracle_coverage_strict: float | None = None
    oracle_coverage_lenient: float | None = None
    oracle_facts_covered: int = 0
    oracle_total_facts: int = 0
    oracle_unsupported_rate: float | None = None
    oracle_unsupported_identifiers: int = 0
    oracle_total_identifiers: int = 0
    # Text-overlap against reference_summaries/<repo>.json's overview -- null when no
    # reference file exists for this repo. BERTScore is intentionally excluded from
    # the live endpoint (see pipeline.ScoredResult's docstring); only the batch
    # harness computes it, since it costs a model download/load on first use.
    text_overlap_scored: bool = False
    bleu4: float | None = None
    rouge_l: float | None = None
    meteor: float | None = None
    # Failure taxonomy tags (see evaluation/failure_analysis.py) -- always populated
    # for a successful run, no extra judge call needed.
    failure_tags: list[str] = []


class CompareResponse(BaseModel):
    repo_name: str
    source_url: str
    framework: str | None
    runs: list[ComparisonRun]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "phase": "4 - Ollama layer + Neo4j graph + context builder"}


@app.post("/analyze", response_model=ParsedRepository)
def analyze(req: AnalyzeRequest) -> ParsedRepository:
    """Clone + parse a repo, returning the raw ParsedRepository -- a debug/dev
    endpoint for inspecting parser output directly, without the graph/LLM layers."""
    try:
        return analyze_repository(req.url, max_size_mb=req.max_size_mb)
    except AnalysisError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/summarize", response_model=SummarizeResponse)
def summarize(req: SummarizeRequest) -> SummarizeResponse:
    """Runs the full pipeline: parse -> write to Neo4j -> build knowledge_graph
    context -> ask the local Ollama model for a summary. Requires a reachable Neo4j
    and Ollama daemon (see backend/.env.example). Single model, single
    (knowledge_graph) representation -- see /compare for the full 3x3 ablation."""
    try:
        parsed, result = generate_repository_summary(
            req.url, model=req.model, max_size_mb=req.max_size_mb
        )
    except AnalysisError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PipelineInfrastructureError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return SummarizeResponse(
        repo_name=parsed.metadata.name,
        source_url=parsed.metadata.source_url,
        framework=parsed.metadata.detected_framework,
        summary=result.output.parsed,
        summary_raw_text=result.output.raw_text,
        metrics=result.metrics,
        status=result.status,
        error=result.error,
    )


@app.post("/diagram", response_model=DiagramResponse)
def diagram(req: DiagramRequest) -> DiagramResponse:
    """Parse -> write to Neo4j -> generate a Mermaid architecture diagram directly
    from the graph. No LLM call -- deterministic and free, unlike /summarize."""
    try:
        parsed, diagram_mermaid = generate_repository_diagram(req.url, max_size_mb=req.max_size_mb)
    except AnalysisError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PipelineInfrastructureError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return DiagramResponse(
        repo_name=parsed.metadata.name,
        source_url=parsed.metadata.source_url,
        framework=parsed.metadata.detected_framework,
        diagram_mermaid=diagram_mermaid,
    )


@app.post("/compare", response_model=CompareResponse)
def compare(req: CompareRequest) -> CompareResponse:
    """Runs the full 3-way representation ablation (raw / dependency_graph /
    knowledge_graph) across all requested models, then scores each summary for
    hallucination. This is len(models) * 3 generation calls PLUS a judge call each --
    expect several minutes, especially with the default 3 models."""
    try:
        parsed, scored = run_scored_ablation(
            req.url, models=req.models, judge_model=req.judge_model, max_size_mb=req.max_size_mb
        )
    except AnalysisError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PipelineInfrastructureError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return CompareResponse(
        repo_name=parsed.metadata.name,
        source_url=parsed.metadata.source_url,
        framework=parsed.metadata.detected_framework,
        runs=[_comparison_run(s) for s in scored],
    )


def _comparison_run(scored) -> "ComparisonRun":
    r = scored.result
    h = scored.hallucination
    c = scored.coverage
    t = scored.text_overlap
    oc = scored.oracle_coverage
    oh = scored.oracle_hallucination
    judge_model = h.judge_model if h else (c.judge_model if c else None)
    return ComparisonRun(
        model=r.model,
        context_variant=r.context_variant,
        latency_ms=r.metrics.latency_ms,
        input_tokens=r.metrics.input_tokens,
        output_tokens=r.metrics.output_tokens,
        estimated_cost_usd=r.metrics.estimated_cost_usd,
        status=r.status,
        error=r.error,
        hallucination_score=(h.hallucination_score if h and h.judged else None),
        hallucination_judged=(h.judged if h else False),
        total_claims=(h.total_claims if h else 0),
        unsupported_claims=(len(h.unsupported_claims) if h else 0),
        coverage_score=(c.coverage_score if c and c.judged else None),
        coverage_judged=(c.judged if c else False),
        total_facts=(c.total_facts if c else 0),
        missing_facts=(len(c.missing_facts) if c else 0),
        judge_model=judge_model,
        self_judged=(bool(judge_model and judge_model == r.model)),
        oracle_scored=(oc is not None),
        oracle_coverage_strict=(oc.coverage_strict if oc else None),
        oracle_coverage_lenient=(oc.coverage_lenient if oc else None),
        oracle_facts_covered=(oc.covered_strict if oc else 0),
        oracle_total_facts=(oc.total_facts if oc else 0),
        oracle_unsupported_rate=(oh.unsupported_identifier_rate if oh else None),
        oracle_unsupported_identifiers=(oh.unsupported if oh else 0),
        oracle_total_identifiers=(oh.total_candidates if oh else 0),
        text_overlap_scored=(t is not None),
        bleu4=(t.bleu4 if t else None),
        rouge_l=(t.rouge_l if t else None),
        meteor=(t.meteor if t else None),
        failure_tags=[tag.value for tag in scored.failure_tags],
    )


@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": "Repository Intelligence Platform API",
        "docs": "/docs",
    }
