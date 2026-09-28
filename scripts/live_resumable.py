"""Run a frozen Live evaluation with scripts/live_diagnose.py so that it survives the calling session and applies the
pre-registered interruption rule (eval/holdout_v4/PASS_RULE.md).

- By default the run is started in a detached process (its own session) and this command returns at once.
- Saved cases are never re-run. Each start is recorded in artifacts/live/<label>/attempts.json.
- If the previous start was killed (it has no end record), the case then in flight (the first case, in run order,
  without a saved result) is recorded as interrupted, and it is re-run once from scratch.
- If the same case was in flight at two interruptions, or any case ended in an error or a budget stop, nothing more
  is started and the run is INCOMPLETE.

Usage: python scripts/live_resumable.py --label L3-holdout-v4 --cases all --cases-file eval/holdout_v4/cases.json \
           --cap 4.555697 [--dry-run]
It never prints the API key; live_diagnose.py itself refuses to run without one.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def plan_attempt(ids: list[str], saved: set[str], errored: set[str], attempts: list[dict[str, Any]],
                 now: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """What to do at a (re)start, and the updated attempt log. Pure: no files, no network."""
    attempts = [dict(a) for a in attempts]
    remaining = [i for i in ids if i not in saved]
    if attempts and "ended_at" not in attempts[-1] and "interrupted_case" not in attempts[-1]:
        # the previous start was killed: the case then in flight is the first one still without a result
        attempts[-1]["interrupted_case"] = remaining[0] if remaining else None
        attempts[-1]["interruption_detected_at"] = now
    ended_badly = [a for a in attempts if a.get("result") in ("stopped", "error")]
    if errored or ended_badly:
        why = (f"case(s) ended in an error: {sorted(errored)}" if errored
               else f"attempt {ended_badly[0]['n']} ended with result '{ended_badly[0]['result']}'")
        return {"action": "incomplete", "reason": why, "remaining": remaining}, attempts
    if not remaining:
        return {"action": "done", "remaining": []}, attempts
    kills = sum(1 for a in attempts if a.get("interrupted_case") == remaining[0])
    if kills >= 2:
        return {"action": "incomplete", "remaining": remaining,
                "reason": f"{remaining[0]} was in flight at two interruptions; it is not started a third time"}, attempts
    attempts.append({"n": len(attempts) + 1, "started_at": now, "remaining": remaining,
                     "rerun_after_interruption": remaining[0] if kills else None})
    return {"action": "run", "remaining": remaining}, attempts


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--cases", required=True, help="comma-separated case ids, or 'all' (with --cases-file)")
    ap.add_argument("--cases-file", default=None)
    ap.add_argument("--cap", type=float, required=True, help="absolute task-ledger cap (NEM_AGENT_TOTAL_BUDGET_USD)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan; start nothing")
    ap.add_argument("--foreground", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()

    from nem_agent import budget, config, paths
    from nem_agent.evaluation.runner import load_cases

    if args.cap > config.LIVE_TOTAL_BUDGET_USD:
        print(f"refused: cap {args.cap} is above the task cap {config.LIVE_TOTAL_BUDGET_USD}")
        return 2
    out_dir = paths.artifacts_dir() / "live" / args.label
    logs = paths.artifacts_dir() / "logs"
    if not args.foreground and not args.dry_run:
        logs.mkdir(parents=True, exist_ok=True)
        with open(logs / f"{args.label}_driver.log", "a") as log:
            p = subprocess.Popen([sys.executable, __file__, *sys.argv[1:], "--foreground"], cwd=REPO,
                                 stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                 start_new_session=True)
        print(f"{args.label}: started detached (pid {p.pid}); log {logs / (args.label + '_driver.log')}")
        return 0

    cases = load_cases(Path(args.cases_file) if args.cases_file else None)["cases"]
    ids = [c["case_id"] for c in cases] if args.cases == "all" else [x.strip() for x in args.cases.split(",") if x.strip()]
    saved = {i for i in ids if (out_dir / f"{i}.json").exists()}
    errored = {i for i in ids if (out_dir / f"{i}.error.json").exists()}
    att_path = out_dir / "attempts.json"
    attempts = json.loads(att_path.read_text()) if att_path.exists() else []
    plan, attempts = plan_attempt(ids, saved, errored, attempts, _now())
    print(f"{_now()} {args.label}: {plan['action']} "
          f"({len(saved)}/{len(ids)} saved){': ' + plan['reason'] if 'reason' in plan else ''}")
    if args.dry_run:
        print(json.dumps(plan))
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    if plan["action"] == "run":
        attempts[-1].update(cap=args.cap, counted_at_start=budget.spent())
    att_path.write_text(json.dumps(attempts, indent=2) + "\n")
    if plan["action"] != "run":
        return 0 if plan["action"] == "done" else 2

    n = attempts[-1]["n"]
    cmd = [sys.executable, "-u", str(REPO / "scripts" / "live_diagnose.py"), "--cases", ",".join(plan["remaining"]),
           "--label", args.label] + (["--cases-file", args.cases_file] if args.cases_file else [])
    with open(logs / f"{args.label}_attempt{n}.log", "w") as log:
        rc = subprocess.run(cmd, cwd=REPO, env={**os.environ, "NEM_AGENT_TOTAL_BUDGET_USD": str(args.cap)},
                            stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL).returncode
    summary_path = out_dir / "summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {"cases": []}
    if summary_path.exists():
        (out_dir / f"summary_attempt{n}.json").write_text(summary_path.read_text())
    result = ("stopped" if any("stopped" in c for c in summary["cases"])
              else "error" if rc != 0 or any("error" in c for c in summary["cases"]) else "ok")
    attempts[-1].update(ended_at=_now(), exit_code=rc, result=result, counted_at_end=budget.spent())
    att_path.write_text(json.dumps(attempts, indent=2) + "\n")
    print(f"{_now()} {args.label}: attempt {n} ended: {result} (exit {rc}); counted {budget.spent()}")
    return 0 if result == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
