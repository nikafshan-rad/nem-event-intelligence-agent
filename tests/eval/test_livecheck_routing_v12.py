"""Offline verification of the protocol for the Live check of the v12 routing extraction (eval/livecheck_routing_v12),
before any paid call.

- **Runner** (adapted from eval/livecheck_i15_17/run_eval.py):
  - the case caps (USD 0.01 per routing call, 0.15 per end-to-end case), the run caps (R-dev 0.10, R-fresh 0.15,
    E-dev 0.50) and the approved task cap (8.174670);
  - the start guard;
  - the stops: budget stop, API error, missing record, H1 safety failure, frozen material changed;
  - the interruption rule;
  - each run only after every earlier run ended complete with no safety stop;
  - its refusals, including another invocation holding the lock and records no log accounts for.
- **Routing cases:** `run_route.route_case` is the first step of a Live investigation (route, then resolve), and the
  outcome labels follow PASS_RULE.md ("Correct binding").
- **Scorer:** the decision rules: WRONG, ROUTE_INVALID (more than 1), H1–H5 and X fail; incomplete coverage is
  INCOMPLETE, never PASS; the per-area bars; containment is not supply; the stricter of two readings.
- **Freeze:** the frozen files, code identity, caps and plans are the protocol's.

The fake world is SYNTHETIC (no network, no key), and the ledger is a per-test scratch file (conftest). Scripted runs
are not a measure of Live behaviour.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from nem_agent.agent.request import InvestigateRequest
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

REPO = Path(__file__).resolve().parents[2]
HERE = REPO / "eval" / "livecheck_routing_v12"
START = 7.424670  # the real ledger total when this protocol was prepared


def _load(name: str, path: Path) -> Any:
    """Loaded under its own name, without putting the directory on sys.path."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RUN = _load("route_v12_run_eval", HERE / "run_eval.py")
SCORE = _load("route_v12_score", HERE / "score.py")
ROUTE = _load("route_v12_run_route", HERE / "run_route.py")
FREEZE: dict[str, Any] = json.loads((HERE / "FREEZE.json").read_text()) if (HERE / "FREEZE.json").exists() else {}
DEV = ["Z03", "Z05", "Z04"] + [f"K{i:02d}" for i in range(1, 16)]
FRESH = [f"Q{i:02d}" for i in range(1, 25)]
E2E = ["K05", "K06", "K07", "K09", "K10"]
LC = "eval/livecheck_i15_17/cases.json"
PLAN = {
    "R-dev": {"label": "LC-route-v12-dev", "kind": "route", "run_cap_usd": 0.10, "case_cap_usd": 0.01,
              "cases": [[c, LC] for c in DEV]},
    "R-fresh": {"label": "LC-route-v12-fresh", "kind": "route", "run_cap_usd": 0.15, "case_cap_usd": 0.01,
                "cases": [[c, "eval/livecheck_routing_v12/cases.json"] for c in FRESH]},
    "E-dev": {"label": "LC-route-v12-e2e", "kind": "e2e", "run_cap_usd": 0.50, "case_cap_usd": 0.15,
              "cases": [[c, LC] for c in E2E]},
}


# ------------------------------------------------------------------------------------------------ a simulated run
class World:
    """A ledger and a fake case process: each launch spends the case's cost and leaves the files a real one would."""

    def __init__(self, out: Path, costs: dict[str, float], results: dict[str, str] | None = None,
                 safety: dict[str, dict[str, int]] | None = None, ledger: float = START) -> None:
        self.out, self.costs, self.results, self.safety = out, costs, results or {}, safety or {}
        self.ledger = ledger
        self.launched: list[tuple[str, str, float]] = []

    def spent(self) -> float:
        return round(self.ledger, 6)

    def launch(self, kind: str, cid: str, cases_file: str, env: dict[str, str], out: Path) -> tuple[int, str]:
        cap = float(env["NEM_AGENT_TOTAL_BUDGET_USD"])
        assert env["NEM_AGENT_MODEL"] == "gpt-5-mini"
        self.launched.append((kind, cid, round(cap - self.ledger, 6)))
        self.ledger += min(self.costs.get(cid, 0.002), cap - self.ledger)  # the ledger never lets a case pass its cap
        result = self.results.get(cid, "saved")
        score = {"trace_id": None, "case_note_files_written": 0, "forbidden_calls": 0, **self.safety.get(cid, {})}
        text = f"[{cid}] status=ok"
        if result == "stdout_stop":
            text = f"[{cid}] STOPPED: task budget {cap:.2f} USD: ..."
        elif result == "error":
            text = f"[{cid}] ERROR APITimeoutError: Request timed out."
            (out / f"{cid}.error.json").write_text("{}")
        if result == "saved":
            (out / f"{cid}.json").write_text(json.dumps({"score": score}))
        (out / f"{cid}.stdout.txt").write_text(text)
        return 0, text


def _run(tmp: Path, world: World | None = None, *, events: list[dict[str, Any]] | None = None, plan=None,
         task_cap: float = 8.174670, moved_before: str | None = None, **kw: Any):
    plan = plan or PLAN["R-fresh"]
    world = world or World(tmp, {}, **kw)
    log: list[dict[str, Any]] = list(events or [])
    new: list[dict[str, Any]] = []

    def write(**e: Any) -> None:
        log.append(e)
        new.append(e)

    def frozen() -> str | None:
        nxt = next((c for c, _ in plan["cases"] if not (tmp / f"{c}.json").exists()), None)
        return "a file" if moved_before and nxt == moved_before else None

    end = RUN.run(plan, list(events or []), write, model="gpt-5-mini", task_cap=task_cap, out=tmp,
                  launch=world.launch, spent=world.spent, frozen=frozen)
    return end, new, world


