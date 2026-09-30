"""Run the development-only Live check in PROTOCOL.md once: F04, W19, W04, W18, one scripts/live_diagnose.py process
per case.

- Refuses to start unless the files match FREEZE.json, the checkout's src/ is the frozen tree, the ledger total is the
  frozen starting balance, no ledger override is set, and its run log does not exist yet.
- Sets NEM_AGENT_TOTAL_BUDGET_USD to the ledger's committed total at start + 0.48, so the ledger refuses any call
  that would take this run past USD 0.48, and NEM_AGENT_MODEL to the frozen model.
- Starts a case only if at least USD 0.28 of that allowance remains.
- After each case, applies check_case.py. It stops the run at a budget stop, a safety failure, or a case charge above
  USD 0.10. An error ends only that case.
- Never retries or re-runs a case.

Usage (detached, so it survives the calling session):
    setsid nohup .venv/bin/python eval/live_check_p1_dev/run_check.py > /dev/null 2>&1 &
It never reads or prints the API key; live_diagnose.py refuses to run without one.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(HERE))

from nem_agent import budget, config  # noqa: E402

LABEL = "live-check-p1-dev"
OUT = REPO / "artifacts" / "live" / LABEL


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()


def _refusal(freeze: dict) -> str | None:
    for rel, want in freeze["files_sha256"].items():
        if hashlib.sha256((REPO / rel).read_bytes()).hexdigest() != want:
            return f"{rel} differs from FREEZE.json"
    if _git("rev-parse", "HEAD:src") != freeze["src_tree"] or _git("status", "--porcelain", "--", "src"):
        return "the checkout's src/ is not the frozen tree"
    if os.environ.get("NEM_AGENT_BUDGET_LEDGER") or os.environ.get("NEM_AGENT_TOTAL_BUDGET_USD"):
        return "a ledger override is set"
    if round(budget.spent(), 6) != freeze["ledger_start_usd"]:
        return f"the ledger total {budget.spent()} is not the frozen starting balance {freeze['ledger_start_usd']}"
    if freeze["prompt_version"] != config.PROMPT_VERSION:
        return "the prompt version differs"
    return None


def main() -> int:
    freeze = json.loads((HERE / "FREEZE.json").read_text())
    why = _refusal(freeze)
    if why:
        print(f"refused: {why}")
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    log = OUT / "run_log.jsonl"
    try:
        fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)  # one run only
    except FileExistsError:
        print(f"refused: {log} exists; this check runs once")
        return 2
    from check_case import check_saved

    start = budget.spent()
    allowance, guard, stop_cost = freeze["allowance_usd"], freeze["guard_usd"], freeze["case_cost_stop_usd"]
    cap = round(start + allowance, 6)
    env = dict(os.environ, NEM_AGENT_TOTAL_BUDGET_USD=f"{cap:.6f}", NEM_AGENT_MODEL=freeze["model"])
    with os.fdopen(fd, "w") as fh:
        def write(**kw: object) -> None:
            fh.write(json.dumps({"at": _now(), **kw}, default=str) + "\n")
            fh.flush()

        write(event="start", commit=_git("rev-parse", "HEAD"), code_commit=freeze["code_commit"],
              src_tree=freeze["src_tree"], model=freeze["model"], prompt_version=config.PROMPT_VERSION,
              ledger_committed=start, run_cap=cap, allowance=allowance, guard=guard, case_cost_stop=stop_cost,
              protocol_sha256=freeze["files_sha256"]["eval/live_check_p1_dev/PROTOCOL.md"], pid=os.getpid())
        plan = freeze["cases"]
        for i, (cid, cases_file) in enumerate(plan):
            before = budget.spent()
            if cap - before < guard:
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
            cost = round(after - before, 6)
            try:
                checked = check_saved(OUT, cid) if outcome == "saved" else None
            except Exception as exc:  # a check that cannot run stops the run, like a safety failure
                checked = {"case_verdict": "unchecked", "safety_failures": [f"checker error: {type(exc).__name__}: {exc}"]}
            write(event="case_end", case=cid, outcome=outcome, returncode=rc, ledger_after=after, ledger_cost=cost,
                  case_verdict=(checked or {}).get("case_verdict", "incomplete"),
                  safety_failures=(checked or {}).get("safety_failures", []))
            reason = ("budget stop" if outcome == "stopped" else
                      f"safety failure: {checked['safety_failures']}" if checked and checked["safety_failures"] else
                      f"case charge {cost} above {stop_cost}" if cost > stop_cost else None)
            if reason:
                write(event="run_stopped", after_case=cid, reason=reason, not_run=[c for c, _ in plan[i + 1:]])
                break
        end = budget.spent()
        write(event="end", ledger_committed=end, run_cost=round(end - start, 6))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
