"""The comparative routing-only evaluation of route contracts v15 and v16 (eval/compare_route_v15_v16/PROTOCOL.md),
offline. Covered:
- the sample: 23 development configurations (two duplicates left out), 40 held-out questions and 6 controls, 322
  slots;
- the gold: the development gold derived from verified sources, the writer's records checked, the comparison of two
  records on every gated item, and the frozen gold;
- the per-slot runner on its actual code path: each arm's contract, one routing call and nothing after it, API errors
  of every kind with the ledger's settlement, and incomplete responses;
- the reservations: measured on the runner's own path, equal to what the runner then reserves, with the slot's ledger
  cap admitting exactly that reservation;
- the freeze: the order, the denominators and the run cap, and the frozen files;
- the runner loop: accounting kinds kept apart, API errors and interruptions as terminal records, the stops, and every
  refusal;
- the scorer: both layers, attribution, every critical violation, silent omission, partial handling, the verdict's
  precedence, the interval and V0;
- the complete harness, all 322 frozen slots, through the scripted transport and a scratch ledger.

Nothing here calls a model. Every routing decision is SYNTHETIC, and none is written for a held-out question. The
ledger is a scratch one (tests/conftest.py).
"""

from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from nem_agent import budget

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "eval" / "compare_route_v15_v16"


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"cmp1516_{name}", DIR / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _json(name: str) -> Any:
    p = DIR / name
    return json.loads(p.read_text()) if p.exists() else None


CFG = _load("configs")
GOLDMOD = _load("gold")
ROUTE = _load("run_route")
RUN = _load("run_eval")
SCORE = _load("score")
FRZ = _load("freeze")
DEV_GOLD = {g["config"]: g for g in GOLDMOD.dev_gold()}
DEV_CASES = {c["config"]: c for c in CFG.development_cases()}
FREEZE = _json("FREEZE.json")
GOLD = {g["config"]: g for g in _json("GOLD.json")["cases"]} if _json("GOLD.json") else None
CASES = _json("cases.json")["cases"] if _json("cases.json") else None
WRITER = _json("WRITER_OUTPUT.json")
needs_freeze = pytest.mark.skipif(FREEZE is None, reason="FREEZE.json is written once the reviewed gold is frozen")
DEMAND = {"get_forecast_runs", "compare_forecast_actual"}
MODEL = "gpt-5-mini"
USAGE = {"input_tokens": 9000, "output_tokens": 700, "input_tokens_details": {"cached_tokens": 0},
         "output_tokens_details": {"reasoning_tokens": 500}}


# ------------------------------------------------------------------------------------------------ synthetic inputs
def _resp(decision: dict[str, Any], status: str = "completed", text: str | None = None,
          usage: dict[str, Any] | None = None) -> dict[str, Any]:
    """A SYNTHETIC Responses-API routing response."""
    return {"id": "resp_test", "status": status,
            "incomplete_details": {"reason": "max_output_tokens"} if status == "incomplete" else None,
            "output": [{"type": "message", "role": "assistant",
                        "content": [{"type": "output_text", "text": text if text is not None else json.dumps(decision)}]}],
            "usage": usage or USAGE}


NO_RUN = {"selection": "none", "selection_text": None, "half_hour_text": None}
NO_MAX = {"kind": "none", "measure": None, "measure_text": None, "peak_text": None, "window": None, "window_text": None}


def _fc(domain: str, request_text: str | None, op: str = "none", op_text: str | None = None, scope: str | None = None,
        scope_text: str | None = None, unsupported_text: str | None = None) -> dict[str, Any]:
    return {"operation": op, "operation_text": op_text, "scope": scope, "scope_text": scope_text, "domain": domain,
            "request_text": request_text, "unsupported_text": unsupported_text}


def _v15(intent: str | None, region: str | None, event_date: str | None, fc: dict[str, Any] | None = None,
         run: dict[str, Any] | None = None, mx: dict[str, Any] | None = None, as_of_text: str | None = None,
         **core: Any) -> dict[str, Any]:
    """A SYNTHETIC route contract v15 decision."""
    return {"intent": intent, "region": region, "event_date": event_date, "as_of_text": as_of_text,
            "needs_clarification": False, "clarification_reason": None, "clarification": None, "out_of_scope": False,
            **core, "requested": {"forecast_run": {**NO_RUN, **(run or {})}, "maximum": {**NO_MAX, **(mx or {})},
                                  "forecast": fc or _fc("none", None)}}


def _op(i: str, stance: str, kind: str, subject: str, subject_text: str | None, operation_text: str | None,
        scope: str | None = None, run: str | None = None, cutoff: str | None = None) -> dict[str, Any]:
    return {"id": i, "stance": stance, "kind": kind, "subject": subject, "subject_text": subject_text,
            "operation_text": operation_text, "scope_ref": scope, "run_ref": run, "cutoff_ref": cutoff}


def _v16(intent: str | None, region: str | None, event_date: str | None, ops: list[dict[str, Any]],
         scopes: list[tuple[str, str, str]] = (), runs: list[tuple[str, str, str]] = (),  # type: ignore[assignment]
         cutoffs: list[tuple[str, str]] = (), cutoff_ref: str | None = None, **core: Any) -> dict[str, Any]:  # type: ignore[assignment]
    """A SYNTHETIC route contract v16 decision (a request plan)."""
    return {"intent": intent, "region": region, "event_date": event_date, "needs_clarification": False,
            "clarification_reason": None, "clarification": None, "out_of_scope": False, **core,
            "plan": {"operations": ops, "scopes": [{"id": i, "kind": k, "text": t} for i, k, t in scopes],
                     "runs": [{"id": i, "selection": s, "text": t} for i, s, t in runs],
                     "cutoffs": [{"id": i, "text": t} for i, t in cutoffs], "cutoff_ref": cutoff_ref}}


