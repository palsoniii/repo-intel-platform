"""
Statistical rigor across models/methods (IEEE-paper eval expansion, Step 1.6).

Turns the harness's flat per-(repo, model, representation) rows into:
- mean +/- 95% CI per (model, representation) cell, for any metric field.
- paired significance testing (Wilcoxon signed-rank) between representations
  within a model, and between models within a representation -- paired because
  the harness's design is repeated-measures: the same repo is scored under every
  (model, representation) combination, so a paired test is the correct one (this
  is what the original 6-repo battery's REPORT.md did by hand with a sign test;
  Wilcoxon uses the magnitude of the paired differences too, not just their sign,
  so it has more power for the same sample).

Deliberately generic over rows-as-dicts (works directly against
`EvaluationRow.model_dump()`, a CSV `DictReader` row, or a SQLite query result) and
over which metric field to analyze, rather than being hallucination-score-specific
-- coverage, G-Eval quality scores, and text-overlap metrics all need the same
mean/CI/paired-test treatment.
"""

from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel
from scipy import stats as scipy_stats

Row = dict  # a harness result row: at minimum {"repo_name", "model", "context_variant", <metric_field>}


class CellSummary(BaseModel):
    group_key: tuple[str, ...]  # e.g. (model, context_variant)
    n: int
    mean: float
    std: float
    ci95_low: float
    ci95_high: float


def summarize_by_cell(rows: list[Row], metric_field: str, group_fields: tuple[str, ...] = ("model", "context_variant")) -> list[CellSummary]:
    """Mean +/- 95% CI (t-distribution, appropriate for the small per-cell sample
    sizes here) for every distinct combination of `group_fields`."""
    groups: dict[tuple[str, ...], list[float]] = {}
    for row in rows:
        value = row.get(metric_field)
        if value is None:
            continue
        key = tuple(str(row.get(f, "")) for f in group_fields)
        groups.setdefault(key, []).append(float(value))

    summaries = []
    for key, values in sorted(groups.items()):
        n = len(values)
        mean = sum(values) / n
        if n < 2:
            summaries.append(CellSummary(group_key=key, n=n, mean=round(mean, 4), std=0.0, ci95_low=round(mean, 4), ci95_high=round(mean, 4)))
            continue
        std = (sum((v - mean) ** 2 for v in values) / (n - 1)) ** 0.5
        sem = std / (n ** 0.5)
        t_crit = scipy_stats.t.ppf(0.975, df=n - 1)
        margin = t_crit * sem
        summaries.append(
            CellSummary(
                group_key=key,
                n=n,
                mean=round(mean, 4),
                std=round(std, 4),
                ci95_low=round(mean - margin, 4),
                ci95_high=round(mean + margin, 4),
            )
        )
    return summaries


def add_coverage_efficiency(
    rows: list[Row],
    coverage_field: str = "coverage_score",
    token_field: str = "input_tokens",
    out_field: str = "coverage_per_1k_input_tokens",
    per_tokens: int = 1000,
) -> list[Row]:
    """Returns new row dicts with a derived `out_field`: how much coverage a
    representation delivers per unit of input-token cost. Fuses the two
    strongest results in the study (coverage improves with structure; structure
    is also cheaper in input tokens) into one directly comparable number instead
    of two separate claims a reader has to mentally combine -- e.g. 'structured
    context delivers N times more coverage per 1,000 input tokens than raw'.
    Pure arithmetic over fields every row already has; feed the result straight
    into summarize_by_cell / compare_all_levels_within like any other metric.
    Rows missing either field, or with token_field == 0, are passed through
    unchanged (no out_field key), matching summarize_by_cell's existing
    None-skipping behavior for a metric a row doesn't have."""
    result: list[Row] = []
    for row in rows:
        new_row = dict(row)
        coverage = row.get(coverage_field)
        tokens = row.get(token_field)
        if coverage is not None and tokens:
            new_row[out_field] = round(float(coverage) / (float(tokens) / per_tokens), 4)
        result.append(new_row)
    return result


