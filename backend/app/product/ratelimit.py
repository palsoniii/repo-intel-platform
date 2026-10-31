"""
Per-visitor limits for a public deployment (PUBLIC_MODE=true). Off by default, so the
local demo is never throttled.

Each limit is a sliding one-hour window per client IP, kept in memory: right for the
single-instance deployment this is built for, and it resets on restart. Behind a
proxy, uvicorn must run with --proxy-headers so request.client is the visitor, not
the proxy (the production image does).
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

WINDOW_S = 3600.0
DEFAULTS = {"analyses": 10, "asks": 40}


def public_mode() -> bool:
    return os.environ.get("PUBLIC_MODE", "").strip().lower() in ("1", "true", "yes")


def _limit(kind: str) -> int:
    raw = os.environ.get(f"RATE_LIMIT_{kind.upper()}_PER_HOUR", "").strip()
    return int(raw) if raw.isdigit() else DEFAULTS[kind]


_hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def check(request: Request, kind: str) -> None:
    """Raises 429 once this visitor has used up `kind` for the hour."""
    if not public_mode():
        return
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    limit = _limit(kind)
    with _lock:
        hits = _hits[(kind, ip)]
        while hits and now - hits[0] > WINDOW_S:
            hits.popleft()
        if len(hits) >= limit:
            wait_min = max(1, int((WINDOW_S - (now - hits[0])) / 60))
            what = "repositories analysed" if kind == "analyses" else "questions asked"
            raise HTTPException(
                429,
                f"This demo allows {limit} {what} per hour per visitor. Try again in about {wait_min} min.",
            )
        hits.append(now)


def reset() -> None:
    with _lock:
        _hits.clear()
