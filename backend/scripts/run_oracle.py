"""T3 -- run the parser oracle over every stored summary in battery_v2.db.

No LLM. Reuses the parse cache that T5's parse phase already built.

Emits two files:
  oracle_scores.csv    -- one row per summary (157). Row-level metrics.
  fact_decisions.csv   -- one row per (summary, fact) ~= 10,000 rows. This is the
                          fact-level ground truth that T7's confusion matrix needs, and
                          it is what replaces the 24-row human validation sample at
                          roughly 400x the scale.
"""
from __future__ import annotations

import csv
import json
import os
import sqlite3
import sys

sys.path.insert(0, "/app")

from app.evaluation.oracle import score_coverage_oracle, score_hallucination_oracle
from app.schemas.parser_schema import ParsedRepository

RESULTS = "/app/evaluation_results"
SRC_DB = os.path.join(RESULTS, "battery_v2.db")
CACHE_DIR = os.path.join(RESULTS, "parse_cache")
OUT_ROWS = os.path.join(RESULTS, "oracle_scores.csv")
OUT_FACTS = os.path.join(RESULTS, "fact_decisions.csv")

ROW_COLS = [
    "repo_name", "model", "context_variant", "judge_model",
    "total_facts", "covered_strict", "covered_lenient",
    "oracle_coverage_strict", "oracle_coverage_lenient",
    "judge_coverage_score", "judge_coverage_judged",
    "total_candidates", "supported", "unsupported", "oracle_unsupported_rate",
    "input_tokens", "output_tokens", "latency_ms",
    "per_category_strict", "per_category_lenient", "rule_histogram",
    "unsupported_samples",
]

FACT_COLS = ["repo_name", "model", "context_variant", "fact", "category",
             "oracle_strict", "oracle_lenient", "rule", "judge_said_missing"]


def load_parsed(name):
    p = os.path.join(CACHE_DIR, name + ".json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return ParsedRepository.model_validate_json(fh.read())


def main():
    c = sqlite3.connect(SRC_DB)
    c.row_factory = sqlite3.Row
    rows = [dict(r) for r in c.execute(
        "SELECT * FROM evaluation_runs WHERE run_status='success' "
        "AND summary_text IS NOT NULL AND summary_text != ''").fetchall()]
    c.close()
    print("loaded %d summaries" % len(rows))

    parses = {}
    fr = open(OUT_ROWS, "w", newline="", encoding="utf-8")
    ff = open(OUT_FACTS, "w", newline="", encoding="utf-8")
    wr = csv.DictWriter(fr, fieldnames=ROW_COLS); wr.writeheader()
    wf = csv.DictWriter(ff, fieldnames=FACT_COLS); wf.writeheader()

    n_facts = 0
    skipped = 0
    for r in rows:
        name = r["repo_name"]
        if name not in parses:
            p = load_parsed(name)
            if p is None:
                print("  SKIP %s -- no cached parse" % name)
                skipped += 1
                continue
            parses[name] = p
        parsed = parses[name]
        summary = r["summary_text"]

        cov = score_coverage_oracle(parsed, summary)
        hal = score_hallucination_oracle(parsed, summary)

        # what the mistral judge claimed was missing, for the fact-level confusion matrix
        try:
            judge_missing = set(json.loads(r["missing_facts_list"] or "[]"))
        except Exception:
            judge_missing = set()

        wr.writerow({
            "repo_name": name, "model": r["model"], "context_variant": r["context_variant"],
            "judge_model": r["judge_model"],
            "total_facts": cov.total_facts,
            "covered_strict": cov.covered_strict, "covered_lenient": cov.covered_lenient,
            "oracle_coverage_strict": cov.coverage_strict,
            "oracle_coverage_lenient": cov.coverage_lenient,
            "judge_coverage_score": r["coverage_score"],
            "judge_coverage_judged": r["coverage_judged"],
            "total_candidates": hal.total_candidates, "supported": hal.supported,
            "unsupported": hal.unsupported,
            "oracle_unsupported_rate": hal.unsupported_identifier_rate,
            "input_tokens": r["input_tokens"], "output_tokens": r["output_tokens"],
            "latency_ms": r["latency_ms"],
            "per_category_strict": json.dumps(cov.per_category_strict),
            "per_category_lenient": json.dumps(cov.per_category_lenient),
            "rule_histogram": json.dumps(cov.rule_histogram),
            "unsupported_samples": json.dumps(hal.unsupported_samples),
        })

        for m in cov.matches:
            wf.writerow({
                "repo_name": name, "model": r["model"],
                "context_variant": r["context_variant"],
                "fact": m.fact, "category": m.category,
                "oracle_strict": int(m.strict), "oracle_lenient": int(m.lenient),
                "rule": m.rule,
                "judge_said_missing": int(m.fact in judge_missing),
            })
            n_facts += 1

    fr.close(); ff.close()
    print("wrote %s  (%d summary rows, %d skipped)" % (OUT_ROWS, len(rows) - skipped, skipped))
    print("wrote %s  (%d fact-level decisions)" % (OUT_FACTS, n_facts))


if __name__ == "__main__":
    main()