DEC = {  # SYNTHETIC: careful readings of development questions only (none is written for a held-out question)
    ("V15-D03", "A"): _v15("forecast_review", "NSW1", "2026-07-31", _fc(
        "operational_demand", "How accurate were the operational demand forecasts for NSW1 on 31 July 2026",
        "window_comparison", "How accurate were the operational demand forecasts", "whole_local_day", "on 31 July 2026")),
    ("V15-D03", "B"): _v16("forecast_review", "NSW1", "2026-07-31", [
        _op("o1", "asked", "forecast_comparison", "operational_demand", "operational demand forecasts",
            "How accurate were the operational demand forecasts", scope="s1")],
        scopes=[("s1", "whole_local_day", "on 31 July 2026")]),
    ("V15-N04", "A"): _v15("forecast_review", "VIC1", "2026-08-17", _fc(
        "operational_demand", "For Victoria, I want AEMO's operational demand forecast values for a single half-hour on "
        "17 August 2026: the one ending at 18:30 AEST. What did they show", "forecast_value",
        "I want AEMO's operational demand forecast values", "half_hour",
        "a single half-hour on 17 August 2026: the one ending at 18:30 AEST")),
    ("V15-N04", "B"): _v16("forecast_review", "VIC1", "2026-08-17", [
        _op("o1", "declined", "forecast_value", "weather", "weather", "Leave the weather forecast out of this one"),
        _op("o2", "asked", "forecast_value", "operational_demand", "operational demand",
            "I want AEMO's operational demand forecast values", scope="s1")],
        scopes=[("s1", "half_hour", "a single half-hour on 17 August 2026: the one ending at 18:30 AEST")]),
    ("V15-N07", "A"): _v15("forecast_review", "QLD1", "2026-08-04", _fc(
        "operational_demand", "How did AEMO's operational demand forecast for Queensland compare with actual "
        "operational demand between 06:00 and noon AEST on 4 August 2026", "window_comparison",
        "How did AEMO's operational demand forecast for Queensland compare with actual operational demand", "explicit",
        "between 06:00 and noon AEST on 4 August 2026")),
    ("V15-D09", "A"): _v15("forecast_review", "SA1", "2026-07-31", _fc(
        "weather", "What was the weather forecast for Adelaide on 31 July 2026", "forecast_value")),
    ("V15-D09", "B"): _v16("forecast_review", "SA1", "2026-07-31", [
        _op("o1", "asked", "forecast_value", "weather", "weather", "What was the weather forecast")]),
    ("V15-D10", "A"): _v15("market_event_review", "QLD1", "2025-10-05", mx={
        "kind": "maximum", "measure": "operational_demand", "measure_text": "operational demand",
        "peak_text": "highest", "window": "whole_local_day", "window_text": "that entire local day"},
        as_of_text="Based only on data published by noon Brisbane time on Sunday 5 October 2025"),
    ("V15-D10", "B"): _v16("market_event_review", "QLD1", "2025-10-05", [
        _op("o1", "asked", "demand_maximum", "operational_demand", "operational demand",
            "what was the highest operational demand in Queensland", scope="s1", cutoff="c1")],
        scopes=[("s1", "whole_local_day", "over that entire local day")],
        cutoffs=[("c1", "Based only on data published by noon Brisbane time on Sunday 5 October 2025")]),
    ("E2E-D01", "A"): _v15("market_event_review", "NSW1", "2026-07-29", mx={
        "kind": "maximum", "measure": "dispatch_total_demand", "measure_text": "dispatch total demand",
        "peak_text": "highest", "window": "whole_local_day", "window_text": "across the whole day"}),
    ("E2E-D01", "B"): _v16("market_event_review", "NSW1", "2026-07-29", [
        _op("o1", "asked", "demand_maximum", "dispatch_total_demand", "dispatch total demand",
            "at which five-minute interval was NSW dispatch total demand highest", scope="s1")],
        scopes=[("s1", "whole_local_day", "across the whole day")]),
}
SENT_BACK = {"A": _v15(None, None, None, needs_clarification=True, clarification_reason="unclear_question",
                       clarification="Which analysis is meant?"),
             "B": _v16(None, None, None, [], needs_clarification=True, clarification_reason="unclear_question",
                       clarification="Which analysis is meant?")}


def _arm(monkeypatch: pytest.MonkeyPatch, arm: str) -> None:
    for k in ROUTE.PLAN_SETTINGS:
        monkeypatch.delenv(k, raising=False)
    for k, v in ROUTE.ARM_ENV[arm].items():
        monkeypatch.setenv(k, v)


def _record(monkeypatch: pytest.MonkeyPatch, config: str, arm: str, decision: dict[str, Any] | None = None,
            **resp: Any) -> dict[str, Any]:
    _arm(monkeypatch, arm)
    script = {"response": _resp(decision if decision is not None else DEC[(config, arm)], **resp)}
    return ROUTE.route_call(DEV_CASES[config], arm, client=ROUTE.ScriptedTransport(script), write_trace=False)


# ------------------------------------------------------------------------------------------------ the sample
def test_the_sample_is_69_configurations_and_322_slots():
    assert len(DEV_CASES) == 23 and len(CFG.HELDOUT) == 40 and len(CFG.CONTROLS) == 6
    assert sum(CFG.ANSWERABLE_QUOTA.values()) == 31 and CFG.REPEATS == {"heldout": 3, "control": 3, "development": 1}
    sets = [{"set": "development"}] * 23 + [{"set": "heldout"}] * 40 + [{"set": "control"}] * 6
    assert CFG.slots_per_arm(sets) == 161


def test_two_end_to_end_records_duplicate_v15_configurations_and_are_left_out():
    d = CFG.duplicate_check()
    assert d["duplicates"] == {"R02": "V15-D02", "F07": "V15-D10"}
    kept = {c[4:] for c in DEV_CASES if c.startswith("E2E-")}
    assert kept == set(CFG.E2E_KEPT) and not kept & set(d["duplicates"])
    assert sum(c.startswith("V15-") for c in DEV_CASES) == 17


# ------------------------------------------------------------------------------------------------ the gold
def test_the_development_gold_is_derived_and_well_formed():
    assert len(DEV_GOLD) == 23 and sum(g["answerable"] for g in DEV_GOLD.values()) == 13
    assert all(GOLDMOD.check(g) == [] for g in DEV_GOLD.values())
    for c in ("V15-N07", "E2E-F07N"):  # "noon" with no request cutoff: known-unsupported, the reading kept
        assert DEV_GOLD[c]["acceptable_outcomes"] == ["clarify"] and DEV_GOLD[c]["unsupported_time"] == "noon"
    assert "noon" in DEV_GOLD["V15-N07"]["reader"]["scope_key_words"]
    asked = [m for m in DEV_GOLD["V15-N07"]["mentions"] if m["stance"] == "asked"]
    assert len(asked) == 1  # one asked demand request, not a duplicate


@pytest.mark.skipif(WRITER is None, reason="the writer's records are not in the repository yet")
def test_the_writers_records_meet_the_format_ids_and_quotas():
    assert GOLDMOD.check_writer(WRITER["cases"]) == []
    bad = copy.deepcopy(WRITER["cases"])
    bad[0]["answerable"] = not bad[0]["answerable"]
    assert GOLDMOD.check_writer(bad)
    assert any("IDs" in p for p in GOLDMOD.check_writer(bad[1:]))


def test_two_mentions_may_not_share_their_words():
    g = copy.deepcopy(DEV_GOLD["V15-N04"])
    g["mentions"][1]["anchors"] = [g["mentions"][0]["anchors"][0]]
    assert any("overlap" in p for p in GOLDMOD.check(g))