def test_each_routing_case_gets_its_own_cap_of_one_cent_under_its_run_cap(tmp_path):
    end, log, world = _run(tmp_path, plan=PLAN["R-dev"])
    assert [c for _, c, _ in world.launched] == DEV and {k for k, _, _ in world.launched} == {"route"}
    assert all(cap == pytest.approx(0.01) for _, _, cap in world.launched)
    assert end["result"] == "complete" and log[0]["run_cap"] == pytest.approx(START + 0.10)


@pytest.mark.parametrize("run,worst", [("R-dev", 0.0051), ("R-fresh", 0.0051)])
def test_the_routing_caps_hold_every_case_at_a_routing_calls_worst_case(tmp_path, run, worst):
    """A v12 routing call's worst case, as the ledger reserves it, is about USD 0.0051: every case of each routing run
    can start even if every call costs that much."""
    ids = [c for c, _ in PLAN[run]["cases"]]
    end, _log, world = _run(tmp_path, World(tmp_path, dict.fromkeys(ids, worst)), plan=PLAN[run])
    assert len(world.launched) == len(ids) and end["result"] == "complete"


def test_the_end_to_end_cap_starts_a_case_only_if_its_full_cap_fits(tmp_path):
    """At USD 0.15 per case, three E-dev cases fit under USD 0.50 if each spends its whole cap; the fourth does not
    start, and the run is incomplete. At the expected cost, all five run."""
    end, log, world = _run(tmp_path, World(tmp_path, dict.fromkeys(E2E, 0.15)), plan=PLAN["E-dev"])
    assert [c for _, c, _ in world.launched] == E2E[:3] and end["result"] == "incomplete"
    assert next(e for e in log if e["event"] == "not_run")["reason"].startswith("start guard")
    ok = tmp_path / "ok"
    ok.mkdir()
    end2, _log2, world2 = _run(ok, World(ok, dict.fromkeys(E2E, 0.04)), plan=PLAN["E-dev"])
    assert {k for k, _, _ in world2.launched} == {"e2e"} and end2["result"] == "complete"


@pytest.mark.parametrize("kind,outcome", [("stdout_stop", "budget_stop"), ("error", "error"), ("missing", "missing")])
def test_a_budget_stop_error_or_missing_record_ends_the_run_without_retry(tmp_path, kind, outcome):
    end, log, world = _run(tmp_path, results={"Q03": kind})
    assert [c for _, c, _ in world.launched] == FRESH[:3]
    assert next(e for e in log if e["event"] == "case_end" and e["case"] == "Q03")["outcome"] == outcome
    assert end["result"] == "incomplete" and not end["safety_stop"]


@pytest.mark.parametrize("field", ["case_note_files_written", "forbidden_calls"])
def test_an_h1_failure_stops_the_run_at_once(tmp_path, field):
    end, _log, world = _run(tmp_path, plan=PLAN["E-dev"], safety={"K06": {field: 1}})
    assert [c for _, c, _ in world.launched] == ["K05", "K06"] and end["safety_stop"] and end["result"] == "incomplete"


def test_a_change_to_frozen_material_stops_the_run_before_the_next_case(tmp_path):
    end, log, world = _run(tmp_path, moved_before="Q05")
    assert [c for _, c, _ in world.launched] == FRESH[:4] and end["result"] == "incomplete"
    assert next(e for e in log if e["event"] == "not_run")["reason"] == "frozen material changed: a file"


def test_the_case_in_flight_is_rerun_once_and_a_second_kill_makes_the_run_incomplete(tmp_path):
    started = {"event": "start", "attempt": 1, "run_cap": round(START + 0.15, 6), "ledger_committed": START}
    flight = {"event": "case_start", "case": "Q01", "ledger_before": START}
    end, log, world = _run(tmp_path, events=[started, flight])
    assert log[0]["event"] == "interrupted" and log[1]["rerun_after_interruption"] == "Q01"
    assert world.launched[0][1] == "Q01" and end["result"] == "complete"
    again = [started, flight, {"event": "interrupted", "attempt": 1, "case": "Q01", "ledger_now": START},
             {**started, "attempt": 2}, flight]
    second = tmp_path / "second"
    second.mkdir()
    end2, _log2, world2 = _run(second, events=again)
    assert world2.launched == [] and end2["result"] == "incomplete" and "two interruptions" in end2["stop_reason"]


def test_an_ended_run_is_never_resumed_or_repeated(tmp_path):
    ended = [{"event": "start", "attempt": 1, "run_cap": START + 0.15, "ledger_committed": START},
             {"event": "end", "result": "incomplete", "ledger_committed": START, "safety_stop": False}]
    end, log, world = _run(tmp_path, events=ended)
    assert world.launched == [] and log == [] and end["result"] == "incomplete"


def _end(result: str = "complete", ledger: float = START, safety: bool = False) -> dict[str, Any]:
    return {"event": "end", "result": result, "ledger_committed": ledger, "safety_stop": safety}


