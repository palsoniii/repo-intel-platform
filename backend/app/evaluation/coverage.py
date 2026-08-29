"""
Coverage / recall scorer -- the companion metric to hallucination.py (Week 4 follow-up).

Hallucination asks "of the claims the summary made, how many are false" (precision-
like) -- it says nothing about completeness, so a summary that mentions almost
nothing can score a perfect 0.0. Coverage asks the inverse question: "of the facts
the parser actually found, how many did the summary mention" (recall). Neither
metric alone is "quality" -- together they distinguish a summary that's faithful
AND complete from one that's faithful only because it said almost nothing.

Structurally this mirrors hallucination.py (same judge plumbing, same local-model-
quirk-tolerant verdict parsing), with one important difference: hallucination's
"claims" are extracted BY the judge FROM the summary, because we don't know in
advance what a summary will say. Coverage's fact list is built DETERMINISTICALLY
from the parser's ground truth -- we already know what's true before the judge runs.
So only "is this specific fact mentioned in the summary" needs judgment (paraphrase
detection); the denominator (total_facts) is never at the judge's mercy the way
hallucination's claim count is.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from pydantic import BaseModel

from app.providers.base import BaseLLMProvider
from app.schemas.llm_result import ContextVariant, LLMTask
from app.schemas.parser_schema import ParsedRepository

COVERAGE_JUDGE_SYSTEM_PROMPT = (
    "You are checking how completely a software repository summary covers a known "
    "set of facts. You are given a numbered FACT LIST extracted by static analysis, "
    "and a SUMMARY written by another model. Respond only with valid JSON."
)

COVERAGE_PROMPT_TEMPLATE = """\
Below is a numbered list of facts about a repository (extracted by static analysis) \
followed by a generated summary. For each fact, decide whether the summary mentions \
it -- even indirectly or in different words (e.g. "manages the app's tasks" covers \
"Endpoint: GET /tasks" if the summary clearly describes that capability). Naming the \
exact dependency, endpoint, or class counts as covered even if only listed, not \
explained.

Rules:
- A fact counts as covered if the summary states it specifically enough that a \
reader would know it's true of this repo -- not from generic filler ("this is a web \
app") that could describe any repo.
- When genuinely unsure, mark the fact as covered rather than missing -- this metric \
is about what's completely absent, not about penalizing brief phrasing.
- Judge only against the summary text given. Do not use outside knowledge.

FACT LIST:
{facts}

SUMMARY:
{summary}

Return a single JSON object with exactly this key:
- "missing_facts": a list of the exact fact strings (copied verbatim from the FACT \
LIST) that the summary does NOT mention anywhere (empty list if it covers everything).

Respond with only the JSON object and no other text.
"""


class CoverageResult(BaseModel):
    repo_name: str
    context_variant: ContextVariant
    judge_model: str
    total_facts: int
    missing_facts: list[str]
    coverage_score: float  # covered / total; 1.0 = every fact mentioned
    judged: bool  # False if the judge's output couldn't be parsed into the expected shape
    judge_raw_output: str
    # Judge format-compliance telemetry. unmatched_verdict_items counts entries the
    # judge named as missing that could not be resolved to any known fact even after
    # canonicalisation. Before the T1 fix these were dropped SILENTLY and every drop
    # inflated coverage. This count is a reported metric, not just debug output.
    unmatched_verdict_items: int = 0
    unmatched_samples: list[str] = []


def build_coverable_facts(parsed: ParsedRepository, max_items: int = 40) -> list[str]:
    """Deterministic, atomic, checkable facts from the parser's ground truth -- the
    things a genuinely complete summary would mention. Capped per category (max_items)
    the same way hallucination.py's build_ground_truth() is, so a huge repo doesn't
    blow past the judge's context window."""
    meta = parsed.metadata
    facts: list[str] = []

    if meta.detected_framework:
        version = f" {meta.framework_version}" if meta.framework_version else ""
        facts.append(f"Framework: {meta.detected_framework}{version}")
    if meta.detected_language:
        facts.append(f"Language: {meta.detected_language}")

    facts.extend(f"Dependency: {d.name}" for d in parsed.dependencies.external[:max_items])
    facts.extend(
        f"Endpoint: {e.method.value} {e.path}" for e in parsed.api_endpoints[:max_items]
    )
    facts.extend(f"Class/Service: {c.name}" for c in parsed.classes[:max_items])
    facts.extend(f"Database entity: {d.name}" for d in parsed.database_entities[:max_items])

    return facts


def categorize_facts(facts: list[str]) -> dict[str, int]:
    """Buckets a fact list (as returned by build_coverable_facts) by its category
    prefix -- the text before the first ': ', e.g. 'Dependency: express' ->
    'Dependency'. Used to report coverage broken out by fact type (dependencies,
    endpoints, classes, database entities) rather than only as one aggregate
    number, which hides whether structured context's advantage is spread evenly
    or concentrated in a specific category."""
    counts: dict[str, int] = {}
    for fact in facts:
        category = fact.split(":", 1)[0]
        counts[category] = counts.get(category, 0) + 1
    return counts


