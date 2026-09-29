"""Run the live check in PROTOCOL.md once: W20, then F01–F04, one scripts/live_diagnose.py process per case.

- Sets NEM_AGENT_TOTAL_BUDGET_USD to the ledger's committed total at start + 0.40, so the ledger refuses any call
  that would take this run past USD 0.40.
- Starts a case only if at least USD 0.28 (a case's worst case) of that allowance remains.
- Never retries or re-runs a case, and refuses to start if its run log already exists.

Usage (detached, so it survives the calling session):
    setsid nohup .venv/bin/python eval/live_check_2026_09_29/run_check.py > /dev/null 2>&1 &
It never reads or prints the API key; live_diagnose.py refuses to run without one.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from nem_agent import budget  # noqa: E402

ALLOWANCE, GUARD, LABEL = 0.40, 0.28, "live-check-2026-09-29"
PLAN = [("W20", "eval/holdout_v4/cases.json")] + [(f"F0{i}", "eval/live_check_2026_09_29/cases.json") for i in range(1, 5)]
OUT = REPO / "artifacts" / "live" / LABEL


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    log = OUT / "run_log.jsonl"
    try:
        fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)  # one run only
    except FileExistsError:
        print(f"refused: {log} exists; this check runs once")
        return 2
    start = budget.spent()
    cap = round(start + ALLOWANCE, 6)
    env = dict(os.environ, NEM_AGENT_TOTAL_BUDGET_USD=f"{cap:.6f}")
    with os.fdopen(fd, "w") as fh:
        def write(**kw: object) -> None:
            fh.write(json.dumps({"at": _now(), **kw}) + "\n")
            fh.flush()

        write(event="start", ledger_committed=start, run_cap=cap, allowance=ALLOWANCE, guard=GUARD, pid=os.getpid())
        for cid, cases_file in PLAN:
            before = budget.spent()
            if cap - before < GUARD:
                write(event="not_run", case=cid, reason="budget guard", remaining=round(cap - before, 6))
                continue
            write(event="case_start", case=cid, ledger_before=before)
            with (OUT / f"{cid}.stdout.txt").open("w") as so:
                rc = subprocess.run([sys.executable, str(REPO / "scripts" / "live_diagnose.py"), "--cases", cid,
                                     "--cases-file", cases_file, "--label", LABEL], cwd=REPO, env=env, stdout=so,
                                    stderr=subprocess.STDOUT).returncode
            after = budget.spent()
            text = (OUT / f"{cid}.stdout.txt").read_text()
            outcome = ("stopped" if "STOPPED:" in text else "error" if "ERROR" in text or rc != 0
                       else "saved" if (OUT / f"{cid}.json").exists() else "missing")
            write(event="case_end", case=cid, outcome=outcome, returncode=rc, ledger_after=after,
                  ledger_cost=round(after - before, 6))
            if outcome == "stopped":
                break
        end = budget.spent()
        write(event="end", ledger_committed=end, run_cost=round(end - start, 6))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
