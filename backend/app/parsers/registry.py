"""
Parser registry: tries each registered parser's detect() against a repo and
dispatches to the first match. Adding a new framework parser only requires
appending it to PARSERS below.
"""

from __future__ import annotations

from pathlib import Path

from app.parsers.base import BaseParser, UnsupportedFrameworkError
from app.parsers.express_parser import ExpressParser
from app.schemas.parser_schema import ParsedRepository

# Order matters only in the rare case multiple detect() calls could both return True.
PARSERS: list[BaseParser] = [
    ExpressParser(),
    # NestJSParser(),      # added in Phase 6
]


def parse_repository(repo_path: Path) -> ParsedRepository:
    for parser in PARSERS:
        if parser.detect(repo_path):
            return parser.parse(repo_path)
    raise UnsupportedFrameworkError(
        f"No registered parser could handle the repo at {repo_path}. "
        f"Currently supported: {[p.framework_name for p in PARSERS]}"
    )
