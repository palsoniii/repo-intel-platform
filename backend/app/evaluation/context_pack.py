"""Context packs: the frozen inputs to a generation run, so generation can happen
somewhere that cannot clone a repo or reach a Neo4j.

The battery has two halves with very different requirements. Cloning, tree-sitter
parsing, the Neo4j round-trip and context rendering are CPU-only, need network access
and a database, and take seconds. Generation needs a GPU, needs neither network nor
database, and takes hours. A job-scheduled GPU node typically offers the opposite of
what the first half wants: no inbound services, often no route to github.com, and a
wall-clock budget you do not want to spend on `git clone`.

A pack is that seam. Build it once where the network and the database live; ship the
file; generate from it on the GPU. Because the pack stores the *rendered* context
strings rather than re-deriving them, a run from a pack is also exactly reproducible
in a way a run from URLs is not -- upstream repos move, and `main` today is not `main`
last week.

The parsed repository travels with the contexts because scoring needs it: both judges
and the deterministic oracle score against parser-extracted ground truth, not against
the context text.

Format is one JSON file, `version` gated so a stale pack fails loudly rather than
silently scoring against contexts that no longer match the code that reads them.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from app.schemas.llm_result import ContextVariant
from app.schemas.parser_schema import ParsedRepository

# Bump when the meaning of a field changes (e.g. a context variant starts including
# something it did not before). Packs are compared by equality, not by range: an older
# pack is not "probably fine", it was rendered by different code.
PACK_VERSION = 1


class PackedRepository(BaseModel):
    """One repository: its parse, and its three rendered contexts."""

    source_url: str
    parsed: ParsedRepository
    contexts: dict[ContextVariant, str]

    def context_map(self) -> dict[ContextVariant, str]:
        """Keys come back as ContextVariant even after a JSON round-trip, where they
        arrive as bare strings."""
        return {ContextVariant(k): v for k, v in self.contexts.items()}


class ContextPack(BaseModel):
    version: int = PACK_VERSION
    built_at: str
    max_raw_chars: int
    notes: str = ""
    repositories: list[PackedRepository] = Field(default_factory=list)

    def write(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        return path

    @classmethod
    def read(cls, path: str | Path) -> "ContextPack":
        pack = cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
        if pack.version != PACK_VERSION:
            raise ValueError(
                f"Context pack at {path} is version {pack.version}, but this code reads "
                f"version {PACK_VERSION}. Rebuild it with scripts/build_context_pack.py "
                "-- the contexts in an older pack were rendered by different code, so "
                "scoring against them would compare arms that were never built the same way."
            )
        return pack
