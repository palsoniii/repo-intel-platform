"""Full-claims rejudge for the human-validation sample.

Reads stored summary_text out of a battery DB (no summaries are regenerated) and
re-scores each sampled row with the per-claim hallucination prompt, so every claim
the judge considered is recorded with its supported/unsupported verdict.

Resumable: rows already present in --out are skipped, keyed on
(repo_name, model, context_variant).

Run from backend/:

    python -m scripts.rejudge_full_claims \
      --src-db evaluation_results/battery_qwen14b.db \
      --sample-csv evaluation_results/human_validation_sample_final.csv \
      --context-pack ../context_pack.json \
      --judge gemma2:9b
"""

import argparse
import csv
import json
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

from app.evaluation.hallucination import score_summary
from app.providers.ollama_provider import OllamaProvider
from app.schemas.llm_result import ContextVariant
from app.evaluation.context_pack import ContextPack

# Defaults are derived from this file's location, not the cwd, so the script works
# from any directory instead of silently writing to the wrong place.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
_REPO_DIR = os.path.dirname(_BACKEND_DIR)
_DEFAULT_RESULTS_DIR = os.path.join(_BACKEND_DIR, "evaluation_results")
_DEFAULT_OUT = os.path.join(_DEFAULT_RESULTS_DIR, "human_validation_claims.csv")
_DEFAULT_PACK = os.path.join(_REPO_DIR, "context_pack.json")

FIELDNAMES = ["repo_name", "model", "context_variant", "all_claims_list",
              "total_claims", "judged"]


def load_manifest(csv_path: str) -> list[dict]:
    rows = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = [c for c in ("repo_name", "model", "context_variant")
                   if c not in (reader.fieldnames or [])]
        if missing:
            raise SystemExit(
                f"FATAL: {csv_path} is missing required column(s): {missing}. "
                f"Generate the sample with `python -m scripts.export_human_validation`."
            )
        for r in reader:
            rows.append({
                "repo_name": r["repo_name"],
                "model": r["model"],
                "context_variant": r["context_variant"]
            })
    return rows

def load_summaries(db_path: str, manifest: list[dict]) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Check table name
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    table_name = "evaluation_runs"
    if table_name not in tables and tables:
        table_name = tables[0]

    try:
        cur.execute(f"SELECT repo_name, model, context_variant, summary_text FROM {table_name} WHERE run_status = 'success'")
    except Exception as e:
        print(f"Failed querying db {db_path}: {e}")
        return {}

    summaries = {}
    for r in cur.fetchall():
        key = (r["repo_name"], r["model"], r["context_variant"])
        summaries[key] = r["summary_text"]

    return summaries

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src-db", required=True, help="Database to read summaries from (e.g. battery_qwen14b.db)")
    ap.add_argument("--sample-csv", required=True, help="Manifest CSV with repo_name, model, context_variant")
    ap.add_argument("--context-pack", "--pack", dest="context_pack", default=_DEFAULT_PACK,
                    help="Path to context_pack.json")
    ap.add_argument("--out", default=_DEFAULT_OUT)
    ap.add_argument("--judge", default="gemma2:9b")
    a = ap.parse_args()

    for label, path in (("--src-db", a.src_db), ("--sample-csv", a.sample_csv),
                        ("--context-pack", a.context_pack)):
        if not os.path.exists(path):
            print(f"FATAL: {label} not found: {path}", file=sys.stderr)
            return 2

    manifest = load_manifest(a.sample_csv)
    summaries = load_summaries(a.src_db, manifest)
    src_stem = os.path.splitext(os.path.basename(a.src_db))[0]
    print(f"manifest rows: {len(manifest)}   summaries in {src_stem}: {len(summaries)}")

    pack = ContextPack.read(a.context_pack)
    parsed_repos = {repo.parsed.metadata.name: repo.parsed for repo in pack.repositories}
    print(f"repos in context pack: {len(parsed_repos)}")

    provider = OllamaProvider()

    # An --out written by an older version has only the first four columns. Reuse the
    # existing header rather than appending wider rows into it, which would misalign
    # every column for the reader downstream.
    existing_header = None
    if os.path.exists(a.out) and os.path.getsize(a.out) > 0:
        with open(a.out, "r", newline="", encoding="utf-8") as f:
            existing_header = next(csv.reader(f), None)

    processed = set()
    if existing_header:
        with open(a.out, "r", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                processed.add((r["repo_name"], r["model"], r["context_variant"]))

    fieldnames = existing_header if existing_header else FIELDNAMES
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)

    out_f = open(a.out, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(out_f, fieldnames=fieldnames, extrasaction="ignore")
    if not existing_header:
        writer.writeheader()

    n_written = n_skipped = n_no_summary = n_no_repo = n_error = n_unjudged = 0
    n_claims = 0

    for item in manifest:
        key = (item["repo_name"], item["model"], item["context_variant"])
        if key in processed:
            print(f"Skipping {key}, already processed.")
            n_skipped += 1
            continue

        summary_text = summaries.get(key)
        if not summary_text:
            # Expected: the manifest spans all three battery DBs, so each run only
            # finds its own arm's rows here.
            n_no_summary += 1
            continue

        parsed = parsed_repos.get(item["repo_name"])
        if not parsed:
            print(f"Skipping {key}, repo not found in context pack.")
            n_no_repo += 1
            continue

        print(f"Scoring {key}...")
        variant_enum = ContextVariant(item["context_variant"])

        try:
            result = score_summary(
                provider=provider,
                parsed=parsed,
                summary_text=summary_text,
                context_variant=variant_enum,
                judge_model=a.judge
            )

            # judged=False means the judge's output could not be parsed into the
            # expected shape; all_claims is then empty. Recording it keeps the failure
            # visible instead of writing an innocuous-looking "[]" row.
            if not result.judged or not result.all_claims:
                n_unjudged += 1
                print(f"  WARNING: {key} produced NO claims (judged={result.judged}). "
                      f"Raw judge output starts: {result.judge_raw_output[:120]!r}")

            out_row = {
                "repo_name": item["repo_name"],
                "model": item["model"],
                "context_variant": item["context_variant"],
                "all_claims_list": json.dumps(result.all_claims),
                "total_claims": result.total_claims,
                "judged": int(bool(result.judged)),
            }
            writer.writerow(out_row)
            out_f.flush()
            processed.add(key)
            n_written += 1
            n_claims += len(result.all_claims)
        except Exception as e:
            print(f"Error scoring {key}: {e}")
            n_error += 1

    out_f.close()

    print(f"\n--- {src_stem} summary ---")
    print(f"  rows written        : {n_written}  ({n_claims} claims)")
    print(f"  already processed   : {n_skipped}")
    print(f"  no summary in this db: {n_no_summary}")
    print(f"  repo not in pack    : {n_no_repo}")
    print(f"  judge unparseable   : {n_unjudged}")
    print(f"  errors              : {n_error}")
    print(f"Done. Wrote to {a.out}")

    # Fail loudly rather than leaving a plausible-looking empty file behind.
    if n_written == 0 and n_skipped == 0:
        print(f"FATAL: scored nothing from {src_stem}. Every manifest row was skipped "
              f"or errored -- check the counts above.", file=sys.stderr)
        return 1
    if n_written > 0 and n_claims == 0:
        print(f"FATAL: {n_written} row(s) scored but the judge returned zero claims for "
              f"all of them. The review sheet would be empty. Check that '{a.judge}' is "
              f"loaded and answering in the expected JSON shape.", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