@pytest.mark.parametrize("mutate, flagged", [
    (lambda r: r.update(region="NSW1"), "region"),
    (lambda r: r.update(cutoff_utc="2026-08-17T00:00:00Z"), "cutoff_utc"),
    (lambda r: r.update(demand_forecast_tools="not_used"), "demand_forecast_tools"),
    (lambda r: r["mentions"][1].update(stance="asked"), "mention"),
    (lambda r: r["resolution"]["scope"].update(start_utc="2026-08-17T07:30:00Z"), "resolution.scope.start_utc"),
    (lambda r: r["resolution"]["run"].update(rule="last_issued_before"), "resolution.run"),
    (lambda r: r["resolution"].update(not_answered=["weather"]), "resolution.not_answered"),
    (lambda r: r.update(intents=["market_event_review"]), "intents"),
    (lambda r: r.update(acceptable_outcomes=["clarify"], outcome="clarify"), "acceptable_outcomes"),
])
def test_the_comparison_flags_every_gated_item(mutate, flagged):
    a = DEV_GOLD["V15-N04"]
    assert GOLDMOD.compare(a, copy.deepcopy(a)) == []
    b = copy.deepcopy(a)
    mutate(b)
    assert any(d.startswith(flagged) for d in GOLDMOD.compare(a, b))


def test_agreeing_records_merge_to_the_members_both_share():
    a = copy.deepcopy(DEV_GOLD["V15-D10"])
    b = copy.deepcopy(a)
    b["intents"] = ["market_event_review"]
    assert GOLDMOD.compare(a, b) == [] and GOLDMOD.merge(a, b)["intents"] == ["market_event_review"]


@needs_freeze
def test_the_frozen_gold_holds_the_writers_records_and_the_derived_development_gold():
    assert GOLD is not None and CASES is not None
    assert len(GOLD) == len(CASES) and {c["config"] for c in CASES} == set(GOLD)
    for c in DEV_GOLD:  # development gold is never changed by this evaluation
        assert GOLD[c] == DEV_GOLD[c] or GOLDMOD.compare(GOLD[c], DEV_GOLD[c]) == []
    held = [g for c, g in GOLD.items() if c in CFG.HELDOUT + CFG.CONTROLS]
    assert all(GOLDMOD.check(g, CFG.FAMILY_OF[g["config"]]) == [] for g in held)
    assert FREEZE["denominators"]["answerable_heldout_questions"] == sum(
        1 for g in held if g["answerable"] and g["config"] in CFG.HELDOUT)


# ------------------------------------------------------------------------------------------------ the per-slot runner
@pytest.mark.parametrize("arm, contract, prompts", [("A", "v15", "prompts/v16"), ("B", "v16", "prompts/v17")])
def test_each_arm_runs_its_contract_and_only_the_routing_call(arm, contract, prompts, monkeypatch):
    rec = _record(monkeypatch, "V15-D03", arm)
    assert rec["route_contract"] == contract == rec["decision_contract"] and rec["prompt_version"] == prompts
    assert rec["score"]["model_calls"] == 1 and rec["score"]["tools_executed"] == 0
    assert rec["score"]["case_note_files_written"] == 0 and rec["api_error"] is None and not rec["route_invalid"]
    assert rec["resolution"]["status"] == "ok" and set(rec["tools_offered"]) & DEMAND
    assert rec["route_call"]["usage_cost_usd"] == budget.call_cost(MODEL, USAGE)
    assert ("plan" in (rec["resolution"]["requests"] or {})) == (arm == "B")


def test_a_slot_refuses_route_plan_settings_that_are_not_its_arms(monkeypatch):
    _arm(monkeypatch, "A")
    with pytest.raises(SystemExit):
        ROUTE.route_call(DEV_CASES["V15-D03"], "B", client=ROUTE.ScriptedTransport({"response": _resp({})}))
    _arm(monkeypatch, "B")
    monkeypatch.setenv("NEM_AGENT_PLAN_POLICY", "V0")
    with pytest.raises(SystemExit):
        ROUTE.route_call(DEV_CASES["V15-D03"], "B", client=ROUTE.ScriptedTransport({"response": _resp({})}))


@pytest.mark.parametrize("status_code, settled_at_worst", [(400, False), (429, False), (500, True), (None, True)])
def test_an_api_error_is_recorded_with_the_ledgers_settlement_and_counted_unresolved(status_code, settled_at_worst,
                                                                                      monkeypatch):
    case = DEV_CASES["V15-D03"]
    reservation = FRZ.measure_reservations([case])["V15-D03"]["B"]
    _arm(monkeypatch, "B")
    before = budget.spent()
    rec = ROUTE.route_call(case, "B", client=ROUTE.ScriptedTransport(
        {"raise": {"status_code": status_code, "message": "scripted failure"}}), write_trace=False)
    after = budget.spent()
    settled = reservation if settled_at_worst else 0.0
    assert rec["api_error"]["status_code"] == status_code and rec["api_error"]["settled_usd"] == settled
    assert rec["decision"] is None and rec["resolution"] is None and round(after - before, 6) == settled
    slot = {"slot": 1, "arm": "B", "case": "x", "reservation_usd": reservation}
    e = RUN.slot_end(slot, RUN.outcome("", rec), rec, before, after)
    # whatever the ledger settled (an HTTP 4xx at zero), the cost is not observed: conservative counts the reservation
    assert (e["outcome"], e["unresolved"], e["observed_usd"], e["conservative_usd"]) == (
        "api_error", True, None, reservation)
    assert SCORE.outcome_of(rec) == "no_reading"


def test_an_incomplete_response_is_no_reading_but_its_usage_is_observed(monkeypatch):
    rec = _record(monkeypatch, "V15-D03", "B", text='{"intent": "forecast_re', status="incomplete")
    assert rec["route_invalid"] and rec["route_call"]["status"] == "incomplete"
    assert rec["resolution"]["status"] == "needs_clarification" and rec["tools_offered"] == []
    assert SCORE.outcome_of(rec) == "no_reading" and RUN.observed_cost(rec) == budget.call_cost(MODEL, USAGE)


# ------------------------------------------------------------------------------------------------ reservations
def test_the_measured_reservation_is_what_the_runner_reserves_and_measuring_writes_nothing(monkeypatch):
    ledger = budget.ledger_path()
    cases = [DEV_CASES["V15-D03"], DEV_CASES["E2E-D01"]]
    measured = FRZ.measure_reservations(cases)
    assert not ledger.exists() or ledger.read_text() == ""
    for c in cases:
        for arm in ("A", "B"):
            _record(monkeypatch, c["config"], arm, decision=SENT_BACK[arm])
            reserved = [json.loads(ln) for ln in ledger.read_text().splitlines() if '"reserve"' in ln][-1]
            assert reserved["usd"] == measured[c["config"]][arm] and reserved["stage"] == "route"
    assert all(0.004 < v < 0.008 for m in measured.values() for v in m.values())


def test_the_slots_ledger_cap_admits_exactly_its_frozen_reservation(monkeypatch):
    reservation = FRZ.measure_reservations([DEV_CASES["V15-D03"]])["V15-D03"]["B"]
    monkeypatch.setenv("NEM_AGENT_TOTAL_BUDGET_USD", f"{budget.spent() + reservation + 1e-6:.6f}")
    assert _record(monkeypatch, "V15-D03", "B")["api_error"] is None
    monkeypatch.setenv("NEM_AGENT_TOTAL_BUDGET_USD", f"{budget.spent() + reservation - 1e-5:.6f}")
    with pytest.raises(budget.BudgetExceeded):
        _record(monkeypatch, "V15-D03", "B")


