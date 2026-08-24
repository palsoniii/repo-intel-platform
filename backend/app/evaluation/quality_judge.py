"""
G-Eval rubric scorer (Week 4+ / IEEE-paper eval expansion).

Implements the G-Eval protocol (Liu et al., 2023 -- "G-Eval: NLG Evaluation using
GPT-4 with Better Human Alignment"), the same methodology arXiv:2501.07857 (the
closest paper in this project's lit review) uses to score repository summaries.
G-Eval is NOT "ask an LLM for a 1-5 number" -- it's a specific, human-validated
protocol with two things that make it meaningfully more rigorous than that:

1. Each criterion has explicit, detailed evaluation steps the judge is walked
   through (chain-of-thought), not just a one-line definition.
2. The reported score is a probability-weighted average over the *logprobs* of
   the candidate score tokens (Score = sum(P(s=i) * i) for i in 1..5), not the
   single digit the model happened to sample -- this smooths out sampling noise
   and produces a continuous, more discriminating score than a bare integer.

G-Eval's original protocol *generates* the evaluation steps via an LLM call from
just a criterion definition. This module hand-authors them instead (once, fixed,
version-controlled) rather than regenerating them per run: this project's own
methodology requires "a fixed rubric and a fixed judge model/prompt across all
comparisons" (so scoring is reproducible across the whole battery) -- an
LLM-regenerated rubric would itself be a source of non-determinism between runs,
which is exactly what a fixed rubric is meant to rule out. This is a deliberate
scope decision, documented so it can be justified in the paper's methodology
section, not an oversight.

Criteria (summaries): Completeness, Conciseness, Correctness, Cohesiveness, Domain
Specificity -- the exact five arXiv:2501.07857 uses with BLEU/ROUGE/BERTScore.

Criteria (diagrams): Value, Comprehensibility -- mirroring CIAO's (arXiv:2604.08293)
RQ1/RQ2 Likert item wording. CIAO's third dimension, RQ3 "accuracy," is deliberately
NOT re-judged subjectively here: this project already has an OBJECTIVE analog --
`diagram_score.py`'s precision/recall/F1 of extracted modules/imports/endpoints
against hand-verified annotations -- which checks accuracy against real ground
truth instead of asking a judge to guess whether a diagram matches the source it
was generated from.

Logprob access requires Ollama's native `/api/generate` endpoint (`logprobs`/
`top_logprobs`), which the `ollama` Python package's `.chat()` wrapper used by
`BaseLLMProvider` does not expose (see `ollama-python` issue #517). This module
therefore talks to Ollama directly over HTTP rather than through
`BaseLLMProvider.judge()`, and gracefully degrades to sample-averaging (score k
generations, average the parsed integers) if a given model/Ollama version doesn't
return logprobs -- still far more rigorous than a single unweighted sample, and
the degradation is recorded on every result (`method` field) so it's auditable
which rows used which scoring path.
"""

from __future__ import annotations

import json
import math
import os
import re
from typing import Callable, Literal, Optional

import httpx
from pydantic import BaseModel

from app.schemas.llm_result import ContextVariant

DEFAULT_HOST = "http://localhost:11434"
SCORE_RANGE = (1, 5)

# -- Fixed rubric: hand-authored G-Eval-style chain-of-thought steps -----------

GEVAL_CRITERIA_SUMMARY: dict[str, dict[str, object]] = {
    "completeness": {
        "definition": "Does the summary cover all the significant aspects of the repository present in the context (framework, purpose, main entry points, key dependencies)?",
        "steps": [
            "List every distinct fact category present in the context: framework/language, purpose/domain, main services or entry points, and significant dependencies.",
            "For each category, check whether the summary mentions it specifically enough that a reader would learn that fact -- not from generic filler that could describe any repo.",
            "Count how many of the categories present in the context are actually covered by the summary.",
            "A summary covering all categories present is a 5; a summary missing most of them is a 1.",
        ],
    },
    "conciseness": {
        "definition": "Is the summary free of redundant, repetitive, or padded content relative to the information it conveys?",
        "steps": [
            "Identify any sentence or clause that repeats a fact already stated elsewhere in the summary.",
            "Identify any sentence that is pure filler (generic praise, restating the prompt, hedging) rather than information about the repository.",
            "A summary with no redundancy or filler is a 5; a summary that is mostly repetition or filler is a 1.",
        ],
    },
    "correctness": {
        "definition": "Are the claims the summary makes about the repository consistent with the context, without hallucinated technologies, dependencies, or capabilities?",
        "steps": [
            "List every specific, checkable claim the summary makes (named technologies, frameworks, dependencies, endpoints, capabilities).",
            "For each claim, check whether it is supported by the context or contradicts it.",
            "A summary where every claim is supported is a 5; a summary with multiple fabricated or contradicted claims is a 1.",
        ],
    },
    "cohesiveness": {
        "definition": "Does the summary read as a well-organized, logically flowing description rather than a disconnected list of facts?",
        "steps": [
            "Check whether sentences connect logically (cause/effect, general-to-specific) rather than being an arbitrary sequence of unrelated statements.",
            "Check whether terminology is used consistently throughout (the same component isn't referred to by different names in different sentences).",
            "A summary that reads as a coherent short description is a 5; a summary that reads as disconnected fragments is a 1.",
        ],
    },
    "domain_specificity": {
        "definition": "Does the summary use terms and concepts specific to this repository's actual domain and stack, rather than generic descriptions that could apply to any web service?",
        "steps": [
            "Check whether the summary names the actual framework, language, and notable libraries from the context, rather than saying only \"a web application\" or \"a backend service.\"",
            "Check whether the summary reflects the repository's specific purpose (e.g. \"a REST API for managing tutorials\") rather than a generic capability description.",
            "A summary full of repo-specific, checkable detail is a 5; a summary that is entirely generic boilerplate language is a 1.",
        ],
    },
}