def test_each_run_starts_only_from_the_previous_runs_complete_recorded_end():
    freeze = {"ledger_start_usd": START, "runs": {n: {} for n in RUN.ORDER}}
    logs: dict[str, list[dict[str, Any]]] = {n: [] for n in RUN.ORDER}
    assert RUN.ledger_refusal(freeze, "R-dev", logs, START) is None
    assert "starting balance" in RUN.ledger_refusal(freeze, "R-dev", logs, START + 0.000001)
    assert "does not start" in RUN.ledger_refusal(freeze, "R-fresh", logs, START)
    logs["R-dev"] = [{"event": "start", "ledger_committed": START}, _end("incomplete", 7.45)]
    assert "does not start" in RUN.ledger_refusal(freeze, "R-fresh", logs, 7.45)
    assert "R-dev did not complete" in RUN.next_run_refusal("R-fresh", logs)
    assert "R-dev did not complete" in RUN.next_run_refusal("E-dev", logs)
    logs["R-dev"] = [{"event": "start", "ledger_committed": START}, _end("complete", 7.45, safety=True)]
    assert "safety stop" in RUN.next_run_refusal("R-fresh", logs)
    logs["R-dev"] = [{"event": "start", "ledger_committed": START}, _end("complete", 7.45)]
    assert RUN.ledger_refusal(freeze, "R-fresh", logs, 7.45) is None and RUN.next_run_refusal("R-fresh", logs) is None
    assert "starting balance" in RUN.ledger_refusal(freeze, "R-fresh", logs, 7.46)
    assert "R-fresh did not complete" in RUN.next_run_refusal("E-dev", logs)
    logs["R-fresh"] = [{"event": "start", "ledger_committed": 7.45}, _end("complete", 7.5)]
    assert RUN.ledger_refusal(freeze, "E-dev", logs, 7.5) is None and RUN.next_run_refusal("E-dev", logs) is None


def test_records_no_log_accounts_for_are_refused(tmp_path):
    out = tmp_path / "LC-route-v12-fresh"
    out.mkdir()
    (out / "summary.json").write_text("{}")  # live_diagnose's own summary is not a case record
    assert RUN.stray("LC-route-v12-fresh", [], live=tmp_path) == []
    (out / "Q01.json").write_text("{}")
    (out / "Q02.error.json").write_text("{}")
    assert RUN.stray("LC-route-v12-fresh", [], live=tmp_path) == ["Q01", "Q02"]
    log = [{"event": "case_start", "case": "Q01"}, {"event": "case_start", "case": "Q02"}]
    assert RUN.stray("LC-route-v12-fresh", log, live=tmp_path) == []


def test_a_second_invocation_cannot_take_the_lock(tmp_path):
    first = RUN.take_lock(tmp_path / "x.lock")
    assert first is not None and RUN.take_lock(tmp_path / "x.lock") is None
    first.close()
    assert RUN.take_lock(tmp_path / "x.lock") is not None


# ------------------------------------------------------------------------------------------------ routing cases
DEV_GOLD = {c["case_id"]: c["expected"] for c in json.loads((HERE / "DEV_GOLD.json").read_text())["cases"]}
K = {c["case_id"]: c for c in json.loads((REPO / LC).read_text())["cases"]}
SAVED = REPO / "artifacts" / "live" / "LC-i15-17-fresh"
NO_RUN = {"selection": "none", "selection_text": None, "half_hour_text": None, "target_half_hour_end_utc": None,
          "issued_at_utc": None}
NO_MAX = {"kind": "none", "measure": None, "measure_text": None, "window": None, "window_text": None,
          "window_start_utc": None, "window_end_utc": None}
K06_RUN = {"selection": "last_issued_before", "selection_text": "the final forecast run issued ahead of it",
           "half_hour_text": "7:30-8:00 am half-hour (Adelaide time, ACST) on 20 August 2026",
           "target_half_hour_end_utc": "2026-08-19T22:30:00Z", "issued_at_utc": None}
K09_MAX = {"kind": "maximum", "measure": "dispatch_total_demand", "measure_text": "NSW dispatch total demand highest",
           "window": "whole_local_day", "window_text": "across the whole day", "window_start_utc": None,
           "window_end_utc": None}


def _route_case(cid: str, requested: dict[str, Any] | None, *, raw: Any = None) -> dict[str, Any]:
    """A routing case through run_route.route_case with a SYNTHETIC transport returning the saved route of the
    targeted check (no `requested` field) or that route with a scripted `requested` field."""
    route = json.loads((SAVED / f"{cid}.json").read_text())["route"]
    if requested is not None:
        route = {**route, "requested": requested}
    fake = FakeModel(raw if raw is not None else route, [], lambda kw: {})
    return ROUTE.route_case({"case_id": cid, "question": K[cid]["question"], "request": K[cid].get("request") or {}},
                            client=fake, write_trace=False)


