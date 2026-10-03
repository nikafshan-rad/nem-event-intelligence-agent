"""Run the three pre-registered runs of the Live check of the v12 routing extraction (PASS_RULE.md) on the frozen code,
in this order. Adapted from eval/livecheck_i15_17/run_eval.py: the same start guard, stops, interruption rule and
refusals, with three runs, a per-run case cap, an exclusive lock and a check for records no log accounts for.
- R-dev, the 18 development routing cases (label LC-route-v12-dev): one routing call each (run_route.py);
- R-fresh, the 24 fresh routing cases (label LC-route-v12-fresh): one routing call each (run_route.py);
- E-dev, the 5 development end-to-end cases (label LC-route-v12-e2e): the full Live investigation
  (eval/livecheck_i15_17/run_case.py, unchanged).

Between runs:
- A run starts only if every earlier run ended complete with no safety stop. A result that misses supply or shows
  WRONG or X does not stop a later run (PASS_RULE.md).
- A safety stop (H1) in any run stops everything: no later run starts, in this or any later invocation.

Spending is capped **before every model call**, by the ledger: `nem_agent.budget.reserve` refuses a call when the
amount already spent or reserved, plus that call's worst case, would exceed `NEM_AGENT_TOTAL_BUDGET_USD`. This runner
sets that variable for each case process, so these caps hold at once:
- **Case cap:** the ledger total at the case's start + the run's case cap (USD 0.01 for a routing case, 0.15 for an
  end-to-end case).
- **Run cap:** the ledger total at the run's first start + the run's cap (USD 0.10 for R-dev, 0.15 for R-fresh, 0.50
  for E-dev). It is fixed at the first start and kept when the run is resumed.
- **Approved task cap:** the value the owner approves, given as `--approved-task-cap`. It must be at least the frozen
  starting balance plus the caps of the runs requested.
- **Start guard:** a case starts only if its full case cap fits under both other caps.

- **Refusals:** it refuses to start in any of these situations:
  - another invocation holds the lock;
  - the frozen files differ from FREEZE.json;
  - the checkout's `src/` is not the frozen tree, or is modified;
  - a run's number of cases differs from the frozen count;
  - a run's directory holds records its log does not account for;
  - a ledger, cap, price or model override is set;
  - the prompt version differs;
  - no API key is set (the key is never read or printed here);
  - the approved task cap is missing or too low;
  - **at a run's first start**, the ledger total is not the expected balance: the frozen starting balance for R-dev,
    and the previous run's recorded end for the others;
  - **at a resume**, the ledger total is below the run's last recorded value;
  - an earlier run ended with a safety stop.
- **Interruption** (the environment kills this runner): re-run the same command.
  - Saved cases are never re-run.
  - The case that was in flight is re-run once from scratch, and its cost stays counted.
  - If the same case is in flight at a second kill, it is not started again, and the run is INCOMPLETE.
  - If the case saved its record before the kill, it is finished, not re-run.
- **Stops:** any budget stop, API error or timeout, missing record, H1 safety failure, or change to the frozen files
  or `src/` (checked before each case) ends the run, and it is INCOMPLETE. No case is retried. An H1 failure, or a
  change to the frozen material, also stops every later run.
- **Duplicates:** an ended run is never resumed or repeated (INCOMPLETE is final).
- **Records:** `artifacts/live/<label>/`: the run log (`run_log.jsonl`), each case's standard output, the record and
  its trace.

Usage (it detaches, so the run survives the calling session; to resume, run the same command again):
    .venv/bin/python eval/livecheck_routing_v12/run_eval.py --approved-task-cap <USD> [--dry-run]
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "src"))

from nem_agent import budget, config  # noqa: E402

LIVE = REPO / "artifacts" / "live"
LOCK = LIVE / "LC-route-v12.lock"
ORDER = ("R-dev", "R-fresh", "E-dev")
CASE_RUNNERS = {"route": HERE / "run_route.py", "e2e": REPO / "eval" / "livecheck_i15_17" / "run_case.py"}
# environment variables that would change what a call may cost, where it is counted, or which model answers
OVERRIDES = ("NEM_AGENT_BUDGET_LEDGER", "NEM_AGENT_TOTAL_BUDGET_USD", "NEM_AGENT_SESSION_BUDGET_USD",
             "NEM_AGENT_PRICE_INPUT_PER_MTOK", "NEM_AGENT_PRICE_CACHED_INPUT_PER_MTOK", "NEM_AGENT_PRICE_OUTPUT_PER_MTOK",
             "NEM_AGENT_MODEL")
Write = Callable[..., None]


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()


# ------------------------------------------------------------------------------------------------ caps and outcomes
def required_task_cap(freeze: dict[str, Any], runs: list[str]) -> float:
    """The lowest task cap that holds every run requested: the frozen starting balance plus their caps."""
    return round(freeze["ledger_start_usd"] + sum(freeze["runs"][r]["run_cap_usd"] for r in runs), 6)


def case_cap(run_cap: float, task_cap: float, ledger_before: float, per_case: float) -> float | None:
    """The ledger cap for a case starting at ``ledger_before``: ``ledger_before + per_case``, or None when that would
    exceed the run cap or the approved task cap (the case does not start)."""
    cap = round(ledger_before + per_case, 6)
    return cap if cap <= round(min(run_cap, task_cap), 6) else None


def outcome(stdout: str, returncode: int, saved: bool, trace: dict[str, Any] | None) -> str:
    """budget_stop, error, saved or missing. An end-to-end case's controller catches a ledger refusal after routing and
    returns a partial answer, so a saved record whose trace shows one is a budget stop too; a model call that raised is
    an error."""
    events = (trace or {}).get("events", [])
    refused = any(e.get("name") == "budget_exceeded" and str(e.get("reason", "")).startswith(("task budget", "session budget"))
                  for e in events)
    if "STOPPED:" in stdout or refused:
        return "budget_stop"
    if ("ERROR" in stdout or "UNVERIFIED" in stdout or returncode != 0
            or any(e.get("kind") == "model" and str(e.get("name", "")).endswith(":error") for e in events)):
        return "error"
    return "saved" if saved else "missing"


def safety(record: dict[str, Any]) -> list[str]:
    """H1 failures, which stop everything: a write to the case-note store, or a call to a forbidden tool."""
    s = record.get("score") or {}
    out = []
    if s.get("case_note_files_written"):
        out.append(f"{s['case_note_files_written']} case-note file(s) written")
    if s.get("forbidden_calls"):
        out.append(f"{s['forbidden_calls']} forbidden call(s)")
    return out


# ------------------------------------------------------------------------------------------------ the freeze
def changed(freeze: dict[str, Any]) -> str | None:
    """Whether a frozen file or the checkout's src/ differs from the freeze."""
    for rel, want in freeze["files_sha256"].items():
        p = REPO / rel
        if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != want:
            return f"{rel} differs from FREEZE.json"
    if _git("rev-parse", "HEAD:src") != freeze["src_tree"] or _git("status", "--porcelain", "--", "src"):
        return "the checkout's src/ is not the frozen tree"
    return None


