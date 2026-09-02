#!/usr/bin/env python3
"""
Generate parse_cache JSON files from context_pack.json.

Run this ONCE on the cluster (in the Jupyter setup job) before submitting
rejudge jobs.  It requires zero network access, zero Neo4j, zero tree-sitter.

Usage (from anywhere):
    python hpc/generate_parse_cache.py \
        --pack /data/mpstme-dishank/context_pack.json \
        --out  /data/mpstme-dishank/evaluation_results/parse_cache
"""
import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pack", required=True,
                    help="Path to context_pack.json")
    ap.add_argument("--out", required=True,
                    help="Directory to write <repo_name>.json files into")
    args = ap.parse_args()

    pack_path = Path(args.pack)
    out_dir   = Path(args.out)

    if not pack_path.exists():
        print(f"ERROR: context pack not found at {pack_path}", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    pack = json.loads(pack_path.read_text(encoding="utf-8"))

    repos = pack.get("repositories", [])
    if not repos:
        print("ERROR: no repositories in context pack", file=sys.stderr)
        return 1

    written = skipped = 0
    for repo in repos:
        parsed = repo.get("parsed")
        if not parsed:
            print(f"  SKIP (no parsed block): {repo.get('url', '?')}")
            skipped += 1
            continue
        name = parsed.get("metadata", {}).get("name") or parsed.get("name", "")
        if not name:
            print(f"  SKIP (no name): {repo.get('url', '?')}")
            skipped += 1
            continue
        dest = out_dir / f"{name}.json"
        dest.write_text(json.dumps(parsed, ensure_ascii=False), encoding="utf-8")
        print(f"  wrote {dest.name}  ({dest.stat().st_size // 1024} KB)")
        written += 1

    print(f"\nDone: {written} written, {skipped} skipped -> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