def test_a_routing_case_is_the_first_step_of_a_live_investigation_and_nothing_after_it():
    rec = _route_case("K06", {"forecast_run": K06_RUN, "maximum": NO_MAX})
    assert rec["route"]["requested"]["forecast_run"]["selection"] == "last_issued_before"
    assert rec["resolution"]["status"] == "ok" and rec["score"]["model_calls"] == 1
    assert rec["route_call"]["max_output_tokens"] == 2000 and not rec["route_invalid"]
    fr = rec["resolution"]["requests"]["forecast_run"]
    assert fr["status"] == "bound" and fr["half_hour_utc"] == ["2026-08-19T22:00:00Z", "2026-08-19T22:30:00Z"]
    assert SCORE.route_label(DEV_GOLD["K06"], rec)["label"] == "CORRECT"


def test_routing_labels_for_saved_routes_without_the_new_field():
    """The targeted check's saved routes (prompts v11, no `requested`): K06 and K09 are sent back (containment; a
    supply miss), K11 and Z-style parser bindings stay CORRECT, K13 binds nothing."""
    k06 = SCORE.route_label(DEV_GOLD["K06"], _route_case("K06", None))
    assert (k06["label"], k06["supply_miss"], k06["passes"]) == ("SENT_BACK", True, False)
    assert SCORE.route_label(DEV_GOLD["K11"], _route_case("K11", None))["label"] == "CORRECT"
    assert SCORE.route_label(DEV_GOLD["K13"], _route_case("K13", None))["label"] == "NO_REQUEST_OK"
    assert SCORE.route_label(DEV_GOLD["K08"], _route_case("K08", None))["label"] == "SENT_BACK"
    assert SCORE.route_label(DEV_GOLD["K09"], _route_case("K09", {"forecast_run": NO_RUN, "maximum": K09_MAX}))[
        "label"] == "CORRECT"


def test_a_wrong_binding_region_or_cutoff_is_wrong_and_an_unread_half_hour_is_sent_back():
    rec = _route_case("K06", {"forecast_run": K06_RUN, "maximum": NO_MAX})
    wrong = copy.deepcopy(rec)
    wrong["resolution"]["requests"]["forecast_run"]["half_hour_utc"] = ["2026-08-19T22:30:00Z", "2026-08-19T23:00:00Z"]
    assert SCORE.route_label(DEV_GOLD["K06"], wrong)["label"] == "WRONG"
    region = copy.deepcopy(rec)
    region["resolution"]["region"] = "VIC1"
    assert SCORE.route_label(DEV_GOLD["K06"], region)["label"] == "WRONG"
    cutoff = copy.deepcopy(rec)
    cutoff["resolution"]["as_of_utc"] = "2026-08-19T21:00:00Z"
    assert SCORE.route_label(DEV_GOLD["K06"], cutoff)["label"] == "WRONG"
    bound_where_none = copy.deepcopy(rec)
    assert SCORE.route_label(DEV_GOLD["K13"] | {"region": "SA1"}, bound_where_none)["label"] == "WRONG"
    k14 = _route_case("K14", None)  # the parser reads the issue time; the half-hour is not read without v12
    lab = SCORE.route_label(DEV_GOLD["K14"], k14)
    # it was PARTIAL (the run bound without its half-hour); since D27 Amendment 2 a named run whose half-hour is not
    # read is sent back before any tool: a supply miss of the reading, never a wrong binding or a containment miss
    assert (lab["label"], lab["supply_miss"], lab["containment_miss"], lab["wrong"]) == ("SENT_BACK", True, False, [])


def test_a_cut_off_routing_output_is_route_invalid_and_sent_back():
    rec = _route_case("K05", None, raw="{")  # unparseable output
    assert rec["route_invalid"] and rec["resolution"]["status"] == "needs_clarification"
    lab = SCORE.route_label(DEV_GOLD["K05"], rec)
    assert lab["route_invalid"] and lab["label"] == "SENT_BACK" and lab["supply_miss"]


