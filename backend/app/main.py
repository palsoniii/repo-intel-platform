"""
FastAPI entrypoint. Real endpoints get added as each module (parser, graph, context,
providers, evaluation) is built out; /summarize is the first one that runs the full
GitHub URL -> parser -> Neo4j -> context -> Ollama -> summary pipeline, no mocks.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.pipeline import AnalysisError, analyze_repository, generate_repository_summary
from app.schemas.llm_result import LLMMetrics, RunStatus
from app.schemas.parser_schema import ParsedRepository

app = FastAPI(
    title="Repository Intelligence Platform",
    description="Static-analysis-driven repository understanding + multi-LLM comparison",
    version="0.3.0-phase2-4",
)


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
