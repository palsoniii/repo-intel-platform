import argparse
import csv
import json
import os
import sqlite3
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

# Use the same loader as harness
from app.evaluation.context_pack import ContextPack

# Defaults derived from this file's location, not the cwd.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
_REPO_DIR = os.path.dirname(_BACKEND_DIR)
_DEFAULT_RESULTS_DIR = os.path.join(_BACKEND_DIR, "evaluation_results")
_DEFAULT_CLAIMS = os.path.join(_DEFAULT_RESULTS_DIR, "human_validation_claims.csv")
_DEFAULT_PACK = os.path.join(_REPO_DIR, "context_pack.json")
_DEFAULT_OUT = os.path.join(_DEFAULT_RESULTS_DIR, "human_review.xlsx")

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
    parser.add_argument("--claims-csv", default=_DEFAULT_CLAIMS)
    # --context-pack is the spelling every other script in the repo uses; --pack is
    # kept because existing runbooks pass it.
    parser.add_argument("--pack", "--context-pack", dest="pack", default=_DEFAULT_PACK)
    parser.add_argument("--out", default=_DEFAULT_OUT)
    args = parser.parse_args()

    if not os.path.exists(args.claims_csv):
        print(f"FATAL: claims CSV not found: {args.claims_csv}", file=sys.stderr)
        print("Run `python -m scripts.rejudge_full_claims` first.", file=sys.stderr)
        return 2

    # Load context pack
    if not os.path.exists(args.pack):
        print(f"FATAL: context pack not found: {args.pack}", file=sys.stderr)
        return 2
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

    # A claims CSV whose every all_claims_list is "[]" (the judge's output never
    # parsed) yields zero rows here. Saving a header-only workbook would look like
    # success and waste the reviewer's time, so stop instead.
    if not rows:
        print(f"FATAL: {args.claims_csv} contains no claims -- nothing to review.",
              file=sys.stderr)
        print("Every all_claims_list is empty, which means the judge's output could not "
              "be parsed. Re-run scripts.rejudge_full_claims and check its "
              "'judge unparseable' count.", file=sys.stderr)
        return 1

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

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    wb.save(args.out)
    print(f"Created review sheet at {args.out}")
    print(f"  {len(rows)} claims across {len(set(r['repo_name'] for r in rows))} repos")
    print(f"Reviewer fills column {verdict_letter} (human_verdict) on the 'Review' sheet. "
          f"Model and context variant are hidden in 'Answer Key' -- do not unhide them "
          f"before scoring.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