GEVAL_CRITERIA_DIAGRAM: dict[str, dict[str, object]] = {
    "value": {
        "definition": "Would a developer find this architecture diagram valuable for understanding and maintaining the system's structure and dependencies? (mirrors CIAO Q1/Q2/Q3)",
        "steps": [
            "Check whether the diagram provides architectural insight beyond what's visible from a directory listing alone (module relationships, endpoint ownership).",
            "Check whether the diagram would help a developer locate which module to modify for a given change.",
            "A diagram a developer would genuinely want to keep as reference documentation is a 5; a diagram providing no more insight than a file tree is a 1.",
        ],
    },
    "comprehensibility": {
        "definition": "Is the diagram clear, well-structured, and easy to follow, using appropriate terminology and without excessive clutter? (mirrors CIAO Q5/Q6/Q7/Q8)",
        "steps": [
            "Check whether node and edge labels are clear and use standard architecture/framework terminology.",
            "Check whether the diagram is readable at a glance or requires significant effort to trace relationships.",
            "Check for excessive redundancy (duplicated nodes/edges, unnecessary clutter) that would make the diagram harder to follow.",
            "A clear, well-organized, appropriately-detailed diagram is a 5; a cluttered or confusing one is a 1.",
        ],
    },
}

JUDGE_SYSTEM_PROMPT = (
    "You are an expert software engineering reviewer scoring one dimension of a "
    "generated artifact. Follow the evaluation steps exactly, then respond with your "
    "reasoning followed by a final line in the exact form 'Score: X' where X is an "
    "integer from 1 to 5."
)

GEVAL_PROMPT_TEMPLATE = """\
You are evaluating a generated {target_kind} for the criterion "{criterion_name}".

Criterion definition: {definition}

Evaluation steps:
{steps}

{target_kind_label}:
{target_text}

{reference_label}
{reference_text}

Follow the evaluation steps above, then respond with brief reasoning (2-3 sentences) \
followed by a final line in the exact form:
Score: X

where X is a single integer from 1 (worst) to 5 (best).
"""


class GEvalScore(BaseModel):
    criterion: str
    score: float  # continuous if logprob-weighted, else the plain integer sampled
    method: Literal["logprob_weighted", "sample_averaged", "unparsed"]
    raw_response: str


class QualityJudgeResult(BaseModel):
    repo_name: str
    context_variant: ContextVariant
    judge_model: str
    target: Literal["summary", "diagram"]
    scores: dict[str, GEvalScore]
    mean_score: Optional[float]  # None if every criterion failed to parse


# -- Ollama HTTP call (bypasses BaseLLMProvider -- see module docstring) -------

GenerateFn = Callable[[str, str, str], dict]  # (host, model, prompt) -> raw /api/generate JSON