def score_coverage(
    provider: BaseLLMProvider,
    parsed: ParsedRepository,
    summary_text: str,
    context_variant: ContextVariant,
    judge_model: Optional[str] = None,
) -> CoverageResult:
    """Run the judge over one summary and return how much of the parser's ground
    truth it actually covers. `summary_text` is the summary being graded (raw_text or
    a JSON string); the judge reads it as prose, same as hallucination.score_summary().
    `judge_model` should generally differ from the model that wrote the summary, same
    caveat as the hallucination judge -- the caller chooses."""
    judge_model = judge_model or provider.default_model
    facts = build_coverable_facts(parsed)

    if not facts:
        # Nothing the parser found to check coverage against (e.g. a near-empty repo)
        # -- vacuously "fully covered" rather than an undefined 0/0.
        return CoverageResult(
            repo_name=parsed.metadata.name,
            context_variant=context_variant,
            judge_model=judge_model,
            total_facts=0,
            missing_facts=[],
            coverage_score=1.0,
            judged=True,
            judge_raw_output="(no ground-truth facts to check coverage against)",
        )

    facts_block = "\n".join(f"{i + 1}. {fact}" for i, fact in enumerate(facts))
    user_prompt = COVERAGE_PROMPT_TEMPLATE.format(facts=facts_block, summary=summary_text)

    result = provider.judge(
        system_prompt=COVERAGE_JUDGE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        repo_name=parsed.metadata.name,
        context_variant=context_variant,
        model=judge_model,
        task=LLMTask.COVERAGE_JUDGE,
    )

    verdict = _parse_coverage_verdict(result.output.raw_text, facts)
    if verdict is None:
        # PARSE FAILURE -- the judge's output was not the expected JSON shape.
        # coverage_score is written as 0.0 only because the field is non-optional;
        # it is NOT a measurement. Every analysis MUST filter on `judged` / the
        # persisted `coverage_judged` column before aggregating, or these rows will
        # be read as genuinely uncovered summaries and drag every mean down.
        return CoverageResult(
            repo_name=parsed.metadata.name,
            context_variant=context_variant,
            judge_model=judge_model,
            total_facts=len(facts),
            missing_facts=[],
            coverage_score=0.0,
            judged=False,
            judge_raw_output=result.output.raw_text,
        )

    missing, unmatched = verdict
    score = (len(facts) - len(missing)) / len(facts)
    return CoverageResult(
        repo_name=parsed.metadata.name,
        context_variant=context_variant,
        judge_model=judge_model,
        total_facts=len(facts),
        missing_facts=missing,
        coverage_score=round(score, 4),
        judged=True,
        judge_raw_output=result.output.raw_text,
        unmatched_verdict_items=len(unmatched),
        unmatched_samples=unmatched[:5],
    )


def _canon(s: str) -> str:
    """Canonical form for matching a judge's fact string against the known fact list.

    Aggressive normalisation is safe here because the result is still looked up in an
    index built from the ACTUAL fact list -- the judge can never introduce a fact the
    parser did not find. This closes the formatting hole without re-opening the
    fact-invention hole the original exact-match guard existed to close.
    """
    s = s.strip().strip("`'\" ")
    s = re.sub(r"^\s*\d+[.)]\s*", "", s)        # strip "12. " list numbering
    s = s.lower()
    s = re.sub(r"[^a-z0-9/:@._-]+", " ", s)      # keep code-ish characters
    return re.sub(r"\s+", " ", s).strip()


_INDEX_REF = re.compile(r"^(?:fact|item|no|number|#)?\s*[#.)]?\s*(\d{1,3})\s*[.)]?$")


def _resolve_index(item: str, facts: list[str]) -> Optional[str]:
    """Resolve a bare positional reference ('7', '#7', 'fact 7') to its fact.

    The prompt presents the fact list numbered from 1 (see score_coverage), so a judge
    that answers with positions rather than text is giving a correct, resolvable answer
    in a different notation -- previously it was counted as unmatched and the miss was
    lost. Out-of-range positions stay unmatched rather than being clamped: a number the
    list cannot justify is not evidence of anything.

    A bare integer is unambiguous here because every generated fact carries a category
    prefix ('Endpoint: ...', 'Dependency: ...'), so no real fact is a lone number.
    """
    m = _INDEX_REF.match(item.strip().strip("`'\" ").lower())
    if m is None:
        return None
    n = int(m.group(1))
    return facts[n - 1] if 1 <= n <= len(facts) else None


def _build_fact_index(facts: list[str]) -> dict[str, str]:
    """Two keys per fact -> the canonical fact string.

    1. the whole fact:                        'endpoint: get /tasks'
    2. the value after the category prefix:   'get /tasks'

    Key 2 catches the dominant failure mode: judges that answer with the identifier
    but drop the 'Endpoint: ' category prefix.
    """
    idx: dict[str, str] = {}
    for f in facts:
        idx.setdefault(_canon(f), f)
        if ":" in f:
            idx.setdefault(_canon(f.split(":", 1)[1]), f)
    return idx


def _parse_coverage_verdict(
    raw_text: str, facts: list[str]
) -> Optional[tuple[list[str], list[str]]]:
    """Returns the list of missing facts, or None if the judge's output isn't the
    expected JSON shape. Local models sometimes wrap JSON in prose or code fences, so
    a bare json.loads isn't enough -- extract the first JSON object, same approach as
    hallucination.py's verdict parsing."""
    text = raw_text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    missing = data.get("missing_facts")
    if not isinstance(missing, list):
        return None

    # Resolve each entry to a known fact via canonicalisation, deduplicated. The
    # membership check is DELIBERATELY RETAINED: we only ever return strings that are
    # already in `facts`, so the judge still cannot invent a fact. What changed is that
    # a non-verbatim rendering of a REAL fact ("GET /tasks" for "Endpoint: GET /tasks")
    # now resolves instead of being silently dropped -- and anything that still fails to
    # resolve is COUNTED and returned rather than discarded in silence.
    idx = _build_fact_index(facts)
    seen: list[str] = []
    unmatched: list[str] = []
    for item in missing:
        fact = idx.get(_canon(str(item))) or _resolve_index(str(item), facts)
        if fact is None:
            unmatched.append(str(item)[:120])
        elif fact not in seen:
            seen.append(fact)
    return seen, unmatched
