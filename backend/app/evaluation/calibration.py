"""
Calibration / confidence scorer (IEEE-paper eval expansion, Step 1.3).

Implements the method arXiv:2404.19318 (Calibration of LLMs on Code Summarization)
actually uses: a reference-free confidence signal computed as the *geometric mean*
of a generation's own output-token log-probabilities (the paper's own justification:
"the product, not the sum, of individual probabilities better represents the
probability of a sequence"), then validated by checking whether that raw confidence
predicts actual quality -- via Platt scaling (logistic regression mapping raw
confidence to P(correct)) and two calibration metrics: Brier score and Expected
Calibration Error (ECE). "Correctness" is defined the same way the paper defines
it: a generated summary's `overview` is "correct" if its BERTScore similarity to
the reference summary clears a threshold.

Scope: this needs a *second* generation call per (repo, model, representation) with
logprobs requested -- it is not free, which is why the user scoped this to a
representative subset of repos rather than the full battery (see harness.py's
`--calibration-repos` flag). It reuses the same raw-HTTP-to-Ollama pattern as
quality_judge.py, for the same reason (BaseLLMProvider.judge()/.generate_summary()
go through the `ollama` package's `.chat()`, which doesn't expose logprobs).
"""

from __future__ import annotations

import math
import os
from typing import Callable, Optional

import httpx
from pydantic import BaseModel

DEFAULT_HOST = "http://localhost:11434"

GenerateFn = Callable[[str, str, str], dict]  # (host, model, prompt) -> raw /api/generate JSON
BertScorer = Callable[[list[str], list[str]], list[float]]


