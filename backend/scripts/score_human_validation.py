import argparse
import pandas as pd
from sklearn.metrics import cohen_kappa_score
from scipy.stats import spearmanr
import numpy as np

def main():
    parser = argparse.ArgumentParser(description="Score human validation sheet.")
    parser.add_argument("--sheet", default="evaluation_results/human_review.xlsx")
    args = parser.parse_args()

    try:
        df_review = pd.read_excel(args.sheet, sheet_name="Review")
        df_key = pd.read_excel(args.sheet, sheet_name="Answer Key")
    except Exception as e:
        print(f"Failed to read {args.sheet}: {e}")
        return

    # The two worksheets are joined on row_id, never positionally: a reviewer sorting
    # or deleting rows in Excel would silently misalign a positional join and produce
    # a plausible-looking but wrong kappa.
    for label, df in (("Review", df_review), ("Answer Key", df_key)):
        if "row_id" not in df.columns:
            raise SystemExit(
                f"'{label}' worksheet in {args.sheet} has no 'row_id' column. "
                f"This sheet predates the row_id join -- regenerate it with "
                f"`python -m scripts.build_review_sheet` (note: a sheet already "
                f"hand-scored under the old layout cannot be joined reliably)."
            )

    key_cols = ["row_id", "repo_name", "model", "context_variant", "judge_verdict"]
    missing = [c for c in key_cols if c not in df_key.columns]
    if missing:
        raise SystemExit(f"'Answer Key' worksheet is missing columns: {missing}")

    df_review = df_review.merge(df_key[key_cols], on="row_id", how="left",
                                suffixes=("", "_key"))

    # Grouping keys come from the Answer Key (the Review sheet blanks repeated repo
    # facts and does not carry model/context_variant at all -- it is blinded).
    if "repo_name_key" in df_review.columns:
        df_review["repo_name"] = df_review["repo_name_key"]

    # Filter out empty claims or verdicts
    df_review = df_review.dropna(subset=["human_verdict"])
    if df_review.empty:
        print("No human verdicts found.")
        return

    unjoined = df_review[df_review["judge_verdict"].isna()]
    if not unjoined.empty:
        bad_ids = unjoined["row_id"].tolist()
        raise SystemExit(
            f"{len(unjoined)} scored row(s) have no judge_verdict after joining on "
            f"row_id: {bad_ids[:20]}{' ...' if len(bad_ids) > 20 else ''}. "
            f"Those row_ids are missing from the 'Answer Key' worksheet -- do not "
            f"report agreement from a partial join."
        )

    # Standardize string capitalization and stripping
    df_review['human_verdict'] = df_review['human_verdict'].astype(str).str.strip().str.title()
    df_review['judge_verdict'] = df_review['judge_verdict'].astype(str).str.strip().str.title()

    total_claims = len(df_review)

    # Kappa WITH unsure
    kappa_with = cohen_kappa_score(df_review['human_verdict'], df_review['judge_verdict'])

    # Kappa WITHOUT unsure
    df_filtered = df_review[df_review['human_verdict'] != 'Unsure']
    claims_without_unsure = len(df_filtered)
    if claims_without_unsure > 0:
        kappa_without = cohen_kappa_score(df_filtered['human_verdict'], df_filtered['judge_verdict'])
    else:
        kappa_without = float('nan')

    print(f"--- Claim-Level Agreement ---")
    print(f"Sample size (with 'Unsure'): {total_claims} claims")
    print(f"Cohen's kappa (with 'Unsure'): {kappa_with:.4f}")
    print(f"Sample size (without 'Unsure'): {claims_without_unsure} claims")
    print(f"Cohen's kappa (without 'Unsure'): {kappa_without:.4f}")

    # Spearman correlation
    # We need to compute hallucination score per summary (repo_name, model, context_variant)
    # Hallucination score = fraction of claims that are Unsupported

    groups = df_review.groupby(['repo_name', 'model', 'context_variant'])

    human_scores = []
    judge_scores = []

    for name, group in groups:
        # Exclude 'Unsure' from fraction denominator? Usually yes, or treat as supported?
        # The prompt says: "fraction of that row's claims the human marked Unsupported"
        # Let's compute it strictly as (unsupported / total_decisions)
        h_decisions = group[group['human_verdict'] != 'Unsure']
        if len(h_decisions) == 0:
            continue

        h_score = sum(h_decisions['human_verdict'] == 'Unsupported') / len(h_decisions)

        j_decisions = group[group['judge_verdict'] != 'Unsure']
        if len(j_decisions) == 0:
            continue

        j_score = sum(j_decisions['judge_verdict'] == 'Unsupported') / len(j_decisions)

        human_scores.append(h_score)
        judge_scores.append(j_score)

    if len(human_scores) > 1:
        corr, pval = spearmanr(human_scores, judge_scores)
        print(f"\n--- Summary-Level Hallucination Correlation ---")
        print(f"Sample size: {len(human_scores)} summaries")
        print(f"Spearman correlation: {corr:.4f} (p-value={pval:.4g})")
    else:
        print("\nNot enough summaries with definitive decisions to compute Spearman correlation.")

if __name__ == "__main__":
    main()
