"""
Unit tests for the G-Eval quality judge, run against an injected `generate_fn` so
they never touch a live Ollama daemon -- same offline-by-default convention as the
rest of the evaluation test suite. Covers the three scoring paths: logprob-weighted,
sample-averaged fallback, and the unparsed degenerate case.
"""

from app.evaluation.quality_judge import (
    GEVAL_CRITERIA_DIAGRAM,
    GEVAL_CRITERIA_SUMMARY,
    score_diagram_quality,
    score_summary_quality,
)
from app.schemas.llm_result import ContextVariant


def _logprob_response(score_text: str, sampled_digit: str, digit_probs: dict[str, float]) -> dict:
    """Builds a fake /api/generate response with a logprobs entry for the sampled
    digit token, carrying alternative digit probabilities in top_logprobs."""
    import math

    top_logprobs = [{"token": d, "logprob": math.log(p)} for d, p in digit_probs.items()]
    return {
        "response": score_text,
        "logprobs": [
            {"token": "S", "logprob": -0.1, "top_logprobs": []},
            {"token": sampled_digit, "logprob": math.log(digit_probs[sampled_digit]), "top_logprobs": top_logprobs},
        ],
    }


def test_logprob_weighted_scoring_produces_continuous_score():
    calls = []

    def fake_generate(host, model, prompt):
        calls.append((host, model))
        return _logprob_response(
            "Reasoning here.\nScore: 4",
            sampled_digit="4",
            digit_probs={"3": 0.1, "4": 0.7, "5": 0.2},
        )

    result = score_summary_quality(
        repo_name="sample-repo",
        context_variant=ContextVariant.KNOWLEDGE_GRAPH,
        summary_text='{"overview": "test"}',
        judge_model="qwen2.5-coder:7b",
        host="http://fake-host:11434",
        generate_fn=fake_generate,
    )

    assert set(result.scores.keys()) == set(GEVAL_CRITERIA_SUMMARY.keys())
    for score in result.scores.values():
        assert score.method == "logprob_weighted"
        # weighted average of {3:0.1, 4:0.7, 5:0.2} = 3.1+2.8+1.0... compute directly
        assert 3.9 < score.score < 4.2
    assert result.mean_score is not None
    # One generate_fn call per criterion (5 for summaries), not per-criterion x sample_count
    assert len(calls) == len(GEVAL_CRITERIA_SUMMARY)


def test_falls_back_to_sample_averaging_when_no_logprobs():
    responses = iter(["Score: 3", "Score: 4", "Score: 4"] * len(GEVAL_CRITERIA_SUMMARY))

    def fake_generate(host, model, prompt):
        return {"response": next(responses)}  # no "logprobs" key at all

    result = score_summary_quality(
        repo_name="sample-repo",
        context_variant=ContextVariant.RAW,
        summary_text='{"overview": "test"}',
        judge_model="granite-code:3b-instruct",
        generate_fn=fake_generate,
        sample_count=3,
    )

    for score in result.scores.values():
        assert score.method == "sample_averaged"
        assert score.score == round((3 + 4 + 4) / 3, 4)


def test_unparsed_response_does_not_crash_and_is_excluded_from_mean():
    def fake_generate(host, model, prompt):
        return {"response": "I refuse to follow the format."}

    result = score_summary_quality(
        repo_name="sample-repo",
        context_variant=ContextVariant.DEPENDENCY_GRAPH,
        summary_text='{"overview": "test"}',
        judge_model="deepseek-coder:6.7b-instruct",
        generate_fn=fake_generate,
        sample_count=2,
    )

    for score in result.scores.values():
        assert score.method == "unparsed"
        assert score.score == 0.0
    assert result.mean_score is None  # every criterion failed to parse


def test_diagram_quality_uses_diagram_criteria_not_summary_criteria():
    def fake_generate(host, model, prompt):
        return _logprob_response("Score: 5", sampled_digit="5", digit_probs={"5": 0.9, "4": 0.1})

    result = score_diagram_quality(
        repo_name="sample-repo",
        context_variant=ContextVariant.KNOWLEDGE_GRAPH,
        diagram_text="flowchart TD\n  mod_0 --> mod_1",
        judge_model="qwen2.5-coder:7b",
        generate_fn=fake_generate,
    )

    assert set(result.scores.keys()) == set(GEVAL_CRITERIA_DIAGRAM.keys())
    assert "accuracy" not in result.scores  # accuracy is diagram_score.py's job, not a judge dimension
    assert result.target == "diagram"


def test_partial_parse_failures_are_excluded_from_mean_but_others_still_count():
    call_count = {"n": 0}

    def fake_generate(host, model, prompt):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {"response": "no score given"}  # first criterion unparseable
        return _logprob_response("Score: 5", sampled_digit="5", digit_probs={"5": 1.0})

    result = score_summary_quality(
        repo_name="sample-repo",
        context_variant=ContextVariant.RAW,
        summary_text='{"overview": "test"}',
        judge_model="qwen2.5-coder:7b",
        generate_fn=fake_generate,
        sample_count=1,  # no fallback retries -- the first criterion's single unparseable sample must stick
    )

    methods = [s.method for s in result.scores.values()]
    assert "unparsed" in methods
    assert result.mean_score is not None
    assert result.mean_score > 4.9  # only the valid (score=5) criteria are averaged
