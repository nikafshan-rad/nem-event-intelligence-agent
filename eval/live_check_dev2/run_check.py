"""Run the second development-only Live check in PROTOCOL.md once: F01, F03, W18 and W19 (required), then F04 and W04
(optional controls), one scripts/live_diagnose.py process per case.

Spending is capped **before every model call**, by the ledger: `nem_agent.budget.reserve` refuses a call when the
amount already spent or reserved, plus that call's worst case, would exceed `NEM_AGENT_TOTAL_BUDGET_USD`. This runner
sets that variable per case process, so two caps hold at once:
- **Run cap:** no case process is given a cap above the ledger total at the start of the run + `run_cap_usd`.
- **Case cap:** each case process gets its own ledger total at its start + `case_cap_usd`, so no call can take one
  case past `case_cap_usd`.
- **Start guard:** a case starts only if its full case cap fits under the run cap, so the run cap never cuts a case
  short.

The cap counts every reservation that was never settled (an interrupted call or a crashed process) at its worst case,
and the controller settles a call whose outcome is unknown (a timeout, a connection error, a 5xx) at its worst case.
The OpenAI client makes no hidden retries (`max_retries=0`). Nothing here checks spending after a call; the stops
below only decide whether another case starts.

- **Refusals:** it refuses to start in any of these situations:
  - the files differ from FREEZE.json;
  - the checkout's `src/` is not the frozen tree, or is modified;
  - the ledger total is not the frozen starting balance;
  - a ledger, cap or price override is set;
  - the prompt version differs;
  - no API key is set (the key is never read or printed here);
  - the run log already exists.
- **Stops:** any budget stop, API error, missing record or safety failure ends the run, and so does a change to the
  frozen files or `src/`, which is checked again before each case. No case is retried or re-run.
- **Records:** the run log, each case's standard output, the record and its trace, and the checker's output.

Usage (detached, so it survives the calling session):
    setsid nohup .venv/bin/python eval/live_check_dev2/run_check.py > /dev/null 2>&1 &
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(HERE))

from nem_agent import budget, config  # noqa: E402

LABEL = "live-check-dev2"
OUT = REPO / "artifacts" / "live" / LABEL
# environment variables that would change what a call may cost or where it is counted
OVERRIDES = ("NEM_AGENT_BUDGET_LEDGER", "NEM_AGENT_TOTAL_BUDGET_USD", "NEM_AGENT_SESSION_BUDGET_USD",
             "NEM_AGENT_PRICE_INPUT_PER_MTOK", "NEM_AGENT_PRICE_CACHED_INPUT_PER_MTOK", "NEM_AGENT_PRICE_OUTPUT_PER_MTOK",
             "NEM_AGENT_MODEL")


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()


def case_cap(run_cap: float, ledger_before: float, per_case: float) -> float | None:
    """The ledger cap for a case starting at ``ledger_before``: ``ledger_before + per_case``, or None when that would
    exceed the run cap (the case does not start)."""
    cap = round(ledger_before + per_case, 6)
    return cap if cap <= round(run_cap, 6) else None


def outcome(stdout: str, returncode: int, saved: bool, trace: dict[str, Any] | None) -> str:
    """budget_stop, error, saved or missing. The controller catches a refusal after routing and returns a partial
    answer, so a saved record whose trace shows a ledger refusal is a budget stop too."""
    refused = any(e.get("name") == "budget_exceeded" and str(e.get("reason", "")).startswith(("task budget", "session budget"))
                  for e in (trace or {}).get("events", []))
    if "STOPPED:" in stdout or refused:
        return "budget_stop"
    if "ERROR" in stdout or "UNVERIFIED" in stdout or returncode != 0:
        return "error"
    return "saved" if saved else "missing"


def changed(freeze: dict[str, Any]) -> str | None:
    """Whether a frozen file or the checkout's src/ differs from the freeze."""
    for rel, want in freeze["files_sha256"].items():
        if hashlib.sha256((REPO / rel).read_bytes()).hexdigest() != want:
            return f"{rel} differs from FREEZE.json"
    if _git("rev-parse", "HEAD:src") != freeze["src_tree"] or _git("status", "--porcelain", "--", "src"):
        return "the checkout's src/ is not the frozen tree"
    return None


def refusal(freeze: dict[str, Any]) -> str | None:
    why = changed(freeze)
    if why:
        return why
    if any(os.environ.get(k) for k in OVERRIDES):
        return "a ledger, cap, price or model override is set"
    if round(budget.spent(), 6) != freeze["ledger_start_usd"]:
        return f"the ledger total {budget.spent()} is not the frozen starting balance {freeze['ledger_start_usd']}"
    if freeze["prompt_version"] != config.PROMPT_VERSION:
        return "the prompt version differs"
    if not os.environ.get("OPENAI_API_KEY"):
        return "no API key is set"
    return None


