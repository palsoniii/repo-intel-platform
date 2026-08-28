"""T5b -- wait for the gemma2 re-judge to exit, THEN re-judge with mistral.

Why mistral rather than granite: this isolates the CODE FIX as the sole intervention.
Same model, same stored summaries, same prompts -- only coverage.py differs between
battery_v2.db's mistral column and this run. If the scores move, the harness bug caused
the conclusion inversion. Granite would add a third opinion but would not test the
mechanism.

Why Python and not a shell loop: this backend image has no `ps`, no `pgrep` and no
`kill`. A shell `while pgrep ...` loop exits IMMEDIATELY on "command not found", which
launched mistral concurrently with gemma2 on the first attempt -- and with
OLLAMA_MAX_LOADED_MODELS=1 that means evict-and-reload thrashing on every single call,
the same pattern that made deepseek unusable. Process detection here reads /proc
directly so it depends on nothing outside the stdlib.

Serialisation is the whole point: exactly one judge model resident at a time.
"""
from __future__ import annotations

import os
import subprocess
import time

RESULTS = "/app/evaluation_results"
GEMMA_LOG = os.path.join(RESULTS, "rejudge_gemma2.log")
CHAIN_LOG = os.path.join(RESULTS, "chain_mistral.log")
# NB: rejudge.py slugifies the model name (":" -> "_", "." -> "_"), so gemma2:9b writes
# rejudge_gemma2_9b.db. The .log name is separate -- it is set by the launch command.
GEMMA_DB = os.path.join(RESULTS, "rejudge_gemma2_9b.db")
MISTRAL = "mistral:7b-instruct"

POLL_S = 60
MAX_WAIT_S = 4 * 60 * 60  # hard stop; never wait past the deadline window


def say(msg: str) -> None:
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    with open(CHAIN_LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def gemma_running() -> bool:
    """True if the gemma2 re-judge python process is alive. Reads /proc directly.

    Self-exclusion matters: this watcher's own argv mentions the same script name, and
    `pkill -f` matching its own command line has killed the wrong process three separate
    times on this project (handoff gotcha #4). Comparing against our own PID is exact
    rather than relying on a pattern trick.
    """
    me = os.getpid()
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == me:
            continue
        try:
            with open("/proc/%s/cmdline" % pid, "rb") as fh:
                cmd = fh.read().replace(b"\0", b" ").decode("utf-8", "replace")
        except (OSError, IOError):
            continue
        if "rejudge.py" in cmd and "gemma2" in cmd and "chain_mistral" not in cmd:
            return True
    return False


def gemma_rows() -> int:
    import sqlite3
    try:
        c = sqlite3.connect(GEMMA_DB)
        n = c.execute("SELECT COUNT(*) FROM rejudged").fetchone()[0]
        c.close()
        return int(n)
    except Exception:
        return 0


def main() -> int:
    say("chain started (pid %d); waiting for gemma2 re-judge to exit" % os.getpid())

    if not gemma_running():
        say("WARNING: gemma2 is not running right now. Waiting 120s in case it is "
            "between rows, then re-checking.")
        time.sleep(120)
        if not gemma_running():
            say("gemma2 still not running -- treating it as finished/dead.")

    waited = 0
    while gemma_running() and waited < MAX_WAIT_S:
        time.sleep(POLL_S)
        waited += POLL_S
        if waited % 600 == 0:
            say("still waiting; gemma2 rows so far=%d (%d min elapsed)"
                % (gemma_rows(), waited // 60))

    if waited >= MAX_WAIT_S:
        say("ABORT: gemma2 still running after %d h. Not starting mistral -- two judges "
            "resident at once would thrash the 9.7 GB budget." % (MAX_WAIT_S // 3600))
        return 1

    say("gemma2 process has exited")

    # Anchored so it cannot match a line this script itself wrote (gotcha #5).
    done = False
    try:
        with open(GEMMA_LOG, encoding="utf-8") as fh:
            for line in fh:
                if "] JUDGE PHASE DONE" in line:
                    done = True
                    break
    except OSError:
        pass

    n = gemma_rows()
    say("gemma2 completion marker: %s | rows persisted: %d" % (done, n))
    if not done:
        say("NOTE: no completion marker. gemma2 is resumable -- re-running the same "
            "command skips rows already in its db. Proceeding with mistral regardless, "
            "because mistral is the experiment that tests the mechanism.")

    say("launching mistral re-judge under the FIXED harness")
    with open(os.path.join(RESULTS, "rejudge_mistral.log"), "w", encoding="utf-8") as out:
        rc = subprocess.call(
            ["python", "/app/rejudge.py", "--judge", MISTRAL],
            stdout=out, stderr=subprocess.STDOUT,
        )
    say("mistral re-judge exited rc=%d" % rc)
    say("chain complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
