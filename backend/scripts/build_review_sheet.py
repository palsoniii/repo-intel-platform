import argparse
import csv
import json
import os
import sqlite3
from pathlib import Path

from openpyxl import Workbook
from openpyxl.worksheet.datavalidation import DataValidation

# Use the same loader as harness
from app.evaluation.context_pack import ContextPack

def main():
    parser = argparse.ArgumentParser(description="Build human review excel sheet.")
    parser.add_argument("--claims-csv", default="evaluation_results/human_validation_claims.csv")
    parser.add_argument("--pack", default="context_pack.json")
    parser.add_argument("--out", default="evaluation_results/human_review.xlsx")
    args = parser.parse_args()
    
    if not os.path.exists(args.claims_csv):
        print(f"File {args.claims_csv} not found.")
        return

    # Load context pack
    if not os.path.exists(args.pack):
        print(f"Context pack {args.pack} not found.")
        return
    pack = ContextPack.read(args.pack)
    
    # Fast lookup for repo facts
    repo_facts = {}
    for repo in pack.repositories:
        name = repo.parsed.metadata.name
        framework = getattr(repo.parsed.metadata, 'framework', 'Unknown')
        deps = ", ".join([d.name for d in repo.parsed.dependencies.external])
        endpoints = []
        for mod in repo.parsed.modules:
            for cls in mod.classes:
                for ep in cls.endpoints:
                    endpoints.append(f"{ep.method.upper()} {ep.path}")
        repo_facts[name] = {
            "framework": framework,
            "deps": deps,
            "endpoints": "\n".join(endpoints) if endpoints else "None"
        }

    # Read claims
    rows = []
    with open(args.claims_csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    # Sort by repo_name, then by claim_text
    rows.sort(key=lambda x: (x.get('repo_name', ''), x.get('claim_text', '')))

    wb = Workbook()
    ws_review = wb.active
    ws_review.title = "Review"
    ws_key = wb.create_sheet(title="Answer Key")
    ws_key.sheet_state = 'hidden'

    headers_review = ["repo_name", "framework", "known_dependencies", "known_endpoints", "model", "context_variant", "claim_text", "human_verdict"]
    headers_key = headers_review + ["judge_verdict"]

    ws_review.append(headers_review)
    ws_key.append(headers_key)

    # Dropdown for human_verdict
    dv = DataValidation(type="list", formula1='"Supported,Unsupported,Unsure"', allow_blank=True)
    ws_review.add_data_validation(dv)

    last_repo = None
    for row_idx, row in enumerate(rows, start=2): # 1-indexed, header is row 1
        repo_name = row.get('repo_name', '')
        model = row.get('model', '')
        variant = row.get('context_variant', '')
        claim_text = row.get('claim_text', '')
        judge_verdict = row.get('judge_verdict', '')

        # Grouping display logic (blank out if same repo)
        if repo_name == last_repo:
            disp_framework = ""
            disp_deps = ""
            disp_endpoints = ""
        else:
            facts = repo_facts.get(repo_name, {})
            disp_framework = facts.get("framework", "")
            disp_deps = facts.get("deps", "")
            disp_endpoints = facts.get("endpoints", "")

        review_row = [
            repo_name, disp_framework, disp_deps, disp_endpoints, model, variant, claim_text, ""
        ]
        key_row = review_row + [judge_verdict]

        ws_review.append(review_row)
        ws_key.append(key_row)

        dv.add(f"H{row_idx}") # Column H is human_verdict

        last_repo = repo_name

    # Basic formatting
    ws_review.column_dimensions['A'].width = 25 # repo_name
    ws_review.column_dimensions['C'].width = 30 # dependencies
    ws_review.column_dimensions['D'].width = 40 # endpoints
    ws_review.column_dimensions['G'].width = 60 # claim_text
    ws_review.column_dimensions['H'].width = 15 # human_verdict
    
    # Enable text wrap on endpoints and claims
    from openpyxl.styles import Alignment
    for row_idx in range(2, len(rows) + 2):
        ws_review.cell(row=row_idx, column=4).alignment = Alignment(wrap_text=True) # D
        ws_review.cell(row=row_idx, column=7).alignment = Alignment(wrap_text=True) # G

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    wb.save(args.out)
    print(f"Created review sheet at {args.out}")

if __name__ == "__main__":
    main()
