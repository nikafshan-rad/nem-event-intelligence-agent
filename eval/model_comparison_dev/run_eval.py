"""Run the development comparison of gpt-5-mini and gpt-6.1-sol (PROTOCOL.md) on the frozen code: the 58 slots of
FREEZE.json in their frozen, alternating order. Adapted from eval/livecheck_routing_v12/run_eval.py (the same start
guard, stops, interruption rule, lock and stray-record check), for one plan whose slots alternate between models and
whose spend is accounted per run (R-mini, R-sol, E-mini, E-sol).

- **A slot** is one process, with its model's environment: `NEM_AGENT_MODEL`, the accounting prices
  (`NEM_AGENT_PRICE_*`), and the slot's ledger caps. A routing slot runs the v12 check's `run_route.py`, an end-to-end
  slot the targeted check's `run_case.py`, both unchanged.
- **Caps** (PROTOCOL.md, "Caps"), enforced together:
  - **Per call** (`nem_agent.budget`): the slot's ledger cap is the ledger total at its start plus its run's case cap
    (`NEM_AGENT_TOTAL_BUDGET_USD`). The session budget is the same case cap (`NEM_AGENT_SESSION_BUDGET_USD`), so it
    never binds first.
  - **Start guard:** a slot starts only if its run's spend so far plus the case cap is within the run cap, and the
    ledger total plus the case cap is within the approved task cap.
- **Stops:** any budget stop, API error or timeout, missing record, H1 safety failure, or change to the frozen files or
  `src/` ends the comparison (INCOMPLETE). No slot is retried or repeated because of its result.
- **Interruption:** re-run the same command. Saved slots are never re-run. The slot in flight is re-run once from
  scratch (its cost stays counted against its run). A slot in flight at a second interruption is not started again.
- **Refusals:**
  - the lock is held;
  - frozen files or `src/` differ;
  - the slot plan does not match the cases;
  - a label directory holds records the log does not account for;
  - the caller sets a ledger, cap, price or model override;
  - the prompt version differs;
  - no API key is set (never read or printed);
  - the approved task cap is below the required one;
  - at the first start, the ledger is not the frozen one (total, line count, SHA-256 prefix); at a resume, it is below
    its last recorded value;
  - an earlier safety stop.

Usage (it detaches; to resume, run the same command again):
    .venv/bin/python eval/model_comparison_dev/run_eval.py --approved-task-cap <USD> [--dry-run]
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
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "src"))

from nem_agent import budget, config  # noqa: E402

LIVE = REPO / "artifacts" / "live"
LOG_DIR = LIVE / "MC-dev"
LOCK = LIVE / "MC-dev.lock"
CASE_RUNNERS = {"route": REPO / "eval" / "livecheck_routing_v12" / "run_route.py",
                "e2e": REPO / "eval" / "livecheck_i15_17" / "run_case.py"}
OVERRIDES = ("NEM_AGENT_BUDGET_LEDGER", "NEM_AGENT_TOTAL_BUDGET_USD", "NEM_AGENT_SESSION_BUDGET_USD",
             "NEM_AGENT_PRICE_INPUT_PER_MTOK", "NEM_AGENT_PRICE_CACHED_INPUT_PER_MTOK", "NEM_AGENT_PRICE_OUTPUT_PER_MTOK",
             "NEM_AGENT_MODEL")
Write = Callable[..., None]


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()


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


def plan_mismatch(freeze: dict[str, Any]) -> str | None:
    """The slot plan must name only cases that exist, and hold each run's frozen number of slots."""
    files: dict[str, set[str]] = {}
    for s in freeze["slots"]:
        rel = s["cases_file"]
        if rel not in files:
            files[rel] = {c["case_id"] for c in json.loads((REPO / rel).read_text())["cases"]}
        if s["case"] not in files[rel]:
            return f"slot {s['slot']}: {s['case']} is not in {rel}"
    count = Counter(s["run"] for s in freeze["slots"])
    for run, spec in freeze["runs"].items():
        if count[run] != spec["slots"]:
            return f"{run} has {count[run]} slots, the freeze {spec['slots']}"
    return None