def _default_generate(host: str, model: str, prompt: str) -> dict:
    resp = httpx.post(
        f"{host}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False, "logprobs": True},
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.json()


def geometric_mean_confidence(response_json: dict) -> Optional[float]:
    """exp(mean(logprob)) over every output token -- the geometric mean of the
    per-token probabilities. Returns None (not an exception) if this Ollama
    version/model didn't return logprobs, so callers can skip the sample rather
    than crash -- the exact response shape can't be verified without a live daemon."""
    logprobs = response_json.get("logprobs")
    if not isinstance(logprobs, list) or not logprobs:
        return None
    values = [entry.get("logprob") for entry in logprobs if isinstance(entry.get("logprob"), (int, float))]
    if not values:
        return None
    return math.exp(sum(values) / len(values))


class CalibrationSample(BaseModel):
    repo_name: str
    model: str
    raw_confidence: Optional[float]  # None if logprobs unavailable for this sample
    correct: Optional[bool]  # None if BERTScore couldn't be computed
    bertscore_f1: Optional[float] = None


def build_calibration_sample(
    repo_name: str,
    model: str,
    generated_overview: str,
    reference_overview: str,
    response_json: dict,
    bert_scorer: BertScorer,
    correctness_threshold: float = 0.5,
) -> CalibrationSample:
    confidence = geometric_mean_confidence(response_json)
    [f1] = bert_scorer([reference_overview], [generated_overview])
    return CalibrationSample(
        repo_name=repo_name,
        model=model,
        raw_confidence=confidence,
        correct=f1 >= correctness_threshold,
        bertscore_f1=round(f1, 4),
    )


def generate_with_confidence(
    repo_name: str,
    model: str,
    prompt: str,
    reference_overview: str,
    extract_overview_fn: Callable[[str], str],
    bert_scorer: BertScorer,
    host: Optional[str] = None,
    generate_fn: Optional[GenerateFn] = None,
    correctness_threshold: float = 0.5,
) -> CalibrationSample:
    """Runs one generation with logprobs requested and builds a calibration sample
    from it. `extract_overview_fn` pulls the comparable prose text out of the raw
    generation (pass `text_overlap.extract_overview` in production)."""
    host = host or os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
    generate_fn = generate_fn or _default_generate
    response_json = generate_fn(host, model, prompt)
    generated_overview = extract_overview_fn(response_json.get("response", ""))
    return build_calibration_sample(
        repo_name=repo_name,
        model=model,
        generated_overview=generated_overview,
        reference_overview=reference_overview,
        response_json=response_json,
        bert_scorer=bert_scorer,
        correctness_threshold=correctness_threshold,
    )


# -- Platt scaling + calibration metrics ---------------------------------------


class PlattScaler(BaseModel):
    a: float
    b: float

    def calibrate(self, raw_confidence: float) -> float:
        """P(correct) = 1 / (1 + exp(a * raw_confidence + b))."""
        return 1.0 / (1.0 + math.exp(self.a * raw_confidence + self.b))


def fit_platt_scaling(samples: list[CalibrationSample]) -> Optional[PlattScaler]:
    """Fits (a, b) by maximum likelihood (minimizing log loss) via scipy. Needs at
    least a few samples with both a raw_confidence and a correctness label, and at
    least one example of each class -- otherwise the fit is degenerate and this
    returns None rather than a meaningless scaler."""
    from scipy.optimize import minimize

    usable = [s for s in samples if s.raw_confidence is not None and s.correct is not None]
    if len(usable) < 4 or len({s.correct for s in usable}) < 2:
        return None

    x = [s.raw_confidence for s in usable]
    y = [1.0 if s.correct else 0.0 for s in usable]

    def neg_log_likelihood(params: list[float]) -> float:
        a, b = params
        eps = 1e-12
        total = 0.0
        for xi, yi in zip(x, y):
            p = 1.0 / (1.0 + math.exp(max(min(a * xi + b, 500), -500)))
            p = min(max(p, eps), 1 - eps)
            total -= yi * math.log(p) + (1 - yi) * math.log(1 - p)
        return total

    result = minimize(neg_log_likelihood, x0=[0.0, 0.0], method="Nelder-Mead")
    a, b = result.x
    return PlattScaler(a=float(a), b=float(b))


class CalibrationReport(BaseModel):
    n_samples: int
    brier_score: float
    brier_skill_score: float
    expected_calibration_error: float
    scaler: Optional[PlattScaler]


def evaluate_calibration(samples: list[CalibrationSample], n_bins: int = 5) -> Optional[CalibrationReport]:
    """Brier score, Brier Skill Score (vs. the always-predict-the-base-rate
    baseline), and Expected Calibration Error, after Platt-scaling raw confidence
    into a calibrated P(correct). Returns None if there isn't enough usable data
    (matches fit_platt_scaling's own minimum)."""
    scaler = fit_platt_scaling(samples)
    if scaler is None:
        return None

    usable = [s for s in samples if s.raw_confidence is not None and s.correct is not None]
    calibrated = [scaler.calibrate(s.raw_confidence) for s in usable]
    labels = [1.0 if s.correct else 0.0 for s in usable]
    n = len(usable)

    brier = sum((p - y) ** 2 for p, y in zip(calibrated, labels)) / n
    base_rate = sum(labels) / n
    brier_baseline = sum((base_rate - y) ** 2 for y in labels) / n
    brier_skill = 1 - (brier / brier_baseline) if brier_baseline > 0 else 0.0

    # Expected Calibration Error: bin by predicted probability, compare each bin's
    # mean predicted confidence to its actual accuracy, weight by bin size.
    bins: list[list[tuple[float, float]]] = [[] for _ in range(n_bins)]
    for p, y in zip(calibrated, labels):
        idx = min(int(p * n_bins), n_bins - 1)
        bins[idx].append((p, y))
    ece = 0.0
    for bucket in bins:
        if not bucket:
            continue
        avg_conf = sum(p for p, _ in bucket) / len(bucket)
        avg_acc = sum(y for _, y in bucket) / len(bucket)
        ece += (len(bucket) / n) * abs(avg_conf - avg_acc)

    return CalibrationReport(
        n_samples=n,
        brier_score=round(brier, 4),
        brier_skill_score=round(brier_skill, 4),
        expected_calibration_error=round(ece, 4),
        scaler=scaler,
    )
