"""Run the comparison (PROTOCOL.md) on the frozen code: the 322 slots of FREEZE.json in their frozen order, once each.
Adapted from eval/livecheck_route_v15/run_eval.py (frozen, unchanged): the same lock, freeze check, stray-record check
and detached start, with these differences, all pre-registered in PROTOCOL.md:

- **Two arms:** each slot runs in its arm's environment (``run_route.ARM_ENV``): A with the route plan off, B with it on
  and policy V1.
- **Terminal records:** ``saved``; ``api_error`` (recorded by the slot; the run continues; nothing is retried);
  ``interrupted`` (the slot's process ended without a record, or the runner was killed with the slot in flight, found
  at the next start). An interrupted slot counts at its full reservation and is never started again.
- **Caps, enforced independently:**
  - the ledger (`nem_agent.budget`): each slot's ledger cap is the ledger total before it plus its frozen reservation;
  - the conservative account: a slot starts only if the conservative spend so far (observed usage cost where a
    response was observed, the full reservation otherwise) plus its reservation is within the frozen run cap, and the
    run cap within the approved spend.
- **Stops:** the start guard, a ledger budget refusal, a change to frozen files or `src/`, or a safety failure (C6: a
  tool executed or a case-note write). The rest are not run.
- **Accounting paths** (`--ledger`): `historical`, the default ledger, which must match its recorded state at the first
  start; or `evaluation`, `artifacts/live_budget/CMP-route-v15-v16.ledger.jsonl`, absent or empty at the first start.
- **Completeness and reconciliation** are recorded at the end: one terminal record per slot, and the ledger's change
  per slot summing to its total change.

Usage (it detaches; to resume, run the same command again):
    .venv/bin/python eval/compare_route_v15_v16/run_eval.py --ledger evaluation --approved-spend <USD> [--dry-run]
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "src"))

from nem_agent import budget  # noqa: E402

LIVE = REPO / "artifacts" / "live"
LOG_NAME = "CMP-route-v15-v16"
LOCK = LIVE / "CMP-route-v15-v16.lock"
CASE_RUNNER = HERE / "run_route.py"
EVALUATION_LEDGER = REPO / "artifacts" / "live_budget" / "CMP-route-v15-v16.ledger.jsonl"
HISTORICAL_LEDGER = {"total": 9.336937, "lines": 3226, "sha256_prefix": "f303c2bc70aadd8f"}  # as previously recorded
TERMINAL = ("saved", "api_error", "interrupted")
OVERRIDES = ("NEM_AGENT_HOME", "NEM_AGENT_BUDGET_LEDGER", "NEM_AGENT_TOTAL_BUDGET_USD", "NEM_AGENT_SESSION_BUDGET_USD",
             "NEM_AGENT_PRICE_INPUT_PER_MTOK", "NEM_AGENT_PRICE_CACHED_INPUT_PER_MTOK", "NEM_AGENT_PRICE_OUTPUT_PER_MTOK",
             "NEM_AGENT_MODEL", "NEM_AGENT_ROUTE_PLAN", "NEM_AGENT_PLAN_POLICY", "CMP_ROUTE_FAKE")
Write = Callable[..., None]


def _sibling(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"compare_route_v15_v16_{name}", HERE / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()


# ------------------------------------------------------------------------------------------------ the freeze
def changed(freeze: dict[str, Any]) -> str | None:
    for rel, want in freeze["files_sha256"].items():
        p = REPO / rel
        if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != want:
            return f"{rel} differs from FREEZE.json"
    if _git("rev-parse", "HEAD:src") != freeze["src_tree"] or _git("status", "--porcelain", "--", "src"):
        return "the checkout's src/ is not the frozen tree"
    return None


def plan_mismatch(freeze: dict[str, Any], cases: list[dict[str, Any]] | None = None) -> str | None:
    """Each configuration holds its frozen repeats in each arm; slots are numbered in order; the run cap is the sum of
    the slots' reservations."""
    cases = json.loads((HERE / "cases.json").read_text())["cases"] if cases is None else cases
    want = {(c["config"], arm): c["repeats"] for c in cases for arm in ("A", "B")}
    got: dict[tuple[str, str], int] = {}
    for s in freeze["slots"]:
        got[(s["config"], s["arm"])] = got.get((s["config"], s["arm"]), 0) + 1
    if got != want:
        return "the plan does not hold each configuration's frozen repeats in each arm"
    if [s["slot"] for s in freeze["slots"]] != list(range(1, len(freeze["slots"]) + 1)):
        return "the plan's slots are not numbered in order"
    if len({s["case"] for s in freeze["slots"]}) != len(freeze["slots"]):
        return "the plan's slot names are not distinct"
    if round(sum(s["reservation_usd"] for s in freeze["slots"]), 6) != round(freeze["run_cap_usd"], 6):
        return "the run cap is not the sum of the slots' reservations"
    return None


