"""
BaseParser: the interface every framework-specific parser plugin implements.

To add support for a new framework:
  1. Subclass BaseParser
  2. Implement `detect()` -- cheap, file-signature-based check (should NOT do a full parse)
  3. Implement `parse()` -- full static analysis, returning a ParsedRepository
  4. Register the parser in parsers/registry.py (created when the registry is built)

Parsers should never raise on recoverable issues (e.g. one file fails to parse) --
log to `metadata.parse_warnings` and continue. Only raise for unrecoverable conditions
(e.g. repo path doesn't exist).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from app.schemas.parser_schema import ParsedRepository


class UnsupportedFrameworkError(Exception):
    """Raised when no registered parser's detect() matches the repo."""


class BaseParser(ABC):
    framework_name: str  # e.g. "express", "spring_boot", "nestjs"

    @abstractmethod
    def detect(self, repo_path: Path) -> bool:
        """Cheap signature check (package.json contents, pom.xml presence, etc).
        Must not perform full parsing. Return True if this parser should handle
        the repo at repo_path."""
        raise NotImplementedError

    @abstractmethod
    def parse(self, repo_path: Path) -> ParsedRepository:
        """Full static analysis of the repo at repo_path. Must return a
        ParsedRepository even in degraded/partial-success cases -- populate
        metadata.parse_warnings rather than raising for per-file failures."""
        raise NotImplementedError
