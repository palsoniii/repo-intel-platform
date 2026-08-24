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