class CategoryCoverageSummary(BaseModel):
    group_key: tuple[str, ...]  # e.g. (model, context_variant)
    category: str  # "Dependency", "Endpoint", "Class/Service", "Database entity", ...
    n_rows: int
    total_facts: int  # summed across the group's rows
    missing_facts: int  # summed across the group's rows
    coverage: float  # (total_facts - missing_facts) / total_facts; 1.0 if total_facts == 0


def category_coverage_breakdown(
    rows: list[Row], group_fields: tuple[str, ...] = ("model", "context_variant")
) -> list[CategoryCoverageSummary]:
    """Coverage broken out by fact category instead of one aggregate number per
    row -- reads the `facts_by_category` (per-category totals) and
    `missing_facts_list` (which specific facts were missing, category-prefixed
    e.g. 'Dependency: express') JSON columns EvaluationRow now persists. Lets the
    write-up say something sharper than 'coverage improves': whether structured
    context's advantage is spread evenly across dependencies/endpoints/classes/
    database entities, or concentrated in one category. Rows with missing or
    unparseable JSON in either column are skipped for that row rather than
    raising, consistent with this module's general "a bad row degrades the
    sample size, not the whole computation" stance."""
    # group_key -> category -> [total_facts_this_row, missing_facts_this_row, n_rows]
    totals: dict[tuple[str, ...], dict[str, list[int]]] = {}

    for row in rows:
        key = tuple(str(row.get(f, "")) for f in group_fields)
        try:
            by_category: dict[str, int] = json.loads(row.get("facts_by_category") or "{}")
            missing_list: list[str] = json.loads(row.get("missing_facts_list") or "[]")
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(by_category, dict) or not isinstance(missing_list, list):
            continue

        missing_by_category: dict[str, int] = {}
        for fact in missing_list:
            category = str(fact).split(":", 1)[0]
            missing_by_category[category] = missing_by_category.get(category, 0) + 1

        for category, total in by_category.items():
            bucket = totals.setdefault(key, {}).setdefault(category, [0, 0, 0])
            bucket[0] += total
            bucket[1] += missing_by_category.get(category, 0)
            bucket[2] += 1

    summaries = []
    for key, by_category in sorted(totals.items()):
        for category, (total_facts, missing_facts, n_rows) in sorted(by_category.items()):
            coverage = (total_facts - missing_facts) / total_facts if total_facts > 0 else 1.0
            summaries.append(
                CategoryCoverageSummary(
                    group_key=key, category=category, n_rows=n_rows,
                    total_facts=total_facts, missing_facts=missing_facts,
                    coverage=round(coverage, 4),
                )
            )
    return summaries


def diagram_f1_report(
    rows: list[Row], group_fields: tuple[str, ...] = ("framework",)
) -> dict[str, list[CellSummary]]:
    """Mean +/- 95% CI for all four diagram graph-diff F1 fields
    (module/import/endpoint/overall), grouped by `group_fields` (default:
    framework, since the diagram is deterministic per repo and doesn't vary by
    generator model or representation -- grouping by model would just repeat
    the same numbers 3x). A thin convenience wrapper around summarize_by_cell,
    which already handles these fields generically since they're plain floats
    on EvaluationRow; exists so this specific, previously-unreported metric
    family has one obvious call site rather than requiring a reader to
    remember to call summarize_by_cell four separate times."""
    return {
        field: summarize_by_cell(rows, field, group_fields=group_fields)
        for field in (
            "diagram_module_f1", "diagram_import_f1", "diagram_endpoint_f1", "diagram_overall_f1",
        )
    }


class PairedTestResult(BaseModel):
    metric_field: str
    factor: str  # which field is being compared, e.g. "context_variant"
    level_a: str
    level_b: str
    held_fixed: dict[str, str]  # the other factor's value, if any (e.g. {"model": "qwen2.5-coder:7b"})
    n_pairs: int
    mean_diff: float  # mean(a - b)
    wilcoxon_statistic: Optional[float]
    p_value: Optional[float]
    note: Optional[str] = None  # e.g. why the test couldn't run


