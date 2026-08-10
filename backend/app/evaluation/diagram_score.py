"""
Diagram graph-diff scorer (Week 4 / Phase 7).

Scores the architecture the pipeline extracted against a manually annotated
"expected" architecture for the same repo -- precision / recall / F1 over modules
(nodes), import relationships (edges), and API endpoints. Since our diagram is
generated deterministically from the graph (no LLM), this measures whether the
parser + graph builder recovered the right structure, which is exactly what
"diagram correctness" means here.

The `expected` structure is human-annotated ground truth, one file per evaluation
repo (roadmap Week 3 annotation task). Those annotations don't exist yet -- the
eval repos aren't chosen -- so this ships as the scoring logic plus a loader,
ready to run the moment the annotations land.

Actual structure is extracted from the ParsedRepository (what the diagram is built
from) rather than by re-parsing our own Mermaid text: the two carry identical
structural content, and reading the objects is far more robust than string-parsing
generated Mermaid.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from app.schemas.parser_schema import ParsedRepository


class GraphStructure(BaseModel):
    """A repository's architecture as comparable sets. Used for BOTH the extracted
    actual structure and the annotated expected structure, so scoring is symmetric.
    Import edges are (from_path, to_path) pairs; endpoints are 'METHOD /path' strings."""

    modules: list[str] = Field(default_factory=list)
    imports: list[tuple[str, str]] = Field(default_factory=list)
    endpoints: list[str] = Field(default_factory=list)


class CategoryScore(BaseModel):
    precision: float
    recall: float
    f1: float
    missing: list[str]  # in expected, not produced (false negatives)
    extra: list[str]  # produced, not in expected (false positives)


class GraphDiffScore(BaseModel):
    repo_name: str
    modules: CategoryScore
    imports: CategoryScore
    endpoints: CategoryScore
    overall_f1: float  # mean of the three category F1s


def extract_actual_structure(parsed: ParsedRepository) -> GraphStructure:
    id_to_path = {m.id: m.path for m in parsed.modules}
    imports = [
        (id_to_path[e.from_module_id], id_to_path[e.to_module_id])
        for e in parsed.dependencies.internal
        if e.from_module_id in id_to_path and e.to_module_id in id_to_path
    ]
    return GraphStructure(
        modules=[m.path for m in parsed.modules],
        imports=imports,
        endpoints=[f"{e.method.value} {e.path}" for e in parsed.api_endpoints],
    )


def load_expected(path: str | Path) -> GraphStructure:
    """Load a manually annotated expected structure from a JSON file. `imports` may
    be given as [["a", "b"], ...] (JSON has no tuples) -- pydantic coerces the inner
    lists to tuples."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return GraphStructure.model_validate(data)


def score_diagram(actual: GraphStructure, expected: GraphStructure, repo_name: str) -> GraphDiffScore:
    modules = _score_category(actual.modules, expected.modules)
    imports = _score_category(
        [_edge_str(e) for e in actual.imports], [_edge_str(e) for e in expected.imports]
    )
    endpoints = _score_category(actual.endpoints, expected.endpoints)
    overall = round((modules.f1 + imports.f1 + endpoints.f1) / 3, 4)
    return GraphDiffScore(
        repo_name=repo_name,
        modules=modules,
        imports=imports,
        endpoints=endpoints,
        overall_f1=overall,
    )


def _edge_str(edge: tuple[str, str]) -> str:
    return f"{edge[0]} -> {edge[1]}"


def _score_category(actual_items: list[str], expected_items: list[str]) -> CategoryScore:
    actual, expected = set(actual_items), set(expected_items)

    if not actual and not expected:
        # Nothing expected and nothing produced -- vacuously a perfect match, not a
        # divide-by-zero. (e.g. a repo with genuinely no internal imports.)
        return CategoryScore(precision=1.0, recall=1.0, f1=1.0, missing=[], extra=[])

    true_positives = len(actual & expected)
    precision = true_positives / len(actual) if actual else 0.0
    recall = true_positives / len(expected) if expected else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return CategoryScore(
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        missing=sorted(expected - actual),
        extra=sorted(actual - expected),
    )