# ------------------------------------------------------------------------------------------------ the freeze
def _synthetic_cases() -> list[dict[str, Any]]:
    return [*({"config": c, "set": "development", "repeats": 1} for c in DEV_CASES),
            *({"config": c, "set": "heldout", "repeats": 3} for c in CFG.HELDOUT),
            *({"config": c, "set": "control", "repeats": 3} for c in CFG.CONTROLS)]


def test_the_order_is_frozen_interleaved_and_holds_every_slot_once():
    cases = _synthetic_cases()
    res = {c["config"]: {"A": 0.0055, "B": 0.0057} for c in cases}
    slots = FRZ.plan_slots(cases, res)
    assert slots == FRZ.plan_slots(cases, res) and len(slots) == 322
    assert sum(s["arm"] == "A" for s in slots) == 161 and len({s["case"] for s in slots}) == 322
    pairs = [(slots[i], slots[i + 1]) for i in range(0, 322, 2)]
    assert all((a["config"], a["repeat"]) == (b["config"], b["repeat"]) and a["arm"] != b["arm"] for a, b in pairs)
    first = [a["arm"] for a, _ in pairs]
    assert first.count("A") > 40 and first.count("B") > 40  # the arms' order varies
    freeze = {"slots": slots, "run_cap_usd": round(sum(s["reservation_usd"] for s in slots), 6)}
    assert RUN.plan_mismatch(freeze, cases) is None
    assert RUN.plan_mismatch({**freeze, "run_cap_usd": freeze["run_cap_usd"] + 0.01}, cases)
    assert RUN.plan_mismatch({**freeze, "slots": slots[:-1]}, cases)


def test_the_denominators_follow_the_frozen_gold():
    cases = _synthetic_cases()
    gold = [{"config": c["config"], "answerable": c["config"] in CFG.HELDOUT[:31]} for c in cases]
    d = FRZ.denominators(gold, cases)
    assert (d["answerable_heldout_questions"], d["availability_slots_per_arm"], d["incomplete_rate_slots_per_arm"],
            d["control_slots_per_arm"], d["slots_per_arm"], d["infrastructure_threshold"]["max_count"]) == (
        31, 93, 138, 18, 161, 8)


@needs_freeze
def test_the_freeze_matches_the_files_the_code_and_the_ceiling():
    try:
        why = RUN.changed(FREEZE)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("not a git checkout")
    assert why is None and RUN.plan_mismatch(FREEZE) is None
    assert len(FREEZE["slots"]) == 322 and FREEZE["run_cap_usd"] <= FRZ.MAX_PREPARED_USD
    assert FREEZE["run_cap_usd"] == round(sum(s["reservation_usd"] for s in FREEZE["slots"]), 6)
    assert FREEZE["arms"] == {"A": {"env": {}, "route_contract": "v15", "prompt_version": "prompts/v16"},
                              "B": {"env": {"NEM_AGENT_ROUTE_PLAN": "1", "NEM_AGENT_PLAN_POLICY": "V1"},
                                    "route_contract": "v16", "prompt_version": "prompts/v17"}}
    assert FREEZE["model"] == MODEL and FREEZE["route_max_output_tokens"] == 2000
    assert FREEZE["denominators"]["availability_slots_per_arm"] == 3 * FREEZE["denominators"][
        "answerable_heldout_questions"]


@needs_freeze
def test_the_frozen_reservations_are_remeasured_exactly():
    assert FRZ.measure_reservations(CASES) == FREEZE["reservations_usd"]
    assert FRZ.plan_slots(CASES, FREEZE["reservations_usd"]) == FREEZE["slots"]


# ------------------------------------------------------------------------------------------------ the runner loop
def _freeze(n: int = 6, reservation: float = 0.005, label: str = "T") -> dict[str, Any]:
    slots = [{"slot": i, "config": "V15-D03", "set": "development", "arm": "AB"[(i - 1) % 2], "repeat": 1 + (i - 1) // 2,
              "case": f"{i:03d}-x", "reservation_usd": reservation} for i in range(1, n + 1)]
    return {"label": label, "model": MODEL, "slots": slots, "run_cap_usd": round(n * reservation, 6),
            "files_sha256": {}, "src_tree": "x"}


class _Fake:
    """SYNTHETIC slot processes and ledger: each slot's behaviour is scripted; the ledger is a running total."""

    def __init__(self, plan: dict[int, tuple[Any, ...]] | None = None) -> None:
        self.plan, self.ledger, self.launched = plan or {}, 0.0, []

    def spent(self) -> float:
        return round(self.ledger, 6)

    def launch(self, slot: dict[str, Any], env: dict[str, str], live: Path, label: str) -> tuple[int, str]:
        assert env["NEM_AGENT_TOTAL_BUDGET_USD"] == f"{self.spent() + slot['reservation_usd'] + 1e-6:.6f}"
        assert env["NEM_AGENT_MODEL"] == MODEL
        assert {k: env.get(k) for k in ROUTE.PLAN_SETTINGS} == {k: ROUTE.ARM_ENV[slot["arm"]].get(k)
                                                                 for k in ROUTE.PLAN_SETTINGS}
        self.launched.append(slot["slot"])
        kind = self.plan.get(slot["slot"], ("saved", 0.002))
        out = live / label
        out.mkdir(parents=True, exist_ok=True)
        rec: dict[str, Any] = {"api_error": None, "route_call": {"usage_cost_usd": None},
                               "score": {"case_note_files_written": 0, "tools_executed": 0, "model_calls": 1}}
        if kind[0] == "stop":
            return 0, f"[{slot['case']}] STOPPED: task budget"
        if kind[0] == "crash":  # reserved, never settled, no record
            self.ledger += slot["reservation_usd"]
            return 1, "Traceback"
        if kind[0] == "saved":
            self.ledger += kind[1]
            rec["route_call"]["usage_cost_usd"] = kind[1]
        elif kind[0] == "api_error":
            self.ledger += kind[2]
            rec["api_error"] = {"type": "APIStatusError", "status_code": kind[1], "settled_usd": kind[2]}
        elif kind[0] == "notes":
            self.ledger += 0.002
            rec["route_call"]["usage_cost_usd"] = 0.002
            rec["score"]["case_note_files_written"] = 1
        (out / f"{slot['case']}.json").write_text(json.dumps(rec))
        return 0, "saved"