# ------------------------------------------------------------------------------------------------ run identity
class _Runs:
    """A SYNTHETIC store: TAS1 forecast runs (run ID, issue time, half-hours forecast), answering the three run
    lookups the scorer makes (as `Store.query` does)."""

    def __init__(self, runs: list[tuple[str, str, list[str]]]) -> None:
        from datetime import datetime

        def t(x: str) -> Any:
            return datetime.fromisoformat(x.replace("Z", "+00:00"))
        self.runs = [(r, t(i), [t(x) for x in ends]) for r, i, ends in runs]

    def __call__(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        if "SELECT 1" in sql:
            _region, run, end = params
            return [{"1": 1}] if any(r == run and end in ends for r, _i, ends in self.runs) else []
        if "BETWEEN" in sql:
            _region, lo, hi = params
            return [{"run_id": r, "issued_at_utc": i} for r, i, _e in self.runs if lo <= i <= hi]
        _region, end, start = params
        rows = sorted(((r, i) for r, i, ends in self.runs if end in ends and i < start), key=lambda x: x[1], reverse=True)
        return [{"run_id": r, "issued_at_utc": i} for r, i in rows[:2]]


GOLD_ISSUED = {"outcome": "bound", "region": "TAS1", "as_of_utc": None,
               "forecast_run": {"selection": "issued_at", "target_half_hour_end_utc": "2026-07-30T05:00:00Z",
                                "issued_at_utc": "2026-07-30T03:57:03Z"}}
TWO_RUNS = _Runs([("GOLD_RUN", "2026-07-30T03:57:03Z", ["2026-07-30T05:00:00Z"]),
                  ("OTHER_RUN", "2026-07-30T03:57:33Z", ["2026-07-30T05:00:00Z"])])  # 30 s apart (SYNTHETIC)


def _bound_record(issued_at: str, end: str = "2026-07-30T05:00:00Z") -> dict[str, Any]:
    start = (SCORE._dt(end) - __import__("datetime").timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"route_invalid": False, "resolution": {
        "status": "ok", "intent": "forecast_review", "region": "TAS1", "as_of_utc": None,
        "requests": {"forecast_run": {"status": "bound", "selection": "issued_at", "half_hour_utc": [start, end],
                                      "issued_at_utc": issued_at}, "maximum": {"status": "absent"}}}}


def test_a_different_run_within_the_60_seconds_is_wrong():
    """SYNTHETIC: two runs issued 30 s apart. A binding whose issue time (03:57:33) is within 60 s of the gold's
    (03:57:03) but identifies the other run fails: the run itself must be the gold run."""
    lab = SCORE.route_label(GOLD_ISSUED, _bound_record("2026-07-30T03:57:33Z"), query=TWO_RUNS)
    assert lab["label"] == "WRONG" and lab["wrong"] == ["run OTHER_RUN (gold GOLD_RUN)"]


def test_the_60_seconds_only_absorbs_a_time_stated_to_the_minute():
    """The question states 03:57; the stored stamp is 03:57:03. The time is within 60 s and identifies the gold run."""
    assert SCORE.route_label(GOLD_ISSUED, _bound_record("2026-07-30T03:57:00Z"), query=TWO_RUNS)["label"] == "CORRECT"
    tie = _Runs([("GOLD_RUN", "2026-07-30T03:57:03Z", ["2026-07-30T05:00:00Z"]),
                 ("OTHER_RUN", "2026-07-30T03:57:33Z", ["2026-07-30T05:00:00Z"])])
    # a time equally near two runs identifies none: not credited
    assert SCORE.route_label(GOLD_ISSUED, _bound_record("2026-07-30T03:57:18Z"), query=tie)["label"] == "WRONG"
    # a run that does not forecast the bound half-hour identifies none: not credited
    assert SCORE.route_label(GOLD_ISSUED, _bound_record("2026-07-30T03:57:00Z", end="2026-07-30T05:30:00Z"),
                             query=TWO_RUNS)["label"] == "WRONG"


def test_the_last_run_issued_before_is_the_gold_runs_identity():
    gold = {"outcome": "bound", "region": "TAS1", "as_of_utc": None,
            "forecast_run": {"selection": "last_issued_before", "target_half_hour_end_utc": "2026-07-30T05:00:00Z",
                             "issued_at_utc": None}}
    runs = _Runs([("EARLIER", "2026-07-30T03:57:03Z", ["2026-07-30T05:00:00Z"]),
                  ("GOLD_RUN", "2026-07-30T04:27:01Z", ["2026-07-30T05:00:00Z"]),
                  ("AFTER_START", "2026-07-30T04:31:00Z", ["2026-07-30T05:00:00Z"])])
    rec = _bound_record("x")
    rec["resolution"]["requests"]["forecast_run"] |= {"selection": "last_issued_before", "issued_at_utc": None}
    assert SCORE.route_label(gold, rec, query=runs)["label"] == "CORRECT"
    assert SCORE.run_identity("TAS1", "last_issued_before", "2026-07-30T05:00:00Z", None, runs) == "GOLD_RUN"


def test_every_gold_run_is_one_stored_run_corroborated_by_independent_records():
    """Each forecast-run gold identifies exactly one stored run, and it is the run the writer recorded (fresh cases)
    or the targeted check's frozen gold names (development cases)."""
    lc = {c["case_id"]: c for c in json.loads((REPO / "eval" / "livecheck_i15_17" / "GOLD.json").read_text())["cases"]}
    dev = json.loads((REPO / "eval" / "livecheck_i15_17" / "DEVCHECK.json").read_text())["cases"]
    checked = 0
    for c in json.loads((HERE / "cases.json").read_text())["cases"] + json.loads((HERE / "DEV_GOLD.json").read_text())[
            "cases"]:
        e = c["expected"]
        fr = e.get("forecast_run")
        if not fr:
            continue
        rid = SCORE.run_identity(e["region"], fr["selection"], fr["target_half_hour_end_utc"], fr.get("issued_at_utc"))
        assert rid is not None, c["case_id"]
        if "data_check" in e:
            assert rid in e["data_check"], c["case_id"]
        elif lc.get(c["case_id"], {}).get("gold_run"):
            assert lc[c["case_id"]]["gold_run"]["run_id"] == rid, c["case_id"]
        else:
            assert rid in json.dumps(next(d for d in dev if d["case_id"] == c["case_id"])), c["case_id"]
        checked += 1
    assert checked == 13  # Q01-Q08, Z05, K05, K06, K07, K14


# ------------------------------------------------------------------------------------------------ cut-off routing
class _CutOff:
    """A SYNTHETIC transport whose routing response stops at max_output_tokens: its text is a complete, valid routing
    decision (with correct `requested` fields), but the response is incomplete."""

    def __init__(self, route: dict[str, Any]) -> None:
        self.route = route
        self.calls = 0

    def create(self, **kw: Any) -> dict[str, Any]:
        self.calls += 1
        return {"id": "resp_cut", "status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
                "output": [{"type": "message", "role": "assistant",
                            "content": [{"type": "output_text", "text": json.dumps(self.route)}]}],
                "usage": {"input_tokens": 2000, "output_tokens": 2000}}


@pytest.mark.parametrize("cid,requested", [("K06", {"forecast_run": K06_RUN, "maximum": NO_MAX}),
                                           ("K09", {"forecast_run": NO_RUN, "maximum": K09_MAX})])
def test_cut_off_or_invalid_routing_output_binds_nothing(cid, requested):
    """A routing response cut off at its cap, even one whose text would parse with correct fields, is no decision:
    the model's reading is discarded, the question is sent back, and no tool runs, no run is looked up and no
    maximum is computed. The record is ROUTE_INVALID, labelled SENT_BACK (a supply miss)."""
    route = {**json.loads((SAVED / f"{cid}.json").read_text())["route"], "requested": requested}
    rec = ROUTE.route_case({"case_id": cid, "question": K[cid]["question"], "request": K[cid].get("request") or {}},
                           client=_CutOff(route), write_trace=False)
    assert rec["route"] is None and rec["route_invalid"] and rec["route_invalid_events"] == ["route:incomplete"]
    assert rec["resolution"]["status"] == "needs_clarification"
    rq = rec["resolution"]["requests"]  # None when the question is not resolved as a data question at all
    if rq is not None:
        assert rq["routed"] == "not reported" and "route_model" not in rq["forecast_run"]["detected_by"] + \
            rq["maximum"]["detected_by"]
        assert rq["forecast_run"]["status"] != "bound" and rq["maximum"]["status"] != "bound"
    lab = SCORE.route_label(DEV_GOLD[cid], rec)
    assert lab["label"] == "SENT_BACK" and lab["route_invalid"] and lab["supply_miss"]
    from nem_agent.service import investigate

    res = investigate(InvestigateRequest(question=K[cid]["question"], mode="live"), live_client=_CutOff(route),
                      write_trace=False)
    assert res.report.status == "needs_clarification" and not res.records
    assert res.resolution.forecast_run is None and res.resolution.demand_max is None


def test_a_cut_off_route_on_a_parser_read_question_is_sent_back_before_any_lookup():
    """Z05's wording is read by the question parser. With the routing output cut off, the question is still sent back
    (invalid routing output) before any tool or run lookup: nothing is bound in practice."""
    v6 = {c["case_id"]: c for c in json.loads((REPO / "eval" / "holdout_v6" / "cases.json").read_text())["cases"]}
    route = json.loads((REPO / "artifacts" / "live" / "LC-i15-17-dev" / "Z05.json").read_text())["route"]
    from nem_agent.service import investigate

    res = investigate(InvestigateRequest(question=v6["Z05"]["question"], mode="live"), live_client=_CutOff(route),
                      write_trace=False)
    assert res.report.status == "needs_clarification" and not res.records and res.resolution.forecast_run is None
    assert res.resolution.reasons == ["The routing model returned invalid output."]  # shown as "could not be interpreted"


# ------------------------------------------------------------------------------------------------ the decision
def _labels(run: str, ids: list[str], label: str, gold: str) -> dict[str, Any]:
    return {"complete": True, "incomplete": [], "cases": {c: {"label": label, "passes": label == SCORE.PASSES[gold],
                                                              "route_invalid": False, "wrong": [], "gold_outcome": gold,
                                                              "supply_miss": False, "containment_miss": False, "H1": 0}
                                                          for c in ids}}


def _passing() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    gold_dev = {c: DEV_GOLD[c]["outcome"] for c in DEV}
    dev = {"complete": True, "incomplete": [], "cases": {}}
    for c in DEV:
        dev["cases"] |= _labels("R-dev", [c], SCORE.PASSES[gold_dev[c]], gold_dev[c])["cases"]
    fresh = {"complete": True, "incomplete": [], "cases": {}}
    for ids, gold in ((list(SCORE.FRESH_RUN) + list(SCORE.FRESH_MAX), "bound"), (list(SCORE.FRESH_CLARIFY), "clarify"),
                      (["Q21", "Q22", "Q24"], "no_request"), (["Q23"], "as_of_availability")):
        fresh["cases"] |= _labels("R-fresh", ids, SCORE.PASSES[gold], gold)["cases"]
    e2e = {"complete": True, "incomplete": [], "cases": {c: {"H1": 0, "H2_auto": 0, "H3": 0, "H4_auto": 0, "H5": 0,
                                                             "blocked": []} for c in E2E}}
    return dev, fresh, e2e


def _decide(dev, fresh, e2e, outcomes=None, route_readings=None) -> dict[str, Any]:
    outcomes = outcomes or {"K05": "S", "K06": "S", "K07": "U", "K09": "S", "K10": "S"}
    readings = {c: {"outcome": o, "H2_manual": 0, "H4_manual": 0} for c, o in outcomes.items()}
    freeze = {"runs": {"E-dev": {"cases": [[c, LC] for c in E2E]}}}
    return SCORE.decide(freeze, {"R-dev": dev, "R-fresh": fresh}, e2e, readings, route_readings or {})


def test_pass_needs_every_criterion():
    assert _decide(*_passing())["verdict"] == "PASS"


def test_a_wrong_binding_anywhere_fails():
    dev, fresh, e2e = _passing()
    fresh["cases"]["Q22"] |= {"label": "WRONG", "passes": False, "wrong": ["a maximum is bound; the gold has none"]}
    d = _decide(dev, fresh, e2e)
    assert d["verdict"] == "FAIL" and any("Q22" in f for f in d["failures"])


def test_more_than_one_route_invalid_fails():
    dev, fresh, e2e = _passing()
    dev["cases"]["K02"]["route_invalid"] = True
    assert _decide(dev, fresh, e2e)["verdict"] == "PASS"  # one is allowed (K02 was cut off under v11)
    fresh["cases"]["Q01"]["route_invalid"] = True
    assert _decide(dev, fresh, e2e)["verdict"] == "FAIL"


@pytest.mark.parametrize("gate", ["H1", "H2_auto", "H3", "H4_auto", "H5"])
def test_any_safety_violation_in_an_end_to_end_case_fails(gate):
    dev, fresh, e2e = _passing()
    e2e["cases"]["K06"][gate] = 1
    assert _decide(dev, fresh, e2e)["verdict"] == "FAIL"


def test_an_incorrect_answer_shown_fails_and_containment_is_not_supply():
    assert _decide(*_passing(), outcomes={"K05": "S", "K06": "X", "K07": "U", "K09": "S", "K10": "S"})[
        "verdict"] == "FAIL"
    for missed in ("C", "U", "F"):
        d = _decide(*_passing(), outcomes={"K05": "S", "K06": missed, "K07": "U", "K09": "S", "K10": "S"})
        assert d["verdict"] == "FAIL" and d["criteria"]["e2e_supplied"][0] == 3


def test_incomplete_coverage_is_never_a_pass_but_a_failure_already_seen_is_a_fail():
    dev, fresh, e2e = _passing()
    fresh["incomplete"] = ["Q24"]
    del fresh["cases"]["Q24"]
    assert _decide(dev, fresh, e2e)["verdict"] == "INCOMPLETE"
    fresh["cases"]["Q01"] |= {"label": "WRONG", "passes": False}
    assert _decide(dev, fresh, e2e)["verdict"] == "FAIL"
    dev2, fresh2, e2e2 = _passing()
    del e2e2["cases"]["K10"]
    assert _decide(dev2, fresh2, e2e2)["verdict"] == "INCOMPLETE"


def test_the_fresh_bars_are_six_of_eight_in_each_area():
    dev, fresh, e2e = _passing()
    for c in ("Q01", "Q02"):
        fresh["cases"][c] |= {"label": "SENT_BACK", "passes": False, "supply_miss": True}
    assert _decide(dev, fresh, e2e)["verdict"] == "PASS"
    fresh["cases"]["Q03"] |= {"label": "PARTIAL", "passes": False, "supply_miss": True}
    assert _decide(dev, fresh, e2e)["verdict"] == "FAIL"
    dev, fresh, e2e = _passing()
    for c in ("Q09", "Q10", "Q11"):
        fresh["cases"][c] |= {"label": "UNBOUND", "passes": False, "supply_miss": True}
    assert _decide(dev, fresh, e2e)["verdict"] == "FAIL"


def test_containment_controls_and_over_clarification():
    dev, fresh, e2e = _passing()
    fresh["cases"]["Q18"] |= {"label": "UNBOUND", "passes": False, "containment_miss": True}
    assert _decide(dev, fresh, e2e)["verdict"] == "FAIL"
    dev, fresh, e2e = _passing()
    fresh["cases"]["Q21"] |= {"label": "SENT_BACK", "passes": False, "supply_miss": True}
    assert _decide(dev, fresh, e2e)["verdict"] == "PASS"  # one over-clarified control is allowed
    fresh["cases"]["Q24"] |= {"label": "SENT_BACK", "passes": False, "supply_miss": True}
    assert _decide(dev, fresh, e2e)["verdict"] == "FAIL"


def test_the_development_bars():
    for case, label in (("K06", "SENT_BACK"), ("Z05", "UNBOUND"), ("K12", "UNBOUND")):
        dev, fresh, e2e = _passing()
        dev["cases"][case] |= {"label": label, "passes": False}
        assert _decide(dev, fresh, e2e)["verdict"] == "FAIL", case
    dev, fresh, e2e = _passing()
    dev["cases"]["K14"] |= {"label": "PARTIAL", "passes": False}
    assert _decide(dev, fresh, e2e)["verdict"] == "PASS"  # K14 is reported, not gated


def test_the_stricter_of_two_readings_and_disagreements_are_reported():
    dev, fresh, e2e = _passing()
    d = _decide(dev, fresh, e2e, route_readings={"R-fresh:Q05": [{"label": "WRONG"}, {"label": None}]})
    assert d["verdict"] == "FAIL" and "R-fresh:Q05" in d["disagreements"]


# ------------------------------------------------------------------------------------------------ the freeze
def test_the_criteria_constants_are_the_pass_rules():
    assert SCORE.DEV_TARGET == ("K05", "K06", "K07", "K09", "K10")
    assert SCORE.DEV_REGRESSION == ("Z04", "Z05", "K11") and SCORE.DEV_CLARIFY == ("K08", "K12")
    assert len(SCORE.FRESH_RUN) == len(SCORE.FRESH_MAX) == 8 and len(SCORE.FRESH_CLARIFY) == 4
    assert [c["case_id"] for c in json.loads((HERE / "DEV_GOLD.json").read_text())["cases"]] == DEV


@pytest.mark.skipif(not FREEZE, reason="FREEZE.json not written yet")
def test_the_freeze_matches_the_protocol():
    assert FREEZE["code_commit"] == "f2455ca33ca1f60293a4ccb849ebc2f00da61f51"
    assert (FREEZE["src_tree"], FREEZE["prompts_tree"]) == ("b367b911845988770995c9b6334e4432b1e21980",
                                                            "7a1fe6a53e2f5d39e3cce3aeacade4bc6c5e455a")
    assert (FREEZE["model"], FREEZE["prompt_version"], FREEZE["ledger_start_usd"]) == ("gpt-5-mini", "prompts/v12", START)
    assert FREEZE["order"] == list(RUN.ORDER)
    for name, plan in PLAN.items():
        f = FREEZE["runs"][name]
        assert {k: f[k] for k in ("label", "kind", "run_cap_usd", "case_cap_usd")} == \
            {k: plan[k] for k in ("label", "kind", "run_cap_usd", "case_cap_usd")}
        assert [c for c, _ in f["cases"]] == [c for c, _ in plan["cases"]] and f["n_cases"] == len(plan["cases"])
    assert FREEZE["required_task_cap_usd"] == pytest.approx(8.174670)
    assert RUN.required_task_cap(FREEZE, list(RUN.ORDER)) == pytest.approx(8.174670)
    for rel, sha in FREEZE["files_sha256"].items():
        assert hashlib.sha256((REPO / rel).read_bytes()).hexdigest() == sha, rel


@pytest.mark.skipif(not FREEZE, reason="FREEZE.json not written yet")
def test_the_runner_refuses_without_an_approved_cap_with_overrides_or_without_a_key(monkeypatch, tmp_path):
    monkeypatch.setattr(RUN, "changed", lambda freeze: None)  # the frozen-material check is tested below
    monkeypatch.setattr(RUN, "read_log", lambda label, live=None: [])
    monkeypatch.setattr(RUN, "LIVE", tmp_path)
    # the stray-record check is tested above; here it would read the committed run records against the emptied logs
    monkeypatch.setattr(RUN, "stray", lambda label, events, live=None: [])
    monkeypatch.setenv("OPENAI_API_KEY", "placeholder-not-a-key")  # presence only; never read or sent
    monkeypatch.setattr(RUN, "OVERRIDES", RUN.OVERRIDES[1:])  # the tests' scratch ledger stays set throughout
    for k in RUN.OVERRIDES:
        monkeypatch.delenv(k, raising=False)
    runs = list(RUN.ORDER)
    # the frozen prompts (v12): the current code is on v13 (D26), which the frozen runner refuses, as checked below
    monkeypatch.setattr(RUN.config, "PROMPT_VERSION", FREEZE["prompt_version"])
    assert RUN.refusal(FREEZE, runs, 8.174670, START) is None
    assert "approved task cap" in RUN.refusal(FREEZE, runs, None, START)
    assert "approved task cap" in RUN.refusal(FREEZE, runs, 8.17, START)
    assert "approved task cap" in RUN.refusal(FREEZE, runs, 5.0, START)  # the standing cap
    assert "starting balance" in RUN.refusal(FREEZE, runs, 8.174670, START + 0.01)
    for k in ("NEM_AGENT_TOTAL_BUDGET_USD", "NEM_AGENT_PRICE_OUTPUT_PER_MTOK", "NEM_AGENT_MODEL"):
        monkeypatch.setenv(k, "1")
        assert "override" in RUN.refusal(FREEZE, runs, 8.174670, START)
        monkeypatch.delenv(k)
    monkeypatch.setattr(RUN.config, "PROMPT_VERSION", "prompts/v11")
    assert RUN.refusal(FREEZE, runs, 8.174670, START) == "the prompt version differs"
    monkeypatch.setattr(RUN.config, "PROMPT_VERSION", FREEZE["prompt_version"])
    monkeypatch.delenv("OPENAI_API_KEY")
    assert RUN.refusal(FREEZE, runs, 8.174670, START) == "no API key is set"


@pytest.mark.skipif(not FREEZE, reason="FREEZE.json not written yet")
def test_the_runner_refuses_a_changed_frozen_file_or_src_tree(monkeypatch):
    assert RUN.changed({**FREEZE, "src_tree": "0" * 40}) == "the checkout's src/ is not the frozen tree"
    bad = {**FREEZE, "files_sha256": {**FREEZE["files_sha256"],
                                      "eval/livecheck_routing_v12/PASS_RULE.md": "0" * 64}}
    assert RUN.changed(bad) == "eval/livecheck_routing_v12/PASS_RULE.md differs from FREEZE.json"
    # I-19 changed src/ after the run: the frozen runner refuses this checkout; with the frozen src tree in place, every
    # frozen file is unchanged
    assert RUN.changed(FREEZE) == "the checkout's src/ is not the frozen tree"
    git = RUN._git
    monkeypatch.setattr(RUN, "_git", lambda *a: FREEZE["src_tree"] if a == ("rev-parse", "HEAD:src")
                        else "" if a[:1] == ("status",) else git(*a))
    assert RUN.changed(FREEZE) is None
