"""T4 -- statistics on the oracle-measured representation effect + token efficiency.

Design notes:
  * Unit of analysis is the REPO. Rows are paired within (repo, writer) so each
    comparison is a within-repo contrast, which removes repo difficulty as a nuisance.
  * Wilcoxon signed-rank (paired, non-parametric) -- n=18 and the scores are bounded
    proportions, so a t-test's assumptions are not met.
  * Holm-Bonferroni across the whole comparison family. Raw p-values are reported too,
    but the corrected ones are what may be claimed.
  * Effect size: matched-pairs rank-biserial correlation. A p-value alone is not
    evidence of magnitude at n=18.
  * Bootstrap 95% CIs (10,000 resamples) on every reported mean.
"""
from __future__ import annotations

import csv
import itertools
import json
import os
import sys

import numpy as np
from scipy import stats

RESULTS = "/app/evaluation_results"
SRC = os.path.join(RESULTS, "oracle_scores.csv")
OUT = os.path.join(RESULTS, "ORACLE_STATS.txt")

VARIANTS = ["raw", "dependency_graph", "knowledge_graph"]
RNG = np.random.default_rng(42)

_lines = []


def P(s=""):
    print(s, flush=True)
    _lines.append(s)


def boot_ci(x, n=10000):
    x = np.asarray(x, dtype=float)
    if len(x) < 2:
        return (float("nan"), float("nan"))
    idx = RNG.integers(0, len(x), size=(n, len(x)))
    means = x[idx].mean(axis=1)
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def rank_biserial(a, b):
    """Matched-pairs rank-biserial r for Wilcoxon signed-rank. Range -1..1."""
    d = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    d = d[d != 0]
    if len(d) == 0:
        return 0.0
    r = stats.rankdata(np.abs(d))
    return float((r[d > 0].sum() - r[d < 0].sum()) / r.sum())


def holm(pairs):
    """pairs: list of (label, p). Returns dict label -> (p, p_adj, reject@.05)."""
    m = len(pairs)
    order = sorted(pairs, key=lambda t: t[1])
    out, running = {}, 0.0
    for i, (lab, p) in enumerate(order):
        adj = min(1.0, max(running, (m - i) * p))
        running = adj
        out[lab] = (p, adj, adj < 0.05)
    return out


