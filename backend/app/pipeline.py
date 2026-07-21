"""
Top-level orchestration: URL in, ParsedRepository out. This is what the FastAPI
endpoint (and later, the evaluation harness) calls -- it doesn't know about
GitPython or tree-sitter directly, just this one function.
"""

from __future__ import annotations

from app.acquisition.clone import AcquiredRepo, CloneFailedError, InvalidRepoUrlError, RepoTooLargeError, clone_repository
from app.parsers.base import UnsupportedFrameworkError
from app.parsers.registry import parse_repository
from app.schemas.parser_schema import ParsedRepository


class AnalysisError(Exception):
    """Wraps all recoverable failure modes with a consistent message for the API layer."""


def analyze_repository(url: str, max_size_mb: int = 200) -> ParsedRepository:
    acquired: AcquiredRepo | None = None
    try:
        acquired = clone_repository(url, max_size_mb=max_size_mb)
        parsed = parse_repository(acquired.local_path)
        parsed.metadata.source_url = url
        parsed.metadata.commit_sha = acquired.commit_sha
        return parsed
    except (InvalidRepoUrlError, CloneFailedError, RepoTooLargeError, UnsupportedFrameworkError) as e:
        raise AnalysisError(str(e)) from e
    finally:
        if acquired is not None:
            acquired.cleanup()
