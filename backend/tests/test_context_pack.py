"""Unit tests for context packs -- the frozen generation inputs that let the battery
run on a GPU node with no Neo4j and no network (see scripts/build_context_pack.py).

Offline by design: a pack exists precisely so nothing here needs infrastructure.
"""

import json

import pytest

from app.evaluation.context_pack import PACK_VERSION, ContextPack, PackedRepository
from app.schemas.llm_result import ContextVariant
from app.schemas.parser_schema import (
    Dependencies,
    ModuleNode,
    ParsedRepository,
    RepoMetadata,
)


def _parsed() -> ParsedRepository:
    return ParsedRepository(
        metadata=RepoMetadata(
            name="sample-repo",
            source_url="https://github.com/test/sample-repo",
            detected_language="typescript",
            detected_framework="nestjs",
        ),
        modules=[ModuleNode(id="mod_0", path="src/app.ts", kind="module", imports=[])],
        dependencies=Dependencies(),
    )


def _pack() -> ContextPack:
    return ContextPack(
        built_at="2026-08-29T00:00:00+00:00",
        repositories=[
            PackedRepository(
                source_url="https://github.com/test/sample-repo",
                parsed=_parsed(),
                contexts={
                    ContextVariant.RAW: "raw source text",
                    ContextVariant.DEPENDENCY_GRAPH: "module dependency graph",
                    ContextVariant.KNOWLEDGE_GRAPH: "full knowledge graph",
                },
            )
        ],
    )


def test_pack_round_trips_through_disk(tmp_path):
    path = _pack().write(tmp_path / "pack.json")
    back = ContextPack.read(path)

    assert len(back.repositories) == 1
    repo = back.repositories[0]
    assert repo.parsed.metadata.name == "sample-repo"
    assert repo.parsed.modules[0].path == "src/app.ts"


def test_context_keys_survive_as_enum_not_string(tmp_path):
    """JSON has no enum type, so the keys come back as bare strings. Everything
    downstream keys on ContextVariant, so the pack must convert them back -- a str key
    would silently miss every lookup and produce an empty ablation."""
    back = ContextPack.read(_pack().write(tmp_path / "pack.json"))
    contexts = back.repositories[0].context_map()

    assert set(contexts) == {
        ContextVariant.RAW,
        ContextVariant.DEPENDENCY_GRAPH,
        ContextVariant.KNOWLEDGE_GRAPH,
    }
    assert contexts[ContextVariant.KNOWLEDGE_GRAPH] == "full knowledge graph"


def test_a_pack_from_a_different_version_is_refused(tmp_path):
    """Contexts in an older pack were rendered by different code. Scoring against them
    would silently compare arms that were never built the same way, so this must fail
    loudly rather than load."""
    path = tmp_path / "stale.json"
    data = json.loads(_pack().model_dump_json())
    data["version"] = PACK_VERSION + 1
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="Rebuild it"):
        ContextPack.read(path)


def test_the_whole_parse_travels_with_the_pack(tmp_path):
    """Scoring runs against the parsed repository, not the context text -- both judges
    and the deterministic oracle need it. If it did not survive the round-trip the GPU
    node could generate but never score."""
    back = ContextPack.read(_pack().write(tmp_path / "pack.json"))
    parsed = back.repositories[0].parsed

    assert parsed.metadata.detected_framework == "nestjs"
    assert parsed.metadata.detected_language == "typescript"
    assert len(parsed.modules) == 1
