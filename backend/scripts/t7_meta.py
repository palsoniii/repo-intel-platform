"""T7 -- judge meta-evaluation against the deterministic oracle.

Produces the paper's central table plus the fact-level confusion analysis.

Runs against whatever judge columns exist; missing runs are skipped with a note, so this
is safe to run before the mistral-fixed re-judge completes and again afterwards.

Key output: SPECIFICITY -- of the facts the oracle says a summary genuinely MISSED, what
fraction did the judge also flag as missing? A judge that says "everything is covered"
scores near zero here regardless of how good its overall correlation looks.
"""
from __future__ import annotations

import json
import os
import sqlite3

import numpy as np
import pandas as pd
from scipy import stats

R = "/app/evaluation_results"
OUT = os.path.join(R, "T7_META_EVALUATION.txt")
KEY = ["repo_name", "model", "context_variant"]
_lines = []


def P(s=""):
    print(s, flush=True)
    _lines.append(s)


def boot_ci_rho(x, y, n=4000, seed=7):
    rng = np.random.default_rng(seed)
    x, y = np.asarray(x), np.asarray(y)
    out = []
    for _ in range(n):
        i = rng.integers(0, len(x), len(x))
        if len(set(y[i])) < 2 or len(set(x[i])) < 2:
            continue
        out.append(stats.spearmanr(x[i], y[i]).statistic)
    if not out:
        return (float("nan"), float("nan"))
    return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


def load_judges():
    """-> list of (label, dataframe with KEY + coverage + missing_list + unmatched)"""
    js = []

    c = sqlite3.connect(os.path.join(R, "battery_v2.db"))
    v2 = pd.read_sql_query(
        "SELECT repo_name, model, context_variant, coverage_score, coverage_judged, "
        "missing_facts_list, total_facts FROM evaluation_runs WHERE run_status='success'", c)
    c.close()
    v2 = v2[v2["coverage_judged"] == 1].copy()
    v2["coverage"] = pd.to_numeric(v2["coverage_score"], errors="coerce")
    v2["unmatched"] = np.nan  # not recorded by the original harness
    js.append(("mistral:7b-instruct (ORIGINAL harness)", v2))

    for slug, label in [("gemma2_9b", "gemma2:9b (fixed harness)"),
                        ("mistral_7b-instruct", "mistral:7b-instruct (FIXED harness)")]:
        p = os.path.join(R, "rejudge_%s.db" % slug)
        if not os.path.exists(p):
            P("  [skip] %s -- run not present yet" % label)
            continue
        c = sqlite3.connect(p)
        try:
            d = pd.read_sql_query(
                "SELECT repo_name, model, context_variant, coverage_score, "
                "missing_facts_list, unmatched_verdict_items, self_judged, total_facts "
                "FROM rejudged WHERE coverage_judged='1'", c)
        except Exception as e:
            P("  [skip] %s -- %s" % (label, e)); c.close(); continue
        c.close()
        if not len(d):
            P("  [skip] %s -- no judged rows" % label); continue
        d["coverage"] = pd.to_numeric(d["coverage_score"], errors="coerce")
        d["unmatched"] = pd.to_numeric(d["unmatched_verdict_items"], errors="coerce")
        js.append((label, d))
    return js