def paired_test(
    rows: list[Row],
    metric_field: str,
    factor: str,
    level_a: str,
    level_b: str,
    pair_key_fields: tuple[str, ...] = ("repo_name",),
    held_fixed: Optional[dict[str, str]] = None,
) -> PairedTestResult:
    """Wilcoxon signed-rank test between `factor`=level_a and `factor`=level_b,
    pairing rows on `pair_key_fields` (default: same repo). `held_fixed` filters to
    a specific value of the OTHER factor first (e.g. {"model": "qwen2.5-coder:7b"}
    when comparing representations within one model), so model and representation
    are treated as independent factors rather than collapsed into one leaderboard
    column, per the project's own factorial-design requirement."""
    held_fixed = held_fixed or {}
    filtered = [r for r in rows if all(str(r.get(k)) == v for k, v in held_fixed.items())]

    a_values = {tuple(str(r.get(k)) for k in pair_key_fields): r.get(metric_field) for r in filtered if str(r.get(factor)) == level_a}
    b_values = {tuple(str(r.get(k)) for k in pair_key_fields): r.get(metric_field) for r in filtered if str(r.get(factor)) == level_b}

    common_keys = sorted(set(a_values) & set(b_values))
    pairs = [(a_values[k], b_values[k]) for k in common_keys if a_values[k] is not None and b_values[k] is not None]

    if len(pairs) < 2:
        return PairedTestResult(
            metric_field=metric_field, factor=factor, level_a=level_a, level_b=level_b,
            held_fixed=held_fixed, n_pairs=len(pairs), mean_diff=0.0,
            wilcoxon_statistic=None, p_value=None,
            note=f"Only {len(pairs)} paired observation(s) -- Wilcoxon needs at least 2.",
        )

    diffs = [float(a) - float(b) for a, b in pairs]
    mean_diff = sum(diffs) / len(diffs)

    if all(d == 0 for d in diffs):
        return PairedTestResult(
            metric_field=metric_field, factor=factor, level_a=level_a, level_b=level_b,
            held_fixed=held_fixed, n_pairs=len(pairs), mean_diff=0.0,
            wilcoxon_statistic=None, p_value=None,
            note="All paired differences are zero -- Wilcoxon is undefined (no evidence of a difference).",
        )

    statistic, p_value = scipy_stats.wilcoxon([a for a, _ in pairs], [b for _, b in pairs])
    return PairedTestResult(
        metric_field=metric_field, factor=factor, level_a=level_a, level_b=level_b,
        held_fixed=held_fixed, n_pairs=len(pairs), mean_diff=round(mean_diff, 4),
        wilcoxon_statistic=round(float(statistic), 4), p_value=round(float(p_value), 4),
    )


def compare_all_levels_within(
    rows: list[Row],
    metric_field: str,
    factor: str,
    fixed_factor: str,
    pair_key_fields: tuple[str, ...] = ("repo_name",),
) -> list[PairedTestResult]:
    """Runs every pairwise comparison of `factor`'s levels, separately for each
    value of `fixed_factor` -- e.g. factor="context_variant", fixed_factor="model"
    compares raw/dependency_graph/knowledge_graph pairwise within each model, so
    the model and representation factors stay isolated rather than pooled."""
    fixed_values = sorted({str(r.get(fixed_factor)) for r in rows if r.get(fixed_factor) is not None})
    factor_levels = sorted({str(r.get(factor)) for r in rows if r.get(factor) is not None})

    results = []
    for fixed_value in fixed_values:
        for i, level_a in enumerate(factor_levels):
            for level_b in factor_levels[i + 1 :]:
                results.append(
                    paired_test(
                        rows, metric_field, factor, level_a, level_b,
                        pair_key_fields=pair_key_fields,
                        held_fixed={fixed_factor: fixed_value},
                    )
                )
    return results