def env_for(freeze: dict[str, Any], slot: dict[str, Any], cap: float) -> dict[str, str]:
    """The slot's environment: its model, the accounting prices, and its ledger and session caps."""
    m = freeze["models"][slot["model"]]
    p = m["accounting_prices"]
    per_case = freeze["runs"][slot["run"]]["case_cap_usd"]
    return dict(os.environ, NEM_AGENT_MODEL=m["id"], NEM_AGENT_PRICE_INPUT_PER_MTOK=str(p[0]),
                NEM_AGENT_PRICE_CACHED_INPUT_PER_MTOK=str(p[1]), NEM_AGENT_PRICE_OUTPUT_PER_MTOK=str(p[2]),
                NEM_AGENT_TOTAL_BUDGET_USD=f"{cap:.6f}", NEM_AGENT_SESSION_BUDGET_USD=f"{per_case:.6f}")


def ledger_state() -> dict[str, Any]:
    p = budget.ledger_path()
    data = p.read_bytes() if p.exists() else b""
    return {"total": round(budget.spent(), 6), "lines": sum(1 for ln in data.splitlines() if ln.strip()),
            "sha256_prefix": hashlib.sha256(data).hexdigest()[:16]}


# ------------------------------------------------------------------------------------------------ the log
def read_log(live: Path = LIVE) -> list[dict[str, Any]]:
    p = live / "MC-dev" / "run_log.jsonl"
    return [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()] if p.exists() else []


def state(events: list[dict[str, Any]]) -> dict[str, Any]:
    """What the log says: finished slots, whether the comparison ended, each run's spend so far (slot costs, an
    interrupted slot's cost included), how often each slot was in flight at a kill, and the slot in flight."""
    starts = [e for e in events if e.get("event") == "start"]
    done = {e["slot"]: e["outcome"] for e in events if e.get("event") == "slot_end"}
    end = next((e for e in events if e.get("event") == "end"), None)
    spent: defaultdict[str, float] = defaultdict(float)
    for e in events:
        if e.get("event") in ("slot_end", "interrupted") and e.get("run"):
            spent[e["run"]] += float(e.get("ledger_cost") or 0.0)
    in_flight, unrecorded = None, False
    if starts and end is None:
        last = max(i for i, e in enumerate(events) if e.get("event") == "start")
        since = events[last:]
        open_ = [e for e in since if e.get("event") == "slot_start" and e["slot"] not in done]
        in_flight = open_[-1] if open_ else None
        unrecorded = not any(e.get("event") == "interrupted" for e in since)
    kills = Counter(e["slot"] for e in events if e.get("event") == "interrupted" and e.get("slot"))
    return {"attempts": len(starts), "done": done, "end": end, "spent": spent, "in_flight": in_flight,
            "kills": kills, "unrecorded_kill": unrecorded,
            "safety_stop": any(e.get("event") == "end" and e.get("safety_stop") for e in events)}


def stray(freeze: dict[str, Any], events: list[dict[str, Any]], live: Path = LIVE) -> list[str]:
    """Records in a label directory that no slot of the log started: a duplicate or stray run leaves them."""
    started = {(e["label"], e["case"]) for e in events if e.get("event") == "slot_start"}
    out = []
    for label in sorted({s["label"] for s in freeze["slots"]}):
        d = live / label
        if not d.exists():
            continue
        for p in d.glob("*.json"):
            cid = p.name.split(".")[0]
            if cid != "summary" and (label, cid) not in started:
                out.append(f"{label}/{p.name}")
    return sorted(out)


def refusal(freeze: dict[str, Any], approved: float | None, ledger: dict[str, Any],
            events: list[dict[str, Any]], live: Path = LIVE) -> str | None:
    why = changed(freeze) or plan_mismatch(freeze)
    if why:
        return why
    extra = stray(freeze, events, live)
    if extra:
        return f"label directories hold records the log does not account for: {', '.join(extra[:5])}"
    st = state(events)
    if st["safety_stop"]:
        return "the comparison ended with a safety stop"
    if st["end"] is not None:
        return "the comparison has ended; it is never resumed or repeated"
    if any(os.environ.get(k) for k in OVERRIDES):
        return "a ledger, cap, price or model override is set"
    if freeze["prompt_version"] != config.PROMPT_VERSION:
        return "the prompt version differs"
    if not os.environ.get("OPENAI_API_KEY"):
        return "no API key is set"
    need = float(freeze["required_task_cap_usd"])
    if approved is None or round(approved, 6) < round(need, 6):
        return f"the approved task cap must be at least USD {need} (given: {approved})"
    if not st["attempts"]:
        want = (round(float(freeze["ledger_start_usd"]), 6), int(freeze["ledger_lines"]), freeze["ledger_sha256_prefix"])
        got = (ledger["total"], ledger["lines"], ledger["sha256_prefix"])
        if got != want:
            return f"the ledger {got} is not the frozen starting ledger {want}"
        return None
    last = max(float(e[k]) for e in events for k in ("ledger_before", "ledger_after", "ledger_now", "ledger_committed")
               if k in e)
    if ledger["total"] < round(last, 6):
        return f"the ledger total {ledger['total']} is below the last recorded value {last}"
    return None


