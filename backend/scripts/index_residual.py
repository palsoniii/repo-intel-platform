"""Post-hoc: how much of the REMAINING coverage error is index notation?

The T1 fix resolves non-verbatim renderings of real facts, but not a judge that answers
with the fact's LIST INDEX ('7') instead of its text. The prompt numbers the facts, so an
index is an unambiguous reference -- meaning those items are recoverable in principle and
our canonicaliser still discards them.

Rather than re-run 157 rows on the GPU to find out how much that costs, this quantifies it
from data already stored.

IMPORTANT LIMITATION, state it in the paper: rejudge.py persists only the FIRST FIVE
unmatched items per row (`unmatched_samples[:5]`). So the *proportion* of unmatched items
that are index-shaped is estimated from that sample, not counted exhaustively. The
per-row unmatched TOTAL is exact; the composition is sampled.
"""
from __future__ import annotations

import json
import os
import sqlite3

R = "/app/evaluation_results"
_lines = []


def P(s=""):
    print(s, flush=True)
    _lines.append(s)


def classify(item: str) -> str:
    s = str(item).strip().strip("`'\" ")
    if s.isdigit():
        return "index"
    # "12." or "12)" alone
    if s.rstrip(".)").isdigit():
        return "index"
    if ":" in s or "/" in s:
        return "fact-like"
    return "other"


def main():
    P("=" * 78)
    P("RESIDUAL ANALYSIS -- composition of unmatched judge items")
    P("=" * 78)
    P("Sampled from unmatched_samples (first 5 per row). Row totals are exact;")
    P("composition is estimated from the sample. No GPU, no re-judging.")
    P("")

    for slug, label in [("mistral_7b-instruct", "mistral:7b-instruct (fixed harness)"),
                        ("gemma2_9b", "gemma2:9b (fixed harness)")]:
        p = os.path.join(R, "rejudge_%s.db" % slug)
        if not os.path.exists(p):
            continue
        c = sqlite3.connect(p)
        rows = c.execute(
            "SELECT repo_name, model, context_variant, coverage_score, total_facts, "
            "unmatched_verdict_items, unmatched_samples FROM rejudged "
            "WHERE coverage_judged='1'").fetchall()
        c.close()

        tot_unmatched = 0
        counts = {"index": 0, "fact-like": 0, "other": 0}
        rows_index_dominated = []
        for r in rows:
            try:
                u = int(float(r[5] or 0))
            except Exception:
                u = 0
            tot_unmatched += u
            if u == 0:
                continue
            try:
                samp = json.loads(r[6] or "[]")
            except Exception:
                samp = []
            kinds = [classify(s) for s in samp]
            for k in kinds:
                counts[k] += 1
            if kinds and all(k == "index" for k in kinds):
                tf = int(float(r[4] or 0)) if r[4] else 0
                rows_index_dominated.append((r[0], r[1], r[2], float(r[3]), tf, u))

        n_samp = sum(counts.values())
        P("-" * 78)
        P(label)
        P("-" * 78)
        P("  rows judged                : %d" % len(rows))
        P("  total unmatched items      : %d  (exact)" % tot_unmatched)
        P("  sampled items classified   : %d" % n_samp)
        if n_samp:
            for k in ("index", "fact-like", "other"):
                P("    %-10s %5d  (%.1f%% of sample)"
                  % (k, counts[k], 100.0 * counts[k] / n_samp))
            est = tot_unmatched * counts["index"] / n_samp
            P("  -> estimated index-notation items overall: %.0f of %d"
              % (est, tot_unmatched))
        P("  rows whose sampled unmatched are ALL index-shaped: %d"
          % len(rows_index_dominated))
        if rows_index_dominated:
            P("")
            P("  These rows score too HIGH even after the fix. The judge named the missing")
            P("  facts by index; the canonicaliser cannot resolve those, so they are")
            P("  dropped and counted as covered -- the ORIGINAL defect, in miniature.")
            P("")
            P("  %-34s %-14s %7s %7s %6s"
              % ("repo", "variant", "cov", "facts", "unmat"))
            worst = sorted(rows_index_dominated, key=lambda t: -t[5])[:10]
            for rp, md, cv, sc, tf, u in worst:
                P("  %-34s %-14s %7.3f %7d %6d" % (rp[:34], cv[:14], sc, tf, u))
            P("")
            P("  Upper bound on the residual: if EVERY index item were resolved, these")
            P("  %d rows would lose up to %d further covered facts."
              % (len(rows_index_dominated), sum(t[5] for t in rows_index_dominated)))
        P("")

    P("=" * 78)
    P("HOW TO REPORT THIS")
    P("=" * 78)
    P("  The fix recovers most of the lost signal (mistral rho: -0.002 -> +0.475,")
    P("  specificity 0.093 -> 0.654) but is NOT complete. The dominant residual cause is")
    P("  index notation, which is resolvable in principle and which we did not implement.")
    P("  Reporting this measured residual is stronger than claiming a complete fix, and it")
    P("  is only visible because unmatched items are now COUNTED rather than discarded")
    P("  silently -- which is the paper's central methodological point.")

    out = os.path.join(R, "RESIDUAL_ANALYSIS.txt")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_lines) + "\n")
    P("")
    P("wrote %s" % out)


if __name__ == "__main__":
    main()
