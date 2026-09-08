"""De-duplicates rejudge output on (repo_name, model, context_variant).

`scripts.rejudge`'s judge phase appends to rejudge_<judge>_<arm>.{db,csv} and
resumes from the .db. If that resume does not engage -- a deleted .db, a second
launch of the same job -- the same combos are judged again and appended, and any
average computed from the file is then weighted by how many times each row
happened to be re-judged.

This keeps the LAST row per key (most recent judged_at wins, so a retry supersedes
the failure it replaced) and rewrites both files. Idempotent.

    python -m scripts.dedupe_rejudge                     # every rejudge_*.db in evaluation_results
    python -m scripts.dedupe_rejudge --db path/to/one.db  # just one
    python -m scripts.dedupe_rejudge --dry-run
"""

from __future__ import annotations

import argparse
import csv
import glob
import os
import shutil
import sqlite3
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
_DEFAULT_RESULTS_DIR = os.path.join(_BACKEND_DIR, "evaluation_results")

KEY = ("repo_name", "model", "context_variant")


def dedupe_one(db_path: str, dry_run: bool = False) -> tuple[int, int]:
    """Returns (rows_before, rows_after)."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(rejudged)")]
    except sqlite3.OperationalError:
        conn.close()
        raise SystemExit(f"{db_path}: no 'rejudged' table")
    if not cols:
        conn.close()
        raise SystemExit(f"{db_path}: no 'rejudged' table")

    rows = [dict(r) for r in conn.execute("SELECT rowid AS _rowid, * FROM rejudged")]
    before = len(rows)

    # Last write wins. rowid is insertion order, which is the tiebreak when two rows
    # share a judged_at second.
    keep: dict[tuple, dict] = {}
    for r in sorted(rows, key=lambda r: (r.get("judged_at") or "", r["_rowid"])):
        keep[tuple(r.get(k) for k in KEY)] = r
    after = len(keep)

    if before == after:
        conn.close()
        return before, after

    if dry_run:
        conn.close()
        return before, after

    ordered = sorted(keep.values(), key=lambda r: r["_rowid"])
    shutil.copy2(db_path, db_path + ".predupe")
    conn.execute("DELETE FROM rejudged")
    conn.executemany(
        "INSERT INTO rejudged (%s) VALUES (%s)"
        % (",".join(cols), ",".join(["?"] * len(cols))),
        [[r.get(c) for c in cols] for r in ordered],
    )
    conn.commit()
    conn.close()

    csv_path = os.path.splitext(db_path)[0] + ".csv"
    if os.path.exists(csv_path):
        shutil.copy2(csv_path, csv_path + ".predupe")
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in ordered:
                w.writerow({c: ("" if r.get(c) is None else r[c]) for c in cols})

    return before, after


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results-dir", default=_DEFAULT_RESULTS_DIR)
    ap.add_argument("--db", action="append", default=[],
                    help="A specific rejudge_*.db (repeatable). Default: all in --results-dir.")
    ap.add_argument("--dry-run", action="store_true", help="Report only, change nothing.")
    a = ap.parse_args()

    targets = a.db or sorted(glob.glob(os.path.join(a.results_dir, "rejudge_*.db")))
    if not targets:
        print(f"No rejudge_*.db found in {a.results_dir}", file=sys.stderr)
        return 1

    total_removed = 0
    for db in targets:
        before, after = dedupe_one(db, a.dry_run)
        removed = before - after
        total_removed += removed
        verb = "would remove" if (a.dry_run and removed) else ("removed" if removed else "clean")
        print(f"  {os.path.basename(db):<52} {before:4d} -> {after:4d} rows  ({verb} {removed})")

    if total_removed and not a.dry_run:
        print(f"\nRemoved {total_removed} duplicate row(s). Originals kept as *.predupe.")
    elif total_removed:
        print(f"\n{total_removed} duplicate row(s) present. Re-run without --dry-run to fix.")
    else:
        print("\nNo duplicates.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