def read_log(label: str, live: Path = LIVE) -> list[dict[str, Any]]:
    p = live / label / "run_log.jsonl"
    return [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()] if p.exists() else []


def end_of(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((e for e in events if e.get("event") == "end"), None)


def safety_stopped(logs: dict[str, list[dict[str, Any]]]) -> str | None:
    """The run that ended with a safety stop, if any: nothing more starts after it."""
    return next((n for n in ORDER if (end_of(logs.get(n, [])) or {}).get("safety_stop")), None)


def expected_start(freeze: dict[str, Any], name: str, logs: dict[str, list[dict[str, Any]]]) -> float | None:
    """The ledger total a run's first start must find: the frozen balance for R-dev; the previous run's recorded end
    for the others (it must have ended complete, with no safety stop). None when the run may not start."""
    i = ORDER.index(name)
    if i == 0:
        return float(freeze["ledger_start_usd"])
    prev = end_of(logs[ORDER[i - 1]])
    if prev is None or prev.get("safety_stop") or prev.get("result") != "complete":
        return None
    return float(prev["ledger_committed"])


def ledger_refusal(freeze: dict[str, Any], name: str, logs: dict[str, list[dict[str, Any]]], spent: float) -> str | None:
    events = logs[name]
    if not events:
        want = expected_start(freeze, name, logs)
        if want is None:
            return f"the run before {name} has not ended complete with no safety stop, so {name} does not start"
        if round(spent, 6) != round(want, 6):
            return f"the ledger total {spent} is not the expected starting balance {want} for {name}"
        return None
    last = max(float(e[k]) for e in events for k in ("ledger_committed", "ledger_before", "ledger_after", "ledger_now")
               if k in e)
    if round(spent, 6) < round(last, 6):
        return f"the ledger total {spent} is below {name}'s last recorded value {last}"
    return None


def cases_found(cases: list[list[str]]) -> int:
    """How many of the planned [case ID, cases file] pairs exist in their case files."""
    files: dict[str, set[str]] = {}
    for _cid, rel in cases:
        if rel not in files:
            files[rel] = {c["case_id"] for c in json.loads((REPO / rel).read_text())["cases"]}
    return sum(cid in files[rel] for cid, rel in cases)


def stray(label: str, events: list[dict[str, Any]], live: Path = LIVE) -> list[str]:
    """Records in a run's directory that its log does not account for: a case record (or error record) whose case
    never started under this log. A duplicate or stray run leaves them; the runner does not start over them."""
    out = live / label
    if not out.exists():
        return []
    started = {e["case"] for e in events if e.get("event") == "case_start"}
    found = {p.name.split(".")[0] for p in out.glob("*.json")} - {"summary"}  # live_diagnose's own run summary
    return sorted(found - started)


def refusal(freeze: dict[str, Any], runs: list[str], approved: float | None, spent: float) -> str | None:
    why = changed(freeze)
    if why:
        return why
    if any(cases_found(freeze["runs"][n]["cases"]) != freeze["runs"][n]["n_cases"] for n in ORDER):
        return "a run's number of cases differs from the frozen count"
    logs = {n: read_log(freeze["runs"][n]["label"]) for n in ORDER}
    for n in ORDER:
        extra = stray(freeze["runs"][n]["label"], logs[n])
        if extra:
            return f"{n}'s directory holds records its log does not account for: {', '.join(extra)}"
    stopped = safety_stopped(logs)
    if stopped:
        return f"run {stopped} ended with a safety stop, so no later run starts"
    if any(os.environ.get(k) for k in OVERRIDES):
        return "a ledger, cap, price or model override is set"
    if freeze["prompt_version"] != config.PROMPT_VERSION:
        return "the prompt version differs"
    if not os.environ.get("OPENAI_API_KEY"):
        return "no API key is set"
    need = required_task_cap(freeze, runs)
    if approved is None or round(approved, 6) < need:
        return f"the approved task cap must be at least USD {need} for {'+'.join(runs)} (given: {approved})"
    first = next((n for n in runs if end_of(logs[n]) is None), None)  # the first run that has not ended
    return ledger_refusal(freeze, first, logs, spent) if first else None


# ------------------------------------------------------------------------------------------------ one run
def state(events: list[dict[str, Any]]) -> dict[str, Any]:
    """What a run's log says: finished cases, whether it ended, the run cap fixed at its first start, how often each
    case was in flight at a kill, and the case in flight if the last attempt never wrote its end."""
    starts = [e for e in events if e.get("event") == "start"]
    done = {e["case"]: e["outcome"] for e in events if e.get("event") == "case_end"}
    end = next((e for e in events if e.get("event") == "end"), None)
    in_flight = None
    if starts and end is None:
        since = events[max(i for i, e in enumerate(events) if e.get("event") == "start"):]
        open_ = [e["case"] for e in since if e.get("event") == "case_start" and e["case"] not in done]
        in_flight = open_[-1] if open_ else None
    unrecorded = False
    if starts and end is None:
        last = max(i for i, e in enumerate(events) if e.get("event") == "start")
        unrecorded = not any(e.get("event") == "interrupted" for e in events[last:])
    kills = Counter(e["case"] for e in events if e.get("event") == "interrupted" and e.get("case"))
    return {"attempts": len(starts), "done": done, "end": end, "run_cap": starts[0]["run_cap"] if starts else None,
            "ledger_at_first_start": starts[0]["ledger_committed"] if starts else None,
            "in_flight": in_flight, "kills": kills, "unrecorded_kill": unrecorded}


def launch(kind: str, cid: str, cases_file: str, env: dict[str, str], out: Path) -> tuple[int, str]:
    """One case process: run_route.py (routing only) or eval/livecheck_i15_17/run_case.py (end to end); returns its
    exit code and standard output."""
    args = (["--case", cid] if kind == "route" else ["--cases", cid]) + ["--cases-file", cases_file, "--label", out.name]
    with (out / f"{cid}.stdout.txt").open("w") as so:
        rc = subprocess.run([sys.executable, str(CASE_RUNNERS[kind]), *args], cwd=REPO, env=env, stdout=so,
                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL).returncode
    return rc, (out / f"{cid}.stdout.txt").read_text()


def _finish(cid: str, out: Path, rc: int, text: str) -> tuple[str, dict[str, Any] | None]:
    """The case's outcome from its files; copies its trace next to the record."""
    rec_p = out / f"{cid}.json"
    rec = json.loads(rec_p.read_text()) if rec_p.exists() else None
    trace = None
    tid = (rec or {}).get("score", {}).get("trace_id")
    src = REPO / "artifacts" / "traces" / f"{tid}.json"
    if tid and src.exists():
        (out / "traces").mkdir(exist_ok=True)
        shutil.copy(src, out / "traces" / src.name)
        trace = json.loads(src.read_text())
    elif tid and (out / "traces" / f"{tid}.json").exists():
        trace = json.loads((out / "traces" / f"{tid}.json").read_text())
    return outcome(text, rc, rec is not None, trace), rec


def run(plan: dict[str, Any], events: list[dict[str, Any]], write: Write, *, model: str, task_cap: float, out: Path,
        launch: Callable[..., tuple[int, str]] = launch, spent: Callable[[], float] = budget.spent,
        frozen: Callable[[], str | None] = lambda: None, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Start or resume one run. ``events`` is its log so far; ``meta`` (the commit, src/ tree, prompts) goes into each
    start record. ``launch``, ``spent`` and ``frozen`` are injectable so the loop is tested offline."""
    st = state(events)
    ids = [c for c, _ in plan["cases"]]
    per_case = float(plan["case_cap_usd"])
    if st["end"] is not None:
        return st["end"]
    done = dict(st["done"])
    now = spent()
    stop: str | None = None
    rerun = None
    if st["attempts"]:  # the last attempt never wrote its end: the environment killed it
        cid = st["in_flight"]
        kills = st["kills"][cid] if cid else 0
        if st["unrecorded_kill"]:  # (a resume killed before its own start has recorded this kill already)
            write(event="interrupted", attempt=st["attempts"], case=cid, ledger_now=now)
            kills += 1 if cid else 0
        if cid is not None:
            text = (out / f"{cid}.stdout.txt").read_text() if (out / f"{cid}.stdout.txt").exists() else ""
            if (out / f"{cid}.json").exists() or (out / f"{cid}.error.json").exists():
                result, rec = _finish(cid, out, 0 if (out / f"{cid}.json").exists() else 1, text)
                done[cid] = result
                fails = safety(rec) if rec and result == "saved" else []
                write(event="case_end", case=cid, outcome=result, recovered_after_interruption=True, ledger_after=now,
                      safety_failures=fails)
                stop = (f"{result.replace('_', ' ')} in {cid}" if result != "saved"
                        else f"safety failure in {cid}: {fails}" if fails else None)
            elif kills >= 2:
                stop = f"{cid} was in flight at two interruptions; it is not started again"
            else:
                rerun = cid
                if (out / f"{cid}.stdout.txt").exists():
                    (out / f"{cid}.stdout.txt").rename(out / f"{cid}.stdout.interrupted{kills}.txt")
    first = st["run_cap"] is None
    run_cap = round(now + plan["run_cap_usd"], 6) if first else st["run_cap"]
    start_ledger = now if first else st["ledger_at_first_start"]
    write(event="start", attempt=st["attempts"] + 1, label=plan["label"], kind=plan["kind"], run_cap=run_cap,
          ledger_committed=now, task_cap=task_cap, case_cap_usd=per_case, model=model,
          rerun_after_interruption=rerun, **(meta or {}))
    safety_stop = False
    for i, cid in enumerate(ids):
        if cid in done:
            continue
        if stop is None:
            moved = frozen()
            stop = f"frozen material changed: {moved}" if moved else None
        before = spent()
        cap = None if stop else case_cap(run_cap, task_cap, before, per_case)
        if cap is None:
            reason = stop or "start guard: the case cap does not fit under the run cap and the approved task cap"
            stop = stop or reason
            write(event="not_run", cases=[c for c in ids[i:] if c not in done], reason=reason,
                  remaining_run=round(run_cap - before, 6))
            break
        env = dict(os.environ, NEM_AGENT_TOTAL_BUDGET_USD=f"{cap:.6f}", NEM_AGENT_MODEL=model)
        write(event="case_start", case=cid, ledger_before=before, case_ledger_cap=cap, rerun=cid == rerun)
        rc, text = launch(plan["kind"], cid, plan["cases"][i][1], env, out)
        result, rec = _finish(cid, out, rc, text)
        after = spent()
        fails = safety(rec) if rec and result == "saved" else []
        done[cid] = result
        write(event="case_end", case=cid, outcome=result, returncode=rc, ledger_after=after,
              ledger_cost=round(after - before, 6), safety_failures=fails)
        if result != "saved" or fails:
            safety_stop = bool(fails)
            stop = f"safety failure in {cid}: {fails}" if fails else f"{result.replace('_', ' ')} in {cid}"
            rest = [c for c in ids[i + 1:] if c not in done]
            write(event="not_run", cases=rest, reason=stop, remaining_run=round(run_cap - after, 6))
            break
    end_ledger = spent()
    saved = [c for c in ids if done.get(c) == "saved"]
    result = "complete" if len(saved) == len(ids) else "incomplete"
    end = {"event": "end", "result": result, "saved": saved, "not_saved": [c for c in ids if c not in saved],
           "stop_reason": stop, "safety_stop": safety_stop or bool(stop and stop.startswith("safety")),
           "ledger_committed": end_ledger, "run_cost": round(end_ledger - start_ledger, 6), "run_cap": run_cap}
    write(**end)
    return end


# ------------------------------------------------------------------------------------------------ between runs
def next_run_refusal(name: str, logs: dict[str, list[dict[str, Any]]]) -> str | None:
    """Why ``name`` may not start now (PASS_RULE.md, "Runs"), or None: any earlier safety stop stops everything, and
    every earlier run must have ended complete."""
    stopped = safety_stopped(logs)
    if stopped:
        return f"run {stopped} ended with a safety stop"
    for prev in ORDER[:ORDER.index(name)]:
        e = end_of(logs[prev])
        if e is None or e["result"] != "complete":
            return f"{prev} did not complete, so {name} does not start and the check is INCOMPLETE"
    return None


# ------------------------------------------------------------------------------------------------ main
def _writer(path: Path) -> Write:
    def write(**kw: object) -> None:
        with path.open("a") as fh:
            fh.write(json.dumps({"at": _now(), **kw}, default=str) + "\n")

    return write


def take_lock(path: Path = LOCK) -> TextIO | None:
    """An exclusive, non-blocking lock held for the whole invocation; None when another invocation holds it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = path.open("a")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--approved-task-cap", type=float, default=None, help="the task cap the owner approved (USD)")
    ap.add_argument("--dry-run", action="store_true", help="print the refusal check and the plan; start nothing")
    ap.add_argument("--foreground", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    freeze = json.loads((HERE / "FREEZE.json").read_text())
    runs = list(ORDER)
    why = refusal(freeze, runs, args.approved_task_cap, budget.spent())
    if args.dry_run:
        logs = {n: read_log(freeze["runs"][n]["label"]) for n in ORDER}
        print(json.dumps({"refusal": why, "ledger": budget.spent(), "required_task_cap": required_task_cap(freeze, runs),
                          "runs": {n: {k: (dict(v) if isinstance(v, Counter) else v) for k, v in state(logs[n]).items()}
                                   for n in runs}}, indent=1, default=str))
        return 0 if why is None else 2
    if why:
        print(f"refused: {why}")
        return 2
    if not args.foreground:
        logdir = REPO / "artifacts" / "logs"
        logdir.mkdir(parents=True, exist_ok=True)
        with open(logdir / "LC_route_v12_driver.log", "a") as log:
            p = subprocess.Popen([sys.executable, __file__, *sys.argv[1:], "--foreground"], cwd=REPO, stdout=log,
                                 stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
        print(f"started detached (pid {p.pid}); log artifacts/logs/LC_route_v12_driver.log")
        return 0
    lock = take_lock()
    if lock is None:
        print("refused: another invocation holds the lock")
        return 2
    meta = {"commit": _git("rev-parse", "HEAD"), "src_tree": _git("rev-parse", "HEAD:src"),
            "code_commit": freeze["code_commit"], "prompt_version": config.PROMPT_VERSION}
    for name in runs:
        plan = freeze["runs"][name]
        logs_now = {n: read_log(freeze["runs"][n]["label"]) for n in ORDER}
        if end_of(logs_now[name]) is not None:
            continue  # a run that has ended is never resumed
        why_not = next_run_refusal(name, logs_now)
        if why_not:
            print(f"{_now()} {name}: not started ({why_not})")
            break
        lwhy = ledger_refusal(freeze, name, logs_now, budget.spent())
        if lwhy:
            print(f"{_now()} {name}: refused: {lwhy}")
            return 2
        out = LIVE / plan["label"]
        out.mkdir(parents=True, exist_ok=True)
        end = run(plan, logs_now[name], _writer(out / "run_log.jsonl"), model=freeze["model"],
                  task_cap=float(args.approved_task_cap), out=out, frozen=lambda: changed(freeze), meta=meta)
        print(f"{_now()} {name}: {end['result']} ({len(end['saved'])}/{len(plan['cases'])} saved); run cost "
              f"{end['run_cost']}; ledger {end['ledger_committed']}{'; stop: ' + end['stop_reason'] if end['stop_reason'] else ''}")
    lock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
