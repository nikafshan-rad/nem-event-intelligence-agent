"""The routing-only Live check of route contract v13 (eval/livecheck_route_v13/PROTOCOL.md), offline. Covered:
- its configurations and gold;
- its plan and caps;
- its per-call routing runner, through the SYNTHETIC fake transport;
- its scorer and verdict;
- its runner loop: the start guard, stops, interruption and refusals.

Nothing here calls a model:
- the routing decisions given to the fake transport are SYNTHETIC, written as a careful reader would answer;
- the runner's processes, ledger and records are injected.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import random
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "eval" / "livecheck_route_v13"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"lcr13_{name}", DIR / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GOLD = _load("gold")
ROUTE = _load("run_route")
RUN = _load("run_eval")
SCORE = _load("score")
FRZ = _load("freeze")
CASES = {c["config"]: c for c in json.loads((DIR / "cases.json").read_text())["cases"]}
GOLDS = {g["config"]: g for g in json.loads((DIR / "GOLD.json").read_text())["cases"]}
FREEZE = json.loads((DIR / "FREEZE.json").read_text()) if (DIR / "FREEZE.json").exists() else None
NO_RUN = {"selection": "none", "selection_text": None, "half_hour_text": None}
NO_MAX = {"kind": "none", "measure": None, "measure_text": None, "peak_text": None, "window": None, "window_text": None}


def _dec(intent: str, region: str, event_date: str | None, mx: dict | None = None, run: dict | None = None,
         as_of_text: str | None = None, **core: Any) -> dict[str, Any]:
    """A SYNTHETIC v13 routing decision."""
    return {"intent": intent, "region": region, "event_date": event_date, "as_of_text": as_of_text,
            "needs_clarification": False, "clarification_reason": None, "clarification": None, "out_of_scope": False,
            **core, "requested": {"forecast_run": {**NO_RUN, **(run or {})}, "maximum": {**NO_MAX, **(mx or {})}}}


F07_MX = dict(kind="maximum", measure="operational_demand", measure_text="operational demand", peak_text="highest",
              window="whole_local_day", window_text="that entire local day")
F07_CUT = "published by noon Brisbane time on Sunday 5 October 2025"
CAREFUL = {  # SYNTHETIC: how a careful reader following prompts v13 would answer each configuration
    "C01": _dec("market_event_review", "QLD1", "2026-07-29", dict(
        kind="maximum", measure="operational_demand", measure_text="operational demand", peak_text="highest",
        window="whole_local_day", window_text="29 July 2026 (Brisbane time)")),
    "C02": _dec("market_event_review", "SA1", "2026-07-29", dict(
        kind="maximum", measure="dispatch_total_demand", measure_text="dispatch total demand", peak_text="top",
        window="whole_local_day", window_text="the full local day of 29 July 2026 (midnight to midnight, Adelaide time)")),
    "C03": _dec("market_event_review", "NSW1", "2026-07-29", dict(
        kind="maximum", measure="dispatch_total_demand", measure_text="NSW dispatch total demand", peak_text="highest",
        window="whole_local_day", window_text="across the whole day")),
    "C04": _dec("market_event_review", "VIC1", "2026-08-20", dict(
        kind="maximum", measure="dispatch_total_demand", measure_text="VIC1 dispatch total demand (TOTALDEMAND)",
        peak_text="how high", window="event", window_text="that event's full window")),
    "C05": _dec("market_event_review", "QLD1", "2025-10-05", F07_MX, as_of_text=F07_CUT),
    "C06": _dec("market_event_review", "QLD1", "2025-10-05", F07_MX, as_of_text=F07_CUT),
    "C07": _dec("market_event_review", "TAS1", "2026-07-31", dict(
        kind="maximum", measure="unspecified", measure_text="demand", peak_text="top out", window="event",
        window_text="Tasmania's 31 July 2026 high-price episode")),
    "C08": _dec("forecast_review", "QLD1", None, run=dict(
        selection="last_issued_before", selection_text="the run AEMO issued most recently before that half-hour kicked off",
        half_hour_text="the 13:00–13:30 Brisbane-time half-hour"), needs_clarification=True,
        clarification_reason="missing_region_or_date", clarification="Which date is the half-hour on?"),
    "C09": _dec("market_event_review", "SA1", "2026-07-29"),
    "C10": _dec("forecast_review", "SA1", "2026-08-20", run=dict(
        selection="last_issued_before", selection_text="the final forecast run issued ahead of it",
        half_hour_text="7:30-8:00 am half-hour (Adelaide time, ACST) on 20 August 2026")),
    "C11": _dec("forecast_review", "TAS1", "2026-07-31", run=dict(
        selection="issued_at", selection_text="the forecast run issued at 2026-07-30T18:56:59Z",
        half_hour_text="half-hour ending at 8:00 am AEST, 31 July 2026")),
}
EXPECTED = {**{c: "supplied" for c in ("C01", "C02", "C03", "C04", "C05", "C10", "C11")},
            **{c: "contained" for c in ("C06", "C07", "C08", "C09")}}


def _fake(decision: dict[str, Any]):
    from tests.provider.fake_model import FakeModel

    return FakeModel(decision, [], lambda kw: {})


def _record(config: str, decision: dict[str, Any] | None = None, client: Any = None) -> dict[str, Any]:
    rec = ROUTE.route_call(CASES[config], client=client or _fake(decision or CAREFUL[config]), write_trace=False)
    rec["score"]["ledger_cost_usd"] = 0.0016
    return rec


# ------------------------------------------------------------------------------------------------ cases and gold
def test_scope_is_10_questions_11_configurations_and_32_calls():
    data = json.loads((DIR / "cases.json").read_text())
    assert (data["questions"], data["configurations"], data["calls"]) == (10, 11, 32)
    assert {c: CASES[c]["repeats"] for c in CASES} == {"C01": 5, "C02": 5, "C03": 3, "C04": 3, "C05": 3, "C06": 3,
                                                      "C07": 2, "C08": 2, "C09": 2, "C10": 2, "C11": 2}
    assert CASES["C05"]["question"] == CASES["C06"]["question"] and CASES["C05"]["request"] == {
        "as_of_utc": "2025-10-05T02:00:00Z"} and CASES["C06"]["request"] == {}


def test_questions_are_copied_unchanged_and_the_gold_is_reproducible_from_its_sources():
    for c in CASES.values():
        src = next(x for x in json.loads((ROOT / c["source"]["file"]).read_text())["cases"]
                   if x["case_id"] == c["source"]["case_id"])
        assert src["question"] == c["question"]
    cases, gold = GOLD.build()
    assert cases == json.loads((DIR / "cases.json").read_text()) and gold == json.loads((DIR / "GOLD.json").read_text())
    for rel, want in gold["sources_sha256"].items():
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == want, rel


# ------------------------------------------------------------------------------------------------ plan and caps
def test_the_plan_runs_32_calls_in_five_rounds():
    slots = FRZ.plan(random.Random(7))
    assert len(slots) == 32 and [s["slot"] for s in slots] == list(range(1, 33))
    assert {c: sum(s["config"] == c for s in slots) for c in CASES} == {c: CASES[c]["repeats"] for c in CASES}
    assert [sum(s["round"] == r for s in slots) for r in (1, 2, 3, 4, 5)] == [11, 11, 6, 2, 2]
    assert all(s["case"] == s["record"] == f"{s['slot']:02d}-{s['config']}" for s in slots)


def test_the_call_cap_holds_the_exact_reservation_and_the_caps_add_up():
    res = FRZ.reservations()
    assert max(res.values()) <= FRZ.CALL_CAP and set(res) == set(CASES)
    assert round(32 * FRZ.CALL_CAP, 6) == 0.192 and round(8.895359 + 0.192, 6) == 9.087359


# ------------------------------------------------------------------------------------------------ the per-call runner
@pytest.mark.parametrize("config", sorted(CAREFUL))
def test_each_configuration_routes_and_is_classed_as_expected_through_the_fake_transport(config):
    """SYNTHETIC careful readings, through the real per-call runner and the scorer: one routing call, no tool."""
    rec = _record(config)
    assert rec["score"]["model_calls"] == 1 and rec["route_contract"] == "v13"
    assert rec["routing_events"] and rec["resolution"]["requests"] is not None
    c = SCORE.classify(rec, GOLDS[config])
    assert (c["class"], c["violations"]) == (EXPECTED[config], []), c


def test_c05_resolves_with_the_request_cutoff_and_c06_is_sent_back_for_it():
    c05, c06 = _record("C05"), _record("C06")
    co5 = c05["resolution"]["requests"]["cutoff"]
    assert co5["provenance"]["as_of"]["source"] == "request" and c05["resolution"]["as_of_utc"] == "2025-10-05T02:00:00Z"
    assert c06["resolution"]["status"] == "needs_clarification" and c06["resolution"]["requests"]["cutoff"]["status"] == \
        "unresolved"
    # spans are recorded with their offsets
    spans = c05["resolution"]["requests"]["maximum"]["spans"]
    assert any(s["role"] == "window" and s["located"] and s["occurrences"] for s in spans)


def test_an_incomplete_routing_response_is_recorded_with_its_diagnostics_and_fails_closed():
    """SYNTHETIC: valid JSON, then whitespace to the 2,000-token cap (the D02 shape)."""
    from tests.provider.fake_model import FakeModel

    class Truncated(FakeModel):
        def create(self, **kw: Any) -> dict[str, Any]:
            self.requests.append(kw)
            return {"id": "resp_x", "status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
                    "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text",
                                "text": '{"intent":"market_event_review","region":"QLD1"' + " \r" * 500}]}],
                    "usage": {"input_tokens": 1513, "output_tokens": 2000,
                              "output_tokens_details": {"reasoning_tokens": 832}}}

    rec = _record("C01", client=Truncated({}, [], lambda kw: {}))
    assert rec["route_invalid"] and rec["route_call"]["status"] == "incomplete"
    assert rec["route_call"]["reasoning_tokens"] == 832 and rec["incomplete_diagnostics"]["cause"]
    assert rec["resolution"]["status"] == "needs_clarification"
    c = SCORE.classify(rec, GOLDS["C01"])
    assert c["class"] == "incomplete" and c["violations"] == []


def test_a_misread_maximum_is_contained_by_the_resolver_and_a_bound_one_is_caught_by_the_scorer():
    """SYNTHETIC. (a) A reading that claims a maximum for C09 (demand at the price peak) is refused by the resolver
    ("peaked" is a price's extreme there): the call is sent back, an unnecessary clarification, not a violation.
    (b) A record in which a maximum is bound for C09 is a violation for the scorer, whatever produced it."""
    dec = copy.deepcopy(CAREFUL["C09"])
    dec["requested"]["maximum"] = dict(kind="maximum", measure="dispatch_total_demand",
                                       measure_text="dispatch total demand", peak_text="peaked", window="event",
                                       window_text="the SA1 high-price event of 29 July 2026")
    rec = _record("C09", dec)
    assert SCORE.classify(rec, GOLDS["C09"]) == {"class": "unnecessary clarification", "violations": [],
                                                 "detail": SCORE.classify(rec, GOLDS["C09"])["detail"]}
    bound = copy.deepcopy(_record("C09"))
    bound["resolution"]["requests"]["maximum"] = {"status": "bound", "measures": ["total demand"],
                                                  "window_kind": "event", "window_utc": ["a", "b"]}
    c = SCORE.classify(bound, GOLDS["C09"])
    assert any("C09 bound a maximum" in v for v in c["violations"])
    wrong = copy.deepcopy(_record("C03"))
    wrong["resolution"]["requests"]["maximum"]["window_kind"] = "event"
    assert SCORE.classify(wrong, GOLDS["C03"])["class"] == "wrong binding"


# ------------------------------------------------------------------------------------------------ the verdict
@pytest.fixture(scope="module")
def careful_records() -> dict[str, dict[str, Any]]:
    return {c: _record(c) for c in CAREFUL}


def _plan_records(careful: dict[str, dict[str, Any]], override: dict[int, Any] | None = None):
    freeze = {"slots": FRZ.plan(random.Random(3)), "label": "x"}
    recs = {s["slot"]: careful[s["config"]] for s in freeze["slots"]}
    recs.update(override or {})
    return freeze, recs


def test_the_verdict_passes_only_with_containment_evidence_and_supply(careful_records):
    freeze, recs = _plan_records(careful_records)
    d = SCORE.decide(freeze, recs)
    assert d["verdict"] == "PASS" and d["verdict_of"] == SCORE.VERDICT_NAME
    assert "truncation" in d["verdict_note"] and "fixed" in d["verdict_note"]
    assert d["truncation_section"]["C01"] == {"calls": 5, "completed": 5, "incomplete": 0, "classes": {"supplied": 5},
                                              "diagnostics": []}


def test_containment_shown_only_by_incomplete_responses_cannot_pass(careful_records):
    """An incomplete response is fail-closed, not an interpretation: C07 with only incomplete calls is INCONCLUSIVE."""
    incomplete = copy.deepcopy(careful_records["C07"])
    incomplete.update(route_invalid=True, route_call={**incomplete["route_call"], "status": "incomplete"})
    incomplete["resolution"] = {**incomplete["resolution"], "status": "needs_clarification"}
    freeze, recs = _plan_records(careful_records)
    recs.update({s["slot"]: incomplete for s in freeze["slots"] if s["config"] == "C07"})
    d = SCORE.decide(freeze, recs)
    assert d["verdict"] == "INCONCLUSIVE" and d["containment_undemonstrated"] == ["C07"]


def test_verdict_precedence(careful_records):
    freeze, recs = _plan_records(careful_records)
    wrong = copy.deepcopy(careful_records["C03"])
    wrong["resolution"]["requests"]["maximum"]["window_utc"] = ["2026-07-28T14:00:00Z", "2026-07-29T13:00:00Z"]
    one = next(s["slot"] for s in freeze["slots"] if s["config"] == "C03")
    missing = next(s["slot"] for s in freeze["slots"] if s["config"] == "C01")
    # a demonstrated violation fails, even with a call missing
    d = SCORE.decide(freeze, {**recs, one: wrong, missing: None})
    assert d["verdict"] == "FAIL" and d["coverage"]["missing_slots"] == [missing]
    assert SCORE.decide(freeze, {**recs, missing: None})["verdict"] == "INCOMPLETE"
    # supply below its bar: two of C05's three calls sent back
    sent_back = copy.deepcopy(careful_records["C05"])
    sent_back["resolution"]["status"] = "needs_clarification"
    c05 = [s["slot"] for s in freeze["slots"] if s["config"] == "C05"][:2]
    d = SCORE.decide(freeze, {**recs, **{n: sent_back for n in c05}})
    assert d["verdict"] == "INCONCLUSIVE" and not d["supply_bars"]["met"]
    # a dropped cutoff fails
    dropped = copy.deepcopy(careful_records["C06"])
    dropped["resolution"]["status"] = "ok"
    c06 = next(s["slot"] for s in freeze["slots"] if s["config"] == "C06")
    assert SCORE.decide(freeze, {**recs, c06: dropped})["verdict"] == "FAIL"


# ------------------------------------------------------------------------------------------------ the runner loop
def _freeze(**over: Any) -> dict[str, Any]:
    slots = FRZ.plan(random.Random(5))
    src = subprocess.run(["git", "rev-parse", "HEAD:src"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return {"slots": slots, "runs": {"RT": {"cases": 32, "case_cap_usd": 0.006, "run_cap_usd": 0.192}},
            "model": "gpt-5-mini", "label": "LC-route-v13-run", "required_task_cap_usd": 9.087359,
            "ledger_start_usd": 8.895359, "ledger_lines": 3023, "ledger_sha256_prefix": "8dfcdd5e914830cb",
            "prompt_version": "prompts/v13", "files_sha256": {}, "src_tree": src, "code_commit": "x", **over}


class Ledger:
    def __init__(self, start: float = 8.895359):
        self.total = start

    def __call__(self) -> float:
        return round(self.total, 6)


def _loop(freeze, events=None, *, costs=None, outcomes=None, records=None, ledger=None, task_cap=9.087359, live=None):
    ledger = ledger or Ledger()
    log, envs = list(events or []), []

    def write(**kw):
        log.append(kw)

    def launch(slot, env, live_, label):
        envs.append((slot["case"], env))
        ledger.total += (costs or {}).get(slot["slot"], 0.0016)
        return 0, ""

    def finish(slot, rc, text, live_, label):
        return (outcomes or {}).get(slot["slot"], "saved"), (records or {}).get(slot["slot"], {"score": {}})

    end = RUN.run(freeze, list(events or []), write, task_cap=task_cap, launch=launch, finish=finish, spent=ledger,
                  **({"live": live} if live is not None else {}))
    return end, log, envs


def test_a_complete_run_makes_32_calls_with_the_frozen_model_and_caps():
    end, _, envs = _loop(_freeze())
    assert end["result"] == "complete" and end["saved"] == 32 and len(envs) == 32
    env = envs[0][1]
    assert env["NEM_AGENT_MODEL"] == "gpt-5-mini" and float(env["NEM_AGENT_SESSION_BUDGET_USD"]) == 0.006
    assert float(env["NEM_AGENT_TOTAL_BUDGET_USD"]) == round(8.895359 + 0.006, 6)


def test_a_stop_ends_the_run_and_nothing_is_retried():
    for result in ("budget_stop", "error", "missing"):
        end, _, envs = _loop(_freeze(), outcomes={4: result})
        assert end["result"] == "incomplete" and len(envs) == 4 and end["saved"] == 3
    end, _, envs = _loop(_freeze(), records={2: {"score": {"case_note_files_written": 1}}})
    assert end["safety_stop"] and len(envs) == 2


def test_interrupted_attempts_stay_counted_and_may_exhaust_the_run_cap(tmp_path):
    """An interrupted call is re-run once, its cost counted; no retry allowance is added. Here interrupted attempts
    have already spent so much that the start guard stops the run before all 32 calls: INCOMPLETE."""
    f = _freeze()
    events = [{"event": "start", "attempt": 1},
              {"event": "slot_start", "slot": 1, "run": "RT", "case": f["slots"][0]["case"], "ledger_before": 8.895359}]
    end, log, envs = _loop(f, events, ledger=Ledger(8.9), live=tmp_path)
    kill = next(e for e in log if e.get("event") == "interrupted")
    assert kill["slot"] == 1 and kill["ledger_cost"] == round(8.9 - 8.895359, 6) and envs[0][0] == f["slots"][0]["case"]
    assert end["result"] == "complete"
    heavy = events[:1] + [{"event": "interrupted", "slot": 1, "run": "RT", "ledger_cost": 0.19}] + events[1:]
    end2, _, envs2 = _loop(f, heavy, ledger=Ledger(9.09), live=tmp_path, task_cap=9.3)
    assert end2["result"] == "incomplete" and "start guard" in end2["stop_reason"] and envs2 == []


def test_refusals(monkeypatch, tmp_path):
    f = _freeze()
    ok = {"total": 8.895359, "lines": 3023, "sha256_prefix": "8dfcdd5e914830cb"}
    monkeypatch.delenv("NEM_AGENT_BUDGET_LEDGER", raising=False)  # refusal() reads no ledger: it is given one
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-key")
    assert RUN.refusal(f, 9.087359, ok, [], tmp_path) is None
    assert "at least USD 9.087359" in RUN.refusal(f, 9.08, ok, [], tmp_path)
    assert "not the frozen starting ledger" in RUN.refusal(f, 9.087359, dict(ok, lines=3024), [], tmp_path)
    assert "prompt version" in RUN.refusal(dict(f, prompt_version="prompts/v12"), 9.087359, ok, [], tmp_path)
    assert "plan" in RUN.refusal(dict(f, slots=f["slots"][:-1]), 9.087359, ok, [], tmp_path)
    monkeypatch.setenv("NEM_AGENT_MODEL", "gpt-6.1-sol")
    assert "override" in RUN.refusal(f, 9.087359, ok, [], tmp_path)
    monkeypatch.delenv("NEM_AGENT_MODEL")
    monkeypatch.delenv("OPENAI_API_KEY")
    assert "no API key" in RUN.refusal(f, 9.087359, ok, [], tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-key")
    (tmp_path / "LC-route-v13-run").mkdir()
    (tmp_path / "LC-route-v13-run" / "07-C03.json").write_text("{}")
    assert "does not account for" in RUN.refusal(f, 9.087359, ok, [], tmp_path)


# ------------------------------------------------------------------------------------------------ the freeze
@pytest.mark.skipif(FREEZE is None, reason="FREEZE.json not written yet")
def test_the_freeze_matches_the_protocol():
    assert FREEZE["code_commit"].startswith("a648269") and FREEZE["prompt_version"] == "prompts/v13"
    assert FREEZE["model"] == "gpt-5-mini" and FREEZE["route_max_output_tokens"] == 2000
    assert (FREEZE["ledger_start_usd"], FREEZE["ledger_lines"], FREEZE["ledger_sha256_prefix"]) == (
        8.895359, 3023, "8dfcdd5e914830cb")
    assert FREEZE["call_cap_usd"] == 0.006 and FREEZE["runs"]["RT"]["run_cap_usd"] == 0.192
    assert FREEZE["required_task_cap_usd"] == 9.087359
    assert max(FREEZE["reservations_usd"].values()) <= 0.006
    assert FREEZE["slots"] == FRZ.plan(random.Random(FREEZE["order_seed"]))
    for rel, want in FREEZE["files_sha256"].items():
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == want, rel
    assert RUN.plan_mismatch(FREEZE) is None
    head = subprocess.run(["git", "rev-parse", "HEAD:src"], cwd=ROOT, capture_output=True, text=True,
                          check=True).stdout.strip()
    if head != FREEZE["src_tree"]:  # once src/ moves on, the frozen runner refuses to start
        assert RUN.changed(FREEZE) == "the checkout's src/ is not the frozen tree"
