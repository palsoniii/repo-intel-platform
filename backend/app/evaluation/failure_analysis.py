"""
Failure taxonomy (IEEE-paper eval expansion, Step 1.7).

Categorizes failure modes from signals the harness already produces --
hallucination.py's `unsupported_claims`, coverage.py's `missing_facts`, and the
generated overview text itself -- into a fixed set of tags, then aggregates them
into a frequency table. Reviewers expect a qualitative failure breakdown alongside
the numbers (arXiv:2505.12118 and CIAO both report one), not just aggregate scores.

Precision differs deliberately between categories, and that's disclosed rather than
papered over:
- Missing-fact tags (MISSED_*) are precise: coverage.py's `missing_facts` strings
  are already category-prefixed ("Dependency: X", "Endpoint: GET /x", ...) by
  `build_coverable_facts()`, so categorizing them is exact string-prefix matching,
  not guessing.
- Unsupported-claim tags (FABRICATED_*) are heuristic: hallucination.py's
  `unsupported_claims` are free-form text the judge extracted FROM the summary, not
  structured data, so categorizing them means pattern-matching prose (an HTTP-verb
  pattern for endpoints, a keyword list for named technologies). This is
  necessarily lower-precision than the missing-fact tags, which is why fabricated
  claims collapse into two broad buckets (FABRICATED_ENDPOINT,
  FABRICATED_TECHNOLOGY) instead of pretending the same fine-grained precision the
  structured signal has.
"""

from __future__ import annotations

import re
from collections import Counter
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class FailureTag(str, Enum):
    FABRICATED_ENDPOINT = "fabricated_endpoint"
    FABRICATED_TECHNOLOGY = "fabricated_technology"  # named framework/library/db/service not in the facts
    MISSED_ENDPOINT = "missed_endpoint"
    MISSED_DEPENDENCY = "missed_dependency"
    MISSED_FRAMEWORK_OR_LANGUAGE = "missed_framework_or_language"
    MISSED_CLASS_OR_SERVICE = "missed_class_or_service"
    MISSED_DATABASE_ENTITY = "missed_database_entity"
    OVER_GENERIC = "over_generic"  # says almost nothing repo-specific
    MALFORMED_OUTPUT = "malformed_output"  # judge or generator output didn't parse


_ENDPOINT_CLAIM_RE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b\s*[:\s]*/\S*", re.IGNORECASE)

_MISSING_FACT_PREFIX_TO_TAG = {
    "Endpoint:": FailureTag.MISSED_ENDPOINT,
    "Dependency:": FailureTag.MISSED_DEPENDENCY,
    "Framework:": FailureTag.MISSED_FRAMEWORK_OR_LANGUAGE,
    "Language:": FailureTag.MISSED_FRAMEWORK_OR_LANGUAGE,
    "Class/Service:": FailureTag.MISSED_CLASS_OR_SERVICE,
    "Database entity:": FailureTag.MISSED_DATABASE_ENTITY,
}

# A minimum-viable generic-language detector: an overview this short, or one that
# names none of the repo's own actual tech_stack/framework terms, isn't giving a
# reader anything repo-specific to go on -- it could describe nearly any web service.
_MIN_SPECIFIC_WORD_COUNT = 12


class FailureAnalysis(BaseModel):
    repo_name: str
    model: str
    context_variant: str
    tags: list[FailureTag]


def categorize_missing_fact(fact: str) -> Optional[FailureTag]:
    for prefix, tag in _MISSING_FACT_PREFIX_TO_TAG.items():
        if fact.startswith(prefix):
            return tag
    return None


def categorize_unsupported_claim(claim: str) -> FailureTag:
    if _ENDPOINT_CLAIM_RE.search(claim):
        return FailureTag.FABRICATED_ENDPOINT
    return FailureTag.FABRICATED_TECHNOLOGY


def _is_over_generic(overview: str, known_terms: list[str]) -> bool:
    words = overview.split()
    if len(words) < _MIN_SPECIFIC_WORD_COUNT:
        return True
    overview_lower = overview.lower()
    return not any(term.lower() in overview_lower for term in known_terms if term)


def analyze_failures(
    repo_name: str,
    model: str,
    context_variant: str,
    unsupported_claims: list[str],
    missing_facts: list[str],
    generated_overview: str,
    known_terms: list[str],
    hallucination_judged: bool,
    coverage_judged: bool,
) -> FailureAnalysis:
    """`known_terms` should be the repo's actual framework/language/dependency
    names (from ParsedRepository ground truth) -- what OVER_GENERIC checks the
    overview against."""
    tags: list[FailureTag] = []

    if not hallucination_judged or not coverage_judged:
        tags.append(FailureTag.MALFORMED_OUTPUT)

    tags.extend(categorize_unsupported_claim(c) for c in unsupported_claims)

    for fact in missing_facts:
        tag = categorize_missing_fact(fact)
        if tag is not None:
            tags.append(tag)

    if generated_overview.strip() and _is_over_generic(generated_overview, known_terms):
        tags.append(FailureTag.OVER_GENERIC)

    return FailureAnalysis(repo_name=repo_name, model=model, context_variant=context_variant, tags=tags)


def aggregate_failure_frequencies(analyses: list[FailureAnalysis]) -> dict[str, int]:
    """Flat frequency table across every analyzed row -- the thing that actually
    goes in the paper's failure-analysis table."""
    counter: Counter[str] = Counter()
    for analysis in analyses:
        counter.update(tag.value for tag in analysis.tags)
    return dict(sorted(counter.items(), key=lambda kv: -kv[1]))


def aggregate_by_group(
    analyses: list[FailureAnalysis], group_fn
) -> dict[str, dict[str, int]]:
    """Same frequency table, split by an arbitrary grouping key (e.g. `lambda a:
    a.context_variant` or `lambda a: a.model`) -- for "which representation/model
    has the most fabricated-endpoint failures" style breakdowns."""
    groups: dict[str, list[FailureAnalysis]] = {}
    for analysis in analyses:
        groups.setdefault(group_fn(analysis), []).append(analysis)
    return {key: aggregate_failure_frequencies(group) for key, group in sorted(groups.items())}
