"""
Rejudges existing successful runs for G-Eval quality criteria and text overlap metrics.

BERTScore downloads a model on first use via `default_bert_scorer`. On the cluster
`bert-score` is not installed and the compute nodes have no outbound network, so pass
`--no-bertscore` there: BLEU-4, ROUGE-L and METEOR are still computed and
`bertscore_f1` is left empty.

Resumable: rows already present in the output CSV are skipped on a re-run, so a
walltime kill costs at most the row in flight.

Usage:
  python -m scripts.rejudge_quality_and_overlap
  python -m scripts.rejudge_quality_and_overlap --no-bertscore
"""

import argparse
import csv
import json
import os
import sqlite3
from pathlib import Path

from app.schemas.llm_result import ContextVariant
from app.evaluation.quality_judge import score_summary_quality
from app.evaluation.text_overlap import score_text_overlap, default_bert_scorer

# Paths are derived from this file's location, not the cwd. The script is invoked as
# `python -m scripts.rejudge_quality_and_overlap` from backend/, so a relative
# "backend/reference_summaries" default resolved to backend/backend/... and every row
# failed with FileNotFoundError while the script still exited 0 with an empty CSV.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
_DEFAULT_REF_DIR = os.path.join(_BACKEND_DIR, "reference_summaries")
_DEFAULT_RESULTS_DIR = os.path.join(_BACKEND_DIR, "evaluation_results")

# model -> battery DB filename. Absolute paths are built against --results-dir.
DB_STEMS = {
    "codellama:13b-instruct": "battery_codellama13b.db",
    "qwen2.5-coder:14b": "battery_qwen14b.db",
    "qwen2.5-coder:32b": "battery_qwen32b.db"
}

DB_FILES = {
    model: os.path.join(_DEFAULT_RESULTS_DIR, stem)
    for model, stem in DB_STEMS.items()
}