def main():
    rows = list(csv.DictReader(open(SRC, encoding="utf-8")))
    for r in rows:
        for k in ("oracle_coverage_strict", "oracle_coverage_lenient",
                  "oracle_unsupported_rate", "input_tokens", "latency_ms"):
            r[k] = float(r[k]) if r[k] not in ("", "None", None) else None

    writers = sorted({r["model"] for r in rows})
    repos = sorted({r["repo_name"] for r in rows})
    P("=" * 78)
    P("T4 -- ORACLE-MEASURED REPRESENTATION EFFECT")
    P("=" * 78)
    P("rows=%d  repos=%d  writers=%d" % (len(rows), len(repos), len(writers)))
    P("Metric: oracle_coverage_strict (deterministic, no judge involved)")
    P("")

    def cell(w, v, key="oracle_coverage_strict"):
        return {r["repo_name"]: r[key] for r in rows
                if r["model"] == w and r["context_variant"] == v and r[key] is not None}

    # ---------------------------------------------------------------- descriptives
    P("-" * 78)
    P("DESCRIPTIVES  (bootstrap 95% CI, 10k resamples)")
    P("-" * 78)
    for key, lab in [("oracle_coverage_strict", "STRICT"),
                     ("oracle_coverage_lenient", "LENIENT")]:
        P("  %s tier:" % lab)
        for v in VARIANTS:
            x = [r[key] for r in rows if r["context_variant"] == v and r[key] is not None]
            lo, hi = boot_ci(x)
            P("    %-18s n=%3d  mean=%.4f  95%% CI [%.4f, %.4f]  sd=%.4f"
              % (v, len(x), np.mean(x), lo, hi, np.std(x)))
        P("")

    # ------------------------------------------------------------ paired contrasts
    P("-" * 78)
    P("PAIRED CONTRASTS -- Wilcoxon signed-rank, paired within (repo, writer)")
    P("-" * 78)
    tests, detail = [], {}
    for w in writers + ["POOLED"]:
        for v1, v2 in itertools.combinations(VARIANTS, 2):
            if w == "POOLED":
                a, b = [], []
                for ww in writers:
                    c1, c2 = cell(ww, v1), cell(ww, v2)
                    for rp in sorted(set(c1) & set(c2)):
                        a.append(c1[rp]); b.append(c2[rp])
            else:
                c1, c2 = cell(w, v1), cell(w, v2)
                common = sorted(set(c1) & set(c2))
                a = [c1[rp] for rp in common]
                b = [c2[rp] for rp in common]
            if len(a) < 6:
                continue
            try:
                st_, p = stats.wilcoxon(a, b, zero_method="wilcox")
            except ValueError:
                continue
            lab = "%s | %s vs %s" % (w.split(":")[0], v1, v2)
            tests.append((lab, float(p)))
            detail[lab] = (len(a), float(np.mean(a)), float(np.mean(b)), rank_biserial(a, b))

    adj = holm(tests)
    P("  %-46s %3s %8s %8s %9s %9s %s"
      % ("comparison", "n", "mean_A", "mean_B", "p_raw", "p_holm", "rank-biserial"))
    for lab, _ in sorted(tests, key=lambda t: t[1]):
        n, ma, mb, rb = detail[lab]
        p, pa, rej = adj[lab]
        star = " *" if rej else "  "
        P("  %-46s %3d %8.4f %8.4f %9.5f %9.5f  r=%+.3f%s"
          % (lab, n, ma, mb, p, pa, rb, star))
    P("")
    P("  * = significant after Holm-Bonferroni at alpha=.05")
    P("  mean_A is the FIRST variant named; positive rank-biserial favours it.")
    P("")

    # ------------------------------------------------------------------ efficiency
    P("-" * 78)
    P("TOKEN EFFICIENCY -- oracle coverage per 1,000 input tokens")
    P("-" * 78)
    P("  %-18s %5s %10s %22s %11s %11s"
      % ("variant", "n", "cov/1k", "95% CI", "mean_tok", "mean_ms"))
    eff = {}
    for v in VARIANTS:
        sub = [r for r in rows if r["context_variant"] == v and r["input_tokens"]]
        e = [r["oracle_coverage_strict"] / (r["input_tokens"] / 1000.0) for r in sub]
        tok = [r["input_tokens"] for r in sub]
        lat = [r["latency_ms"] for r in sub if r["latency_ms"]]
        lo, hi = boot_ci(e)
        eff[v] = np.mean(e)
        P("  %-18s %5d %10.4f   [%.4f, %.4f] %11.0f %11.0f"
          % (v, len(e), np.mean(e), lo, hi, np.mean(tok), np.mean(lat)))
    P("")
    P("  knowledge_graph is %.1fx more token-efficient than raw."
      % (eff["knowledge_graph"] / eff["raw"]))
    P("  dependency_graph is %.1fx more token-efficient than raw."
      % (eff["dependency_graph"] / eff["raw"]))
    P("")

    # ------------------------------------------------- judge vs oracle (mistral row)
    P("-" * 78)
    P("MISTRAL JUDGE vs ORACLE -- resolution comparison, same 157 summaries")
    P("-" * 78)
    jo, oo = [], []
    for r in rows:
        if r["judge_coverage_judged"] == "1" and r["judge_coverage_score"] not in ("", None):
            jo.append(float(r["judge_coverage_score"]))
            oo.append(r["oracle_coverage_strict"])
    rho, prho = stats.spearmanr(jo, oo)
    tau, ptau = stats.kendalltau(jo, oo)
    P("  n=%d paired rows" % len(jo))
    P("  mistral   mean=%.4f  distinct values=%d  at 1.0: %d (%.1f%%)"
      % (np.mean(jo), len(set(jo)), sum(1 for x in jo if x == 1.0),
         100.0 * sum(1 for x in jo if x == 1.0) / len(jo)))
    P("  oracle    mean=%.4f  distinct values=%d  at 1.0: %d (%.1f%%)"
      % (np.mean(oo), len(set(oo)), sum(1 for x in oo if x == 1.0),
         100.0 * sum(1 for x in oo if x == 1.0) / len(oo)))
    P("  Spearman rho = %+.4f (p=%.4g)" % (rho, prho))
    P("  Kendall  tau = %+.4f (p=%.4g)" % (tau, ptau))
    P("")

    # ----------------------------------------------------------- hallucination tier
    P("-" * 78)
    P("HALLUCINATION ORACLE -- unsupported identifier rate")
    P("-" * 78)
    for v in VARIANTS:
        x = [r["oracle_unsupported_rate"] for r in rows
             if r["context_variant"] == v and r["oracle_unsupported_rate"] is not None]
        lo, hi = boot_ci(x)
        P("  %-18s n=%3d mean=%.4f  95%% CI [%.4f, %.4f]" % (v, len(x), np.mean(x), lo, hi))
    P("")

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_lines) + "\n")
    P("wrote %s" % OUT)


if __name__ == "__main__":
    main()
