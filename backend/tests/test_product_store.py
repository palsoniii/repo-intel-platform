"""SQLite store: restart recovery must not clobber work another live process owns."""

import os

import pytest

from app.product import store


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("PRODUCT_DB_PATH", str(tmp_path / "product.db"))
    store.init_db()


def _running(owner_pid: int) -> str:
    a = store.create_analysis("https://github.com/o/r", "o", "r")
    store.update_analysis(a["id"], status="ready", summary_status="running", owner_pid=owner_pid)
    return a["id"]


def test_restart_fails_in_flight_rows_whose_owner_died():
    dead_pid = 2**22 + 12345  # above macOS/Linux default pid limits, so never alive
    aid = _running(dead_pid)
    store.init_db()
    row = store.get_analysis(aid)
    assert row["summary_status"] == "failed"
    assert "restarted" in row["summary_error"]


def test_restart_leaves_rows_owned_by_another_live_process():
    aid = _running(os.getppid())  # the test runner's parent: alive, and not us
    store.init_db()
    assert store.get_analysis(aid)["summary_status"] == "running"


def test_find_latest_for_url_ignores_case_and_failures():
    a = store.create_analysis("https://github.com/Owner/Repo", "Owner", "Repo")
    assert store.find_latest_for_url("https://github.com/owner/repo")["id"] == a["id"]
    store.update_analysis(a["id"], status="failed")
    assert store.find_latest_for_url("https://github.com/owner/repo") is None


def test_cached_answer_replays_in_the_live_event_shape():
    import json

    from app.product import ask

    a = store.create_analysis("https://github.com/o/r2", "o", "r2")
    key = ask.question_key("  How does AUTH work? ")
    assert key == ask.question_key("how does auth work")  # punctuation and case ignored
    store.save_cached_answer(a["id"], key, {"answer": "x" * 60, "sources": [{"path": "a.js"}], "model": "m", "stats": {}})

    events = [json.loads(line) for line in ask.stream_answer(None, {}, {}, "How does auth work?", analysis_id=a["id"])]
    assert events[0] == {"type": "sources", "sources": [{"path": "a.js"}], "model": "m", "cached": True}
    assert "".join(e["text"] for e in events if e["type"] == "token") == "x" * 60
    assert events[-1]["type"] == "done" and events[-1]["cached"] is True