def ledger_state() -> dict[str, Any]:
    p = budget.ledger_path()
    data = p.read_bytes() if p.exists() else b""
    return {"path": str(p), "exists": p.exists(), "total": round(budget.spent(), 6) if p.exists() else 0.0,
            "lines": sum(1 for ln in data.splitlines() if ln.strip()),
            "sha256_prefix": hashlib.sha256(data).hexdigest()[:16]}


def select_ledger(mode: str | None) -> None:
    """Point this process (and so its slots) at the named accounting path."""
    if mode == "evaluation":
        os.environ["NEM_AGENT_BUDGET_LEDGER"] = str(EVALUATION_LEDGER)


# ------------------------------------------------------------------------------------------------ the log
def read_log(live: Path = LIVE) -> list[dict[str, Any]]:
    p = live / LOG_NAME / "run_log.jsonl"
    return [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()] if p.exists() else []


def state(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Slots with an end record, whether the evaluation ended, the conservative spend, and the slot in flight at a
    kill."""
    starts = [i for i, e in enumerate(events) if e.get("event") == "start"]
    done = {e["slot"]: e["outcome"] for e in events if e.get("event") in ("slot_end", "interrupted")}
    end = next((e for e in events if e.get("event") == "end"), None)
    conservative = round(sum(float(e.get("conservative_usd") or 0.0) for e in events
                             if e.get("event") in ("slot_end", "interrupted")), 6)
    in_flight = None
    if starts and end is None:
        open_ = [e for e in events[starts[-1]:] if e.get("event") == "slot_start" and e["slot"] not in done]
        in_flight = open_[-1] if open_ else None
    return {"attempts": len(starts), "done": done, "end": end, "conservative": conservative, "in_flight": in_flight}


def stray(freeze: dict[str, Any], events: list[dict[str, Any]], live: Path = LIVE) -> list[str]:
    started = {e["case"] for e in events if e.get("event") == "slot_start"}
    d = live / freeze["label"]
    if not d.exists():
        return []
    return sorted(f"{freeze['label']}/{p.name}" for p in d.glob("*.json") if p.name.split(".")[0] not in started)


def refusal(freeze: dict[str, Any], mode: str | None, approved: float | None, ledger: dict[str, Any],
            events: list[dict[str, Any]], live: Path = LIVE, env: dict[str, str] | None = None,
            frozen: Callable[[dict[str, Any]], str | None] = changed,
            cases: list[dict[str, Any]] | None = None) -> str | None:
    """Why the evaluation may not start or resume, or None. ``env``: the caller's environment."""
    env = dict(os.environ) if env is None else env
    why = frozen(freeze) or plan_mismatch(freeze, cases)
    if why:
        return why
    extra = stray(freeze, events, live)
    if extra:
        return f"the record directory holds records the log does not account for: {', '.join(extra[:5])}"
    st = state(events)
    if st["end"] is not None:
        return "the evaluation has ended" + (" with a safety stop" if st["end"].get("safety_stop") else "") + \
            "; it is never resumed or repeated"
    caller = sorted(k for k in OVERRIDES if env.get(k))
    if caller:
        return f"an override is set by the caller: {caller}"
    if mode not in ("historical", "evaluation"):
        return "the accounting path is not named (--ledger historical|evaluation)"
    if not env.get("OPENAI_API_KEY"):
        return "no API key is set"
    if approved is None or round(approved, 6) < round(float(freeze["run_cap_usd"]), 6):
        return f"the approved spend must be at least the run cap USD {freeze['run_cap_usd']} (given: {approved})"
    if not st["attempts"]:
        if mode == "historical":
            got = (ledger["total"], ledger["lines"], ledger["sha256_prefix"])
            want = (HISTORICAL_LEDGER["total"], HISTORICAL_LEDGER["lines"], HISTORICAL_LEDGER["sha256_prefix"])
            if got != want:
                return f"the ledger {got} is not the historical ledger as recorded {want}"
        elif ledger["lines"]:
            return f"the evaluation ledger {ledger.get('path')} is not empty at the first start"
    else:
        mode_was = next((e.get("ledger_path_mode") for e in events if e.get("event") == "start"), mode)
        if mode_was != mode:
            return f"the evaluation started on the {mode_was} accounting path; it resumes only on it"
    return None


# ------------------------------------------------------------------------------------------------ slots
def env_for(freeze: dict[str, Any], slot: dict[str, Any], ledger_cap: float, base: dict[str, str] | None = None
            ) -> dict[str, str]:
    """The slot's environment: its arm's route-plan settings, the frozen model, and its ledger and session caps."""
    rr = _sibling("run_route")
    env = {k: v for k, v in (os.environ if base is None else base).items() if k not in rr.PLAN_SETTINGS}
    env.update(rr.ARM_ENV[slot["arm"]])
    env.update(NEM_AGENT_MODEL=freeze["model"], NEM_AGENT_TOTAL_BUDGET_USD=f"{ledger_cap:.6f}",
               NEM_AGENT_SESSION_BUDGET_USD=f"{slot['reservation_usd'] + 1e-6:.6f}")
    return env


def launch(slot: dict[str, Any], env: dict[str, str], live: Path = LIVE, label: str = "") -> tuple[int, str]:
    out = live / label
    out.mkdir(parents=True, exist_ok=True)
    so_p = out / f"{slot['case']}.stdout.txt"
    with so_p.open("w") as so:
        rc = subprocess.run([sys.executable, str(CASE_RUNNER), "--slot", str(slot["slot"]), "--label", label,
                             "--out", str(out)], cwd=REPO, env=env, stdout=so, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL).returncode
    return rc, so_p.read_text()


def outcome(stdout: str, rec: dict[str, Any] | None) -> str:
    """saved, api_error, budget_stop (the ledger refused the reservation: nothing was sent) or interrupted (the slot's
    process ended without a record)."""
    if "STOPPED:" in stdout:
        return "budget_stop"
    if rec is None:
        return "interrupted"
    return "api_error" if rec.get("api_error") else "saved"


def observed_cost(rec: dict[str, Any] | None) -> float | None:
    """The usage-priced cost of a response the slot actually received, or None (no usage observed)."""
    if rec is None or rec.get("api_error"):
        return None
    c = (rec.get("route_call") or {}).get("usage_cost_usd")
    return None if c is None else float(c)


def safety(rec: dict[str, Any] | None) -> list[str]:
    """C6: any tool executed, or any case-note write."""
    s = (rec or {}).get("score") or {}
    out = []
    if s.get("case_note_files_written"):
        out.append(f"{s['case_note_files_written']} case-note file(s) written")
    if s.get("tools_executed"):
        out.append(f"{s['tools_executed']} tool(s) executed")
    return out


def slot_end(s: dict[str, Any], result: str, rec: dict[str, Any] | None, before: float, after: float,
             **extra: Any) -> dict[str, Any]:
    """The slot's accounting, kinds kept apart: reserved, settled (the ledger's change), observed usage, unresolved,
    and conservative (observed where observed, else the full reservation; nothing for a refused reservation)."""
    cost = observed_cost(rec)
    cons = 0.0 if result == "budget_stop" else (cost if cost is not None else float(s["reservation_usd"]))
    return {"event": "interrupted" if result == "interrupted" else "slot_end", "slot": s["slot"], "arm": s["arm"],
            "case": s["case"], "outcome": result, "reserved_usd": float(s["reservation_usd"]), "ledger_after": after,
            "settled_usd": round(after - before, 6), "observed_usd": cost,
            "unresolved": result != "budget_stop" and cost is None, "conservative_usd": cons,
            "safety_failures": safety(rec), **extra}


def run(freeze: dict[str, Any], events: list[dict[str, Any]], write: Write, *, approved: float,
        launch: Callable[..., tuple[int, str]] = launch, spent: Callable[[], float] = budget.spent,
        frozen: Callable[[], str | None] = lambda: None, live: Path = LIVE, meta: dict[str, Any] | None = None,
        base_env: dict[str, str] | None = None) -> dict[str, Any]:
    """Start or resume the evaluation. ``launch``, ``spent`` and ``frozen`` are injectable for offline tests."""
    st = state(events)
    if st["end"] is not None:
        return st["end"]
    log = list(events)

    def emit(**kw: Any) -> None:
        log.append(kw)
        write(**kw)

    label = freeze["label"]
    out = live / label
    slots = freeze["slots"]
    done = dict(st["done"])
    conservative = st["conservative"]
    run_cap = float(freeze["run_cap_usd"])
    stop: str | None = None
    safety_stop = False
    if st["in_flight"]:  # killed with a slot in flight: interrupted, never started again
        f = st["in_flight"]
        rec_p = out / f"{f['case']}.json"
        rec = json.loads(rec_p.read_text()) if rec_p.exists() else None  # a record: only its log entry was lost
        e = slot_end(f, outcome("", rec), rec, float(f["ledger_before"]), spent(), found_at_start=True)
        emit(**e)
        done[f["slot"]] = e["outcome"]
        conservative = round(conservative + e["conservative_usd"], 6)
        if e["safety_failures"]:
            stop, safety_stop = f"safety failure in slot {f['case']}: {e['safety_failures']}", True
    emit(event="start", attempt=st["attempts"] + 1, ledger_committed=spent(), approved_spend=approved,
         run_cap=run_cap, conservative_so_far=conservative, **(meta or {}))
    for i, s in enumerate(slots):
        n = s["slot"]
        if n in done:
            continue
        if stop is None:
            moved = frozen()
            stop = f"frozen material changed: {moved}" if moved else None
        res_usd = float(s["reservation_usd"])
        if stop is None and round(conservative + res_usd, 6) > round(min(run_cap, approved), 6):
            stop = (f"start guard: slot {s['case']} does not fit: conservative spend {conservative} + reservation "
                    f"{res_usd} > run cap {min(run_cap, approved)}")
        if stop:
            emit(event="not_run", slots=[x["slot"] for x in slots[i:] if x["slot"] not in done], reason=stop)
            break
        before = spent()
        cap = round(before + res_usd + 1e-6, 6)
        emit(event="slot_start", slot=n, arm=s["arm"], case=s["case"], model=freeze["model"], ledger_before=before,
             slot_ledger_cap=cap, reservation_usd=res_usd)
        t0 = time.monotonic()
        rc, text = launch(s, env_for(freeze, s, cap, base_env), live, label)
        rec_p = out / f"{s['case']}.json"
        rec = json.loads(rec_p.read_text()) if rec_p.exists() else None
        e = slot_end(s, outcome(text, rec), rec, before, spent(), returncode=rc,
                     elapsed_s=round(time.monotonic() - t0, 1))
        emit(**e)
        done[n] = e["outcome"]
        conservative = round(conservative + e["conservative_usd"], 6)
        if e["outcome"] == "budget_stop" or e["safety_failures"]:
            safety_stop = bool(e["safety_failures"])
            stop = (f"safety failure in slot {s['case']}: {e['safety_failures']}" if safety_stop
                    else f"ledger budget refusal in slot {s['case']}")
            emit(event="not_run", slots=[x["slot"] for x in slots[i + 1:] if x["slot"] not in done], reason=stop)
            break
    terminal = sum(1 for r in done.values() if r in TERMINAL)
    end: dict[str, Any] = {
        "event": "end", "result": "complete" if terminal == len(slots) else "incomplete", "terminal": terminal,
        "of": len(slots), "stop_reason": stop, "safety_stop": safety_stop, "ledger_committed": spent(),
        "conservative_usd": conservative, "run_cap_usd": run_cap, "approved_spend_usd": approved,
        "outcomes": {r: sum(1 for x in done.values() if x == r) for r in sorted(set(done.values()))}}
    end["reconciliation"] = reconcile([*log, end])
    if end["result"] == "complete" and not end["reconciliation"]["reconciles"]:
        end["result"] = "incomplete"
        end["stop_reason"] = "the slot accounting does not reconcile with the ledger"
    emit(**end)
    return end


def reconcile(events: list[dict[str, Any]]) -> dict[str, Any]:
    """The ledger's change per slot against its total change from the first start to the end, and the accounting
    kinds, each summed apart."""
    ends = [e for e in events if e.get("event") in ("slot_end", "interrupted")]
    start = next((e for e in events if e.get("event") == "start"), None)
    last = next((e for e in reversed(events) if e.get("event") == "end"), None)
    change = round(float(last["ledger_committed"]) - float(start["ledger_committed"]), 6) \
        if start is not None and last is not None else None
    settled = round(sum(float(e.get("settled_usd") or 0.0) for e in ends), 6)
    distinct = len({e["slot"] for e in ends})
    return {"slot_records": len(ends), "distinct_slots": distinct,
            "reserved_usd": round(sum(float(e.get("reserved_usd") or 0.0) for e in ends
                                      if e.get("outcome") != "budget_stop"), 6),
            "settled_usd": settled, "ledger_change_usd": change,
            "reconciles": change is not None and distinct == len(ends)
            and abs(settled - change) <= 1e-6 * max(1, len(ends)),
            "observed_usd": round(sum(float(e.get("observed_usd") or 0.0) for e in ends), 6),
            "observed_slots": sum(1 for e in ends if e.get("observed_usd") is not None),
            "unresolved_slots": sum(1 for e in ends if e.get("unresolved")),
            "conservative_usd": round(sum(float(e.get("conservative_usd") or 0.0) for e in ends), 6)}


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
    ap.add_argument("--ledger", choices=["historical", "evaluation"], default=None, help="the accounting path")
    ap.add_argument("--approved-spend", type=float, default=None, help="the spend the owner approved (USD)")
    ap.add_argument("--dry-run", action="store_true", help="print the refusal check and the plan; start nothing")
    ap.add_argument("--foreground", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    caller_env = dict(os.environ)
    freeze = json.loads((HERE / "FREEZE.json").read_text())
    events = read_log()
    select_ledger(args.ledger)
    why = refusal(freeze, args.ledger, args.approved_spend, ledger_state(), events, env=caller_env)
    if args.dry_run:
        print(json.dumps({"refusal": why, "ledger": ledger_state(), "run_cap_usd": freeze["run_cap_usd"],
                          "slots": len(freeze["slots"]), "ended_slots": len(state(events)["done"])}, indent=1))
        return 0 if why is None else 2
    if why:
        print(f"refused: {why}")
        return 2
    if not args.foreground:
        logdir = REPO / "artifacts" / "logs"
        logdir.mkdir(parents=True, exist_ok=True)
        with open(logdir / "CMP_route_v15_v16_driver.log", "a") as log:
            p = subprocess.Popen([sys.executable, __file__, *sys.argv[1:], "--foreground"], cwd=REPO, env=caller_env,
                                 stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
        print(f"started detached (pid {p.pid}); log artifacts/logs/CMP_route_v15_v16_driver.log")
        return 0
    lock = take_lock()
    if lock is None:
        print("refused: another invocation holds the lock")
        return 2
    (LIVE / LOG_NAME).mkdir(parents=True, exist_ok=True)
    meta = {"commit": _git("rev-parse", "HEAD"), "src_tree": _git("rev-parse", "HEAD:src"),
            "ledger_path_mode": args.ledger, "ledger": ledger_state()}
    end = run(freeze, events, _writer(LIVE / LOG_NAME / "run_log.jsonl"), approved=float(args.approved_spend),
              frozen=lambda: changed(freeze), meta=meta)
    print(f"{_now()} evaluation: {end['result']} ({end['terminal']}/{end['of']} slots); conservative "
          f"{end['conservative_usd']}{'; stop: ' + end['stop_reason'] if end['stop_reason'] else ''}")
    lock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
