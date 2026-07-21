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
    generate_repository_summary,
)
from app.schemas.llm_result import LLMMetrics, RunStatus
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
    and Ollama daemon (see backend/.env.example); the 3-way representation ablation
    and multi-model comparison are Week 3 work -- this always uses the
    knowledge_graph representation and provider.default_model unless overridden."""
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


@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": "Repository Intelligence Platform API",
        "docs": "/docs",
    }
