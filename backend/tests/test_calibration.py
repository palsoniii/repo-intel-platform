"""
Unit tests for the calibration module -- geometric-mean logprob confidence, Platt
scaling, Brier score / ECE. All offline: BERTScore and the Ollama call are always
injected, never the real model/network.
"""

import math

from app.evaluation.calibration import (
    CalibrationSample,
    build_calibration_sample,
    evaluate_calibration,
    fit_platt_scaling,
    geometric_mean_confidence,
)


def test_geometric_mean_confidence_computes_correctly():
    # exp(mean(logprobs)) -- logprobs of [-0.1, -0.2, -0.3] -> exp(-0.2)
    response = {"logprobs": [{"token": "a", "logprob": -0.1}, {"token": "b", "logprob": -0.2}, {"token": "c", "logprob": -0.3}]}
    conf = geometric_mean_confidence(response)
    assert conf is not None
    assert math.isclose(conf, math.exp(-0.2), rel_tol=1e-6)


def test_geometric_mean_confidence_returns_none_without_logprobs():
    assert geometric_mean_confidence({"response": "some text"}) is None
    assert geometric_mean_confidence({"logprobs": []}) is None


def test_build_calibration_sample_marks_correct_above_threshold():
    def fake_bert_scorer(references, hypotheses):
        return [0.8]

    sample = build_calibration_sample(
        repo_name="sample-repo",
        model="qwen2.5-coder:7b",
        generated_overview="A REST API for tutorials.",
        reference_overview="A REST API for tutorials with Express.",
        response_json={"logprobs": [{"token": "a", "logprob": -0.05}]},
        bert_scorer=fake_bert_scorer,
        correctness_threshold=0.5,
    )
    assert sample.correct is True
    assert sample.bertscore_f1 == 0.8
    assert sample.raw_confidence is not None


def test_build_calibration_sample_marks_incorrect_below_threshold():
    def fake_bert_scorer(references, hypotheses):
        return [0.2]

    sample = build_calibration_sample(
        repo_name="sample-repo",
        model="qwen2.5-coder:7b",
        generated_overview="totally unrelated text",
        reference_overview="A REST API for tutorials with Express.",
        response_json={"logprobs": [{"token": "a", "logprob": -2.0}]},
        bert_scorer=fake_bert_scorer,
        correctness_threshold=0.5,
    )
    assert sample.correct is False


def _sample(conf: float, correct: bool) -> CalibrationSample:
    return CalibrationSample(repo_name="r", model="m", raw_confidence=conf, correct=correct, bertscore_f1=0.5)


def test_platt_scaling_fits_with_enough_mixed_data():
    samples = [_sample(-0.1, True), _sample(-0.2, True), _sample(-2.0, False), _sample(-3.0, False)]
    scaler = fit_platt_scaling(samples)
    assert scaler is not None
    # Higher raw confidence (closer to 0) should calibrate to a higher P(correct)
    assert scaler.calibrate(-0.1) > scaler.calibrate(-3.0)


def test_platt_scaling_returns_none_with_insufficient_data():
    assert fit_platt_scaling([_sample(-0.1, True)]) is None
    assert fit_platt_scaling([_sample(-0.1, True), _sample(-0.2, True)]) is None  # only one class present


def test_evaluate_calibration_returns_none_when_platt_scaling_fails():
    assert evaluate_calibration([_sample(-0.1, True)]) is None


def test_evaluate_calibration_produces_bounded_metrics():
    samples = [
        _sample(-0.1, True), _sample(-0.15, True), _sample(-0.2, True),
        _sample(-2.0, False), _sample(-2.5, False), _sample(-3.0, False),
    ]
    report = evaluate_calibration(samples)
    assert report is not None
    assert report.n_samples == 6
    assert 0.0 <= report.brier_score <= 1.0
    assert 0.0 <= report.expected_calibration_error <= 1.0
    assert report.brier_skill_score > 0  # should beat the base-rate baseline on this well-separated data


def test_evaluate_calibration_skips_samples_missing_confidence_or_label():
    samples = [
        _sample(-0.1, True), _sample(-0.2, True),
        _sample(-2.0, False), _sample(-2.5, False),
        CalibrationSample(repo_name="r", model="m", raw_confidence=None, correct=True),
    ]
    report = evaluate_calibration(samples)
    assert report is not None
    assert report.n_samples == 4  # the None-confidence sample is excluded