def _default_generate(host: str, model: str, prompt: str, top_logprobs: int = 15) -> dict:
    """Real call to Ollama's native /api/generate with logprobs requested. Injectable
    via `generate_fn` on the scoring functions below so tests never need a live
    Ollama daemon."""
    resp = httpx.post(
        f"{host}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "logprobs": True,
            "top_logprobs": top_logprobs,
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.json()


_SCORE_LINE_RE = re.compile(r"Score:\s*([1-5])", re.IGNORECASE)


def _extract_score_digit(text: str) -> Optional[int]:
    match = _SCORE_LINE_RE.search(text)
    return int(match.group(1)) if match else None


def _logprob_weighted_score(response_json: dict) -> Optional[float]:
    """Best-effort extraction of a probability-weighted score from Ollama's logprobs
    response shape (a `logprobs` list of {token, logprob, top_logprobs: [...]}).
    Returns None (not an exception) on any shape mismatch -- callers fall back to
    sample-averaging, since the exact response shape can't be verified without a
    live Ollama daemon and different versions may format this differently."""
    logprobs = response_json.get("logprobs")
    if not isinstance(logprobs, list) or not logprobs:
        return None

    for entry in logprobs:
        token = str(entry.get("token", "")).strip()
        if token not in {"1", "2", "3", "4", "5"}:
            continue
        candidates = entry.get("top_logprobs") or []
        digit_logprobs: dict[int, float] = {}
        for cand in candidates:
            cand_token = str(cand.get("token", "")).strip()
            if cand_token in {"1", "2", "3", "4", "5"} and "logprob" in cand:
                digit_logprobs[int(cand_token)] = float(cand["logprob"])
        # Make sure the sampled token itself is represented even if the model's own
        # top_logprobs list happened to omit it.
        digit_logprobs.setdefault(int(token), float(entry.get("logprob", 0.0)))
        if not digit_logprobs:
            return None

        # Renormalize over just the digit tokens seen (softmax over their logprobs).
        max_lp = max(digit_logprobs.values())
        weights = {d: math.exp(lp - max_lp) for d, lp in digit_logprobs.items()}
        total = sum(weights.values())
        return sum(d * (w / total) for d, w in weights.items())
    return None


def _score_one_criterion(
    host: str,
    model: str,
    criterion: str,
    definition: str,
    steps: list[str],
    target_kind: str,
    target_kind_label: str,
    target_text: str,
    reference_label: str,
    reference_text: str,
    generate_fn: GenerateFn,
    sample_count: int,
) -> GEvalScore:
    steps_block = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(steps))
    prompt = (
        JUDGE_SYSTEM_PROMPT
        + "\n\n"
        + GEVAL_PROMPT_TEMPLATE.format(
            target_kind=target_kind,
            criterion_name=criterion.replace("_", " "),
            definition=definition,
            steps=steps_block,
            target_kind_label=target_kind_label,
            target_text=target_text,
            reference_label=reference_label,
            reference_text=reference_text,
        )
    )

    response_json = generate_fn(host, model, prompt)
    raw_text = response_json.get("response", "")
    weighted = _logprob_weighted_score(response_json)
    if weighted is not None:
        return GEvalScore(criterion=criterion, score=round(weighted, 4), method="logprob_weighted", raw_response=raw_text)

    # Fallback: logprobs unavailable for this model/Ollama version -- sample
    # `sample_count` times and average the parsed integer scores instead of trusting
    # a single unweighted sample.
    digits = [_extract_score_digit(raw_text)]
    for _ in range(sample_count - 1):
        extra = generate_fn(host, model, prompt)
        digits.append(_extract_score_digit(extra.get("response", "")))
    parsed = [d for d in digits if d is not None]
    if not parsed:
        return GEvalScore(criterion=criterion, score=0.0, method="unparsed", raw_response=raw_text)
    return GEvalScore(
        criterion=criterion,
        score=round(sum(parsed) / len(parsed), 4),
        method="sample_averaged",
        raw_response=raw_text,
    )


def _mean_score(scores: dict[str, GEvalScore]) -> Optional[float]:
    valid = [s.score for s in scores.values() if s.method != "unparsed"]
    return round(sum(valid) / len(valid), 4) if valid else None


def score_summary_quality(
    repo_name: str,
    context_variant: ContextVariant,
    summary_text: str,
    judge_model: str,
    host: Optional[str] = None,
    generate_fn: Optional[GenerateFn] = None,
    sample_count: int = 3,
) -> QualityJudgeResult:
    """G-Eval-scores a generated summary on the five arXiv:2501.07857 criteria."""
    host = host or os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
    generate_fn = generate_fn or _default_generate

    scores = {
        name: _score_one_criterion(
            host=host,
            model=judge_model,
            criterion=name,
            definition=str(spec["definition"]),
            steps=list(spec["steps"]),  # type: ignore[arg-type]
            target_kind="repository summary",
            target_kind_label="GENERATED SUMMARY",
            target_text=summary_text,
            reference_label="",
            reference_text="",
            generate_fn=generate_fn,
            sample_count=sample_count,
        )
        for name, spec in GEVAL_CRITERIA_SUMMARY.items()
    }
    return QualityJudgeResult(
        repo_name=repo_name,
        context_variant=context_variant,
        judge_model=judge_model,
        target="summary",
        scores=scores,
        mean_score=_mean_score(scores),
    )


def score_diagram_quality(
    repo_name: str,
    context_variant: ContextVariant,
    diagram_text: str,
    judge_model: str,
    host: Optional[str] = None,
    generate_fn: Optional[GenerateFn] = None,
    sample_count: int = 3,
) -> QualityJudgeResult:
    """G-Eval-scores a generated Mermaid diagram on value/comprehensibility (CIAO
    RQ1/RQ2 analogs). Accuracy is deliberately NOT scored here -- see module
    docstring; use diagram_score.py's objective F1 against annotations for that."""
    host = host or os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
    generate_fn = generate_fn or _default_generate

    scores = {
        name: _score_one_criterion(
            host=host,
            model=judge_model,
            criterion=name,
            definition=str(spec["definition"]),
            steps=list(spec["steps"]),  # type: ignore[arg-type]
            target_kind="architecture diagram",
            target_kind_label="GENERATED MERMAID DIAGRAM",
            target_text=diagram_text,
            reference_label="",
            reference_text="",
            generate_fn=generate_fn,
            sample_count=sample_count,
        )
        for name, spec in GEVAL_CRITERIA_DIAGRAM.items()
    }
    return QualityJudgeResult(
        repo_name=repo_name,
        context_variant=context_variant,
        judge_model=judge_model,
        target="diagram",
        scores=scores,
        mean_score=_mean_score(scores),
    )