def main():
    orc = pd.read_csv(os.path.join(R, "oracle_scores.csv"))
    facts = pd.read_csv(os.path.join(R, "fact_decisions.csv"))
    P("=" * 84)
    P("T7 -- JUDGE META-EVALUATION vs DETERMINISTIC ORACLE")
    P("=" * 84)
    P("oracle rows=%d   fact-level decisions=%d" % (len(orc), len(facts)))
    P("")

    judges = load_judges()
    P("")

    # ------------------------------------------------------------ row-level table
    P("-" * 84)
    P("ROW-LEVEL AGREEMENT WITH THE ORACLE")
    P("-" * 84)
    P("  %-42s %5s %8s %18s %7s %8s" % ("judge", "n", "rho", "95% CI", "%at1.0", "distinct"))
    for label, d in judges:
        m = orc.merge(d[KEY + ["coverage"]], on=KEY, how="inner").dropna(
            subset=["coverage", "oracle_coverage_strict"])
        if len(m) < 8:
            P("  %-42s (too few rows)" % label); continue
        x, y = m["oracle_coverage_strict"].values, m["coverage"].values
        rho = stats.spearmanr(x, y).statistic
        lo, hi = boot_ci_rho(x, y)
        sat = 100.0 * (y == 1.0).mean()
        P("  %-42s %5d %+8.4f   [%+.3f,%+.3f] %6.1f%% %8d"
          % (label, len(m), rho, lo, hi, sat, len(set(y))))
    x = orc["oracle_coverage_strict"].values
    P("  %-42s %5d %8s %18s %6.1f%% %8d"
      % ("oracle (reference)", len(x), "--", "--", 100.0 * (x == 1.0).mean(), len(set(x))))
    P("")

    # ------------------------------------------------- fact-level confusion matrix
    P("-" * 84)
    P("FACT-LEVEL CONFUSION vs ORACLE  (the human-validation substitute)")
    P("-" * 84)
    P("  Reference = oracle STRICT. Judge 'missing' = fact appears in its missing_facts_list.")
    P("  SENSITIVITY = P(judge says covered | oracle says covered)")
    P("  SPECIFICITY = P(judge says MISSING  | oracle says MISSING)   <-- the decisive one")
    P("")
    P("  %-42s %9s %9s %11s %11s" % ("judge", "n_facts", "sens", "SPEC", "balanced"))
    for label, d in judges:
        rows = []
        for _, r in d.iterrows():
            try:
                miss = set(json.loads(r["missing_facts_list"] or "[]"))
            except Exception:
                miss = set()
            rows.append(((r["repo_name"], r["model"], r["context_variant"]), miss))
        lut = dict(rows)
        sub = facts[facts.apply(
            lambda f: (f["repo_name"], f["model"], f["context_variant"]) in lut, axis=1)]
        if not len(sub):
            P("  %-42s (no overlap)" % label); continue
        jm = sub.apply(
            lambda f: f["fact"] in lut[(f["repo_name"], f["model"], f["context_variant"])],
            axis=1).values
        oc = sub["oracle_strict"].values.astype(bool)
        jc = ~jm  # judge says covered when it did NOT list the fact as missing
        tp = int((oc & jc).sum());  fn = int((oc & ~jc).sum())
        tn = int((~oc & ~jc).sum()); fp = int((~oc & jc).sum())
        sens = tp / (tp + fn) if (tp + fn) else float("nan")
        spec = tn / (tn + fp) if (tn + fp) else float("nan")
        P("  %-42s %9d %9.4f %11.4f %11.4f"
          % (label, len(sub), sens, spec, (sens + spec) / 2))
    P("")
    P("  A judge that calls everything covered scores sens=1.000, SPEC=0.000.")
    P("")

    # ------------------------------------------------------ format compliance
    P("-" * 84)
    P("JUDGE FORMAT COMPLIANCE  (unmatched_verdict_items -- new metric from the T1 fix)")
    P("-" * 84)
    for label, d in judges:
        if d["unmatched"].isna().all():
            P("  %-42s not recorded (pre-fix harness)" % label); continue
        u = d["unmatched"].fillna(0)
        P("  %-42s rows with unmatched>0: %3d/%3d   total items: %d"
          % (label, int((u > 0).sum()), len(u), int(u.sum())))
    P("")

    # ------------------------------------------------------ inter-judge agreement
    if len(judges) >= 2:
        P("-" * 84)
        P("PAIRWISE INTER-JUDGE AGREEMENT (Spearman)")
        P("-" * 84)
        base = orc[KEY + ["oracle_coverage_strict"]].copy()
        for label, d in judges:
            base = base.merge(d[KEY + ["coverage"]].rename(columns={"coverage": label}),
                              on=KEY, how="left")
        cols = ["oracle_coverage_strict"] + [l for l, _ in judges]
        cm = base[cols].corr(method="spearman")
        P("  " + " " * 44 + "  ".join("%-10s" % c[:10] for c in cols))
        for c in cols:
            P("  %-42s " % c[:42] + "  ".join(
                "%-10.3f" % cm.loc[c, c2] if not np.isnan(cm.loc[c, c2]) else "%-10s" % "--"
                for c2 in cols))
        P("")
        # Interpretation must be READ OFF the matrix, not asserted. On this data the two
        # judges are slightly ANTI-correlated with each other while one tracks the oracle
        # well -- the opposite of the "correlated errors" pattern, and a stronger result:
        # averaging these two judges into a panel would produce noise, not a better score.
        jl = [l for l, _ in judges]
        if len(jl) >= 2:
            worst = None
            for i in range(len(jl)):
                for j in range(i + 1, len(jl)):
                    v = cm.loc[jl[i], jl[j]]
                    if not np.isnan(v) and (worst is None or v < worst[2]):
                        worst = (jl[i], jl[j], v)
            if worst:
                P("  Judge-vs-judge agreement, lowest pair: rho=%+.3f" % worst[2])
                P("    %s" % worst[0])
                P("    %s" % worst[1])
                best_o = max((cm.loc["oracle_coverage_strict", l] for l in jl
                              if not np.isnan(cm.loc["oracle_coverage_strict", l])),
                             default=float("nan"))
                if worst[2] < best_o:
                    P("  The judges agree with EACH OTHER (%+.3f) LESS than the best judge"
                      % worst[2])
                    P("  agrees with the oracle (%+.3f). They are not making the same" % best_o)
                    P("  mistake with different calibration -- they are measuring different")
                    P("  things. Averaging them into a panel would yield noise, not accuracy.")
                    P("  Cf. arXiv 2605.29800 on why panel size does not buy independence.")
                else:
                    P("  Judges agree with each other more than with the oracle: the")
                    P("  correlated-error pattern of arXiv 2605.29800. A panel of these")
                    P("  judges would not have caught the defect.")
        P("")

    # ------------------------------------------------------ self-preference test
    P("-" * 84)
    P("SELF-PREFERENCE  (gemma2 is both a writer and a judge)")
    P("-" * 84)
    for label, d in judges:
        if "self_judged" not in d.columns:
            continue
        m = orc.merge(d[KEY + ["coverage", "self_judged"]], on=KEY, how="inner").dropna(
            subset=["coverage"])
        m["gap"] = m["coverage"] - m["oracle_coverage_strict"]
        a = m[m["self_judged"] == "1"]["gap"]
        b = m[m["self_judged"] == "0"]["gap"]
        if len(a) < 5 or len(b) < 5:
            continue
        u = stats.mannwhitneyu(a, b, alternative="two-sided")
        P("  %s" % label)
        P("    self-judged     n=%3d  mean gap = %+.4f" % (len(a), a.mean()))
        P("    non-self-judged n=%3d  mean gap = %+.4f" % (len(b), b.mean()))
        P("    Mann-Whitney U p=%.4f  -> %s"
          % (u.pvalue, "NO significant self-preference" if u.pvalue >= .05
             else "SIGNIFICANT difference -- investigate"))
        P("")

    # ------------------------------------- disagreement sample (paraphrase vs error)
    P("-" * 84)
    P("DISAGREEMENT SAMPLE -- bounds the oracle's paraphrase blind spot (§6.5)")
    P("-" * 84)
    P("  Facts the JUDGE credited but the ORACLE did not. Each is either genuine")
    P("  paraphrase (oracle limitation) or judge error. Read and classify these.")
    P("")
    for label, d in judges:
        if "gemma2" not in label:
            continue
        lut = {}
        for _, r in d.iterrows():
            try:
                lut[(r["repo_name"], r["model"], r["context_variant"])] = set(
                    json.loads(r["missing_facts_list"] or "[]"))
            except Exception:
                pass
        cand = facts[(facts["oracle_strict"] == 0) & facts.apply(
            lambda f: (f["repo_name"], f["model"], f["context_variant"]) in lut
            and f["fact"] not in lut[(f["repo_name"], f["model"], f["context_variant"])],
            axis=1)]
        P("  %s: %d such facts" % (label, len(cand)))
        if len(cand):
            s = cand.sample(min(30, len(cand)), random_state=11)
            s[["repo_name", "model", "context_variant", "fact", "category"]].to_csv(
                os.path.join(R, "disagreement_sample.csv"), index=False)
            P("  -> wrote disagreement_sample.csv (%d rows) for manual classification"
              % len(s))
            P("")
            for _, r in s.head(12).iterrows():
                P("     %-28s %-16s %s" % (r["repo_name"][:28], r["context_variant"][:16],
                                           r["fact"][:52]))
    P("")

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_lines) + "\n")
    P("wrote %s" % OUT)


if __name__ == "__main__":
    main()
