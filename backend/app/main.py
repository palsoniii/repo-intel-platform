"""
FastAPI entrypoint. Kept minimal for Phase 0 -- real endpoints (analyze repo, fetch
run history, run evaluation batch) get added as each module (parser, graph, context,
providers, evaluation) is built in subsequent phases.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.pipeline import AnalysisError, analyze_repository
from app.schemas.parser_schema import ParsedRepository

app = FastAPI(
    title="Repository Intelligence Platform",
    description="Static-analysis-driven repository understanding + multi-LLM comparison",
    version="0.2.0-phase1",
)


class AnalyzeRequest(BaseModel):
    url: str
    max_size_mb: int = 200


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "phase": "1 - acquisition + Express parser"}


@app.post("/analyze", response_model=ParsedRepository)
def analyze(req: AnalyzeRequest) -> ParsedRepository:
    """Clone + parse a repo, returning the raw ParsedRepository. This is a debug/dev
    endpoint for Phase 1 -- once the graph/context/LLM layers exist (Phase 2+), this
    will trigger the full pipeline and return summaries/diagrams instead."""
    try:
        return analyze_repository(req.url, max_size_mb=req.max_size_mb)
    except AnalysisError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": "Repository Intelligence Platform API",
        "docs": "/docs",
    }
