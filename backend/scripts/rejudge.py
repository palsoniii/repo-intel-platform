#!/usr/bin/env python3
"""T5 -- re-judge Run 2's STORED summaries with a different judge model.

No regeneration: battery_v2.db persists summary_text, so this varies ONLY the judge
while holding summaries, writers, repos and prompts fixed. That is the experiment
PROJECT_HANDOFF.md claimed already existed but did not.

Two phases, deliberately separated:
  parse  -- clone+parse all 18 repos ONCE, cache to disk as JSON. Network-bound.
  judge  -- score from the cache. GPU-bound, touches the network ZERO times.
analyze_repository() clones and then deletes the checkout, so without this cache the
GPU loop would re-clone per row (157 clones) over a link the handoff documents as
intermittently broken. Splitting them means a network failure costs seconds, not hours.

Resumable: re-running skips (repo, model, variant) rows already present in the output.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import signal
import sqlite3
import sys
import time
import traceback

# Ensure the backend/ directory is on sys.path regardless of cwd.
# When invoked as `python -m scripts.rejudge` from backend/, Python adds backend/
# automatically. When invoked as a script directly, we need to add it ourselves.
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.evaluation.coverage import score_coverage
from app.evaluation.hallucination import score_summary
from app.pipeline import analyze_repository
from app.providers.ollama_provider import OllamaProvider
from app.schemas.llm_result import ContextVariant
from app.evaluation.context_pack import ContextPack
from app.schemas.parser_schema import ParsedRepository

# Default fallback paths (overridden by --src-db / --out-dir / --cache-dir args).
# These are relative to backend/ so the script is portable across environments.
_DEFAULT_RESULTS = os.path.join(_BACKEND_DIR, "evaluation_results")
RESULTS  = _DEFAULT_RESULTS
SRC_DB   = os.path.join(RESULTS, "battery_v2.db")
CACHE_DIR = os.path.join(RESULTS, "parse_cache")
ROW_TIMEOUT_S = 300

OUT_COLS = [
    "repo_name", "source_url", "framework", "model", "context_variant", "judge_model",
    "self_judged", "coverage_score", "total_facts", "missing_facts", "missing_facts_list",
    "coverage_judged", "unmatched_verdict_items", "unmatched_samples",
    "hallucination_score", "total_claims", "unsupported_claims", "hallucination_judged",
    "elapsed_s", "judged_at", "error",
]


def log(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


class RowTimeout(Exception):
    pass


def _alarm(signum, frame):
    raise RowTimeout()


def load_rows(src_db):
    c = sqlite3.connect(src_db)
    c.row_factory = sqlite3.Row
    rows = [
        dict(r)
        for r in c.execute(
            "SELECT * FROM evaluation_runs "
            "WHERE run_status='success' AND summary_text IS NOT NULL AND summary_text != ''"
        ).fetchall()
    ]
    c.close()
    return rows


# ---------------------------------------------------------------- phase: parse
def phase_parse(rows, cache_dir, context_pack_path=None):
    os.makedirs(cache_dir, exist_ok=True)
    repos = {}
    for r in rows:
        repos.setdefault(r["repo_name"], r["source_url"])
    log("PARSE PHASE -- %d unique repos" % len(repos))

    # Preload from context pack if available
    pack_data = {}
    if context_pack_path and os.path.exists(context_pack_path):
        log("PARSE PHASE -- loading context pack from %s" % context_pack_path)
        try:
            pack = ContextPack.read(context_pack_path)
            for repo in pack.repositories:
                pack_data[repo.parsed.metadata.name] = repo.parsed
            log("PARSE PHASE -- loaded %d repos from context pack" % len(pack_data))
        except Exception as e:
            log("PARSE PHASE -- failed to load context pack: %s" % e)

    for i, (name, url) in enumerate(sorted(repos.items()), 1):
        path = os.path.join(cache_dir, name + ".json")
        if os.path.exists(path) and os.path.getsize(path) > 0:
            log("  [%d/%d] %s: cached, skip" % (i, len(repos), name))
            continue
            
        if name in pack_data:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(pack_data[name].model_dump_json())
            log("  [%d/%d] %s: parsed from context pack (0s network time)" % (i, len(repos), name))
            continue

        log("  [%d/%d] %s: missing from context pack, falling back to live clone" % (i, len(repos), name))
        for attempt in (1, 2, 3):
            try:
                t0 = time.time()
                parsed = analyze_repository(url)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(parsed.model_dump_json())
                log("  [%d/%d] %s: parsed in %.0fs" % (i, len(repos), name, time.time() - t0))
                break
            except Exception as e:
                log("  [%d/%d] %s: attempt %d FAILED: %s" % (i, len(repos), name, attempt, e))
                if attempt == 3:
                    log("  [%d/%d] %s: GIVING UP -- rows for this repo will be skipped"
                        % (i, len(repos), name))
                else:
                    time.sleep(10 * attempt)

    have = len([f for f in os.listdir(cache_dir) if f.endswith(".json")])
    log("PARSE PHASE DONE -- %d/%d repos cached" % (have, len(repos)))


def load_parsed(name, cache_dir):
    path = os.path.join(cache_dir, name + ".json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return ParsedRepository.model_validate_json(fh.read())


# ---------------------------------------------------------------- phase: judge
def phase_judge(rows, judge, out_dir, src_stem):
    slug = judge.replace(":", "_").replace("/", "_").replace(".", "_")
    cache_dir = os.path.join(out_dir, "parse_cache")
    # When src_stem is set (--src-db was given explicitly), incorporate it into
    # the output filename so multiple source DBs don't clobber each other.
    if src_stem:
        out_db  = os.path.join(out_dir, "rejudge_%s_%s.db"  % (slug, src_stem))
        out_csv = os.path.join(out_dir, "rejudge_%s_%s.csv" % (slug, src_stem))
    else:
        # Backward-compat: old naming used by t7_meta.py / make_figures.py.
        out_db  = os.path.join(out_dir, "rejudge_%s.db"  % slug)
        out_csv = os.path.join(out_dir, "rejudge_%s.csv" % slug)

    conn = sqlite3.connect(out_db)
    conn.execute("CREATE TABLE IF NOT EXISTS rejudged (%s)"
                 % ",".join("%s TEXT" % c for c in OUT_COLS))
    conn.commit()
    done = set(conn.execute(
        "SELECT repo_name, model, context_variant FROM rejudged").fetchall())
    if done:
        log("RESUME -- %d rows already judged, skipping those" % len(done))

    csv_new = not os.path.exists(out_csv)
    csv_fh = open(out_csv, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(csv_fh, fieldnames=OUT_COLS)
    if csv_new:
        writer.writeheader()

    provider = OllamaProvider()
    signal.signal(signal.SIGALRM, _alarm)

    todo = [r for r in rows
            if (r["repo_name"], r["model"], r["context_variant"]) not in done]
    log("JUDGE PHASE -- judge=%s, %d rows to score" % (judge, len(todo)))

    parse_cache = {}
    n_ok = 0
    n_fail = 0
    t_start = time.time()

    for i, r in enumerate(todo, 1):
        name = r["repo_name"]
        tag = "[%d/%d] %s/%s/%s" % (i, len(todo), name,
                                    r["model"].split(":")[0], r["context_variant"])
        rec = dict((c, None) for c in OUT_COLS)
        rec.update(
            repo_name=name,
            source_url=r["source_url"],
            framework=r["framework"],
            model=r["model"],
            context_variant=r["context_variant"],
            judge_model=judge,
            # gemma2:9b is BOTH a writer and this judge. 51/157 rows are self-judged.
            # Flagged here so the primary analysis can exclude them and report them
            # separately as a self-preference measurement against the oracle.
            self_judged=1 if r["model"] == judge else 0,
            judged_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        )

        if name not in parse_cache:
            p = load_parsed(name, cache_dir)
            if p is None:
                rec["error"] = "no cached parse"
                log("  %s: SKIP (no cached parse)" % tag)
                _persist(conn, writer, csv_fh, rec)
                n_fail += 1
                continue
            parse_cache[name] = p
        parsed = parse_cache[name]

        try:
            variant = ContextVariant(r["context_variant"])
        except Exception:
            rec["error"] = "bad variant %s" % r["context_variant"]
            _persist(conn, writer, csv_fh, rec)
            n_fail += 1
            continue

        t0 = time.time()
        try:
            signal.alarm(ROW_TIMEOUT_S)
            cov = score_coverage(provider, parsed, r["summary_text"], variant,
                                 judge_model=judge)
            signal.alarm(0)

            signal.alarm(ROW_TIMEOUT_S)
            hal = score_summary(provider, parsed, r["summary_text"], variant,
                                judge_model=judge)
            signal.alarm(0)

            unm_n = getattr(cov, "unmatched_verdict_items", 0)
            rec.update(
                coverage_score=cov.coverage_score,
                total_facts=cov.total_facts,
                missing_facts=len(cov.missing_facts),
                missing_facts_list=json.dumps(cov.missing_facts),
                coverage_judged=1 if cov.judged else 0,
                unmatched_verdict_items=unm_n,
                unmatched_samples=json.dumps(getattr(cov, "unmatched_samples", [])),
                hallucination_score=hal.hallucination_score,
                total_claims=hal.total_claims,
                unsupported_claims=hal.unsupported_claims,
                hallucination_judged=1,
                elapsed_s=round(time.time() - t0, 1),
            )
            n_ok += 1
            log("  %s: cov=%.3f (%d/%d) unmatched=%d hal=%.2f %.0fs"
                % (tag, cov.coverage_score,
                   cov.total_facts - len(cov.missing_facts), cov.total_facts,
                   unm_n, hal.hallucination_score, time.time() - t0))
        except RowTimeout:
            signal.alarm(0)
            rec["error"] = "row timeout >%ds" % ROW_TIMEOUT_S
            rec["elapsed_s"] = round(time.time() - t0, 1)
            n_fail += 1
            log("  %s: TIMEOUT after %ds -- continuing" % (tag, ROW_TIMEOUT_S))
        except Exception as e:
            signal.alarm(0)
            rec["error"] = ("%s: %s" % (type(e).__name__, e))[:300]
            rec["elapsed_s"] = round(time.time() - t0, 1)
            n_fail += 1
            log("  %s: ERROR %s: %s" % (tag, type(e).__name__, e))
            traceback.print_exc()

        _persist(conn, writer, csv_fh, rec)  # flush EVERY row (handoff gotcha #6)

        if i % 10 == 0:
            el = time.time() - t_start
            log("  --- %d/%d done, %.1f min elapsed, ~%.0f min remaining ---"
                % (i, len(todo), el / 60, (el / i) * (len(todo) - i) / 60))

    csv_fh.close()
    conn.close()
    log("JUDGE PHASE DONE -- ok=%d fail=%d in %.1f min"
        % (n_ok, n_fail, (time.time() - t_start) / 60))
    log("  -> %s" % out_db)
    _summarise(out_db, judge)


def _persist(conn, writer, csv_fh, rec):
    conn.execute(
        "INSERT INTO rejudged (%s) VALUES (%s)"
        % (",".join(OUT_COLS), ",".join(["?"] * len(OUT_COLS))),
        [None if rec[c] is None else str(rec[c]) for c in OUT_COLS],
    )
    conn.commit()
    writer.writerow(rec)
    csv_fh.flush()


def _summarise(out_db, judge):
    c = sqlite3.connect(out_db)
    rows = c.execute(
        "SELECT coverage_score, self_judged, unmatched_verdict_items FROM rejudged "
        "WHERE coverage_judged='1'").fetchall()
    c.close()
    if not rows:
        log("SUMMARY: no judged rows")
        return
    scores = [float(r[0]) for r in rows]
    clean = [float(r[0]) for r in rows if r[1] == "0"]
    perfect = sum(1 for s in scores if s == 1.0)
    unm = sum(int(r[2] or 0) for r in rows)
    log("=" * 62)
    log("SUMMARY for judge=%s" % judge)
    log("  judged rows        : %d  (non-self-judged: %d)" % (len(rows), len(clean)))
    log("  distinct cov values: %d     [ACCEPTANCE: >15]" % len(set(scores)))
    log("  coverage == 1.0    : %d/%d = %.1f%%   [ACCEPTANCE: <60%%]"
        % (perfect, len(scores), 100.0 * perfect / len(scores)))
    log("  mean coverage      : %.4f" % (sum(scores) / len(scores)))
    if clean:
        log("  mean (non-self)    : %.4f" % (sum(clean) / len(clean)))
    log("  unmatched items    : %d total  (judge format-compliance metric)" % unm)
    ok = len(set(scores)) > 15 and perfect / float(len(scores)) < 0.60
    log("  ACCEPTANCE: %s" % ("PASS -- judge discriminates" if ok
                              else "FAIL -- judge saturates (report as prompt-leniency finding)"))
    log("=" * 62)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", required=True)
    ap.add_argument("--context-pack", default=None, help="Path to pre-built context_pack.json")
    ap.add_argument("--phase", choices=["parse", "judge", "all"], default="all")
    ap.add_argument(
        "--src-db", default=None,
        help=(
            "Source battery DB to read summaries from. "
            "Default: battery_v2.db (backward-compat). "
            "When set, output files are named rejudge_<judge>_<src_stem>.{db,csv} "
            "and placed alongside the source DB."
        ),
    )
    a = ap.parse_args()

    if a.src_db is None:
        src_db  = SRC_DB
        out_dir = RESULTS
        src_stem = None   # use old naming (backward-compat)
    else:
        src_db   = os.path.abspath(a.src_db)
        out_dir  = os.path.dirname(src_db)
        src_stem = os.path.splitext(os.path.basename(src_db))[0]  # e.g. battery_codellama13b

    cache_dir = os.path.join(out_dir, "parse_cache")

    rows = load_rows(src_db)
    log("loaded %d successful rows with summary_text from %s" % (len(rows), src_db))
    if a.phase in ("parse", "all"):
        phase_parse(rows, cache_dir, context_pack_path=a.context_pack)
    if a.phase in ("judge", "all"):
        phase_judge(rows, a.judge, out_dir, src_stem)
    return 0


if __name__ == "__main__":
    sys.exit(main())