# ------------------------------------------------------------------------------------------------ slots
def outcome(stdout: str, returncode: int, saved: bool, trace: dict[str, Any] | None) -> str:
    """budget_stop, error, saved or missing (as the v12 runner reads them)."""
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


def launch(slot: dict[str, Any], env: dict[str, str], live: Path = LIVE) -> tuple[int, str]:
    """One slot's process; returns its exit code and standard output."""
    out = live / slot["label"]
    out.mkdir(parents=True, exist_ok=True)
    args = ((["--case", slot["case"]] if slot["kind"] == "route" else ["--cases", slot["case"]])
            + ["--cases-file", slot["cases_file"], "--label", slot["label"]])
    so_p = out / f"{slot['case']}.stdout.txt"
    with so_p.open("w") as so:
        rc = subprocess.run([sys.executable, str(CASE_RUNNERS[slot["kind"]]), *args], cwd=REPO, env=env, stdout=so,
                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL).returncode
    return rc, so_p.read_text()


def finish(slot: dict[str, Any], rc: int, text: str, live: Path = LIVE) -> tuple[str, dict[str, Any] | None]:
    """The slot's outcome from its files; copies its trace next to the record."""
    out = live / slot["label"]
    rec_p = out / f"{slot['case']}.json"
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


def run(freeze: dict[str, Any], events: list[dict[str, Any]], write: Write, *, task_cap: float,
        launch: Callable[..., tuple[int, str]] = launch, finish: Callable[..., tuple[str, dict[str, Any] | None]] = finish,
        spent: Callable[[], float] = budget.spent, frozen: Callable[[], str | None] = lambda: None,
        live: Path = LIVE, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Start or resume the comparison. ``launch``, ``finish``, ``spent`` and ``frozen`` are injectable so the loop is
    tested offline."""
    st = state(events)
    if st["end"] is not None:
        return st["end"]
    slots = freeze["slots"]
    by_n = {s["slot"]: s for s in slots}
    done = dict(st["done"])
    run_spent: defaultdict[str, float] = defaultdict(float, st["spent"])
    stop: str | None = None
    rerun = None
    now = spent()
    if st["attempts"]:  # the last attempt never wrote its end: the environment killed it
        flight = st["in_flight"]
        n = flight["slot"] if flight else None
        kills = st["kills"][n] if n else 0
        if st["unrecorded_kill"]:
            cost = round(now - float(flight["ledger_before"]), 6) if flight else 0.0
            write(event="interrupted", attempt=st["attempts"], slot=n, run=flight["run"] if flight else None,
                  ledger_now=now, ledger_cost=cost)
            if flight:
                run_spent[flight["run"]] += cost
            kills += 1 if n else 0
        if n is not None:
            s = by_n[n]
            out = live / s["label"]
            if (out / f"{s['case']}.json").exists() or (out / f"{s['case']}.error.json").exists():
                text = (out / f"{s['case']}.stdout.txt").read_text() if (out / f"{s['case']}.stdout.txt").exists() else ""
                result, rec = finish(s, 0 if (out / f"{s['case']}.json").exists() else 1, text)
                done[n] = result
                fails = safety(rec) if rec and result == "saved" else []
                write(event="slot_end", slot=n, run=s["run"], label=s["label"], case=s["case"], outcome=result,
                      recovered_after_interruption=True, ledger_after=now, ledger_cost=0.0, safety_failures=fails)
                stop = (f"{result.replace('_', ' ')} in slot {n}" if result != "saved"
                        else f"safety failure in slot {n}: {fails}" if fails else None)
            elif kills >= 2:
                stop = f"slot {n} was in flight at two interruptions; it is not started again"
            else:
                rerun = n
                so = out / f"{s['case']}.stdout.txt"
                if so.exists():
                    so.rename(out / f"{s['case']}.stdout.interrupted{kills}.txt")
    write(event="start", attempt=st["attempts"] + 1, ledger_committed=now, task_cap=task_cap,
          run_caps={r: v["run_cap_usd"] for r, v in freeze["runs"].items()}, rerun_after_interruption=rerun,
          **(meta or {}))
    safety_stop = False
    for i, s in enumerate(slots):
        n, run_name = s["slot"], s["run"]
        if n in done:
            continue
        if stop is None:
            moved = frozen()
            stop = f"frozen material changed: {moved}" if moved else None
        before = spent()
        per_case = float(freeze["runs"][run_name]["case_cap_usd"])
        run_cap = float(freeze["runs"][run_name]["run_cap_usd"])
        fits = (round(run_spent[run_name] + per_case, 6) <= round(run_cap, 6)
                and round(before + per_case, 6) <= round(task_cap, 6))
        if stop or not fits:
            stop = stop or (f"start guard: slot {n} ({run_name}) does not fit: run spend {round(run_spent[run_name], 6)}"
                            f" + case cap {per_case} > run cap {run_cap}, or ledger {before} + {per_case} > task cap")
            write(event="not_run", slots=[x["slot"] for x in slots[i:] if x["slot"] not in done], reason=stop)
            break
        cap = round(before + per_case, 6)
        write(event="slot_start", slot=n, run=run_name, label=s["label"], case=s["case"], model=freeze["models"][s["model"]]["id"],
              repeat=s["repeat"], ledger_before=before, slot_ledger_cap=cap, rerun=n == rerun)
        t0 = time.monotonic()
        rc, text = launch(s, env_for(freeze, s, cap))
        result, rec = finish(s, rc, text)
        after = spent()
        cost = round(after - before, 6)
        run_spent[run_name] += cost
        fails = safety(rec) if rec and result == "saved" else []
        done[n] = result
        write(event="slot_end", slot=n, run=run_name, label=s["label"], case=s["case"], outcome=result, returncode=rc,
              ledger_after=after, ledger_cost=cost, elapsed_s=round(time.monotonic() - t0, 1), safety_failures=fails)
        if result != "saved" or fails:
            safety_stop = bool(fails)
            stop = f"safety failure in slot {n}: {fails}" if fails else f"{result.replace('_', ' ')} in slot {n}"
            write(event="not_run", slots=[x["slot"] for x in slots[i + 1:] if x["slot"] not in done], reason=stop)
            break
    end_ledger = spent()
    saved = [s["slot"] for s in slots if done.get(s["slot"]) == "saved"]
    end = {"event": "end", "result": "complete" if len(saved) == len(slots) else "incomplete", "saved": len(saved),
           "not_saved": [s["slot"] for s in slots if s["slot"] not in saved], "stop_reason": stop,
           "safety_stop": safety_stop or bool(stop and stop.startswith("safety")), "ledger_committed": end_ledger,
           "run_spend": {r: round(run_spent[r], 6) for r in freeze["runs"]}}
    write(**end)
    return end


# ------------------------------------------------------------------------------------------------ main
def _writer(path: Path) -> Write:
    def write(**kw: object) -> None:
        with path.open("a") as fh:
            fh.write(json.dumps({"at": _now(), **kw}, default=str) + "\n")

    return write


def take_lock(path: Path = LOCK) -> TextIO | None:
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
    events = read_log()
    why = refusal(freeze, args.approved_task_cap, ledger_state(), events)
    if args.dry_run:
        st = state(events)
        print(json.dumps({"refusal": why, "ledger": ledger_state(), "required_task_cap": freeze["required_task_cap_usd"],
                          "slots": len(freeze["slots"]), "done": len(st["done"]), "ended": st["end"] is not None},
                         indent=1, default=str))
        return 0 if why is None else 2
    if why:
        print(f"refused: {why}")
        return 2
    if not args.foreground:
        logdir = REPO / "artifacts" / "logs"
        logdir.mkdir(parents=True, exist_ok=True)
        with open(logdir / "MC_dev_driver.log", "a") as log:
            p = subprocess.Popen([sys.executable, __file__, *sys.argv[1:], "--foreground"], cwd=REPO, stdout=log,
                                 stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
        print(f"started detached (pid {p.pid}); log artifacts/logs/MC_dev_driver.log")
        return 0
    lock = take_lock()
    if lock is None:
        print("refused: another invocation holds the lock")
        return 2
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    meta = {"commit": _git("rev-parse", "HEAD"), "src_tree": _git("rev-parse", "HEAD:src"),
            "code_commit": freeze["code_commit"], "prompt_version": config.PROMPT_VERSION}
    end = run(freeze, events, _writer(LOG_DIR / "run_log.jsonl"), task_cap=float(args.approved_task_cap),
              frozen=lambda: changed(freeze), meta=meta)
    print(f"{_now()} comparison: {end['result']} ({end['saved']}/{len(freeze['slots'])} slots saved); ledger "
          f"{end['ledger_committed']}{'; stop: ' + end['stop_reason'] if end['stop_reason'] else ''}")
    lock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
