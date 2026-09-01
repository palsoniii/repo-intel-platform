#!/usr/bin/env python3
"""Master paper report — reads every result file on disk and produces one
consolidated, paper-ready Markdown document with clearly labeled tables.

CPU-only, off-cluster. Run from the backend/ directory:

    python -m scripts.build_paper_report

Or with explicit paths:

    python -m scripts.build_paper_report --results /path/to/evaluation_results

Output: evaluation_results/PAPER_REPORT.md  (and matching per-table CSVs)

New battery DBs (battery_codellama13b.db, battery_qwen14b.db, battery_qwen32b.db)
and their rejudge outputs may not exist yet. Any missing file's metric cells are
printed as 'PENDING — awaiting cluster run' rather than crashing.
"""
from __future__ import annotations

import argparse
import csv
import itertools
import math
import os
import sqlite3
import sys
import time
from typing import Any

import numpy as np
from scipy import stats as sps

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_RESULTS = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "evaluation_results"))

VARIANTS = ["raw", "dependency_graph", "knowledge_graph"]
RNG = np.random.default_rng(42)

# Old battery DBs (superseded historical data)
OLD_DBS = [
    ("battery_v2.db",                         "Run 2 — qwen7b/codellama7b/gemma2:9b (mistral judge)"),
    ("battery_v3_granite_gemma2judge.db",      "Run 3 — granite-code:8b (gemma2:9b judge)"),
]
# New battery DBs (final roster)
NEW_DBS = [
    ("battery_codellama13b.db", "codellama:13b-instruct"),
    ("battery_qwen14b.db",      "qwen2.5-coder:14b"),
    ("battery_qwen32b.db",      "qwen2.5-coder:32b"),
]
# New rejudge DBs keyed as (judge_slug_prefix, source_stem, label)
NEW_REJUDGE = [
    ("mistral__7b-instruct", "battery_codellama13b", "mistral:7b-instruct vs codellama13b"),
    ("mistral__7b-instruct", "battery_qwen14b",      "mistral:7b-instruct vs qwen14b"),
    ("mistral__7b-instruct", "battery_qwen32b",      "mistral:7b-instruct vs qwen32b"),
    ("gemma2__27b",          "battery_codellama13b", "gemma2:27b vs codellama13b"),
    ("gemma2__27b",          "battery_qwen14b",      "gemma2:27b vs qwen14b"),
    ("gemma2__27b",          "battery_qwen32b",      "gemma2:27b vs qwen32b"),
]

PENDING = "PENDING — awaiting cluster run"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sf(v: Any) -> float | None:
    """Safe float conversion from SQLite text columns."""
    if v is None or v == "" or v == "None":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_db(path: str, table: str = "evaluation_runs") -> list[dict]:
    if not os.path.exists(path):
        return []
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in c.execute(f"SELECT * FROM {table}").fetchall()]
    except Exception:
        rows = []
    c.close()
    return rows


def load_rejudge_db(path: str) -> list[dict]:
    return load_db(path, table="rejudged")


