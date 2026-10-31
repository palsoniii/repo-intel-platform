"""
Dashboard API, mounted under /api. The research endpoints in main.py (/summarize,
/diagram, /compare) are left exactly as they were.
"""

from __future__ import annotations

import threading
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.acquisition.clone import InvalidRepoUrlError, validate_github_url
from app.product import jobs, llm, ratelimit, store, views
from app.product.ask import prime, question_key, stream_answer, suggested_questions
from app.schemas.parser_schema import ParsedRepository

router = APIRouter(prefix="/api", tags=["dashboard"])


class CreateAnalysisRequest(BaseModel):
    url: str
    force: bool = Field(False, description="Re-analyse even if this URL was analysed before")


class AskRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=2000)
    history: list[dict[str, Any]] = Field(default_factory=list)
    fresh: bool = Field(False, description="Ignore a stored answer and ask the model again")


@lru_cache(maxsize=16)
def _parsed(analysis_id: str, updated_at: str) -> ParsedRepository:
    analysis = store.get_analysis(analysis_id)
    return ParsedRepository.model_validate(analysis["parsed_json"])  # type: ignore[index]


def _load(analysis_id: str) -> tuple[dict, ParsedRepository, dict]:
    analysis = store.get_analysis(analysis_id)
    if analysis is None:
        raise HTTPException(404, "No analysis with that id.")
    if analysis["parsed_json"] is None:
        raise HTTPException(409, "This analysis isn't ready yet.")
    # updated_at changes whenever the row does, so a stale cached parse is never served.
    return analysis, _parsed(analysis_id, analysis["updated_at"]), analysis.get("insights_json") or {}


def _public(analysis: dict) -> dict:
    """The fields every view needs, without the large JSON documents."""
    insights = analysis.get("insights_json") or {}
    return {
        k: analysis.get(k)
        for k in (
            "id", "url", "owner", "repo_name", "commit_sha", "framework", "status", "stage",
            "error", "summary_status", "summary_error", "summary_model", "graph_status",
            "created_at", "updated_at",
        )
    } | {"timings": analysis.get("timings_json") or {}, "stats": insights.get("stats")}


@router.post("/analyses")
def create_analysis(req: CreateAnalysisRequest, request: Request) -> dict:
    try:
        owner, repo = validate_github_url(req.url)
    except InvalidRepoUrlError as e:
        raise HTTPException(400, str(e))
    url = f"https://github.com/{owner}/{repo.removesuffix('.git')}"
    # A public deployment never re-analyses on request: a stored result is reused.
    if not req.force or ratelimit.public_mode():
        existing = store.find_latest_for_url(url)
        if existing:
            return _public(existing) | {"reused": True}
    ratelimit.check(request, "analyses")
    analysis = store.create_analysis(url, owner, repo.removesuffix(".git"))
    jobs.submit_analysis(analysis["id"], url)
    return _public(analysis) | {"reused": False}


@router.get("/analyses")
def list_analyses(limit: int = 50) -> list[dict]:
    return [_public(a) for a in store.list_analyses(limit)]


@router.get("/analyses/{analysis_id}")
def get_analysis(analysis_id: str) -> dict:
    analysis = store.get_analysis(analysis_id)
    if analysis is None:
        raise HTTPException(404, "No analysis with that id.")
    out = _public(analysis)
    out["summary"] = analysis.get("summary_json")
    if analysis.get("parsed_json") is not None:
        parsed = _parsed(analysis_id, analysis["updated_at"])
        insights = analysis.get("insights_json") or {}
        out["metadata"] = parsed.metadata.model_dump(mode="json")
        out["layers"] = views.layer_breakdown(parsed, insights)
        out["hotspots"] = views.hotspots(parsed)
        out["suggested_questions"] = suggested_questions(parsed, insights)
    return out


