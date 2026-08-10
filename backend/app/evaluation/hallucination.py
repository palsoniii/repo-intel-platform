"""
LLM-as-judge hallucination scorer (Week 4 / Phase 7).

One local model grades another model's summary against the parser's ground-truth
facts: given the structural facts we KNOW are true (from static analysis) plus the
generated summary, the judge flags any specific factual claim in the summary that
the facts don't support. The score is the fraction of claims that are unsupported.

This is deliberately a pragmatic, buildable metric rather than a novel hallucination
detector -- the roadmap calls for validating the judge against a small human-scored
sample before trusting it, since a local model grading another local model is not
automatically reliable.

The ground truth here is the parser output, not human-written truth -- so this
measures "is the summary faithful to what static analysis found", which is exactly
the axis the research question cares about (does structured context reduce
unsupported claims). It does NOT catch a summary that faithfully repeats something
the parser itself got wrong.
"""

from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel

from app.providers.base import BaseLLMProvider
from app.schemas.llm_result import ContextVariant
from app.schemas.parser_schema import ParsedRepository

JUDGE_SYSTEM_PROMPT = (
    "You are a strict fact-checker for software repository summaries. You are given "
    "a set of GROUND-TRUTH FACTS extracted by static analysis, and a SUMMARY written "
    "by another model. Respond only with valid JSON."
)

JUDGE_PROMPT_TEMPLATE = """\
Below are ground-truth facts about a repository (extracted by static analysis, treat \
them as authoritative) followed by a generated summary. Identify every specific, \
checkable factual claim the summary makes about the repository -- named technologies, \
frameworks, dependencies, endpoints, or structural details -- and decide whether each \
is SUPPORTED by the ground-truth facts.

Rules:
- Flag a claim as "unsupported" ONLY if it names a specific technology, library, \
framework, database, external service, or API style that does not appear in the facts \
(or directly contradicts them) -- e.g. naming MongoDB, GraphQL, or Django when the \
facts don't list them.
- Do NOT flag general descriptions of behavior that are consistent with the facts. If \
the facts list endpoints, then "defines routes" / "handles requests" is SUPPORTED. If \
the facts list config files, then "reads configuration" is SUPPORTED. Treat "routes" \
and "endpoints" as the same thing.
- Do NOT flag vague or high-level phrasing (e.g. "this is a web application").
- Judge only against the facts given. Do not use outside knowledge. When unsure, treat \
a claim as supported.

Return a single JSON object with exactly these keys:
- "total_claims": integer, the number of specific checkable claims you identified
- "unsupported_claims": a list of strings, each the text of one unsupported claim (empty list if none)

GROUND-TRUTH FACTS:
{facts}

SUMMARY:
{summary}

Respond with only the JSON object and no other text.
"""


class HallucinationResult(BaseModel):
    repo_name: str
    context_variant: ContextVariant
    judge_model: str
    total_claims: int
    unsupported_claims: list[str]
    hallucination_score: float  # unsupported / total; 0.0 = fully grounded
    judged: bool  # False if the judge's output couldn't be parsed into the expected shape
    judge_raw_output: str


def build_ground_truth(parsed: ParsedRepository, max_items: int = 40) -> str:
    """Format the parser's known facts into a compact, judge-readable reference block.
    Lists are capped (max_items) so a huge repo doesn't blow past the judge's context
    window -- the judge only needs a representative fact set, not every node."""
    meta = parsed.metadata
    counts = parsed.entity_counts()

    def _capped(names: list[str]) -> str:
        shown = names[:max_items]
        suffix = f" (+{len(names) - max_items} more)" if len(names) > max_items else ""
        return (", ".join(shown) if shown else "(none)") + suffix

    dep_names = [d.name for d in parsed.dependencies.external]
    endpoints = [f"{e.method.value} {e.path}" for e in parsed.api_endpoints]
    class_names = [c.name for c in parsed.classes]
    config_paths = [c.path for c in parsed.config_files]
    db_names = [d.name for d in parsed.database_entities]

    lines = [
        f"Detected framework: {meta.detected_framework or 'unknown'}"
        + (f" (version {meta.framework_version})" if meta.framework_version else ""),
        f"Detected language: {meta.detected_language}",
        f"Counts: {counts['modules']} modules, {counts['classes']} classes, "
        f"{counts['functions']} functions, {counts['api_endpoints']} endpoints, "
        f"{counts['database_entities']} database entities",
        f"External dependencies: {_capped(dep_names)}",
        f"API endpoints: {_capped(endpoints)}",
        f"Classes: {_capped(class_names)}",
        f"Config files: {_capped(config_paths)}",
        f"Database entities: {_capped(db_names)}",
    ]
    return "\n".join(lines)


def score_summary(
    provider: BaseLLMProvider,
    parsed: ParsedRepository,
    summary_text: str,
    context_variant: ContextVariant,
    judge_model: Optional[str] = None,
) -> HallucinationResult:
    """Run the judge over one summary and return a structured hallucination score.
    `summary_text` is the summary being graded (raw_text or a JSON string); the judge
    reads it as prose. `judge_model` should generally differ from the model that wrote
    the summary, to avoid a model grading its own output -- the caller chooses."""
    judge_model = judge_model or provider.default_model
    facts = build_ground_truth(parsed)
    user_prompt = JUDGE_PROMPT_TEMPLATE.format(facts=facts, summary=summary_text)

    result = provider.judge(
        system_prompt=JUDGE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        repo_name=parsed.metadata.name,
        context_variant=context_variant,
        model=judge_model,
    )

    parsed_verdict = _parse_verdict(result.output.raw_text)
    if parsed_verdict is None:
        return HallucinationResult(
            repo_name=parsed.metadata.name,
            context_variant=context_variant,
            judge_model=judge_model,
            total_claims=0,
            unsupported_claims=[],
            hallucination_score=0.0,
            judged=False,
            judge_raw_output=result.output.raw_text,
        )

    total_claims, unsupported = parsed_verdict
    score = len(unsupported) / total_claims if total_claims > 0 else 0.0
    return HallucinationResult(
        repo_name=parsed.metadata.name,
        context_variant=context_variant,
        judge_model=judge_model,
        total_claims=total_claims,
        unsupported_claims=unsupported,
        hallucination_score=round(score, 4),
        judged=True,
        judge_raw_output=result.output.raw_text,
    )


def _parse_verdict(raw_text: str) -> Optional[tuple[int, list[str]]]:
    """Returns (total_claims, unsupported_claims) or None if the judge's output
    isn't the expected JSON shape. Local models sometimes wrap JSON in prose or
    code fences, so a bare json.loads isn't enough -- extract the first JSON object."""
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

    total = data.get("total_claims")
    unsupported = data.get("unsupported_claims")
    if not isinstance(total, int) or not isinstance(unsupported, list):
        return None
    # Drop empty/whitespace entries -- local models sometimes emit a stray "" in the
    # list, which would otherwise inflate the score with a non-claim.
    unsupported = [s for c in unsupported if (s := str(c).strip())]
    # A judge can't report more unsupported claims than total claims -- clamp rather
    # than trust an inconsistent verdict, so the score stays in [0, 1].
    total = max(total, len(unsupported))
    return total, unsupported