def boot_ci(x: list[float], n: int = 10_000) -> tuple[float, float]:
    a = np.asarray(x, dtype=float)
    if len(a) < 2:
        return (float("nan"), float("nan"))
    idx = RNG.integers(0, len(a), size=(n, len(a)))
    means = a[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def rank_biserial(a: list[float], b: list[float]) -> float:
    """Matched-pairs rank-biserial r for Wilcoxon signed-rank. Range −1..1."""
    d = np.asarray(a, float) - np.asarray(b, float)
    d = d[d != 0]
    if len(d) == 0:
        return 0.0
    r = sps.rankdata(np.abs(d))
    return float((r[d > 0].sum() - r[d < 0].sum()) / r.sum())


def holm(pairs: list[tuple[str, float]]) -> dict[str, tuple[float, float, bool]]:
    """Holm-Bonferroni. Returns {label: (p_raw, p_adj, reject@.05)}."""
    m = len(pairs)
    order = sorted(pairs, key=lambda t: t[1])
    out: dict[str, tuple[float, float, bool]] = {}
    running = 0.0
    for i, (lab, p) in enumerate(order):
        adj = min(1.0, max(running, (m - i) * p))
        running = adj
        out[lab] = (p, adj, adj < 0.05)
    return out


def cohen_kappa_binary(x: list[float], y: list[float], threshold: float = 0.7) -> float:
    """Binary Cohen's κ using threshold to binarise continuous coverage scores.
    threshold=0.7 (≥0.7 → 'high coverage', <0.7 → 'low coverage').
    Stated explicitly in the table header so readers can judge the binning."""
    if not x or not y or len(x) != len(y):
        return float("nan")
    n = len(x)
    xb = [int(v >= threshold) for v in x]
    yb = [int(v >= threshold) for v in y]
    p_o = sum(xi == yi for xi, yi in zip(xb, yb)) / n
    p_x1 = sum(xb) / n
    p_y1 = sum(yb) / n
    p_e = p_x1 * p_y1 + (1 - p_x1) * (1 - p_y1)
    if p_e >= 1.0:
        return 0.0
    return (p_o - p_e) / (1 - p_e)


def word_count(text: str | None) -> int:
    if not text:
        return 0
    return len(text.split())


# ---------------------------------------------------------------------------
# Markdown/CSV writers
# ---------------------------------------------------------------------------

_lines: list[str] = []
_csv_dir: str = ""


def P(s: str = "") -> None:
    print(s, flush=True)
    _lines.append(s)


def write_csv(filename: str, headers: list[str], rows: list[list[Any]]) -> None:
    path = os.path.join(_csv_dir, filename)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(headers)
        w.writerows(rows)
    P(f"  → {path}")


# ---------------------------------------------------------------------------
# Metrics helpers
# ---------------------------------------------------------------------------

def _metrics_for_rows(rows: list[dict], field: str) -> dict[tuple[str, str], list[float]]:
    """Returns {(model, variant): [values]} for successful rows."""
    out: dict[tuple[str, str], list[float]] = {}
    for r in rows:
        if r.get("run_status") not in ("success", None, ""):
            continue
        v = _sf(r.get(field))
        if v is None:
            continue
        key = (r.get("model", "?"), r.get("context_variant", "?"))
        out.setdefault(key, []).append(v)
    return out


def descriptives_table(
    rows: list[dict],
    field: str,
    title: str,
    csv_name: str,
    pending: bool = False,
) -> None:
    """Print and save a representation × model descriptives table."""
    P(f"\n### {title}")
    if pending:
        P(f"  {PENDING}")
        return
    if not rows:
        P(f"  {PENDING}")
        return

    models = sorted({r.get("model", "?") for r in rows if r.get("run_status") in ("success", None, "")})
    header = ["model", "variant", "n", "mean", "ci95_lo", "ci95_hi", "sd"]
    csv_rows = []

    P(f"  {'model':<30} {'variant':<18} {'n':>4} {'mean':>8} {'95% CI':>18} {'sd':>8}")
    P("  " + "-" * 80)
    cell_data = _metrics_for_rows(rows, field)
    for model in models:
        for v in VARIANTS:
            vals = cell_data.get((model, v), [])
            if not vals:
                P(f"  {model:<30} {v:<18} {'—':>4}")
                continue
            mean = float(np.mean(vals))
            sd   = float(np.std(vals))
            lo, hi = boot_ci(vals)
            P(f"  {model:<30} {v:<18} {len(vals):>4} {mean:>8.4f}  [{lo:.4f},{hi:.4f}] {sd:>8.4f}")
            csv_rows.append([model, v, len(vals), round(mean, 6), round(lo, 6), round(hi, 6), round(sd, 6)])
    write_csv(csv_name, header, csv_rows)


def wilcoxon_table(
    rows: list[dict],
    field: str,
    title: str,
    csv_name: str,
    pending: bool = False,
) -> None:
    """Wilcoxon + rank-biserial + Holm-Bonferroni across all variant pairs × models."""
    P(f"\n### {title}")
    if pending:
        P(f"  {PENDING}")
        return
    if not rows:
        P(f"  {PENDING}")
        return

    models = sorted({r.get("model", "?") for r in rows
                     if r.get("run_status") in ("success", None, "")})
    cell_data = _metrics_for_rows(rows, field)

    tests: list[tuple[str, float]] = []
    detail: dict[str, tuple] = {}

    for model in models + ["POOLED"]:
        for v1, v2 in itertools.combinations(VARIANTS, 2):
            if model == "POOLED":
                a, b = [], []
                for m in models:
                    c1 = {r["repo_name"]: _sf(r[field]) for r in rows
                          if r.get("model") == m and r.get("context_variant") == v1
                          and _sf(r.get(field)) is not None}
                    c2 = {r["repo_name"]: _sf(r[field]) for r in rows
                          if r.get("model") == m and r.get("context_variant") == v2
                          and _sf(r.get(field)) is not None}
                    for rp in sorted(set(c1) & set(c2)):
                        a.append(c1[rp]); b.append(c2[rp])
            else:
                c1 = {r["repo_name"]: _sf(r[field]) for r in rows
                      if r.get("model") == model and r.get("context_variant") == v1
                      and _sf(r.get(field)) is not None}
                c2 = {r["repo_name"]: _sf(r[field]) for r in rows
                      if r.get("model") == model and r.get("context_variant") == v2
                      and _sf(r.get(field)) is not None}
                common = sorted(set(c1) & set(c2))
                a = [c1[rp] for rp in common]
                b = [c2[rp] for rp in common]
            if len(a) < 6:
                continue
            try:
                _, p = sps.wilcoxon(a, b, zero_method="wilcox")
            except ValueError:
                continue
            lab = f"{model.split(':')[0]} | {v1} vs {v2}"
            tests.append((lab, float(p)))
            detail[lab] = (len(a), float(np.mean(a)), float(np.mean(b)), rank_biserial(a, b))

    if not tests:
        P("  (insufficient data for Wilcoxon tests)")
        return

    adj = holm(tests)
    P(f"  {'comparison':<48} {'n':>3} {'mean_A':>8} {'mean_B':>8} {'p_raw':>9} {'p_holm':>9} {'r_biserial':>11}")
    P("  " + "-" * 100)
    csv_rows = []
    for lab, _ in sorted(tests, key=lambda t: t[1]):
        n, ma, mb, rb = detail[lab]
        p, pa, rej = adj[lab]
        star = " *" if rej else "  "
        P(f"  {lab:<48} {n:>3} {ma:>8.4f} {mb:>8.4f} {p:>9.5f} {pa:>9.5f} {rb:>+11.3f}{star}")
        csv_rows.append([lab, n, round(ma, 6), round(mb, 6), round(p, 6), round(pa, 6), round(rb, 4), "*" if rej else ""])
    P("  * = significant after Holm-Bonferroni at alpha=.05")
    write_csv(csv_name, ["comparison", "n", "mean_A", "mean_B", "p_raw", "p_holm", "rank_biserial", "reject"], csv_rows)


def pairwise_model_table(
    rows_by_name: dict[str, list[dict]],
    field: str,
    model_a: str,
    model_b: str,
    label_a: str,
    label_b: str,
    title: str,
    csv_name: str,
    pending: bool = False,
) -> None:
    """Direct model-vs-model comparison per representation (cross-org or scaling)."""
    P(f"\n### {title}")
    if pending:
        P(f"  {PENDING}")
        return
    rows_a = rows_by_name.get(model_a, [])
    rows_b = rows_by_name.get(model_b, [])
    if not rows_a or not rows_b:
        P(f"  {PENDING}")
        return

    header = ["variant", "model_a", "mean_a", "ci95_lo_a", "ci95_hi_a",
              "model_b", "mean_b", "ci95_lo_b", "ci95_hi_b",
              "p_wilcoxon", "r_biserial"]
    csv_rows = []
    P(f"  {'variant':<18} {label_a:>28} {'':>6} {label_b:>28} {'Wilcoxon p':>11} {'r_bis':>7}")
    P("  " + "-" * 95)
    for v in VARIANTS:
        da = [_sf(r[field]) for r in rows_a
              if r.get("context_variant") == v and _sf(r.get(field)) is not None]
        db = [_sf(r[field]) for r in rows_b
              if r.get("context_variant") == v and _sf(r.get(field)) is not None]
        # Paired within repo
        ra = {r["repo_name"]: _sf(r[field]) for r in rows_a
              if r.get("context_variant") == v and _sf(r.get(field)) is not None}
        rb = {r["repo_name"]: _sf(r[field]) for r in rows_b
              if r.get("context_variant") == v and _sf(r.get(field)) is not None}
        common = sorted(set(ra) & set(rb))
        pa_vals = [ra[rp] for rp in common]
        pb_vals = [rb[rp] for rp in common]

        ma = float(np.mean(da)) if da else float("nan")
        mb = float(np.mean(db)) if db else float("nan")
        lo_a, hi_a = boot_ci(da) if da else (float("nan"), float("nan"))
        lo_b, hi_b = boot_ci(db) if db else (float("nan"), float("nan"))
        if len(pa_vals) >= 6:
            try:
                _, p_w = sps.wilcoxon(pa_vals, pb_vals, zero_method="wilcox")
                rb_val = rank_biserial(pa_vals, pb_vals)
            except ValueError:
                p_w, rb_val = float("nan"), float("nan")
        else:
            p_w = rb_val = float("nan")
        P(f"  {v:<18} {ma:>8.4f} [{lo_a:.3f},{hi_a:.3f}]   {mb:>8.4f} [{lo_b:.3f},{hi_b:.3f}]  {p_w:>11.5f} {rb_val:>+7.3f}")
        csv_rows.append([v, label_a, round(ma, 6), round(lo_a, 4), round(hi_a, 4),
                         label_b, round(mb, 6), round(lo_b, 4), round(hi_b, 4),
                         round(p_w, 6), round(rb_val, 4)])
    write_csv(csv_name, header, csv_rows)


def length_table(rows: list[dict], title: str, csv_name: str, pending: bool = False) -> None:
    P(f"\n### {title}")
    if pending:
        P(f"  {PENDING}")
        return
    if not rows:
        P(f"  {PENDING}")
        return
    models = sorted({r.get("model", "?") for r in rows if r.get("run_status") in ("success", None, "")})
    header = ["model", "variant", "n", "mean_words", "mean_output_tokens"]
    csv_rows = []
    P(f"  {'model':<30} {'variant':<18} {'n':>4} {'mean words':>11} {'mean out_tok':>13}")
    P("  " + "-" * 80)
    for model in models:
        for v in VARIANTS:
            sub = [r for r in rows if r.get("model") == model and r.get("context_variant") == v
                   and r.get("run_status") in ("success", None, "") and r.get("summary_text")]
            if not sub:
                continue
            wc = [word_count(r.get("summary_text")) for r in sub]
            tok = [_sf(r.get("output_tokens")) for r in sub]
            tok = [t for t in tok if t is not None]
            mean_w = float(np.mean(wc))
            mean_t = float(np.mean(tok)) if tok else float("nan")
            P(f"  {model:<30} {v:<18} {len(sub):>4} {mean_w:>11.1f} {mean_t:>13.1f}")
            csv_rows.append([model, v, len(sub), round(mean_w, 1), round(mean_t, 1)])
    write_csv(csv_name, header, csv_rows)


def efficiency_table(rows: list[dict], title: str, csv_name: str, pending: bool = False) -> None:
    P(f"\n### {title}")
    if pending:
        P(f"  {PENDING}")
        return
    if not rows:
        P(f"  {PENDING}")
        return
    models = sorted({r.get("model", "?") for r in rows if r.get("run_status") in ("success", None, "")})
    header = ["model", "variant", "n", "cov_per_1k_tokens", "mean_input_tokens"]
    csv_rows = []
    P(f"  {'model':<30} {'variant':<18} {'n':>4} {'cov/1k tok':>11} {'mean in_tok':>12}")
    P("  " + "-" * 78)
    for model in models:
        for v in VARIANTS:
            sub = [r for r in rows if r.get("model") == model and r.get("context_variant") == v
                   and r.get("run_status") in ("success", None, "")
                   and _sf(r.get("input_tokens")) and _sf(r.get("coverage_score"))]
            if not sub:
                continue
            eff = [_sf(r["coverage_score"]) / (_sf(r["input_tokens"]) / 1000.0) for r in sub]
            toks = [_sf(r["input_tokens"]) for r in sub]
            mean_eff = float(np.mean(eff))
            mean_tok = float(np.mean(toks))
            P(f"  {model:<30} {v:<18} {len(sub):>4} {mean_eff:>11.4f} {mean_tok:>12.0f}")
            csv_rows.append([model, v, len(sub), round(mean_eff, 6), round(mean_tok, 0)])
    write_csv(csv_name, header, csv_rows)


def judge_agreement_table(
    primary_rows_by_model: dict[str, list[dict]],
    rejudge_paths: dict[str, str],
    title: str,
    csv_name: str,
    pending: bool = False,
) -> None:
    """Inter-judge agreement: Spearman ρ and binary Cohen's κ (threshold=0.7)
    between primary judge (gemma2:9b) and each secondary judge, per representation."""
    P(f"\n### {title}")
    if pending:
        P(f"  {PENDING}")
        return

    header = ["secondary_judge", "source_battery", "variant",
              "n", "spearman_rho", "spearman_p", "cohens_kappa_t07"]
    csv_rows = []
    P("  Binary κ threshold = 0.70 (coverage ≥ 0.70 → 'high', < 0.70 → 'low')")
    P(f"  {'secondary judge':<25} {'battery':<18} {'variant':<18} {'n':>4} {'rho':>8} {'p':>9} {'κ(t=.7)':>9}")
    P("  " + "-" * 95)

    any_data = False
    for (judge_slug, src_stem, label) in NEW_REJUDGE:
        key = f"{judge_slug}_{src_stem}"
        rj_path = rejudge_paths.get(key, "")
        if not rj_path or not os.path.exists(rj_path):
            P(f"  {label:<43} {PENDING}")
            continue
        rj_rows = load_rejudge_db(rj_path)
        if not rj_rows:
            P(f"  {label:<43} (empty)")
            continue

        # Map (repo_name, model, variant) -> secondary coverage score
        rj_lut: dict[tuple, float] = {}
        for r in rj_rows:
            if r.get("coverage_judged") in ("1", 1):
                v = _sf(r.get("coverage_score"))
                if v is not None:
                    rj_lut[(r.get("repo_name"), r.get("model"), r.get("context_variant"))] = v

        # Match against primary judge scores from the battery DB for that arm
        model_name = src_stem.replace("battery_", "").replace("codellama13b", "codellama:13b-instruct") \
                                                      .replace("qwen14b", "qwen2.5-coder:14b") \
                                                      .replace("qwen32b", "qwen2.5-coder:32b")
        prim_rows = primary_rows_by_model.get(model_name, [])
        judge_short = judge_slug.split("_")[0]  # "mistral" or "gemma2"
        battery_short = src_stem.replace("battery_", "")

        for v in VARIANTS:
            primary_scores, secondary_scores = [], []
            for r in prim_rows:
                if r.get("context_variant") != v:
                    continue
                ps = _sf(r.get("coverage_score"))
                if ps is None:
                    continue
                rjk = (r.get("repo_name"), r.get("model"), v)
                ss = rj_lut.get(rjk)
                if ss is None:
                    continue
                primary_scores.append(ps)
                secondary_scores.append(ss)
            if len(primary_scores) < 6:
                continue
            rho_val, rho_p = sps.spearmanr(primary_scores, secondary_scores)
            kappa = cohen_kappa_binary(primary_scores, secondary_scores, threshold=0.7)
            P(f"  {judge_short:<25} {battery_short:<18} {v:<18} {len(primary_scores):>4} "
              f"{rho_val:>+8.4f} {rho_p:>9.4g} {kappa:>9.4f}")
            csv_rows.append([judge_slug, src_stem, v, len(primary_scores),
                             round(rho_val, 4), round(rho_p, 6), round(kappa, 4)])
            any_data = True

    if not any_data:
        P(f"  {PENDING}")
    else:
        write_csv(csv_name, header, csv_rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    global _csv_dir

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results", default=_DEFAULT_RESULTS,
                    help="Path to evaluation_results directory")
    a = ap.parse_args()

    R = os.path.abspath(a.results)
    _csv_dir = R
    out_md = os.path.join(R, "PAPER_REPORT.md")

    P(f"# PAPER REPORT — repo-intel-platform")
    P(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    P(f"Results dir: {R}")
    P("")

    # =========================================================================
    # PART 1: SUPERSEDED RESULTS
    # =========================================================================
    P("=" * 80)
    P("## PART 1: SUPERSEDED RESULTS — retained for context only")
    P("")
    P("> **WARNING**: These results used a different generator roster and, for")
    P("> battery_v2.db, a bug-affected harness. They are NOT comparable to Part 2.")
    P("> Do not merge Part 1 and Part 2 tables. Old tables remain only so the")
    P("> paper can explain why the roster changed.")
    P("=" * 80)

    v2_path = os.path.join(R, "battery_v2.db")
    v2_rows = load_db(v2_path)
    v2_ok = [r for r in v2_rows if r.get("run_status") == "success"]
    v2_pending = not bool(v2_ok)

    P(f"\n**Source**: battery_v2.db — {len(v2_ok)} successful rows")
    P("(Roster: qwen2.5-coder:7b, codellama:7b-instruct, gemma2:9b — judge: mistral:7b-instruct)")
    P("")

    descriptives_table(v2_ok, "coverage_score",      "S1: Coverage by Representation × Model (SUPERSEDED)",     "old_coverage.csv",     v2_pending)
    descriptives_table(v2_ok, "hallucination_score",  "S2: Hallucination by Representation × Model (SUPERSEDED)", "old_hallucination.csv", v2_pending)
    descriptives_table(v2_ok, "input_tokens",         "S3: Input Token Count by Representation × Model (SUPERSEDED)", "old_tokens.csv",  v2_pending)
    descriptives_table(v2_ok, "bleu4",                "S4a: BLEU-4 by Representation × Model (SUPERSEDED)",      "old_bleu4.csv",        v2_pending)
    descriptives_table(v2_ok, "rouge_l",              "S4b: ROUGE-L by Representation × Model (SUPERSEDED)",     "old_rouge_l.csv",       v2_pending)
    descriptives_table(v2_ok, "meteor",               "S4c: METEOR by Representation × Model (SUPERSEDED)",      "old_meteor.csv",        v2_pending)

    # =========================================================================
    # PART 2: NEW RESULTS — final roster
    # =========================================================================
    P("\n" + "=" * 80)
    P("## PART 2: NEW RESULTS — Final Roster")
    P("")
    P("**Generator roster**: codellama:13b-instruct, qwen2.5-coder:14b, qwen2.5-coder:32b")
    P("**Primary judge**: gemma2:9b (sole judge for all generator arms)")
    P("**Parser**: corrected (all five defects fixed per PROJECT_HANDOFF.md)")
    P("**Comparability note**: no model is shared with Part 1. These results are")
    P("self-contained. Do not compare individual numbers across Part 1 and Part 2.")
    P("=" * 80)

    # Load new battery DBs
    new_rows_all: list[dict] = []
    new_rows_by_model: dict[str, list[dict]] = {}
    new_pending = False

    for db_file, model_label in NEW_DBS:
        path = os.path.join(R, db_file)
        rows = load_db(path)
        ok = [r for r in rows if r.get("run_status") == "success"]
        if not ok:
            P(f"\n  ⚠ {db_file}: {PENDING}")
            new_pending = True
        else:
            P(f"\n  ✓ {db_file}: {len(ok)} successful rows (model: {model_label})")
            new_rows_all.extend(ok)
            new_rows_by_model[model_label] = ok

    P("")

    descriptives_table(new_rows_all, "coverage_score",     "Table 1: Coverage by Representation × Model",           "new_coverage.csv",       new_pending)
    descriptives_table(new_rows_all, "hallucination_score", "Table 2: Hallucination by Representation × Model",      "new_hallucination.csv",   new_pending)
    descriptives_table(new_rows_all, "input_tokens",        "Table 3: Input Token Count by Representation × Model",  "new_tokens.csv",          new_pending)
    descriptives_table(new_rows_all, "bleu4",               "Table 4a: BLEU-4 by Representation × Model",            "new_bleu4.csv",           new_pending)
    descriptives_table(new_rows_all, "rouge_l",             "Table 4b: ROUGE-L by Representation × Model",           "new_rouge_l.csv",         new_pending)
    descriptives_table(new_rows_all, "meteor",              "Table 4c: METEOR by Representation × Model",            "new_meteor.csv",          new_pending)

    P("")
    P("---")
    P("*Effect sizes and significance below. All p-values: Wilcoxon signed-rank, paired within repo.*")
    P("*Holm-Bonferroni correction applied across all comparisons in each family.*")

    wilcoxon_table(new_rows_all, "coverage_score",     "Table 5: Effect Sizes — Coverage",     "new_effects_coverage.csv",      new_pending)
    wilcoxon_table(new_rows_all, "hallucination_score", "Table 6: Effect Sizes — Hallucination", "new_effects_hallucination.csv", new_pending)
    wilcoxon_table(new_rows_all, "bleu4",               "Table 7: Effect Sizes — BLEU-4 (Holm-corrected)", "new_effects_bleu4.csv", new_pending)
    wilcoxon_table(new_rows_all, "rouge_l",             "Table 8: Effect Sizes — ROUGE-L (Holm-corrected)", "new_effects_rouge_l.csv", new_pending)
    wilcoxon_table(new_rows_all, "meteor",              "Table 9: Effect Sizes — METEOR (Holm-corrected)",  "new_effects_meteor.csv", new_pending)

    # Cross-org comparison: codellama:13b vs qwen2.5-coder:14b
    P("\n---")
    P("*Cross-org comparison: ONE comparison at closely matched ~13-14B scale.*")
    P("*Do not describe this as 'three organisations' — it is one matched pair.*")

    pairwise_model_table(
        new_rows_by_model,
        field="coverage_score",
        model_a="codellama:13b-instruct",
        model_b="qwen2.5-coder:14b",
        label_a="codellama:13b (Meta)",
        label_b="qwen2.5-coder:14b (Alibaba)",
        title="Table 10: Cross-Org Comparison — Coverage (codellama:13b vs qwen14b)",
        csv_name="new_crossorg_coverage.csv",
        pending=new_pending,
    )
    pairwise_model_table(
        new_rows_by_model,
        field="hallucination_score",
        model_a="codellama:13b-instruct",
        model_b="qwen2.5-coder:14b",
        label_a="codellama:13b (Meta)",
        label_b="qwen2.5-coder:14b (Alibaba)",
        title="Table 11: Cross-Org Comparison — Hallucination (codellama:13b vs qwen14b)",
        csv_name="new_crossorg_hallucination.csv",
        pending=new_pending,
    )

    # Within-family scaling: qwen14b vs qwen32b
    P("\n---")
    P("*Within-family scaling: TWO points (14B, 32B). Not a curve. State as*")
    P("*'a two-point comparison at 14B and 32B' — not 'scaling curve'.*")

    pairwise_model_table(
        new_rows_by_model,
        field="coverage_score",
        model_a="qwen2.5-coder:14b",
        model_b="qwen2.5-coder:32b",
        label_a="qwen2.5-coder:14b",
        label_b="qwen2.5-coder:32b",
        title="Table 12: Within-Family Scaling — Coverage (qwen14b vs qwen32b)",
        csv_name="new_scaling_coverage.csv",
        pending=new_pending,
    )
    pairwise_model_table(
        new_rows_by_model,
        field="hallucination_score",
        model_a="qwen2.5-coder:14b",
        model_b="qwen2.5-coder:32b",
        label_a="qwen2.5-coder:14b",
        label_b="qwen2.5-coder:32b",
        title="Table 13: Within-Family Scaling — Hallucination (qwen14b vs qwen32b)",
        csv_name="new_scaling_hallucination.csv",
        pending=new_pending,
    )

    # Inter-judge agreement
    rejudge_paths: dict[str, str] = {}
    for (judge_slug, src_stem, _) in NEW_REJUDGE:
        key = f"{judge_slug}_{src_stem}"
        rejudge_paths[key] = os.path.join(R, f"rejudge_{judge_slug}_{src_stem}.db")

    judge_agreement_table(
        new_rows_by_model,
        rejudge_paths,
        "Table 14: Inter-Judge Agreement (gemma2:9b vs secondary judges)",
        "new_judge_agreement.csv",
        pending=new_pending,
    )

    length_table(new_rows_all, "Table 15: Summary Length Diagnostic", "new_summary_length.csv", new_pending)
    efficiency_table(new_rows_all, "Table 16: Coverage-per-Input-Token Efficiency", "new_efficiency.csv", new_pending)

    P("\n" + "=" * 80)
    P("## End of report")
    P("=" * 80)

    with open(out_md, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_lines) + "\n")
    print(f"\nWrote {out_md}")


if __name__ == "__main__":
    main()