def load_reference(repo_name: str, ref_dir: str = _DEFAULT_REF_DIR) -> str:
    path = os.path.join(ref_dir, f"{repo_name}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Missing reference summary for {repo_name}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        return data.get("overview", "")

def bootstrap_nltk() -> None:
    """METEOR needs NLTK's wordnet corpus and nothing else in this repo downloads it.
    A failure here is not fatal: BLEU-4 and ROUGE-L do not need wordnet, and METEOR
    will surface its own per-row error rather than killing the run."""
    try:
        import nltk
        nltk.download("wordnet", quiet=True)
        nltk.download("omw-1.4", quiet=True)
    except Exception as e:
        print(f"WARNING: could not download NLTK wordnet corpora ({e}). "
              f"METEOR may fail; BLEU-4 and ROUGE-L are unaffected.")

def main():
    parser = argparse.ArgumentParser(description="Rejudge quality and overlap metrics.")
    parser.add_argument("--ref-dir", default=_DEFAULT_REF_DIR)
    parser.add_argument("--results-dir", default=_DEFAULT_RESULTS_DIR,
                        help="Directory holding the battery_*.db inputs and the output CSVs.")
    parser.add_argument("--no-bertscore", action="store_true",
                        help="Skip BERTScore (bertscore_f1 left empty). Required on the "
                             "cluster: bert-score is not installed there and its model "
                             "(distilbert-base-uncased) cannot be downloaded from a "
                             "network-isolated node unless the HF cache is pre-staged.")
    args = parser.parse_args()

    bootstrap_nltk()

    bert_scorer = None if args.no_bertscore else default_bert_scorer
    if args.no_bertscore:
        print("BERTScore disabled (--no-bertscore); BLEU-4, ROUGE-L and METEOR still computed.")

    db_files = {
        model: os.path.join(args.results_dir, stem)
        for model, stem in DB_STEMS.items()
    }

    judge_model = "gemma2:9b"

    for model_name, db_path in db_files.items():
        if not os.path.exists(db_path):
            print(f"Skipping {model_name}, DB not found: {db_path}")
            continue

        csv_name = f"quality_and_overlap_{model_name.replace(':', '_').replace('.', '_')}.csv"
        csv_out = os.path.join(args.results_dir, csv_name)

        # Load processed
        processed = set()
        if os.path.exists(csv_out):
            with open(csv_out, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    processed.add((row["repo_name"], row["context_variant"]))

        # Open DB
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Expecting the table name to be `evaluations` or similar. We can dynamically check
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        table_name = "evaluation_runs"
        if table_name not in tables:
            if tables:
                table_name = tables[0]
            else:
                print(f"No tables in {db_path}")
                continue

        try:
            # We don't assume column names for variant, model etc if they might slightly differ,
            # but standard is repo_name, model, context_variant, run_status, summary_text
            cur.execute(f"SELECT repo_name, model, context_variant, summary_text FROM {table_name} WHERE run_status = 'success'")
            rows = cur.fetchall()
        except sqlite3.OperationalError as e:
            print(f"Error querying {db_path}: {e}")
            continue

        file_exists = os.path.exists(csv_out)
        os.makedirs(args.results_dir, exist_ok=True)
        out_f = open(csv_out, "a", newline="", encoding="utf-8")
        writer = csv.DictWriter(out_f, fieldnames=[
            "repo_name", "model", "context_variant",
            "quality_mean_score", "quality_completeness", "quality_conciseness",
            "quality_correctness", "quality_cohesiveness", "quality_domain_specificity",
            "bleu4", "rouge_l", "meteor", "bertscore_f1"
        ])

        if not file_exists:
            writer.writeheader()

        for row in rows:
            repo_name = row["repo_name"]
            variant_str = row["context_variant"]
            summary = row["summary_text"]
            model = row["model"]

            if (repo_name, variant_str) in processed:
                continue

            print(f"Judging {repo_name} ({variant_str}) for {model}...")

            # 1. Quality
            try:
                variant_enum = ContextVariant(variant_str)
                quality_res = score_summary_quality(
                    repo_name=repo_name,
                    context_variant=variant_enum,
                    summary_text=summary,
                    judge_model=judge_model
                )
            except Exception as e:
                print(f"Quality scoring failed for {repo_name} {variant_str}: {e}")
                continue

            # 2. Overlap
            # An overlap failure must NOT discard quality_res. G-Eval is the expensive
            # half (one judge call per row) and has already been paid for by this point,
            # so write the row with empty overlap columns instead of dropping it.
            try:
                ref_text = load_reference(repo_name, args.ref_dir)
                overlap_res = score_text_overlap(
                    repo_name=repo_name,
                    context_variant=variant_enum,
                    summary_text=summary,
                    reference_overview=ref_text,
                    bert_scorer=bert_scorer
                )
            except Exception as e:
                print(f"Overlap scoring failed for {repo_name} {variant_str}: {e} "
                      f"-- keeping the G-Eval scores, overlap columns left empty.")
                overlap_res = None

            out_row = {
                "repo_name": repo_name,
                "model": model,
                "context_variant": variant_str,
                "quality_mean_score": quality_res.mean_score,
                "quality_completeness": quality_res.scores.get("completeness").score if "completeness" in quality_res.scores else None,
                "quality_conciseness": quality_res.scores.get("conciseness").score if "conciseness" in quality_res.scores else None,
                "quality_correctness": quality_res.scores.get("correctness").score if "correctness" in quality_res.scores else None,
                "quality_cohesiveness": quality_res.scores.get("cohesiveness").score if "cohesiveness" in quality_res.scores else None,
                "quality_domain_specificity": quality_res.scores.get("domain_specificity").score if "domain_specificity" in quality_res.scores else None,
                "bleu4": overlap_res.bleu4 if overlap_res is not None else None,
                "rouge_l": overlap_res.rouge_l if overlap_res is not None else None,
                "meteor": overlap_res.meteor if overlap_res is not None else None,
                "bertscore_f1": overlap_res.bertscore_f1 if overlap_res is not None else None
            }
            writer.writerow(out_row)
            out_f.flush()
            processed.add((repo_name, variant_str))

        out_f.close()

if __name__ == "__main__":
    main()
