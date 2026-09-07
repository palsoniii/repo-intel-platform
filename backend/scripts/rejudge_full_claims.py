import argparse
import csv
import json
import os
import sqlite3
from collections import defaultdict
from pathlib import Path

from app.evaluation.hallucination import score_summary
from app.providers.ollama_provider import OllamaProvider
from app.schemas.llm_result import ContextVariant
from app.evaluation.context_pack import ContextPack

def load_manifest(csv_path: str) -> list[dict]:
    rows = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
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
    table_name = "evaluations"
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--src-db", required=True, help="Database to read summaries from (e.g. battery_v2.db)")
    ap.add_argument("--sample-csv", required=True, help="Manifest CSV with repo_name, model, context_variant")
    ap.add_argument("--context-pack", default="context_pack.json", help="Path to context_pack.json")
    ap.add_argument("--out", default="evaluation_results/human_validation_claims.csv")
    ap.add_argument("--judge", default="gemma2:9b")
    a = ap.parse_args()

    manifest = load_manifest(a.sample_csv)
    summaries = load_summaries(a.src_db, manifest)
    
    pack = ContextPack.read(a.context_pack)
    parsed_repos = {repo.parsed.metadata.name: repo.parsed for repo in pack.repositories}
    
    provider = OllamaProvider()

    processed = set()
    if os.path.exists(a.out):
        with open(a.out, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                processed.add((r["repo_name"], r["model"], r["context_variant"]))

    file_exists = os.path.exists(a.out)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    
    out_f = open(a.out, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(out_f, fieldnames=["repo_name", "model", "context_variant", "all_claims_list"])
    if not file_exists:
        writer.writeheader()

    for item in manifest:
        key = (item["repo_name"], item["model"], item["context_variant"])
        if key in processed:
            print(f"Skipping {key}, already processed.")
            continue
            
        summary_text = summaries.get(key)
        if not summary_text:
            print(f"Skipping {key}, no successful summary found in DB.")
            continue
            
        parsed = parsed_repos.get(item["repo_name"])
        if not parsed:
            print(f"Skipping {key}, repo not found in context pack.")
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
            
            out_row = {
                "repo_name": item["repo_name"],
                "model": item["model"],
                "context_variant": item["context_variant"],
                "all_claims_list": json.dumps(result.all_claims)
            }
            writer.writerow(out_row)
            out_f.flush()
            processed.add(key)
        except Exception as e:
            print(f"Error scoring {key}: {e}")

    out_f.close()
    print(f"Done. Wrote to {a.out}")

if __name__ == "__main__":
    main()
