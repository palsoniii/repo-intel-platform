"""
Pre-analyse the demo repositories so the presentation never waits on a clone or the
model:

    python -m app.product.seed                # every URL in ../demo_repos.txt
    python -m app.product.seed URL [URL ...]  # just these
    python -m app.product.seed --force        # re-analyse even if already stored
    python -m app.product.seed --answers-only # just pre-answer the suggested questions
                                              # for every stored analysis
    python -m app.product.seed --export-seed  # write seed/product.db for the deployment
                                              # image from the analyses stored here

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
SEED_EXPORT = Path(__file__).resolve().parents[2] / "seed" / "product.db"


def main(argv: list[str] | None = None) -> int:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    from app.acquisition.clone import validate_github_url
    from app.product import jobs, store

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("urls", nargs="*")
    parser.add_argument("--force", action="store_true", help="re-analyse repositories already stored")
    parser.add_argument("--no-summary", action="store_true", help="skip the LLM summary")
    parser.add_argument("--no-answers", action="store_true", help="skip pre-answering the suggested questions")
    parser.add_argument("--answers-only", action="store_true", help="only pre-answer questions for stored analyses")
    parser.add_argument("--export-seed", action="store_true", help=f"write {SEED_EXPORT} from the stored analyses")
    args = parser.parse_args(argv)

    if args.export_seed:
        return export_seed(SEED_EXPORT)

    if args.answers_only:
        store.init_db()
        for a in store.list_analyses(limit=200):
            if a["status"] == "ready":
                _pre_answer(a["id"])
        return 0

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
            print(f"skip   {owner}/{repo} (already analysed: {existing['id']})", flush=True)
            if not args.no_answers:
                _pre_answer(existing["id"])
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
            jobs._run_summary(analysis["id"])
        result = store.get_analysis(analysis["id"], include_documents=False)
        s = result.get("stats") or {}
        print(
            f"ok     {owner}/{repo}  {analysis['id']}  summary={result['summary_status']}  "
            f"{time.monotonic() - started:.0f}s"
        )
        if result["summary_status"] == "failed":
            print(f"       summary error: {result['summary_error']}")
        if not args.no_answers:
            _pre_answer(analysis["id"])
    return 1 if failures else 0


def export_seed(target: Path) -> int:
    """Copies the store to `target`, keeping only the latest finished analysis of each
    repository (summary included) and its cached answers. The deployment has no Neo4j,
    so graph_status is cleared rather than claiming the graph is stored there."""
    import sqlite3

    from app.product import store

    store.init_db()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    with store.connect() as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    with sqlite3.connect(target) as conn:
        conn.execute("""
            DELETE FROM analyses WHERE status != 'ready' OR summary_status != 'done'
               OR id NOT IN (SELECT id FROM analyses a WHERE created_at =
                   (SELECT MAX(created_at) FROM analyses b
                     WHERE lower(b.url) = lower(a.url) AND b.status = 'ready' AND b.summary_status = 'done'))
        """)
        conn.execute("DELETE FROM files WHERE analysis_id NOT IN (SELECT id FROM analyses)")
        conn.execute("DELETE FROM answers WHERE analysis_id NOT IN (SELECT id FROM analyses)")
        conn.execute("UPDATE analyses SET graph_status = 'disabled', owner_pid = NULL")
        rows = conn.execute("SELECT owner || '/' || repo_name FROM analyses ORDER BY created_at").fetchall()
    with sqlite3.connect(target) as conn:
        conn.execute("VACUUM")
    for (name,) in rows:
        print(f"seeded {name}")
    print(f"wrote {target} ({target.stat().st_size // 1024} KB, {len(rows)} repositories)")
    return 0


def _pre_answer(analysis_id: str) -> None:
    """Answers the repository's suggested questions now, so clicking one during the
    demo replays instantly. Questions already answered are skipped."""
    from app.product import ask, store
    from app.schemas.parser_schema import ParsedRepository

    analysis = store.get_analysis(analysis_id)
    parsed = ParsedRepository.model_validate(analysis["parsed_json"])
    insights = analysis.get("insights_json") or {}
    files = store.get_all_files(analysis_id)
    for q in ask.suggested_questions(parsed, insights):
        if store.get_cached_answer(analysis_id, ask.question_key(q)):
            continue
        started = time.monotonic()
        error = None
        for line in ask.stream_answer(parsed, insights, files, q, analysis_id=analysis_id):
            if '"type": "error"' in line:
                error = line.strip()
        status = f"error {error}" if error else f"{time.monotonic() - started:.0f}s"
        print(f"       answered: {q}  ({status})", flush=True)


if __name__ == "__main__":
    sys.exit(main())