def _run(tmp_path: Path, freeze: dict[str, Any], fake: _Fake, events: list[dict[str, Any]] | None = None,
         approved: float | None = None, frozen: Any = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    log: list[dict[str, Any]] = list(events or [])
    end = RUN.run(freeze, list(log), lambda **kw: log.append(kw), approved=approved or freeze["run_cap_usd"],
                  launch=fake.launch, spent=fake.spent, frozen=frozen or (lambda: None), live=tmp_path,
                  base_env={"NEM_AGENT_BUDGET_LEDGER": "scratch"})
    return end, log


def test_a_complete_run_reconciles_and_keeps_the_accounting_kinds_apart(tmp_path):
    fake = _Fake({2: ("api_error", 400, 0.0), 3: ("api_error", 500, 0.005)})
    end, _ = _run(tmp_path, _freeze(), fake)
    assert end["result"] == "complete" and end["terminal"] == 6 and end["outcomes"] == {"api_error": 2, "saved": 4}
    r = end["reconciliation"]
    assert r["reconciles"] and r["settled_usd"] == r["ledger_change_usd"] == round(4 * 0.002 + 0.005, 6)
    assert (r["observed_usd"], r["observed_slots"], r["unresolved_slots"]) == (0.008, 4, 2)
    assert r["conservative_usd"] == end["conservative_usd"] == round(4 * 0.002 + 2 * 0.005, 6)  # 4xx at its reservation
    assert r["reserved_usd"] == 0.03 and fake.launched == [1, 2, 3, 4, 5, 6]


def test_a_slot_ending_without_a_record_is_interrupted_and_the_run_continues(tmp_path):
    end, log = _run(tmp_path, _freeze(), _Fake({3: ("crash",)}))
    e = next(x for x in log if x.get("event") == "interrupted")
    assert (e["slot"], e["unresolved"], e["conservative_usd"], e["settled_usd"]) == (3, True, 0.005, 0.005)
    assert end["result"] == "complete" and end["outcomes"]["interrupted"] == 1 and end["reconciliation"]["reconciles"]


@pytest.mark.parametrize("record_saved", [False, True])
def test_a_slot_in_flight_at_a_kill_is_found_at_the_next_start_and_never_started_again(record_saved, tmp_path):
    freeze, fake = _freeze(), _Fake()
    _, first = _run(tmp_path, freeze, fake)
    cut = next(i for i, e in enumerate(first) if e.get("event") == "slot_start" and e["slot"] == 4)
    events = first[:cut + 1]  # killed while slot 4 ran: its log entry and everything after are lost
    if not record_saved:
        (tmp_path / "T" / "004-x.json").unlink()
        for f in (tmp_path / "T").glob("00[56]-x.json"):
            f.unlink()
    else:
        for f in (tmp_path / "T").glob("00[56]-x.json"):
            f.unlink()
    fake2 = _Fake()
    fake2.ledger = fake.ledger - 2 * 0.002  # slots 5 and 6 never ran in this history
    end, log = _run(tmp_path, freeze, fake2, events=events)
    found = next(x for x in log if x.get("found_at_start"))
    assert found["slot"] == 4 and found["outcome"] == ("saved" if record_saved else "interrupted")
    assert fake2.launched == [5, 6] and end["result"] == "complete"


def test_the_start_guard_stops_before_a_slot_that_does_not_fit(tmp_path):
    end, log = _run(tmp_path, _freeze(), _Fake({1: ("api_error", 503, 0.005), 2: ("api_error", 503, 0.005)}),
                    approved=0.0125)
    stop = next(x for x in log if x.get("event") == "not_run")
    assert stop["slots"] == [3, 4, 5, 6] and "start guard" in stop["reason"]
    assert end["result"] == "incomplete" and end["terminal"] == 2


def test_a_ledger_refusal_stops_the_run(tmp_path):
    end, log = _run(tmp_path, _freeze(), _Fake({2: ("stop",)}))
    assert next(x for x in log if x.get("event") == "not_run")["slots"] == [3, 4, 5, 6]
    assert end["result"] == "incomplete" and end["outcomes"] == {"budget_stop": 1, "saved": 1}
    assert end["conservative_usd"] == 0.002  # nothing was sent for the refused slot


def test_a_safety_failure_stops_the_run_and_it_is_never_resumed(tmp_path):
    freeze = _freeze()
    end, log = _run(tmp_path, freeze, _Fake({2: ("notes",)}))
    assert end["safety_stop"] and end["result"] == "incomplete"
    assert "safety stop" in RUN.refusal(freeze, "evaluation", 1.0, {"lines": 0}, log, live=tmp_path,
                                        env={"OPENAI_API_KEY": "k"}, frozen=lambda f: None,
                                        cases=[{"config": "V15-D03", "repeats": 3}])
    fake = _Fake()
    assert _run(tmp_path, freeze, fake, events=log)[0] == end and fake.launched == []


def test_a_change_to_frozen_material_stops_the_run(tmp_path):
    calls = iter([None, None, "score.py differs from FREEZE.json"] + [None] * 10)
    end, _ = _run(tmp_path, _freeze(), _Fake(), frozen=lambda: next(calls))
    assert end["terminal"] == 2 and "score.py differs" in end["stop_reason"]


def _refusal(tmp_path: Path, **over: Any) -> str | None:
    freeze = over.pop("freeze", _freeze())
    kw: dict[str, Any] = {"mode": "evaluation", "approved": freeze["run_cap_usd"], "ledger": {"lines": 0},
                          "events": [], "env": {"OPENAI_API_KEY": "sk-test-not-a-key"}, "frozen": lambda f: None,
                          "cases": [{"config": "V15-D03", "repeats": 3}]}
    kw.update(over)
    return RUN.refusal(freeze, kw["mode"], kw["approved"], kw["ledger"], kw["events"], live=tmp_path, env=kw["env"],
                       frozen=kw["frozen"], cases=kw["cases"])


HISTORICAL = {"total": 9.336937, "lines": 3226, "sha256_prefix": "f303c2bc70aadd8f"}


@pytest.mark.parametrize("over, why", [
    ({}, None),
    ({"mode": "historical", "ledger": HISTORICAL}, None),
    ({"frozen": lambda f: "PROTOCOL.md differs from FREEZE.json"}, "differs"),
    ({"cases": [{"config": "V15-D03", "repeats": 2}]}, "frozen repeats"),
    ({"events": [{"event": "end"}]}, "has ended"),
    ({"mode": None}, "not named"),
    ({"env": {}}, "no API key"),
    ({"approved": 0.01}, "approved spend"),
    ({"approved": None}, "approved spend"),
    ({"ledger": {"lines": 2}}, "not empty"),
    ({"mode": "historical", "ledger": {**HISTORICAL, "total": 9.4}}, "not the historical ledger"),
    ({"events": [{"event": "start", "ledger_path_mode": "historical"}]}, "resumes only on it"),
    *(({"env": {"OPENAI_API_KEY": "k", k: "1"}}, "override") for k in RUN.OVERRIDES),
])
def test_every_refusal(over, why, tmp_path):
    got = _refusal(tmp_path, **over)
    assert (got is None) if why is None else (got is not None and why in got)


def test_records_the_log_does_not_account_for_are_refused(tmp_path):
    (tmp_path / "T").mkdir()
    (tmp_path / "T" / "009-x.json").write_text("{}")
    assert "does not account for" in _refusal(tmp_path)


# ------------------------------------------------------------------------------------------------ the scorer: layers
@pytest.mark.parametrize("config", ["V15-D03", "V15-D10", "E2E-D01"])
def test_both_arms_careful_readings_resolve_exactly_and_score_alike(config, monkeypatch):
    g = DEV_GOLD[config]
    for arm in ("A", "B"):
        rec = _record(monkeypatch, config, arm)
        ext, l2 = SCORE.assess_extraction(rec, g), SCORE.assess_resolution(rec, g, "development")
        assert ext["reading"] == "correct", (arm, ext["errors"])
        assert (l2["outcome"], l2["exact"], l2["acceptable"], l2["violations"], l2["silent_omission"]) == (
            "resolved", True, True, [], False), (arm, l2)
        assert SCORE.attribution(ext, l2) == "correct end to end"


def test_one_definition_scores_both_arms_a_declined_forecast_named_unanswered_is_not_exact(monkeypatch):
    g = DEV_GOLD["V15-N04"]
    a, b = _record(monkeypatch, "V15-N04", "A"), _record(monkeypatch, "V15-N04", "B")
    la, lb = SCORE.assess_resolution(a, g, "development"), SCORE.assess_resolution(b, g, "development")
    assert SCORE.assess_extraction(a, g)["reading"] == SCORE.assess_extraction(b, g)["reading"] == "correct"
    assert la["outcome"] == "resolved" and not la["exact"] and any("not answered" in m for m in la["mismatch"])
    assert SCORE.attribution(SCORE.assess_extraction(a, g), la) == "correct reading mis-resolved by code"
    assert lb["exact"] and lb["acceptable"]
    assert SCORE.assess_extraction(b, g)["plan_items"]["stances_correct"] == 2


def test_a_correct_reading_code_cannot_convert_is_a_resolver_limitation_not_an_extraction_error(monkeypatch):
    rec = _record(monkeypatch, "V15-N07", "A")  # "noon": the words are right, code cannot pin them down
    g = DEV_GOLD["V15-N07"]
    ext = SCORE.assess_extraction(rec, g)
    assert ext["reading"] == "correct" and SCORE.outcome_of(rec) == "clarify"
    assert SCORE.attribution(ext, SCORE.assess_resolution(rec, g, "development")) == "correct end to end"
    resolvable = {**copy.deepcopy(g), "acceptable_outcomes": ["resolved"], "outcome": "resolved"}
    assert SCORE.attribution(ext, SCORE.assess_resolution(rec, resolvable, "development")) == \
        "correct reading rejected by code"


def test_another_kind_only_is_sent_back_by_both_arms_with_no_demand_tool(monkeypatch):
    g = DEV_GOLD["V15-D09"]
    for arm in ("A", "B"):
        rec = _record(monkeypatch, "V15-D09", arm)
        l2 = SCORE.assess_resolution(rec, g, "development")
        assert l2["outcome"] in g["acceptable_outcomes"] and l2["acceptable"] and not l2["violations"]
        assert SCORE.assess_extraction(rec, g)["items"]["other_kind"]


def test_request_words_on_declined_words_are_an_extraction_error(monkeypatch):
    d = copy.deepcopy(DEC[("V15-N04", "A")])
    d["requested"]["forecast"]["request_text"] = "Leave the weather forecast out of this one. For Victoria, I want " \
        "AEMO's operational demand forecast values"
    ext = SCORE.assess_extraction(_record(monkeypatch, "V15-N04", "A", decision=d), DEV_GOLD["V15-N04"])
    assert ext["reading"] == "incorrect" and not ext["items"]["declined_or_background"]


def test_v15_is_not_marked_wrong_for_reading_one_of_two_asked_requests(monkeypatch):
    g = copy.deepcopy(DEV_GOLD["E2E-D01"])
    q = g["question"]
    g["mentions"].append({"stance": "asked", "kind": "forecast_value", "subject": "operational_demand",
                          "anchors": ["what was the level"], "primary": False})
    g["mentions"][0]["primary"] = False
    assert "what was the level" in q
    ext = SCORE.assess_extraction(_record(monkeypatch, "E2E-D01", "A"), g)
    assert ext["items"] == {"intent": True, "region": True, "date": True, "asked_request": True}


def test_v0_is_recompiled_offline_and_reported_only(monkeypatch):
    d = copy.deepcopy(DEC[("V15-D03", "B")])
    d["plan"]["operations"][0]["subject_text"] = "forecasts"  # no demand word: V1 sends it back, V0 resolves it
    rec = _record(monkeypatch, "V15-D03", "B", decision=d)
    g = DEV_GOLD["V15-D03"]
    assert SCORE.outcome_of(rec) == "clarify"
    v0 = SCORE.recompile_v0(rec)
    assert SCORE.assess_resolution(v0, g, "development")["exact"] and os.environ.get("NEM_AGENT_PLAN_POLICY") == "V1"


# ------------------------------------------------------------------------------------------------ the scorer: layer 2
Q = DEV_GOLD["V15-N04"]["question"]
TARGET = ["2026-08-17T08:00:00Z", "2026-08-17T08:30:00Z"]


def _span(role: str, text: str, q: str = Q) -> dict[str, Any]:
    i = q.index(text)
    return {"role": role, "text": text, "occurrences": [[i, i + len(text)]]}


def _syn(status: str = "ok", intent: str | None = "forecast_review", region: str | None = "VIC1",
         as_of: str | None = None, fa: dict[str, Any] | None = None, fr: dict[str, Any] | None = None,
         mx: dict[str, Any] | None = None, notes: tuple[str, ...] = (), tools: tuple[str, ...] = (),
         q: str = Q, score: dict[str, Any] | None = None) -> dict[str, Any]:
    """A SYNTHETIC record with a hand-built resolution."""
    return {"question": q, "request": {}, "api_error": None, "route_invalid": False,
            "decision": {"intent": intent, "region": region, "event_date": None, "plan": {"operations": []}},
            "resolution": {"status": status, "intent": intent, "region": region, "as_of_utc": as_of,
                           "requests": {"forecast": fa or {"status": "absent"}, "forecast_run": fr or {"status": "absent"},
                                        "maximum": mx or {"status": "absent"}, "notes": list(notes),
                                        "ineligible_tools": {}}},
            "tools_offered": list(tools), "score": score or {"case_note_files_written": 0, "tools_executed": 0}}


def _fa(**over: Any) -> dict[str, Any]:
    return {"status": "bound", "operation": "forecast_value", "scope": "half_hour", "target_utc": TARGET,
            "window_utc": None, "half_hours": 1, "unsupported": [], "spans": [], **over}


def _codes(l2: dict[str, Any]) -> list[str]:
    return sorted({v[:2] for v in l2["violations"]})


@pytest.mark.parametrize("rec, codes", [
    (_syn(fa=_fa(), tools=tuple(DEMAND)), []),
    (_syn(fa=_fa(), tools=tuple(DEMAND), as_of="2026-08-17T00:00:00Z"), ["C2"]),
    (_syn(fa=_fa(target_utc=["2026-08-17T07:30:00Z", "2026-08-17T08:00:00Z"]), tools=tuple(DEMAND)), ["C3"]),
    (_syn(fa=_fa(), region="NSW1", tools=tuple(DEMAND)), ["C3"]),
    (_syn(fa=_fa(), fr={"status": "bound", "selection": "last_issued_before", "half_hour_utc": TARGET},
          tools=tuple(DEMAND)), ["C3"]),
    (_syn(fa=_fa(), mx={"status": "bound", "measures": ["total demand"], "window_kind": "day", "window_utc": TARGET},
          tools=tuple(DEMAND)), ["C3"]),
    (_syn(fa=_fa(spans=[_span("operation", "Leave the weather forecast")]), tools=tuple(DEMAND)), ["C4"]),
    (_syn(status="needs_clarification", fa=_fa(spans=[_span("subject", "weather forecast")])), ["C4"]),
    (_syn(fa=_fa(), tools=tuple(DEMAND), score={"case_note_files_written": 1, "tools_executed": 0}), ["C6"]),
])
def test_each_critical_violation(rec, codes):
    assert _codes(SCORE.assess_resolution(rec, DEV_GOLD["V15-N04"], "development")) == codes


def test_c1_demand_tools_where_the_gold_says_not_used_and_c5_a_control_that_proceeds():
    g = DEV_GOLD["V15-D09"]
    rec = _syn(intent="market_event_review", region="SA1", tools=tuple(DEMAND), q=g["question"])
    assert _codes(SCORE.assess_resolution(rec, g, "development")) == ["C1"]
    assert _codes(SCORE.assess_resolution(rec, g, "control")) == ["C1", "C5"]
    assert not SCORE.control_safe(rec) and SCORE.control_safe(_syn(status="needs_clarification", q=g["question"]))


def test_c6_is_counted_for_any_record_even_without_a_resolution():
    rec = {**_syn(), "resolution": None, "api_error": {"status_code": 500},
           "score": {"case_note_files_written": 2, "tools_executed": 0}}
    assert _codes(SCORE.assess_resolution(rec, DEV_GOLD["V15-N04"], "development")) == ["C6"]


def test_an_asked_request_neither_bound_nor_named_is_a_silent_omission():
    g = DEV_GOLD["V15-N04"]
    silent = _syn(intent="market_event_review", tools=tuple(DEMAND))
    named = _syn(intent="market_event_review", notes=("The question also mentions a forecast without showing which, "
                                                      "so no AEMO operational demand forecast is compared or given.",))
    assert SCORE.assess_resolution(silent, g, "development")["silent_omission"]
    l2 = SCORE.assess_resolution(named, g, "development")
    assert not l2["silent_omission"] and l2["outcome"] == "event_review_without_demand_forecast" and not l2["acceptable"]
    mg = DEV_GOLD["V15-D10"]  # a maximum is named by no note: unbound in a proceeding resolution, always silent
    rec = _syn(intent="market_event_review", region="QLD1", as_of=mg["cutoff_utc"], q=mg["question"],
               notes=("Not answered: the question also asks about a weather forecast. This assistant reviews AEMO's "
                      "operational demand forecasts only and gives no other forecast.",))
    assert SCORE.assess_resolution(rec, mg, "development")["silent_omission"]


def _two_requests() -> dict[str, Any]:
    g = copy.deepcopy(DEV_GOLD["E2E-D01"])
    g["mentions"][0]["primary"] = False
    g["mentions"].append({"stance": "asked", "kind": "forecast_value", "subject": "operational_demand",
                          "anchors": ["what was the level"], "primary": False})
    return {**g, "answerable": False, "acceptable_outcomes": ["clarify"], "outcome": "clarify", "intents": [],
            "resolution": None, "demand_forecast_tools": "not_used"}


def test_one_of_two_asked_requests_bound_and_the_other_named_is_partial_never_acceptable():
    g = _two_requests()
    mx = {"status": "bound", "measures": ["total demand"], "window_kind": "day",
          "window_utc": ["2026-07-28T14:00:00Z", "2026-07-29T14:00:00Z"]}
    note = "The question also mentions a forecast without showing which, so no AEMO operational demand forecast is " \
           "compared or given for it."
    partial = _syn(intent="market_event_review", region="NSW1", mx=mx, notes=(note,), q=g["question"])
    l2 = SCORE.assess_resolution(partial, g, "heldout")
    assert l2["partial"] and not l2["silent_omission"] and not l2["violations"] and not l2["acceptable"]
    assert SCORE.attribution({"reading": "correct"}, l2) == "correct reading mis-resolved by code"
    silent = SCORE.assess_resolution(_syn(intent="market_event_review", region="NSW1", mx=mx, q=g["question"]), g,
                                     "heldout")
    assert silent["silent_omission"] and not silent["partial"]


def test_the_not_answered_kinds_are_read_from_the_bound_kinds_and_the_notes():
    rq = {"forecast": {"unsupported": ["price"]}, "notes": [
        "Not answered: the question also asks about a weather forecast. This assistant reviews AEMO's operational "
        "demand forecasts only and gives no other forecast."]}
    assert SCORE.not_answered_kinds(rq) == ["price", "weather"]
    assert SCORE.not_answered_kinds({"notes": ["Not answered: the question also asks about a another kind of "
                                               "forecast."]}) == ["other"]


# ------------------------------------------------------------------------------------------------ the verdict
def _verdict_setup(b_exact: int = 15, a_exact: int = 0, b_cost: float = 0.0025):
    """A SYNTHETIC five-question evaluation: H01–H05 answerable (N04's gold), C01 a control (N07's gold)."""
    gold = {**{h: {**copy.deepcopy(DEV_GOLD["V15-N04"]), "config": h} for h in CFG.HELDOUT[:5]},
            "C01": {**copy.deepcopy(DEV_GOLD["V15-N07"]), "config": "C01"}}
    cases = [{"config": c, "set": "control" if c == "C01" else "heldout", "repeats": 3} for c in gold]
    slots = FRZ.plan_slots(cases, {c: {"A": 0.005, "B": 0.005} for c in gold})
    freeze = {"slots": slots, "denominators": FRZ.denominators(list(gold.values()), cases)}
    exact = _syn(fa=_fa(), tools=tuple(DEMAND))
    back = _syn(status="needs_clarification")
    recs, nb, na = {}, 0, 0
    for s in slots:
        if s["config"] == "C01":
            rec = _syn(status="needs_clarification", q=gold["C01"]["question"])
        elif s["arm"] == "B":
            nb += 1
            rec = exact if nb <= b_exact else back
        else:
            na += 1
            rec = exact if na <= a_exact else back
        cost = b_cost if s["arm"] == "B" else 0.0025
        recs[s["slot"]] = ("saved", rec, {"settled_usd": cost, "observed_usd": cost, "conservative_usd": cost,
                                          "unresolved": False})
    return freeze, gold, recs


def test_met_needs_every_criterion():
    freeze, gold, recs = _verdict_setup()
    out = SCORE.decide(freeze, gold, recs, v0=False)
    assert out["verdict"] == "MET" and out["availability_difference"]["interval_90"]["low"] == 1.0
    b = out["arms"]["B"]
    assert b["availability"] == {"exact": 15, "of": 15, "rate": 1.0, "questions_by_exact_repeats":
                                 {"3": 5, "2": 0, "1": 0, "0": 0}} and b["controls_safe"] == "3 of 3"


@pytest.mark.parametrize("kw, criterion", [({"b_exact": 11}, "2."), ({"b_exact": 2}, "1."),
                                           ({"b_cost": 0.004}, "5.")])
def test_not_met_names_each_unmet_criterion(kw, criterion):
    out = SCORE.decide(*_verdict_setup(**kw), v0=False)
    assert out["verdict"] == "NOT MET" and any(u.startswith(criterion) for u in out["verdict_reasons"]["criteria_unmet"])


def test_the_verdicts_precedence_and_infrastructure_never_erases_a_violation():
    freeze, gold, recs = _verdict_setup()
    b_slots = [s["slot"] for s in freeze["slots"] if s["arm"] == "B" and s["config"] != "C01"]
    a_slots = [s["slot"] for s in freeze["slots"] if s["arm"] == "A"]
    err = {**_syn(), "api_error": {"status_code": 500}, "resolution": None, "decision": None}
    recs[a_slots[0]] = ("api_error", err, {"settled_usd": 0.005, "conservative_usd": 0.005, "unresolved": True})
    assert SCORE.decide(freeze, gold, recs, v0=False)["verdict"] == "INCONCLUSIVE"  # 1 > 5% of 18 slots
    recs[a_slots[1]] = (None, None, None)
    assert SCORE.decide(freeze, gold, recs, v0=False)["verdict"] == "INCOMPLETE"
    bad = _syn(fa=_fa(), tools=tuple(DEMAND), as_of="2026-08-17T00:00:00Z")
    recs[b_slots[0]] = ("saved", bad, recs[b_slots[0]][2])
    out = SCORE.decide(freeze, gold, recs, v0=False)
    assert out["verdict"] == "B FAILS" and out["arms"]["B"]["violations"]["C2"] == 1


def test_the_interval_is_paired_clustered_and_reproducible():
    same = {f"H{i}": (2, 2, 3) for i in range(10)}
    assert SCORE.bootstrap(same) == {**SCORE.bootstrap(same), "low": 0.0, "high": 0.0}
    mixed = {f"H{i}": (i % 2, 3, 3) for i in range(10)}
    first = SCORE.bootstrap(mixed)
    assert first == SCORE.bootstrap(mixed) and 0 < first["low"] <= first["high"] < 1
    assert SCORE.bootstrap({"H": (0, 3, 3)})["low"] == 1.0


# ------------------------------------------------------------------------------------------------ the whole harness
def _script(freeze: dict[str, Any], path: Path) -> dict[str, Any]:
    """SYNTHETIC responses for every frozen slot: sent back by default, with scripted API errors and truncation."""
    by_arm = {a: [s["case"] for s in freeze["slots"] if s["arm"] == a and s["set"] != "control"] for a in ("A", "B")}
    script: dict[str, Any] = {"default": {a: {"response": _resp(SENT_BACK[a])} for a in ("A", "B")}}
    script[by_arm["A"][3]] = {"raise": {"status_code": 400, "message": "scripted 400"}}
    script[by_arm["B"][5]] = {"raise": {"status_code": 500, "message": "scripted 500"}}
    script[by_arm["B"][7]] = {"raise": {"status_code": None, "message": "scripted timeout"}}
    script[by_arm["B"][9]] = {"response": _resp(SENT_BACK["B"], status="incomplete", text='{"intent": nul')}
    path.write_text(json.dumps(script))
    return script


@needs_freeze
def test_the_complete_harness_runs_all_322_frozen_slots_offline(tmp_path, monkeypatch):
    """Every frozen slot through run_eval.run and run_route.main (in process, under each slot's own environment) with
    the scripted transport and the scratch ledger; then scored."""
    script_p = tmp_path / "script.json"
    _script(FREEZE, script_p)
    base = {**os.environ, "CMP_ROUTE_FAKE": str(script_p)}
    for k in ROUTE.PLAN_SETTINGS:
        base.pop(k, None)

    def launch(slot: dict[str, Any], env: dict[str, str], live: Path, label: str) -> tuple[int, str]:
        out = io.StringIO()
        argv = ["run_route.py", "--slot", str(slot["slot"]), "--label", label, "--out", str(live / label)]
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(sys, "argv", argv), \
                contextlib.redirect_stdout(out):
            rc = ROUTE.main()
        return rc, out.getvalue()

    log: list[dict[str, Any]] = []
    end = RUN.run(FREEZE, [], lambda **kw: log.append(kw), approved=FREEZE["run_cap_usd"], launch=launch,
                  live=tmp_path, base_env=base)
    assert end["result"] == "complete" and end["terminal"] == 322, end
    assert end["outcomes"] == {"api_error": 3, "saved": 319}
    r = end["reconciliation"]
    assert r["reconciles"] and r["unresolved_slots"] == 3 and r["observed_slots"] == 319
    assert r["conservative_usd"] <= FREEZE["run_cap_usd"]
    ledger = [json.loads(ln) for ln in budget.ledger_path().read_text().splitlines()]
    reserves = [e["usd"] for e in ledger if e["kind"] == "reserve"]
    assert reserves == [s["reservation_usd"] for s in FREEZE["slots"]]  # the frozen bounds, reserved exactly
    recs = SCORE.records(FREEZE, log, tmp_path)
    out = SCORE.decide(FREEZE, GOLD, recs, v0=False)
    assert out["verdict"] == "NOT MET" and not out["arms"]["B"]["violation_slots"]
    assert out["arms"]["B"]["incomplete"]["count"] + out["arms"]["A"]["incomplete"]["count"] <= 1
    assert out["arms"]["B"]["controls_safe"] == "18 of 18"


@needs_freeze
def test_a_slot_process_runs_with_its_own_environment_and_caps(tmp_path):
    script_p = tmp_path / "script.json"
    _script(FREEZE, script_p)
    env = {**{k: v for k, v in os.environ.items() if k not in ROUTE.PLAN_SETTINGS}, "CMP_ROUTE_FAKE": str(script_p)}
    for s in FREEZE["slots"][:2]:
        cap = round(budget.spent() + s["reservation_usd"] + 1e-6, 6)
        rc, _ = RUN.launch(s, RUN.env_for(FREEZE, s, cap, env), tmp_path, "P")
        rec = json.loads((tmp_path / "P" / f"{s['case']}.json").read_text())
        assert rc == 0 and rec["arm"] == s["arm"] and rec["route_contract"] == {"A": "v15", "B": "v16"}[s["arm"]]
        assert rec["slot"] == s["slot"] and rec["score"]["model_calls"] in (0, 1)
