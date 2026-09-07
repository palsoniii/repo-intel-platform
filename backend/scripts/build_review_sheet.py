import argparse
import csv
import json
import os
import sqlite3
from pathlib import Path

from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

# Use the same loader as harness
from app.evaluation.context_pack import ContextPack

# The visible sheet is BLINDED: `model` and `context_variant` are deliberately absent
# so a reviewer cannot see which arm produced a claim. They live in the hidden
# "Answer Key" worksheet only, joined back by `row_id`.
HEADERS_REVIEW = ["row_id", "repo_name", "framework", "known_dependencies",
                  "known_endpoints", "claim_text", "human_verdict"]
HEADERS_KEY = ["row_id", "repo_name", "framework", "known_dependencies",
               "known_endpoints", "model", "context_variant", "claim_text",
               "human_verdict", "judge_verdict"]


def main():
    parser = argparse.ArgumentParser(description="Build human review excel sheet.")
    parser.add_argument("--claims-csv", default="evaluation_results/human_validation_claims.csv")
    # --context-pack is the spelling every other script in the repo uses; --pack is
    # kept because existing runbooks pass it.
    parser.add_argument("--pack", "--context-pack", dest="pack", default="context_pack.json")
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
        framework = repo.parsed.metadata.detected_framework
        deps = ", ".join([d.name for d in repo.parsed.dependencies.external])
        endpoints = []
        for ep in repo.parsed.api_endpoints:
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
            all_claims_raw = row.get("all_claims_list", "[]")
            try:
                claims = json.loads(all_claims_raw)
            except json.JSONDecodeError:
                claims = []

            for c in claims:
                text = c.get("text", "")
                supported = c.get("supported", False)
                # Map boolean to judge verdict string
                judge_verdict = "Supported" if supported else "Unsupported"

                rows.append({
                    "repo_name": row.get("repo_name", ""),
                    "model": row.get("model", ""),
                    "context_variant": row.get("context_variant", ""),
                    "claim_text": text,
                    "judge_verdict": judge_verdict
                })

    # Sort by repo_name, then by claim_text
    rows.sort(key=lambda x: (x.get('repo_name', ''), x.get('claim_text', '')))

    # row_id is assigned AFTER the sort so it is stable for the join in
    # score_human_validation.py even if the reviewer re-sorts the sheet in Excel.
    for i, row in enumerate(rows, start=1):
        row["row_id"] = i

    wb = Workbook()
    ws_review = wb.active
    ws_review.title = "Review"
    ws_key = wb.create_sheet(title="Answer Key")
    ws_key.sheet_state = 'hidden'

    headers_review = list(HEADERS_REVIEW)
    headers_key = list(HEADERS_KEY)

    ws_review.append(headers_review)
    ws_key.append(headers_key)

    # Column letters are computed from the header positions, never hardcoded, so the
    # dropdown and the widths stay attached to their columns if the layout changes.
    col_review = {name: idx for idx, name in enumerate(headers_review, start=1)}
    verdict_letter = get_column_letter(col_review["human_verdict"])

    # Dropdown for human_verdict
    dv = DataValidation(type="list", formula1='"Supported,Unsupported,Unsure"', allow_blank=True)
    ws_review.add_data_validation(dv)

    last_repo = None
    for row_idx, row in enumerate(rows, start=2): # 1-indexed, header is row 1
        row_id = row.get('row_id')
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
            row_id, repo_name, disp_framework, disp_deps, disp_endpoints, claim_text, ""
        ]
        # The key sheet keeps the un-blanked repo facts plus model/variant/judge_verdict.
        key_row = [
            row_id, repo_name, disp_framework, disp_deps, disp_endpoints,
            model, variant, claim_text, "", judge_verdict
        ]

        ws_review.append(review_row)
        ws_key.append(key_row)

        dv.add(f"{verdict_letter}{row_idx}")

        last_repo = repo_name

    # Basic formatting
    widths = {
        "row_id": 8,
        "repo_name": 25,
        "known_dependencies": 30,
        "known_endpoints": 40,
        "claim_text": 60,
        "human_verdict": 15,
    }
    for name, width in widths.items():
        ws_review.column_dimensions[get_column_letter(col_review[name])].width = width

    # Enable text wrap on endpoints and claims
    from openpyxl.styles import Alignment
    wrap_cols = [col_review["known_endpoints"], col_review["claim_text"]]
    for row_idx in range(2, len(rows) + 2):
        for col in wrap_cols:
            ws_review.cell(row=row_idx, column=col).alignment = Alignment(wrap_text=True)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    wb.save(args.out)
    print(f"Created review sheet at {args.out}")
    print(f"Reviewer fills column {verdict_letter} (human_verdict) on the 'Review' sheet. "
          f"Model and context variant are hidden in 'Answer Key' -- do not unhide them "
          f"before scoring.")

if __name__ == "__main__":
    main()
