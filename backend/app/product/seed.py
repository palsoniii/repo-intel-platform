"""
Pre-analyse the demo repositories so the presentation never waits on a clone or the
model:

    python -m app.product.seed                # every URL in ../demo_repos.txt
    python -m app.product.seed URL [URL ...]  # just these
    python -m app.product.seed --force        # re-analyse even if already stored

Runs in-process against the same SQLite store the API serves from, one repository at
a time (summaries included), and prints a line per repository.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

DEMO_LIST = Path(__file__).resolve().parents[3] / "demo_repos.txt"


def main(argv: list[str] | None = None) -> int:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    from app.acquisition.clone import validate_github_url
    from app.product import jobs, store

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("urls", nargs="*")
    parser.add_argument("--force", action="store_true", help="re-analyse repositories already stored")
    parser.add_argument("--no-summary", action="store_true", help="skip the LLM summary")
    args = parser.parse_args(argv)

    urls = args.urls or [
        line.strip() for line in DEMO_LIST.read_text().splitlines() if line.strip() and not line.startswith("#")
    ]
    store.init_db()
    failures = 0
    for url in urls:
        owner, repo = validate_github_url(url)
        url = f"https://github.com/{owner}/{repo.removesuffix('.git')}"
        existing = store.find_latest_for_url(url)
        if existing and not args.force and existing["summary_status"] == "done":
            print(f"skip   {owner}/{repo} (already analysed: {existing['id']})")
            continue
        started = time.monotonic()
        analysis = store.create_analysis(url, owner, repo.removesuffix(".git"))
        # Run the stages inline rather than on the API's worker pools.
        original = jobs.submit_summary
        jobs.submit_summary = lambda *a, **k: None  # type: ignore[assignment]
        try:
            jobs._run_analysis(analysis["id"], url)
        finally:
            jobs.submit_summary = original  # type: ignore[assignment]
        result = store.get_analysis(analysis["id"], include_documents=False)
        if result["status"] != "ready":
            failures += 1
            print(f"FAILED {owner}/{repo}: {result['error']}")
            continue
        if args.no_summary:
            store.update_analysis(analysis["id"], summary_status="skipped", stage="done")
        else:
            jobs._run_summary(analysis["id"], jobs.summary_model())
        result = store.get_analysis(analysis["id"], include_documents=False)
        s = result.get("stats") or {}
        print(
            f"ok     {owner}/{repo}  {analysis['id']}  summary={result['summary_status']}  "
            f"{time.monotonic() - started:.0f}s"
        )
        if result["summary_status"] == "failed":
            print(f"       summary error: {result['summary_error']}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
