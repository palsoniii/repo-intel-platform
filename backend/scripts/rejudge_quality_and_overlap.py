"""
Rejudges existing successful runs for G-Eval quality criteria and text overlap metrics.
Downloads a BERTScore model on first use via `default_bert_scorer`.

Usage:
  python -m scripts.rejudge_quality_and_overlap
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

DB_FILES = {
    "codellama:13b-instruct": "evaluation_results/battery_codellama13b.db",
    "qwen2.5-coder:14b": "evaluation_results/battery_qwen14b.db",
    "qwen2.5-coder:32b": "evaluation_results/battery_qwen32b.db"
}

def load_reference(repo_name: str, ref_dir: str = "backend/reference_summaries") -> str:
    path = os.path.join(ref_dir, f"{repo_name}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Missing reference summary for {repo_name}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        return data.get("overview", "")

def main():
    parser = argparse.ArgumentParser(description="Rejudge quality and overlap metrics.")
    parser.add_argument("--ref-dir", default="backend/reference_summaries")
    args = parser.parse_args()

    judge_model = "gemma2:9b"
    
    for model_name, db_path in DB_FILES.items():
        if not os.path.exists(db_path):
            print(f"Skipping {model_name}, DB not found: {db_path}")
            continue
            
        csv_out = f"evaluation_results/quality_and_overlap_{model_name.replace(':', '_').replace('.', '_')}.csv"
        
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
            try:
                ref_text = load_reference(repo_name, args.ref_dir)
                overlap_res = score_text_overlap(
                    repo_name=repo_name,
                    context_variant=variant_enum,
                    summary_text=summary,
                    reference_overview=ref_text,
                    bert_scorer=default_bert_scorer
                )
            except Exception as e:
                print(f"Overlap scoring failed for {repo_name} {variant_str}: {e}")
                continue
                
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
                "bleu4": overlap_res.bleu4,
                "rouge_l": overlap_res.rouge_l,
                "meteor": overlap_res.meteor,
                "bertscore_f1": overlap_res.bertscore_f1
            }
            writer.writerow(out_row)
            out_f.flush()
            processed.add((repo_name, variant_str))
            
        out_f.close()

if __name__ == "__main__":
    main()