def launch(cid: str, cases_file: str, env: dict[str, str]) -> tuple[int, str]:
    """One live_diagnose.py process for one case; returns its exit code and standard output."""
    with (OUT / f"{cid}.stdout.txt").open("w") as so:
        rc = subprocess.run([sys.executable, str(REPO / "scripts" / "live_diagnose.py"), "--cases", cid,
                             "--cases-file", cases_file, "--label", LABEL], cwd=REPO, env=env, stdout=so,
                            stderr=subprocess.STDOUT).returncode
    return rc, (OUT / f"{cid}.stdout.txt").read_text()


def run(freeze: dict[str, Any], write: Callable[..., None], *, launch: Callable[..., tuple[int, str]] = launch,
        spent: Callable[[], float] = budget.spent, check: Callable[[Path, str], dict[str, Any]] | None = None,
        frozen: Callable[[dict[str, Any]], str | None] = changed, out: Path = OUT) -> dict[str, Any]:
    """The case loop; ``launch``, ``spent``, ``check`` and ``frozen`` are injectable so the loop is tested offline."""
    if check is None:
        from check_case import check_saved

        check = check_saved
    checker: Callable[[Path, str], dict[str, Any]] = check
    start = spent()
    run_cap = round(start + freeze["run_cap_usd"], 6)
    per_case = freeze["case_cap_usd"]
    write(event="start", commit=freeze.get("run_commit"), code_commit=freeze["code_commit"], src_tree=freeze["src_tree"],
          model=freeze["model"], prompt_version=freeze["prompt_version"], ledger_committed=start, run_cap=run_cap,
          case_cap_usd=per_case, protocol_sha256=freeze["files_sha256"]["eval/live_check_dev2/PROTOCOL.md"])
    plan = freeze["cases"]
    done: dict[str, str] = {}
    stopped = False
    for i, (cid, cases_file) in enumerate(plan):
        before = spent()
        moved = None if stopped else frozen(freeze)
        if moved:
            stopped = True
            write(event="run_stopped", before_case=cid, reason=f"frozen material changed: {moved}",
                  not_run=[c for c, _ in plan[i:]])
        cap = None if stopped else case_cap(run_cap, before, per_case)
        if cap is None:
            write(event="not_run", case=cid, reason="run stopped" if stopped else "start guard: the case cap does not "
                  "fit under the run cap", remaining=round(run_cap - before, 6))
            continue
        env = dict(os.environ, NEM_AGENT_TOTAL_BUDGET_USD=f"{cap:.6f}", NEM_AGENT_MODEL=freeze["model"])
        write(event="case_start", case=cid, ledger_before=before, case_ledger_cap=cap)
        rc, text = launch(cid, cases_file, env)
        rec_p = out / f"{cid}.json"
        trace = None
        if rec_p.exists():
            tid = json.loads(rec_p.read_text())["score"].get("trace_id")
            src = REPO / "artifacts" / "traces" / f"{tid}.json"
            if tid and src.exists():
                (out / "traces").mkdir(exist_ok=True)
                shutil.copy(src, out / "traces" / src.name)
                trace = json.loads(src.read_text())
        after = spent()
        result = outcome(text, rc, rec_p.exists(), trace)
        checked = None
        if result == "saved":
            try:
                checked = checker(out, cid)
            except Exception as exc:  # a check that cannot run stops the run, like a safety failure
                checked = {"case_verdict": "unchecked", "safety_failures": [f"checker error: {type(exc).__name__}: {exc}"]}
        verdict = (checked or {}).get("case_verdict", "incomplete")
        done[cid] = verdict if result == "saved" else "incomplete"
        write(event="case_end", case=cid, outcome=result, returncode=rc, ledger_after=after,
              ledger_cost=round(after - before, 6), case_verdict=done[cid],
              safety_failures=(checked or {}).get("safety_failures", []))
        reason = (f"{result.replace('_', ' ')}" if result != "saved" else
                  f"safety failure: {checked['safety_failures']}" if checked and checked["safety_failures"] else None)
        if reason:
            stopped = True
            write(event="run_stopped", after_case=cid, reason=reason, not_run=[c for c, _ in plan[i + 1:]])
    end = spent()
    required = freeze["required"]
    complete = [c for c in required if done.get(c) not in (None, "incomplete")]
    coverage = {"required_completed": complete, "required_missing": [c for c in required if c not in complete],
                "full_check": len(complete) == len(required)}
    write(event="end", ledger_committed=end, run_cost=round(end - start, 6), coverage=coverage)
    return {"cases": done, "coverage": coverage, "run_cost": round(end - start, 6)}


def main() -> int:
    freeze = json.loads((HERE / "FREEZE.json").read_text())
    why = refusal(freeze)
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
    with os.fdopen(fd, "w") as fh:
        def write(**kw: object) -> None:
            fh.write(json.dumps({"at": _now(), **kw}, default=str) + "\n")
            fh.flush()

        run({**freeze, "run_commit": _git("rev-parse", "HEAD")}, write)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
