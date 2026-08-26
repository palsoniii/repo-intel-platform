"""
Unit tests for the statistics module: mean/CI aggregation and paired significance
testing. Pure computation, no mocks needed.
"""

import json

from app.evaluation.stats import (
    add_coverage_efficiency,
    category_coverage_breakdown,
    compare_all_levels_within,
    diagram_f1_report,
    paired_test,
    summarize_by_cell,
)


def _rows():
    # 3 repos x 2 models x 2 representations, knowledge_graph consistently better
    # (lower hallucination_score) than raw for both models.
    rows = []
    reprs = {"raw": [0.6, 0.5, 0.7], "knowledge_graph": [0.2, 0.1, 0.3]}
    for model in ["qwen2.5-coder:7b", "codellama:7b-instruct"]:
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
        held_fixed={"model": "codellama:7b-instruct"},
    )
    assert result.held_fixed == {"model": "codellama:7b-instruct"}
    assert result.n_pairs == 3


def test_compare_all_levels_within_covers_every_model():
    results = compare_all_levels_within(_rows(), "hallucination_score", factor="context_variant", fixed_factor="model")
    models_covered = {r.held_fixed["model"] for r in results}
    assert models_covered == {"qwen2.5-coder:7b", "codellama:7b-instruct"}
    # 2 representations -> exactly 1 pairwise comparison per model
    assert len(results) == 2


def test_add_coverage_efficiency_computes_ratio():
    rows = [{"coverage_score": 0.8, "input_tokens": 2000}]
    result = add_coverage_efficiency(rows)
    # 0.8 coverage per 2000 tokens -> 0.4 per 1000 tokens
    assert abs(result[0]["coverage_per_1k_input_tokens"] - 0.4) < 1e-6
    # original row is untouched (a new dict is returned)
    assert "coverage_per_1k_input_tokens" not in rows[0]


def test_add_coverage_efficiency_skips_rows_with_zero_or_missing_tokens():
    rows = [
        {"coverage_score": 0.8, "input_tokens": 0},
        {"coverage_score": 0.8},
        {"coverage_score": None, "input_tokens": 1000},
    ]
    result = add_coverage_efficiency(rows)
    assert all("coverage_per_1k_input_tokens" not in r for r in result)


def test_add_coverage_efficiency_custom_field_names():
    rows = [{"my_coverage": 1.0, "my_tokens": 500}]
    result = add_coverage_efficiency(
        rows, coverage_field="my_coverage", token_field="my_tokens", out_field="ratio", per_tokens=500
    )
    assert result[0]["ratio"] == 1.0


def _category_rows():
    # 1 row: raw has 2 facts total in "Dependency", 1 missing; 1 fact in
    # "Endpoint", 0 missing. Mirrors what harness.py now actually persists.
    return [
        {
            "model": "qwen2.5-coder:7b",
            "context_variant": "raw",
            "facts_by_category": json.dumps({"Dependency": 2, "Endpoint": 1}),
            "missing_facts_list": json.dumps(["Dependency: cors"]),
        },
    ]


def test_category_coverage_breakdown_computes_per_category_coverage():
    summaries = category_coverage_breakdown(_category_rows())
    by_category = {s.category: s for s in summaries}
    assert by_category["Dependency"].total_facts == 2
    assert by_category["Dependency"].missing_facts == 1
    assert abs(by_category["Dependency"].coverage - 0.5) < 1e-6
    assert by_category["Endpoint"].total_facts == 1
    assert by_category["Endpoint"].missing_facts == 0
    assert by_category["Endpoint"].coverage == 1.0


def test_category_coverage_breakdown_skips_unparseable_rows():
    rows = [{"model": "m", "context_variant": "raw", "facts_by_category": "not json", "missing_facts_list": "[]"}]
    summaries = category_coverage_breakdown(rows)
    assert summaries == []


def test_category_coverage_breakdown_zero_total_facts_is_vacuously_full_coverage():
    rows = [
        {
            "model": "m", "context_variant": "raw",
            "facts_by_category": json.dumps({"Database entity": 0}),
            "missing_facts_list": json.dumps([]),
        },
    ]
    summaries = category_coverage_breakdown(rows)
    assert summaries[0].coverage == 1.0


def test_diagram_f1_report_groups_by_framework_and_covers_all_four_fields():
    rows = [
        {"framework": "express", "diagram_module_f1": 1.0, "diagram_import_f1": 0.5,
         "diagram_endpoint_f1": 0.8, "diagram_overall_f1": 0.7},
        {"framework": "nestjs", "diagram_module_f1": 0.6, "diagram_import_f1": 0.9,
         "diagram_endpoint_f1": 1.0, "diagram_overall_f1": 0.85},
    ]
    report = diagram_f1_report(rows)
    assert set(report.keys()) == {
        "diagram_module_f1", "diagram_import_f1", "diagram_endpoint_f1", "diagram_overall_f1",
    }
    module_f1_express = next(s for s in report["diagram_module_f1"] if s.group_key == ("express",))
    assert module_f1_express.mean == 1.0
