"""
SQLite store for analyses: one row per analysed repository, plus the source text of
the files it was parsed from (the clone itself is deleted once parsing finishes, and
the file viewer, endpoint snippets and Ask-the-repo all need the code afterwards).

stdlib sqlite3 with a connection per call -- the job runner writes from worker threads
and FastAPI reads from its own threadpool, and a shared connection would need its own
locking for no benefit at this scale.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "product.db"

# Columns that hold JSON documents; decoded on read so callers never see raw strings.
JSON_COLUMNS = ("parsed_json", "summary_json", "insights_json", "timings_json")

SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    id              TEXT PRIMARY KEY,
    url             TEXT NOT NULL,
    owner           TEXT NOT NULL,
    repo_name       TEXT NOT NULL,
    commit_sha      TEXT,
    framework       TEXT,
    status          TEXT NOT NULL,     -- queued | running | ready | failed
    stage           TEXT NOT NULL,     -- see jobs.STAGES
    error           TEXT,
    summary_status  TEXT NOT NULL,     -- pending | running | done | failed | skipped
    summary_error   TEXT,
    summary_model   TEXT,
    graph_status    TEXT NOT NULL,     -- pending | stored | unavailable
    owner_pid       INTEGER,           -- process running this analysis's current stage
    parsed_json     TEXT,
    summary_json    TEXT,
    insights_json   TEXT,
    timings_json    TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS analyses_url ON analyses(url);

CREATE TABLE IF NOT EXISTS answers (
    analysis_id   TEXT NOT NULL,
    question_key  TEXT NOT NULL,
    payload       TEXT NOT NULL,      -- {answer, sources, model, stats}
    created_at    TEXT NOT NULL,
    PRIMARY KEY (analysis_id, question_key)
);

CREATE TABLE IF NOT EXISTS files (
    analysis_id  TEXT NOT NULL,
    path         TEXT NOT NULL,
    content      TEXT NOT NULL,
    PRIMARY KEY (analysis_id, path)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def db_path() -> Path:
    return Path(os.environ.get("PRODUCT_DB_PATH", DEFAULT_DB_PATH))


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(analyses)")}
        if "owner_pid" not in cols:
            conn.execute("ALTER TABLE analyses ADD COLUMN owner_pid INTEGER")
        # A server restart kills its worker threads, and anything they were running
        # would otherwise spin in the UI forever. Rows owned by a process that is
        # still alive (the seed command, or another server) are left alone.
        rows = conn.execute(
            "SELECT id, status, summary_status, owner_pid FROM analyses "
            "WHERE status IN ('queued', 'running') OR "
            "(status = 'ready' AND summary_status IN ('pending', 'running'))"
        ).fetchall()
        for r in rows:
            if r["owner_pid"] != os.getpid() and _pid_alive(r["owner_pid"]):
                continue
            if r["status"] in ("queued", "running"):
                conn.execute(
                    "UPDATE analyses SET status='failed', stage='failed', "
                    "error='The server restarted while this analysis was running. Re-analyze it.', "
                    "updated_at=? WHERE id=?",
                    (_now(), r["id"]),
                )
            else:
                conn.execute(
                    "UPDATE analyses SET summary_status='failed', stage='done', "
                    "summary_error='The server restarted while the summary was being written.', "
                    "updated_at=? WHERE id=?",
                    (_now(), r["id"]),
                )


def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    out = dict(row)
    for col in JSON_COLUMNS:
        if out.get(col) is not None:
            out[col] = json.loads(out[col])
    return out


def create_analysis(url: str, owner: str, repo_name: str) -> dict[str, Any]:
    analysis_id = uuid.uuid4().hex[:12]
    now = _now()
    with connect() as conn:
        conn.execute(
            "INSERT INTO analyses (id, url, owner, repo_name, status, stage, summary_status, "
            "graph_status, owner_pid, timings_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'queued', 'queued', 'pending', 'pending', ?, '{}', ?, ?)",
            (analysis_id, url, owner, repo_name, os.getpid(), now, now),
        )
    return get_analysis(analysis_id)  # type: ignore[return-value]


def update_analysis(analysis_id: str, **fields: Any) -> None:
    if not fields:
        return
    for col in JSON_COLUMNS:
        if col in fields and fields[col] is not None and not isinstance(fields[col], str):
            fields[col] = json.dumps(fields[col])
    fields["updated_at"] = _now()
    assignments = ", ".join(f"{k}=?" for k in fields)
    with connect() as conn:
        conn.execute(
            f"UPDATE analyses SET {assignments} WHERE id=?", (*fields.values(), analysis_id)
        )


def record_timing(analysis_id: str, stage: str, seconds: float) -> None:
    analysis = get_analysis(analysis_id, include_documents=False)
    if analysis is None:
        return
    timings = analysis.get("timings_json") or {}
    timings[stage] = round(seconds, 2)
    update_analysis(analysis_id, timings_json=timings)


_SUMMARY_COLUMNS = (
    "id, url, owner, repo_name, commit_sha, framework, status, stage, error, "
    "summary_status, summary_error, summary_model, graph_status, timings_json, "
    "created_at, updated_at"
)


def get_analysis(analysis_id: str, include_documents: bool = True) -> dict[str, Any] | None:
    cols = "*" if include_documents else _SUMMARY_COLUMNS
    with connect() as conn:
        row = conn.execute(f"SELECT {cols} FROM analyses WHERE id=?", (analysis_id,)).fetchone()
    return _decode(row)


def find_latest_for_url(url: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            f"SELECT {_SUMMARY_COLUMNS} FROM analyses WHERE lower(url)=lower(?) AND status != 'failed' "
            "ORDER BY created_at DESC LIMIT 1",
            (url,),
        ).fetchone()
    return _decode(row)


def list_analyses(limit: int = 50) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            f"SELECT {_SUMMARY_COLUMNS}, insights_json FROM analyses "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_decode(r) for r in rows]  # type: ignore[misc]


def get_cached_answer(analysis_id: str, question_key: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT payload FROM answers WHERE analysis_id=? AND question_key=?", (analysis_id, question_key)
        ).fetchone()
    return json.loads(row["payload"]) if row else None


def save_cached_answer(analysis_id: str, question_key: str, payload: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO answers (analysis_id, question_key, payload, created_at) VALUES (?, ?, ?, ?)",
            (analysis_id, question_key, json.dumps(payload), _now()),
        )


def delete_analysis(analysis_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM answers WHERE analysis_id=?", (analysis_id,))
        conn.execute("DELETE FROM files WHERE analysis_id=?", (analysis_id,))
        conn.execute("DELETE FROM analyses WHERE id=?", (analysis_id,))


def save_files(analysis_id: str, files: dict[str, str]) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM files WHERE analysis_id=?", (analysis_id,))
        conn.executemany(
            "INSERT INTO files (analysis_id, path, content) VALUES (?, ?, ?)",
            [(analysis_id, p, c) for p, c in files.items()],
        )


def get_file(analysis_id: str, path: str) -> str | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT content FROM files WHERE analysis_id=? AND path=?", (analysis_id, path)
        ).fetchone()
    return row["content"] if row else None


def get_all_files(analysis_id: str) -> dict[str, str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT path, content FROM files WHERE analysis_id=?", (analysis_id,)
        ).fetchall()
    return {r["path"]: r["content"] for r in rows}


def list_file_sizes(analysis_id: str) -> dict[str, int]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT path, length(content) AS size FROM files WHERE analysis_id=?", (analysis_id,)
        ).fetchall()
    return {r["path"]: r["size"] for r in rows}
