#!/usr/bin/env python3
"""Human-validation export — fixed-seed N=40 sample for hand-scoring.

Draws from the three new battery DBs (codellama13b, qwen14b, qwen32b).
Output: evaluation_results/human_validation_sample_final.csv

Does NOT overwrite the existing human_validation_sample.csv (drawn from Run 2).

CPU-only, off-cluster. Run from backend/:

    python -m scripts.export_human_validation

Or with explicit paths:

    python -m scripts.export_human_validation --results /path/to/evaluation_results
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sqlite3
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_RESULTS = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "evaluation_results"))

SEED = 42
N = 40

NEW_DBS = [
    "battery_codellama13b.db",
    "battery_qwen14b.db",
    "battery_qwen32b.db",
]

OUT_COLS = [
    "repo_name",
    "source_url",
    "framework",
    "model",
    "context_variant",
    "judge_model",
    "summary_text",
    "coverage_score",
    "hallucination_score",
    "total_facts",
    "missing_facts",
    "missing_facts_list",
    "total_claims",
    "unsupported_claims",
    "input_tokens",
    "output_tokens",
    "run_at",
    # Annotator columns (blank — to be filled by hand-scorer)
    "human_coverage_verdict",    # 'correct' / 'over' / 'under' / 'wrong'
    "human_hallucination_verdict",  # 'clean' / 'minor' / 'major'
    "notes",
]


def load_db(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM evaluation_runs "
            "WHERE run_status='success' AND summary_text IS NOT NULL AND summary_text != ''"
        ).fetchall()]
    except Exception as e:
        print(f"  WARNING: could not read {path}: {e}", file=sys.stderr)
        rows = []
    c.close()
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results", default=_DEFAULT_RESULTS,
                    help="Path to evaluation_results directory")
    ap.add_argument("--n", type=int, default=N, help="Sample size (default 40)")
    ap.add_argument("--seed", type=int, default=SEED, help="Random seed (default 42)")
    a = ap.parse_args()

    R = os.path.abspath(a.results)
    out_path = os.path.join(R, "human_validation_sample_final.csv")

    if os.path.exists(out_path):
        print(f"ERROR: {out_path} already exists. Delete it first if you want to regenerate.", file=sys.stderr)
        sys.exit(1)

    all_rows: list[dict] = []
    for db_file in NEW_DBS:
        path = os.path.join(R, db_file)
        rows = load_db(path)
        if not rows:
            print(f"  WARNING: {db_file} not found or empty — skipped")
        else:
            print(f"  {db_file}: {len(rows)} rows")
            all_rows.extend(rows)

    if not all_rows:
        print(
            "ERROR: no rows loaded from any new battery DB.\n"
            "Run the battery jobs on the cluster and copy the output DBs to:\n"
            f"  {R}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Stratified sample: draw proportionally from each (model, context_variant) cell
    # so every arm and representation has coverage, then top up / trim to N.
    rng = random.Random(a.seed)

    cells: dict[tuple, list[dict]] = {}
    for r in all_rows:
        key = (r.get("model", "?"), r.get("context_variant", "?"))
        cells.setdefault(key, []).append(r)

    sample: list[dict] = []
    per_cell = max(1, a.n // len(cells))
    for key, cell_rows in sorted(cells.items()):
        chosen = rng.sample(cell_rows, min(per_cell, len(cell_rows)))
        sample.extend(chosen)

    # Trim or top up to exactly N
    rng.shuffle(sample)
    if len(sample) > a.n:
        sample = sample[: a.n]
    elif len(sample) < a.n:
        remaining = [r for r in all_rows if r not in sample]
        rng.shuffle(remaining)
        sample.extend(remaining[: a.n - len(sample)])

    sample.sort(key=lambda r: (r.get("model", ""), r.get("context_variant", ""), r.get("repo_name", "")))

    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=OUT_COLS, extrasaction="ignore")
        w.writeheader()
        for r in sample:
            # Blank the annotator columns
            r["human_coverage_verdict"] = ""
            r["human_hallucination_verdict"] = ""
            r["notes"] = ""
            w.writerow(r)

    print(f"\nWrote {len(sample)} rows → {out_path}")
    print(f"Seed: {a.seed}  |  Cells sampled: {len(cells)}")


if __name__ == "__main__":
    main()