@router.delete("/analyses/{analysis_id}")
def delete_analysis(analysis_id: str) -> dict:
    if ratelimit.public_mode():
        raise HTTPException(403, "Deleting analyses is disabled on the public deployment.")
    store.delete_analysis(analysis_id)
    return {"deleted": analysis_id}


@router.get("/analyses/{analysis_id}/graph")
def get_graph(analysis_id: str) -> dict:
    _, parsed, insights = _load(analysis_id)
    return views.knowledge_graph(parsed, insights)


@router.get("/analyses/{analysis_id}/architecture")
def get_architecture(analysis_id: str, include_tests: bool = False) -> dict:
    _, parsed, insights = _load(analysis_id)
    return {
        "layered": views.architecture_diagram(parsed, insights, include_tests=include_tests),
        "nest_modules": views.nest_module_map(parsed, insights),
    }


@router.get("/analyses/{analysis_id}/endpoints")
def get_endpoints(analysis_id: str) -> list[dict]:
    _, parsed, insights = _load(analysis_id)
    return views.endpoints_view(parsed, insights)


@router.get("/analyses/{analysis_id}/models")
def get_models(analysis_id: str) -> dict:
    _, _, insights = _load(analysis_id)
    return views.er_diagram(insights)


@router.get("/analyses/{analysis_id}/dependencies")
def get_dependencies(analysis_id: str) -> list[dict]:
    _, parsed, _ = _load(analysis_id)
    return views.dependencies_view(parsed)


@router.get("/analyses/{analysis_id}/files")
def get_files(analysis_id: str) -> list[dict]:
    _, parsed, insights = _load(analysis_id)
    return views.files_view(parsed, insights, store.list_file_sizes(analysis_id))


@router.get("/analyses/{analysis_id}/file")
def get_file(analysis_id: str, path: str = Query(...)) -> dict:
    content = store.get_file(analysis_id, path)
    if content is None:
        raise HTTPException(404, "That file isn't stored for this analysis.")
    return {"path": path, "content": content}


@router.post("/analyses/{analysis_id}/summary")
def regenerate_summary(analysis_id: str, request: Request) -> dict:
    _load(analysis_id)
    ratelimit.check(request, "asks")
    jobs.submit_summary(analysis_id)
    return {"queued": True}


@router.post("/analyses/{analysis_id}/ask")
def ask(analysis_id: str, req: AskRequest, request: Request) -> StreamingResponse:
    _, parsed, insights = _load(analysis_id)
    files = store.get_all_files(analysis_id)
    if req.history or req.fresh or not store.get_cached_answer(analysis_id, question_key(req.question)):
        ratelimit.check(request, "asks")  # replaying a stored answer costs nothing
    return StreamingResponse(
        stream_answer(
            parsed, insights, files, req.question, req.history,
            analysis_id=analysis_id, use_cache=not req.fresh,
        ),
        media_type="application/x-ndjson",
    )


@router.post("/analyses/{analysis_id}/ask/prime")
def ask_prime(analysis_id: str) -> dict:
    """Called when the Ask tab opens: the model reads the repository overview in the
    background, so the first question only pays for its own files."""
    _, parsed, insights = _load(analysis_id)
    files = store.get_all_files(analysis_id)
    threading.Thread(target=prime, args=(parsed, insights, files), daemon=True).start()
    return {"priming": True}


@router.get("/system")
def system_status() -> dict:
    """What the dashboard depends on, so the UI can say what's missing instead of
    failing."""
    out: dict[str, Any] = llm.status() | {"public": ratelimit.public_mode()}
    out["neo4j"] = {"enabled": jobs.neo4j_enabled()}
    if not jobs.neo4j_enabled():
        return out
    try:
        from app.db.neo4j_client import get_driver

        driver = get_driver()
        try:
            driver.verify_connectivity()
            out["neo4j"]["reachable"] = True
        finally:
            driver.close()
    except Exception as e:  # noqa: BLE001
        out["neo4j"] |= {"reachable": False, "error": str(e).splitlines()[0][:200]}
    return out
