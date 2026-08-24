"""
Text-overlap metrics (BLEU-4, ROUGE-L, METEOR, BERTScore) against a reference
summary's `overview` text -- see reference_summaries/README.md for why only
`overview` is scored this way. `dependencies`/`tech_stack` are unordered fact
lists; scoring those by n-gram overlap would be redundant with (and worse than)
coverage.py's fact-grounded judge scoring, so text-overlap is scoped to the prose
field where fluency/content-overlap is actually the thing being measured.

Standard in the repo-level code-summarization literature this project's paper cites
(arXiv:2502.16704 reports BLEU-4/ROUGE-L/METEOR/BERTScore/BLEURT/SIDE at class and
repo level). BLEURT and SIDE are deliberately out of scope here: BLEURT needs a
TensorFlow checkpoint that's awkward to maintain locally, and SIDE needs the paper's
own released contrastive-learning checkpoint -- neither is reproducible from a pip
install the way BLEU/ROUGE/METEOR/BERTScore are. This is a disclosed scope decision,
not a silent omission -- flag it in the paper's limitations section.
"""

from __future__ import annotations

import json
from typing import Callable, Optional

from pydantic import BaseModel

from app.schemas.llm_result import ContextVariant

# BERTScore's default model (roberta-large) is a large download and slow on a laptop.
# distilbert-base-uncased trades a little correlation-with-human-judgment accuracy
# (still strong per the BERTScore paper's own ablations) for being practical to run
# across a full 18-repo x 3-model x 3-representation battery locally.
DEFAULT_BERTSCORE_MODEL = "distilbert-base-uncased"

BertScorer = Callable[[list[str], list[str]], list[float]]


class TextOverlapResult(BaseModel):
    repo_name: str
    context_variant: ContextVariant
    bleu4: float
    rouge_l: float
    meteor: float
    bertscore_f1: Optional[float] = None  # None if scoring was skipped (no scorer given)
    reference_overview: str
    generated_overview: str
    extracted: bool  # False if `overview` couldn't be pulled from the generated summary


def extract_overview(summary_text: str) -> tuple[str, bool]:
    """Pulls the `overview` field out of a generated summary. `summary_text` is
    raw_text from an LLMResult -- local models sometimes wrap JSON in prose or code
    fences, so this extracts the first JSON object rather than assuming a bare
    json.loads works (same tolerant-parsing approach as hallucination.py/coverage.py).
    Falls back to the raw text itself (extracted=False) so a malformed summary still
    gets *some* text-overlap score instead of being silently skipped."""
    text = summary_text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            overview = data.get("overview")
            if isinstance(overview, str) and overview.strip():
                return overview.strip(), True
        except json.JSONDecodeError:
            pass
    return text, False


def _bleu4(reference: str, hypothesis: str) -> float:
    from nltk.translate.bleu_score import SmoothingFunction, sentence_bleu

    ref_tokens = reference.split()
    hyp_tokens = hypothesis.split()
    if not ref_tokens or not hyp_tokens:
        return 0.0
    # method4 smoothing: these are single-paragraph overviews (a handful of
    # sentences), short enough that unsmoothed BLEU-4 is 0 whenever any 4-gram
    # fails to match at all, which is nearly always at this length -- smoothing is
    # standard practice for sentence/paragraph-level (as opposed to corpus-level) BLEU.
    smoothing = SmoothingFunction().method4
    return sentence_bleu([ref_tokens], hyp_tokens, weights=(0.25, 0.25, 0.25, 0.25), smoothing_function=smoothing)


def _rouge_l(reference: str, hypothesis: str) -> float:
    from rouge_score import rouge_scorer

    scorer = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=True)
    return scorer.score(reference, hypothesis)["rougeL"].fmeasure


def _meteor(reference: str, hypothesis: str) -> float:
    from nltk.translate.meteor_score import meteor_score

    ref_tokens = reference.split()
    hyp_tokens = hypothesis.split()
    if not ref_tokens or not hyp_tokens:
        return 0.0
    return meteor_score([ref_tokens], hyp_tokens)


def default_bert_scorer(references: list[str], hypotheses: list[str]) -> list[float]:
    """Lazy-imported default BERTScore backend -- only touched when a caller doesn't
    inject their own `bert_scorer`, so importing this module (or running the offline
    unit tests) never requires the `bert-score` package or a model download."""
    from bert_score import score as bert_score_fn

    _, _, f1 = bert_score_fn(hypotheses, references, model_type=DEFAULT_BERTSCORE_MODEL, verbose=False)
    return [float(x) for x in f1]


def score_text_overlap(
    repo_name: str,
    context_variant: ContextVariant,
    summary_text: str,
    reference_overview: str,
    bert_scorer: Optional[BertScorer] = None,
) -> TextOverlapResult:
    """Scores one generated summary's `overview` field against the reference
    overview. `bert_scorer` is injectable (batch: list[str], list[str] -> list[float])
    so tests can mock it and callers can batch BERTScore calls across many rows
    instead of loading the model once per row -- pass None to skip BERTScore
    entirely (bertscore_f1 stays None) rather than paying the import/model cost."""
    generated_overview, extracted = extract_overview(summary_text)

    bertscore_f1 = None
    if bert_scorer is not None:
        [bertscore_f1] = bert_scorer([reference_overview], [generated_overview])

    return TextOverlapResult(
        repo_name=repo_name,
        context_variant=context_variant,
        bleu4=round(_bleu4(reference_overview, generated_overview), 4),
        rouge_l=round(_rouge_l(reference_overview, generated_overview), 4),
        meteor=round(_meteor(reference_overview, generated_overview), 4),
        bertscore_f1=round(bertscore_f1, 4) if bertscore_f1 is not None else None,
        reference_overview=reference_overview,
        generated_overview=generated_overview,
        extracted=extracted,
    )
