#!/usr/bin/env python3
"""Build a context pack: clone, parse, write to Neo4j, render all three contexts, and
freeze the result to one JSON file.

Run this where the network and Neo4j live -- a laptop, or an HPC login node with a
Neo4j container. The pack it writes is then the only input the GPU job needs, so the
compute node never clones a repo, never talks to a database, and spends its whole
allocation generating.

    python -m scripts.build_context_pack $(cat ../18_repo_urls.txt) \
        --out evaluation_results/context_pack.json

Then on the GPU node:

    python -m app.evaluation.harness --context-pack evaluation_results/context_pack.json \
        --models qwen2.5-coder:7b --judge-model gemma2:9b ...

A repo that fails to clone or parse is reported and skipped rather than aborting the
build -- the pack records what it contains, and the harness scores what it is given.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.acquisition.clone import (  # noqa: E402
    AcquiredRepo,
    CloneFailedError,
    InvalidRepoUrlError,
    RepoTooLargeError,
    clone_repository,
)
from app.context.builder import build_context  # noqa: E402
from app.db.neo4j_client import get_driver  # noqa: E402
from app.evaluation.context_pack import ContextPack, PackedRepository  # noqa: E402
from app.graph.builder import ensure_constraints, write_parsed_repository  # noqa: E402
from app.parsers.base import UnsupportedFrameworkError  # noqa: E402
from app.parsers.registry import parse_repository  # noqa: E402
from app.pipeline import DEFAULT_MAX_RAW_CHARS, _read_raw_source  # noqa: E402
from app.schemas.llm_result import ContextVariant  # noqa: E402


def build(urls: list[str], max_size_mb: int, max_raw_chars: int, notes: str) -> ContextPack:
    driver = get_driver()
    pack = ContextPack(
        built_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        max_raw_chars=max_raw_chars,
        notes=notes,
    )
    try:
        ensure_constraints(driver)
        for i, url in enumerate(urls, 1):
            print(f"[{i}/{len(urls)}] {url}", flush=True)
            acquired: AcquiredRepo | None = None
            try:
                acquired = clone_repository(url, max_size_mb=max_size_mb)
                parsed = parse_repository(acquired.local_path)
                parsed.metadata.source_url = url
                parsed.metadata.commit_sha = acquired.commit_sha
                # Raw source must be read before cleanup -- it is the one context the
                # graph cannot reproduce.
                raw = _read_raw_source(acquired.local_path, parsed, max_raw_chars)
            except (
                InvalidRepoUrlError,
                CloneFailedError,
                RepoTooLargeError,
                UnsupportedFrameworkError,
            ) as e:
                print(f"    SKIPPED: {e}", flush=True)
                continue
            finally:
                if acquired is not None:
                    acquired.cleanup()

            write_parsed_repository(driver, parsed)
            name = parsed.metadata.name
            contexts = {
                ContextVariant.RAW: raw,
                ContextVariant.DEPENDENCY_GRAPH: build_context(
                    driver, name, ContextVariant.DEPENDENCY_GRAPH
                ),
                ContextVariant.KNOWLEDGE_GRAPH: build_context(
                    driver, name, ContextVariant.KNOWLEDGE_GRAPH
                ),
            }
            sizes = " ".join(f"{v.value}={len(c)}c" for v, c in contexts.items())
            print(f"    {name}: {sizes}", flush=True)
            pack.repositories.append(
                PackedRepository(source_url=url, parsed=parsed, contexts=contexts)
            )
    finally:
        driver.close()
    return pack


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("urls", nargs="+", help="GitHub repo URLs to freeze into the pack")
    ap.add_argument("--out", default="evaluation_results/context_pack.json")
    ap.add_argument("--max-size-mb", type=int, default=200)
    ap.add_argument("--max-raw-chars", type=int, default=DEFAULT_MAX_RAW_CHARS)
    ap.add_argument("--notes", default="", help="Free text recorded in the pack (e.g. which study this is for)")
    args = ap.parse_args()

    pack = build(args.urls, args.max_size_mb, args.max_raw_chars, args.notes)
    if not pack.repositories:
        print("No repositories were packed -- nothing written.", file=sys.stderr)
        return 1

    out = pack.write(args.out)
    mb = out.stat().st_size / 1_048_576
    print(f"\nWrote {len(pack.repositories)} repositories to {out} ({mb:.1f} MB)")
    if len(pack.repositories) != len(args.urls):
        print(f"NOTE: {len(args.urls) - len(pack.repositories)} of {len(args.urls)} URLs were skipped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
