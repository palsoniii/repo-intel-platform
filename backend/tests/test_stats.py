"""
Unit tests for the statistics module: mean/CI aggregation and paired significance
testing. Pure computation, no mocks needed.
"""

from app.evaluation.stats import compare_all_levels_within, paired_test, summarize_by_cell


def _rows():
    # 3 repos x 2 models x 2 representations, knowledge_graph consistently better
    # (lower hallucination_score) than raw for both models.
    rows = []
    reprs = {"raw": [0.6, 0.5, 0.7], "knowledge_graph": [0.2, 0.1, 0.3]}
    for model in ["qwen2.5-coder:7b", "granite-code:3b-instruct"]:
        for context_variant, scores in reprs.items():
            for i, score in enumerate(scores):
                rows.append({
                    "repo_name": f"repo-{i}",
                    "model": model,
                    "context_variant": context_variant,
                    "hallucination_score": score,
                })
    return rows


def test_summarize_by_cell_computes_mean_and_ci():
    summaries = summarize_by_cell(_rows(), "hallucination_score")
    assert len(summaries) == 4  # 2 models x 2 representations
    kg_qwen = next(s for s in summaries if s.group_key == ("qwen2.5-coder:7b", "knowledge_graph"))
    assert kg_qwen.n == 3
    assert abs(kg_qwen.mean - 0.2) < 1e-6
    assert kg_qwen.ci95_low < kg_qwen.mean < kg_qwen.ci95_high


def test_summarize_by_cell_handles_single_observation_without_crashing():
    rows = [{"model": "m", "context_variant": "raw", "hallucination_score": 0.5}]
    summaries = summarize_by_cell(rows, "hallucination_score")
    assert len(summaries) == 1
    assert summaries[0].n == 1
    assert summaries[0].std == 0.0


def test_summarize_by_cell_skips_missing_metric_values():
    rows = [
        {"model": "m", "context_variant": "raw", "hallucination_score": 0.5},
        {"model": "m", "context_variant": "raw", "hallucination_score": None},
    ]
    summaries = summarize_by_cell(rows, "hallucination_score")
    assert summaries[0].n == 1


def test_paired_test_detects_significant_difference():
    result = paired_test(
        _rows(), "hallucination_score", factor="context_variant",
        level_a="raw", level_b="knowledge_graph",
        held_fixed={"model": "qwen2.5-coder:7b"},
    )
    assert result.n_pairs == 3
    assert result.mean_diff > 0  # raw scores higher (worse) than knowledge_graph
    assert result.p_value is not None
    assert result.p_value < 0.5  # consistent direction across all 3 pairs


def test_paired_test_returns_note_when_too_few_pairs():
    rows = [{"repo_name": "r1", "model": "m", "context_variant": "raw", "hallucination_score": 0.5}]
    result = paired_test(rows, "hallucination_score", "context_variant", "raw", "knowledge_graph")
    assert result.n_pairs == 0
    assert result.p_value is None
    assert result.note is not None


def test_paired_test_handles_all_zero_differences():
    rows = [
        {"repo_name": "r1", "model": "m", "context_variant": "raw", "hallucination_score": 0.5},
        {"repo_name": "r1", "model": "m", "context_variant": "knowledge_graph", "hallucination_score": 0.5},
        {"repo_name": "r2", "model": "m", "context_variant": "raw", "hallucination_score": 0.3},
        {"repo_name": "r2", "model": "m", "context_variant": "knowledge_graph", "hallucination_score": 0.3},
    ]
    result = paired_test(rows, "hallucination_score", "context_variant", "raw", "knowledge_graph")
    assert result.p_value is None
    assert "zero" in result.note.lower()


def test_paired_test_keeps_model_and_representation_independent():
    # held_fixed to one model must not leak in the other model's rows
    result = paired_test(
        _rows(), "hallucination_score", factor="context_variant",
        level_a="raw", level_b="knowledge_graph",
        held_fixed={"model": "granite-code:3b-instruct"},
    )
    assert result.held_fixed == {"model": "granite-code:3b-instruct"}
    assert result.n_pairs == 3


def test_compare_all_levels_within_covers_every_model():
    results = compare_all_levels_within(_rows(), "hallucination_score", factor="context_variant", fixed_factor="model")
    models_covered = {r.held_fixed["model"] for r in results}
    assert models_covered == {"qwen2.5-coder:7b", "granite-code:3b-instruct"}
    # 2 representations -> exactly 1 pairwise comparison per model
    assert len(results) == 2
