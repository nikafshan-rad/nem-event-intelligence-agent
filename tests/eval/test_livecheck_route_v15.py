"""The routing-only Live check of route contract v15 (eval/livecheck_route_v15/PROTOCOL.md), offline. Covered:
- its configurations and gold (reproducible from the writer's output, cross-checked with frozen verified sources);
- its plan and caps (each configuration's reservation measured on its actual routing request);
- its per-call runner through the SYNTHETIC fake transport: one routing call, no dispatcher, tool or synthesis, and a
  complete record;
- every scoring branch, eligibility assessment and the verdict's precedence;
- its runner loop: the start guard, stops, interruption accounting and refusals.

Nothing here calls a model:
- the routing decisions given to the fake transport are SYNTHETIC, written as a careful reader following prompts v16
  would answer, or deliberately altered;
- the runner's processes, ledger and records are injected, and the ledger is a scratch one (tests/conftest.py).

Two outcomes are known before any run, from the deterministic code alone (PROTOCOL.md, "Known before the run"). A
correct reading of N04 resolves with a weather part wrongly claimed as unanswered, which is a violation; N07 is sent
back because its period ends at "noon".
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
DIR = ROOT / "eval" / "livecheck_route_v15"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"lcr15_{name}", DIR / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CFG = _load("configs")
GOLDMOD = _load("gold")
ROUTE = _load("run_route")
RUN = _load("run_eval")
SCORE = _load("score")
FRZ = _load("freeze")
CASES = {c["config"]: c for c in json.loads((DIR / "cases.json").read_text())["cases"]}
GOLD = {g["config"]: g for g in json.loads((DIR / "GOLD.json").read_text())["cases"]}
FREEZE = json.loads((DIR / "FREEZE.json").read_text()) if (DIR / "FREEZE.json").exists() else None
NO_RUN = {"selection": "none", "selection_text": None, "half_hour_text": None}
NO_MAX = {"kind": "none", "measure": None, "measure_text": None, "peak_text": None, "window": None, "window_text": None}
DEMAND = {"get_forecast_runs", "compare_forecast_actual"}


def _dec(intent: str | None, region: str | None, event_date: str | None, fc: dict | None = None,
         run: dict | None = None, mx: dict | None = None, as_of_text: str | None = None, **core: Any) -> dict[str, Any]:
    """A SYNTHETIC v15 routing decision."""
    return {"intent": intent, "region": region, "event_date": event_date, "as_of_text": as_of_text,
            "needs_clarification": False, "clarification_reason": None, "clarification": None, "out_of_scope": False,
            **core, "requested": {"forecast_run": {**NO_RUN, **(run or {})}, "maximum": {**NO_MAX, **(mx or {})},
                                  "forecast": fc}}


def _fc(domain: str, request_text: str | None, op: str = "none", op_text: str | None = None, scope: str | None = None,
        scope_text: str | None = None, unsupported_text: str | None = None) -> dict[str, Any]:
    return {"operation": op, "operation_text": op_text, "scope": scope, "scope_text": scope_text, "domain": domain,
            "request_text": request_text, "unsupported_text": unsupported_text}


CAREFUL = {  # SYNTHETIC: how a careful reader following prompts v16 would answer each configuration
    "D01": _dec("forecast_review", "TAS1", "2026-07-31", _fc(
        "operational_demand", "Take the forecast run issued at 2026-07-30T18:56:59Z. For Tasmania's half-hour ending at "
        "8:00 am AEST, 31 July 2026, which POE10, POE50 and POE90 operational demand values did it give, and how much "
        "operational demand was actually recorded in that half-hour", "single_interval_comparison",
        "how much operational demand was actually recorded", "half_hour", "half-hour ending at 8:00 am AEST, 31 July 2026"),
        run={"selection": "issued_at", "selection_text": "the forecast run issued at 2026-07-30T18:56:59Z",
             "half_hour_text": "half-hour ending at 8:00 am AEST, 31 July 2026"}),
    "D02": _dec("forecast_review", "SA1", "2026-08-20", _fc(
        "operational_demand", "Taking South Australia's 7:30-8:00 am half-hour (Adelaide time, ACST) on 20 August 2026: "
        "what POE10, POE50 and POE90 operational demand values were in the final forecast run issued ahead of it, and "
        "what operational demand was actually measured", "single_interval_comparison",
        "what operational demand was actually measured", "half_hour",
        "7:30-8:00 am half-hour (Adelaide time, ACST) on 20 August 2026"),
        run={"selection": "last_issued_before", "selection_text": "the final forecast run issued ahead of it",
             "half_hour_text": "7:30-8:00 am half-hour (Adelaide time, ACST) on 20 August 2026"}),
    "D03": _dec("forecast_review", "NSW1", "2026-07-31", _fc(
        "operational_demand", "How accurate were the operational demand forecasts for NSW1 on 31 July 2026",
        "window_comparison", "How accurate were the operational demand forecasts", "whole_local_day", "on 31 July 2026")),
    "D04": _dec("forecast_review", "SA1", "2026-07-31", _fc(
        "operational_demand", "How did the operational demand forecasts compare with actual demand in SA1 between 18:00 "
        "and 21:00 ACST on 31 July 2026", "window_comparison",
        "How did the operational demand forecasts compare with actual demand", "explicit",
        "between 18:00 and 21:00 ACST on 31 July 2026")),
    "D05": _dec("forecast_review", "VIC1", "2026-08-20", _fc(
        "operational_demand", "what was the newest Victorian operational demand forecast for the 23:00 to 23:30 UTC "
        "half-hour, at POE10, POE50 and POE90", "forecast_value",
        "what was the newest Victorian operational demand forecast", "half_hour", "the 23:00 to 23:30 UTC half-hour"),
        run={"selection": "as_of_availability", "selection_text": "the newest Victorian operational demand forecast",
             "half_hour_text": "the 23:00 to 23:30 UTC half-hour"}, as_of_text="As of 2026-08-19T20:00:00Z"),
    "D06": _dec("forecast_review", "VIC1", "2026-08-20", _fc(
        "operational_demand", "what did the latest available AEMO forecast expect Victorian operational demand to be for "
        "the half-hour ending 2026-08-19T23:30:00Z", "forecast_value",
        "what did the latest available AEMO forecast expect Victorian operational demand to be", "half_hour",
        "half-hour ending 2026-08-19T23:30:00Z", "was cold weather expected to push demand up that morning"),
        run={"selection": "as_of_availability", "selection_text": "the latest available AEMO forecast",
             "half_hour_text": "half-hour ending 2026-08-19T23:30:00Z"}, as_of_text="As of 2026-08-19T21:00:00Z"),
    "D07": _dec("forecast_review", "SA1", "2026-07-29", _fc(
        "operational_demand", "For South Australia's half-hour closing 2026-07-29T08:00:00Z, what POE50 operational "
        "demand did AEMO's newest forecast run show as of 2026-07-29T05:00:00Z", "forecast_value",
        "what POE50 operational demand did AEMO's newest forecast run show", "half_hour",
        "half-hour closing 2026-07-29T08:00:00Z", "what temperature was then expected for Adelaide at that time"),
        run={"selection": "as_of_availability", "selection_text": "AEMO's newest forecast run",
             "half_hour_text": "half-hour closing 2026-07-29T08:00:00Z"}, as_of_text="as of 2026-07-29T05:00:00Z"),
    "D08": _dec("forecast_review", "SA1", "2026-07-31", _fc(
        "operational_demand", "what did the latest issued forecast say for the SA1 peak half-hour on 2026-07-31",
        "forecast_value", "what did the latest issued forecast say", "event_peak_half_hour",
        "the SA1 peak half-hour on 2026-07-31"),
        run={"selection": "as_of_availability", "selection_text": "the latest issued forecast", "half_hour_text": None},
        as_of_text="As of 2026-07-30T14:35:00Z"),
    "D09": _dec("forecast_review", "SA1", "2026-07-31", _fc(
        "weather", "What was the weather forecast for Adelaide on 31 July 2026", "forecast_value")),
    "D10": _dec("market_event_review", "QLD1", "2025-10-05", _fc("none", None),
                mx={"kind": "maximum", "measure": "operational_demand", "measure_text": "operational demand",
                    "peak_text": "highest", "window": "whole_local_day", "window_text": "that entire local day"},
                as_of_text="Based only on data published by noon Brisbane time on Sunday 5 October 2025"),
    "N01": _dec("forecast_review", "QLD1", "2026-08-13", _fc(
        "weather", "What maximum temperature was forecast for the city on 13 August 2026", "forecast_value")),
    "N02": _dec("forecast_review", "SA1", "2026-07-29", _fc(
        "price", "Could you pull AEMO's predispatch price forecasts for South Australia", "forecast_value")),
    "N03": _dec("forecast_review", "NSW1", "2026-08-10", _fc(
        "unclear", "How far off were the forecasts on the day, compared with what actually happened",
        "window_comparison", "How far off were the forecasts on the day, compared with what actually happened")),
    "N04": _dec("forecast_review", "VIC1", "2026-08-17", _fc(
        "operational_demand", "For Victoria, I want AEMO's operational demand forecast values for a single half-hour on "
        "17 August 2026: the one ending at 18:30 AEST. What did they show", "forecast_value",
        "I want AEMO's operational demand forecast values", "half_hour",
        "a single half-hour on 17 August 2026: the one ending at 18:30 AEST")),
    "N05": _dec("forecast_review", "TAS1", "2026-08-02", _fc(
        "weather", "What did the weather forecasters expect for Hobart on 2 August 2026, particularly wind and rain",
        "forecast_value")),
    "N06": _dec("forecast_review", "SA1", "2026-08-14", _fc(
        "weather", "What minimum temperature had been forecast for Adelaide on 14 August 2026", "forecast_value")),
    "N07": _dec("forecast_review", "QLD1", "2026-08-04", _fc(
        "operational_demand", "How did AEMO's operational demand forecast for Queensland compare with actual "
        "operational demand between 06:00 and noon AEST on 4 August 2026", "window_comparison",
        "How did AEMO's operational demand forecast for Queensland compare with actual operational demand", "explicit",
        "between 06:00 and noon AEST on 4 August 2026")),
}
RESOLVED, CONTAINED = "correct resolved request", "correct clarification or unsupported handling"
EXPECTED = {**{c: RESOLVED for c in ("D01", "D02", "D03", "D04", "D05", "D06", "D07", "D08", "D10")},
            **{c: CONTAINED for c in ("D09", "N01", "N02", "N03", "N05", "N06")},
            "N04": "violation", "N07": "unnecessary clarification"}  # N04 and N07: known before the run


def _fake(decision: dict[str, Any] | None):
    from tests.provider.fake_model import FakeModel

    return FakeModel(decision or {}, [], lambda kw: {})


def _record(config: str, decision: dict[str, Any] | None = None, client: Any = None) -> dict[str, Any]:
    rec = ROUTE.route_call(CASES[config], client=client or _fake(decision or CAREFUL[config]), write_trace=False)
    rec["score"]["ledger_cost_usd"] = 0.0025
    return rec


def _careful_with(config: str, **fc: Any) -> dict[str, Any]:
    d = copy.deepcopy(CAREFUL[config])
    d["requested"]["forecast"].update(fc)
    return d


@pytest.fixture(scope="module")
def careful() -> dict[str, dict[str, Any]]:
    return {c: _record(c) for c in CAREFUL}


# ------------------------------------------------------------------------------------------------ cases and gold
def test_scope_is_17_configurations_and_34_calls_in_the_protocols_sets():
    data = json.loads((DIR / "cases.json").read_text())
    assert (data["configurations"], data["calls"]) == (17, 34) and all(c["repeats"] == 2 for c in CASES.values())
    assert CFG.SUPPLY == ["D01", "D02", "D03", "D04", "D05", "D06", "D07", "D10", "N04", "N07"]
    assert CFG.CONTAINMENT == ["D09", "N01", "N02", "N03", "N05", "N06"] and CFG.AMBIGUITY == ["D08"]
    assert CASES["D10"]["request"] == {"as_of_utc": "2025-10-05T02:00:00Z"}
    assert all(CASES[c]["request"] == {} for c in CASES if c != "D10")


def test_familiar_questions_are_copied_unchanged_and_fresh_ones_are_the_writers():
    for c in CFG.familiar_cases():
        assert CASES[c["config"]]["question"] == c["question"]
    for c, rel, cid, _quoted, *_ in CFG.FAMILIAR:
        if cid is not None:
            src = next(x for x in json.loads((ROOT / rel).read_text())["cases"] if x["case_id"] == cid)
            assert src["question"] == CASES[c]["question"]
    writer = {g["config"]: g for g in json.loads((DIR / "WRITER_OUTPUT.json").read_text())["cases"]}
    assert {c: CASES[c]["question"] for c in writer} == {c: g["question"] for c, g in writer.items()}
    assert hashlib.sha256((DIR / "WRITER_OUTPUT.json").read_bytes()).hexdigest().startswith("913b0883")


def test_the_gold_is_reproducible_from_the_writer_and_agrees_with_verified_sources():
    cases, gold, problems = GOLDMOD.build()
    assert problems == []
    assert cases == json.loads((DIR / "cases.json").read_text()) and gold == json.loads((DIR / "GOLD.json").read_text())
    for rel, want in gold["sources_sha256"].items():
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == want, rel
    assert GOLDMOD.cross_check(GOLD) == []
    assert GOLD["D08"]["resolved_reading"] == "operational_demand_forecast" and GOLD["D08"]["domain"] == "unclear"
    assert GOLD["D10"]["resolved_reading"] == "demand_maximum"
    assert all(GOLD[c]["resolved_reading"] is None for c in CFG.CONTAINMENT)


@pytest.mark.parametrize("edit,problem", [
    (lambda g: g["scope"].update(half_hours=2), "half-hours, but the bounds hold"),
    (lambda g: g["request_anchors"].append("words not in it"), "is not copied exactly"),
    (lambda g: g["scope"].update(start_utc="2026-07-30T21:45:00Z"), "not whole half-hours"),
    (lambda g: g["acceptable_outcomes"].append("clarify_unsupported"), "are not the set's"),
    (lambda g: g.update(outcome="clarify_mixed"), "is not listed first"),
])
def test_the_gold_checks_catch_mechanical_and_set_errors(edit, problem):
    g = copy.deepcopy(GOLD["D01"])
    edit(g)
    found = GOLDMOD.check_record(g, CASES["D01"]["question"], {}) + GOLDMOD.set_findings(g)
    assert any(problem in f for f in found), found


def test_a_containment_gold_may_narrow_its_outcomes_but_never_widen_them():
    g = copy.deepcopy(GOLD["N03"])
    assert GOLDMOD.set_findings(g) == []
    g["acceptable_outcomes"] = ["clarify_which_forecast", "resolved"]
    assert GOLDMOD.set_findings(g)


# ------------------------------------------------------------------------------------------------ plan and caps
def test_the_plan_runs_34_calls_in_two_rounds_of_all_17():
    slots = FRZ.plan(random.Random(7))
    assert len(slots) == 34 and [s["slot"] for s in slots] == list(range(1, 35))
    for r in (1, 2):
        assert sorted(s["config"] for s in slots if s["round"] == r) == sorted(CASES)
    assert all(s["case"] == s["record"] == f"{s['slot']:02d}-{s['config']}" for s in slots)


def test_each_actual_routing_request_fits_the_call_cap_and_measuring_writes_no_ledger():
    from nem_agent import budget

    p = budget.ledger_path()
    before = p.read_bytes() if p.exists() else b""
    res = FRZ.reservations(list(CASES.values()))
    assert set(res) == set(CASES) and max(res.values()) <= FRZ.CALL_CAP and min(res.values()) > 0.005
    assert (p.read_bytes() if p.exists() else b"") == before  # captured, never reserved in a ledger
    assert round(34 * FRZ.CALL_CAP, 6) == 0.204 and round(9.227365 + 0.204, 6) == 9.431365
    assert FRZ.LEDGER_START == (9.227365, 3158, "4250ef88a8ad3d35")


# ------------------------------------------------------------------------------------------------ the per-call runner
@pytest.mark.parametrize("config", sorted(CAREFUL))
def test_each_configuration_routes_once_with_a_complete_record_and_is_classed(config, monkeypatch):
    """SYNTHETIC careful readings through the real per-call runner and the scorer: one routing call, and no
    dispatcher, tool, calculation or synthesis."""
    import nem_agent.agent.dispatcher as dispatcher
    import nem_agent.agent.live as live

    def forbidden(*a: Any, **k: Any) -> None:
        raise AssertionError("only routing and resolution may run")
    monkeypatch.setattr(dispatcher.Dispatcher, "__init__", forbidden)
    monkeypatch.setattr(live.LiveController, "run", forbidden)
    fake = _fake(CAREFUL[config])
    rec = _record(config, client=fake)
    assert len(fake.requests) == 1 and fake.requests[0]["text"]["format"]["name"] == "RouteDecision"
    assert rec["score"]["model_calls"] == 1 and rec["route_contract"] == "v15" and not rec["score"]["case_note_files_written"]
    assert SCORE.unassessable(rec) is None  # export completeness
    c = SCORE.classify(rec, GOLD[config])
    assert c["class"] == EXPECTED[config], c


def test_known_before_the_run_n04_and_n07_follow_from_the_code_not_the_model(careful):
    """With correct readings, N04 resolves exactly as the gold says but is noted as also asking for a weather forecast
    it declines ("Leave the weather forecast out" is not read as a negation); N07 is sent back because the code does not
    read "noon". These are outcomes of the merged code, recorded before any run; the questions are not changed."""
    n04 = careful["N04"]["resolution"]
    fa = n04["requests"]["forecast"]
    assert (n04["status"], fa["status"], fa["operation"], fa["target_utc"]) == (
        "ok", "bound", "forecast_value", ["2026-08-17T08:00:00Z", "2026-08-17T08:30:00Z"])
    assert fa["unsupported"] == ["weather"] and n04["requests"]["notes"][0].startswith("Not answered:")
    assert any("wrongly claimed" in v for v in SCORE.classify(careful["N04"], GOLD["N04"])["violations"])
    n07 = careful["N07"]["resolution"]
    assert n07["status"] == "needs_clarification" and n07["requests"]["forecast"]["missing"] == ["scope"]


def test_the_records_carry_every_reading_the_report_needs(careful):
    rec = careful["D06"]
    assert rec["route"]["requested"]["forecast"]["unsupported_text"] == CAREFUL["D06"]["requested"]["forecast"][
        "unsupported_text"]
    fa = rec["resolution"]["requests"]["forecast"]
    assert fa["provenance"]["domain"]["source"] == "route_model" and fa["unsupported"] == ["other"]
    m = SCORE.model_reading(rec, GOLD["D06"])
    assert m["domain_matches_gold"] and m["operation_matches_gold"] and m["request_text_on_the_request"]


# ------------------------------------------------------------------------------------------------ eligibility
def test_tool_eligibility_is_what_live_would_offer(careful):
    assert set(careful["D03"]["tools_offered"]) >= DEMAND  # a resolved forecast review
    assert careful["D09"]["tools_offered"] == []  # sent back: nothing runs
    ev = _record("D09", _dec("market_event_review", "SA1", "2026-07-31", _fc(
        "weather", "What was the weather forecast for Adelaide on 31 July 2026")))
    assert ev["resolution"]["status"] == "ok" and not DEMAND & set(ev["tools_offered"])
    assert "get_weather_context" in ev["tools_offered"]
    c = SCORE.classify(ev, GOLD["D09"])
    assert (c["class"], c["outcome"]) == (CONTAINED, "event_review_unsupported")


# ------------------------------------------------------------------------------------------------ scoring branches
def _violations(rec: dict[str, Any], config: str) -> list[str]:
    c = SCORE.classify(rec, GOLD[config])
    assert c["class"] == "violation", c
    return c["violations"]


def test_a_wrong_binding_fails_whatever_the_status(careful):
    rec = copy.deepcopy(careful["D03"])
    rec["resolution"]["requests"]["forecast"]["window_utc"] = ["2026-07-30T14:00:00Z", "2026-07-31T02:00:00Z"]
    assert any("scope" in v for v in _violations(rec, "D03"))
    rec["resolution"]["status"] = "needs_clarification"  # a bound request is assessed even when sent back
    assert any("scope" in v for v in _violations(rec, "D03"))
    rec = copy.deepcopy(careful["D01"])
    rec["resolution"]["region"] = "VIC1"
    assert any("region" in v for v in _violations(rec, "D01"))


def test_a_dropped_cutoff_fails(careful):
    rec = copy.deepcopy(careful["D05"])
    rec["resolution"]["as_of_utc"] = None
    assert any(v.startswith("dropped cutoff") for v in _violations(rec, "D05"))


def test_demand_forecast_tools_left_available_for_another_kind_fail(careful):
    rec = copy.deepcopy(careful["D09"])
    rec["resolution"].update(status="ok", intent="market_event_review")
    rec["tools_offered"] = ["find_market_events", "compare_forecast_actual"]
    assert any(v.startswith("incorrect tool eligibility") for v in _violations(rec, "D09"))


def test_a_demand_question_proceeding_without_its_request_is_a_missed_request():
    rec = _record("D03", _dec("market_event_review", "NSW1", "2026-07-31", _fc(
        "operational_demand", "How accurate were the operational demand forecasts for NSW1 on 31 July 2026")))
    assert any(v.startswith("missed request") for v in _violations(rec, "D03"))


def test_an_omitted_unsupported_part_fails():
    """The model omits H06's weather expectation, which the parser cannot read: the question is answered as if whole."""
    rec = _record("D06", _careful_with("D06", unsupported_text=None))
    assert any(v.startswith("omitted unsupported part") for v in _violations(rec, "D06"))


def test_an_unsupported_part_on_the_wrong_words_fails():
    rec = _record("D06", _careful_with("D06", unsupported_text="As of 2026-08-19T21:00:00Z"))
    assert any("not the part the question asks for" in v for v in _violations(rec, "D06"))


def test_a_demand_reading_of_the_genuinely_ambiguous_question_fails():
    """A misreading the code cannot detect (D29): the clause holds the date and names no other kind, so it is bound;
    the scorer fails it against the gold. With the date outside the clause, the code itself sends it back."""
    q = CASES["N03"]["question"].rstrip("?")
    rec = _record("N03", _careful_with("N03", domain="operational_demand", request_text=q, scope="whole_local_day",
                                       scope_text="10 August 2026"))
    assert rec["resolution"]["requests"]["forecast"]["status"] == "bound"
    assert any("where the gold has none" in v for v in _violations(rec, "N03"))
    caught = _record("N03", _careful_with("N03", domain="operational_demand", scope="whole_local_day",
                                          scope_text="10 August 2026"))
    assert SCORE.classify(caught, GOLD["N03"])["outcome"] == "clarify_which_forecast"


def test_d08_accepts_its_two_pre_registered_outcomes_and_nothing_relaxed(careful):
    assert SCORE.classify(careful["D08"], GOLD["D08"])["class"] == RESOLVED
    clar = _record("D08", _careful_with("D08", domain="unclear"))
    assert SCORE.classify(clar, GOLD["D08"])["class"] == CONTAINED
    wrong = copy.deepcopy(careful["D08"])
    wrong["resolution"]["requests"]["forecast"]["target_utc"] = ["2026-07-30T17:00:00Z", "2026-07-30T17:30:00Z"]
    assert any("scope" in v for v in _violations(wrong, "D08"))


def test_d10_is_a_maximum_and_claims_no_forecast(careful):
    rec = copy.deepcopy(careful["D10"])
    rec["resolution"]["requests"]["maximum"]["window_utc"] = ["2025-10-04T14:00:00Z", "2025-10-05T02:00:00Z"]
    assert any("maximum" in v for v in _violations(rec, "D10"))
    rec = copy.deepcopy(careful["D10"])
    rec["resolution"]["requests"]["notes"].append("Not answered: the question also asks about a weather forecast.")
    assert any("wrongly claimed" in v for v in _violations(rec, "D10"))


def test_refusal_and_another_kinds_clarification_are_containment():
    refused = _record("N02", {**CAREFUL["N02"], "out_of_scope": True, "clarification": "Price forecasts are out of scope."})
    assert SCORE.classify(refused, GOLD["N02"])["outcome"] == "refusal"
    assert SCORE.classify(refused, GOLD["N02"])["class"] == CONTAINED


def test_an_unacceptable_send_back_of_a_containment_case_is_contained_for_another_reason():
    rec = _record("N03", _careful_with("N03", domain="weather"))  # an ambiguous question read as weather
    c = SCORE.classify(rec, GOLD["N03"])
    assert (c["class"], c["outcome"]) == ("contained for another reason", "clarify_unsupported")


def test_a_supply_question_sent_back_is_an_unnecessary_clarification():
    rec = _record("D03", {**CAREFUL["D03"], "needs_clarification": True, "clarification_reason": "unclear_question",
                          "clarification": "Which forecasts?"})
    assert SCORE.classify(rec, GOLD["D03"])["class"] == "unnecessary clarification"


def test_an_incomplete_response_is_an_extraction_miss_never_containment():
    """SYNTHETIC: valid JSON, then whitespace to the 2,000-token cap."""
    from tests.provider.fake_model import FakeModel

    class Truncated(FakeModel):
        def create(self, **kw: Any) -> dict[str, Any]:
            self.requests.append(kw)
            return {"id": "resp_x", "status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
                    "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text",
                                "text": '{"intent":"forecast_review","region":"SA1"' + " \r" * 500}]}],
                    "usage": {"input_tokens": 3000, "output_tokens": 2000,
                              "output_tokens_details": {"reasoning_tokens": 900}}}

    rec = _record("D09", client=Truncated({}, [], lambda kw: {}))
    assert rec["route_invalid"] and rec["incomplete_diagnostics"]["cause"]
    c = SCORE.classify(rec, GOLD["D09"])
    assert c["class"] == "incomplete or invalid" and c["violations"] == []


def test_a_record_missing_a_needed_field_is_unassessable(careful):
    rec = copy.deepcopy(careful["D03"])
    del rec["resolution"]["requests"]["ineligible_tools"]
    assert SCORE.classify(rec, GOLD["D03"])["class"] == "unassessable"
    assert SCORE.classify(None, GOLD["D03"])["class"] == "unassessable"


# ------------------------------------------------------------------------------------------------ the verdict
def _as_gold_says(careful: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """SYNTHETIC: the careful records, with N04 and N07 as the gold says they should resolve (to test the verdict's
    branches; the merged code does not produce these two)."""
    out = dict(careful)
    n04 = copy.deepcopy(careful["N04"])
    n04["resolution"]["requests"]["forecast"]["unsupported"] = []
    n04["resolution"]["requests"]["notes"] = []
    n07 = copy.deepcopy(careful["D04"])
    g = GOLD["N07"]
    n07["question"] = CASES["N07"]["question"]
    n07["resolution"].update(region="QLD1")
    fa = n07["resolution"]["requests"]["forecast"]
    fa.update(window_utc=[g["scope"]["start_utc"], g["scope"]["end_utc"]], half_hours=12,
              provenance={"domain": {"source": "route_model", "text": "AEMO's operational demand forecast for Queensland",
                                     "conversion": ""}})
    out.update(N04=n04, N07=n07)
    return out


def _plan(records: dict[str, dict[str, Any]], override: dict[int, Any] | None = None):
    freeze = {"slots": FRZ.plan(random.Random(3)), "label": "x"}
    recs = {s["slot"]: records[s["config"]] for s in freeze["slots"]}
    recs.update(override or {})
    return freeze, recs


def _slots(freeze: dict[str, Any], config: str) -> list[int]:
    return [s["slot"] for s in freeze["slots"] if s["config"] == config]


def test_with_the_merged_code_correct_readings_fail_on_n04(careful):
    """Known before the run: careful readings of every question give FAIL, from N04 alone."""
    d = SCORE.decide(*_plan(careful))
    assert d["verdict"] == "FAIL" and all("(N04)" in v for v in d["violations"])
    assert d["supply"]["each_config"]["N07"] == 0 and not d["supply"]["met"]


def test_the_verdict_passes_only_with_supply_and_demonstrated_containment(careful):
    d = SCORE.decide(*_plan(_as_gold_says(careful)))
    assert d["verdict"] == "PASS" and d["verdict_of"] == SCORE.VERDICT_NAME
    assert d["supply"]["total"] == 20 and d["supply"]["of"] == 20 and "D08" not in d["supply"]["each_config"]
    assert d["ambiguity"]["D08"] and set(d["familiar"]) | set(d["fresh"]) == set(CASES)
    assert "no H1–H5 answer review" in d["not_claimed"] and "answers" in d["not_claimed"]


def test_verdict_precedence_and_bars(careful):
    good = _as_gold_says(careful)
    freeze, recs = _plan(good)
    wrong = copy.deepcopy(good["D03"])
    wrong["resolution"]["requests"]["forecast"]["half_hours"] = 47
    d03, d01 = _slots(freeze, "D03"), _slots(freeze, "D01")
    # a violation fails, even with a call missing
    d = SCORE.decide(freeze, {**recs, d03[0]: wrong, d01[0]: None})
    assert d["verdict"] == "FAIL" and d["coverage"]["unassessable_slots"] == [d01[0]]
    assert SCORE.decide(freeze, {**recs, d01[0]: None})["verdict"] == "INCOMPLETE"
    sent_back = copy.deepcopy(good["D03"])
    sent_back["resolution"]["status"] = "needs_clarification"
    sent_back["tools_offered"] = []
    # one configuration never supplied: INCONCLUSIVE, whatever the total
    d = SCORE.decide(freeze, {**recs, **{n: sent_back for n in d03}})
    assert d["verdict"] == "INCONCLUSIVE" and d["supply"]["total"] == 18 and not d["supply"]["met"]
    # four supply calls sent back, each configuration still supplied once: 16 of 20 is below 17
    misses = {_slots(freeze, c)[0]: {**copy.deepcopy(good[c]), "resolution": {**good[c]["resolution"],
                                                                             "status": "needs_clarification"},
                                     "tools_offered": []}
              for c in ("D01", "D02", "D04", "D05")}
    d = SCORE.decide(freeze, {**recs, **misses})
    assert (d["verdict"], d["supply"]["total"]) == ("INCONCLUSIVE", 16)
    three = dict(list(misses.items())[:3])
    assert SCORE.decide(freeze, {**recs, **three})["verdict"] == "PASS"  # 17 of 20


def test_containment_shown_only_by_rejected_responses_cannot_pass(careful):
    good = _as_gold_says(careful)
    freeze, recs = _plan(good)
    rejected = copy.deepcopy(good["N05"])
    rejected.update(route_invalid=True, route_call={**rejected["route_call"], "status": "incomplete"})
    d = SCORE.decide(freeze, {**recs, **{n: rejected for n in _slots(freeze, "N05")}})
    assert d["verdict"] == "INCONCLUSIVE" and d["containment"]["undemonstrated"] == ["N05"]
    assert len(d["extraction_misses"]) == 2


def test_d08_outcomes_are_reported_apart_and_never_in_the_supply_totals(careful):
    good = _as_gold_says(careful)
    freeze, recs = _plan(good)
    clar = _record("D08", _careful_with("D08", domain="unclear"))
    d = SCORE.decide(freeze, {**recs, **{n: clar for n in _slots(freeze, "D08")}})
    assert d["verdict"] == "PASS" and [r["outcome"] for r in d["ambiguity"]["D08"]] == ["clarify_which_forecast"] * 2


# ------------------------------------------------------------------------------------------------ the runner loop
def _freeze(**over: Any) -> dict[str, Any]:
    slots = FRZ.plan(random.Random(5))
    src = subprocess.run(["git", "rev-parse", "HEAD:src"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return {"slots": slots, "runs": {"RT": {"cases": 34, "case_cap_usd": 0.006, "run_cap_usd": 0.204}},
            "model": "gpt-5-mini", "label": "LC-route-v15-run", "required_task_cap_usd": 9.431365,
            "ledger_start_usd": 9.227365, "ledger_lines": 3158, "ledger_sha256_prefix": "4250ef88a8ad3d35",
            "prompt_version": "prompts/v16", "route_contract": "v15", "files_sha256": {}, "src_tree": src,
            "code_commit": "x", **over}


class Ledger:
    def __init__(self, start: float = 9.227365):
        self.total = start

    def __call__(self) -> float:
        return round(self.total, 6)


def _loop(freeze, events=None, *, costs=None, outcomes=None, records=None, ledger=None, task_cap=9.431365, live=None):
    ledger = ledger or Ledger()
    log, envs = list(events or []), []

    def write(**kw):
        log.append(kw)

    def launch(slot, env, live_, label):
        envs.append((slot["case"], env))
        ledger.total += (costs or {}).get(slot["slot"], 0.0025)
        return 0, ""

    def finish(slot, rc, text, live_, label):
        return (outcomes or {}).get(slot["slot"], "saved"), (records or {}).get(slot["slot"], {"score": {}})

    end = RUN.run(freeze, list(events or []), write, task_cap=task_cap, launch=launch, finish=finish, spent=ledger,
                  **({"live": live} if live is not None else {}))
    return end, log, envs


def test_a_complete_run_makes_34_calls_with_the_frozen_model_and_caps():
    end, _, envs = _loop(_freeze())
    assert end["result"] == "complete" and end["saved"] == 34 and len(envs) == 34
    env = envs[0][1]
    assert env["NEM_AGENT_MODEL"] == "gpt-5-mini" and float(env["NEM_AGENT_SESSION_BUDGET_USD"]) == 0.006
    assert float(env["NEM_AGENT_TOTAL_BUDGET_USD"]) == round(9.227365 + 0.006, 6)
    assert round(end["run_spend"]["RT"], 6) == round(34 * 0.0025, 6)


def test_a_stop_ends_the_run_and_nothing_is_retried():
    for result in ("budget_stop", "error", "missing"):
        end, _, envs = _loop(_freeze(), outcomes={4: result})
        assert end["result"] == "incomplete" and len(envs) == 4 and end["saved"] == 3
    end, _, envs = _loop(_freeze(), records={2: {"score": {"case_note_files_written": 1}}})
    assert end["safety_stop"] and len(envs) == 2


def test_interrupted_attempts_stay_counted_and_may_exhaust_the_run_cap(tmp_path):
    """An interrupted call is re-run once, its cost counted against the run cap; no retry allowance is added."""
    f = _freeze()
    events = [{"event": "start", "attempt": 1},
              {"event": "slot_start", "slot": 1, "run": "RT", "case": f["slots"][0]["case"], "ledger_before": 9.227365}]
    end, log, envs = _loop(f, events, ledger=Ledger(9.231), live=tmp_path)
    kill = next(e for e in log if e.get("event") == "interrupted")
    assert kill["slot"] == 1 and kill["ledger_cost"] == round(9.231 - 9.227365, 6) and envs[0][0] == f["slots"][0]["case"]
    assert end["result"] == "complete" and round(end["run_spend"]["RT"], 6) == round(kill["ledger_cost"] + 34 * 0.0025, 6)
    heavy = events[:1] + [{"event": "interrupted", "slot": 1, "run": "RT", "ledger_cost": 0.2}] + events[1:]
    end2, _, envs2 = _loop(f, heavy, ledger=Ledger(9.43), live=tmp_path, task_cap=9.6)
    assert end2["result"] == "incomplete" and "start guard" in end2["stop_reason"] and envs2 == []
    twice = events + [{"event": "interrupted", "slot": 1, "run": "RT", "ledger_cost": 0.003}, {"event": "start",
                                                                                              "attempt": 2}, events[1]]
    end3, _, envs3 = _loop(f, twice, ledger=Ledger(9.233), live=tmp_path)
    assert end3["result"] == "incomplete" and "two interruptions" in end3["stop_reason"] and envs3 == []


def test_refusals(monkeypatch, tmp_path):
    f = _freeze()
    ok = {"total": 9.227365, "lines": 3158, "sha256_prefix": "4250ef88a8ad3d35"}
    monkeypatch.delenv("NEM_AGENT_BUDGET_LEDGER", raising=False)  # refusal() reads no ledger: it is given one
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-key")
    assert RUN.refusal(f, 9.431365, ok, [], tmp_path) is None
    assert "at least USD 9.431365" in RUN.refusal(f, 9.43, ok, [], tmp_path)
    assert "not the frozen starting ledger" in RUN.refusal(f, 9.431365, dict(ok, lines=3159), [], tmp_path)
    assert "prompt version" in RUN.refusal(dict(f, prompt_version="prompts/v15"), 9.431365, ok, [], tmp_path)
    assert "route contract" in RUN.refusal(dict(f, route_contract="v14"), 9.431365, ok, [], tmp_path)
    assert "plan" in RUN.refusal(dict(f, slots=f["slots"][:-1]), 9.431365, ok, [], tmp_path)
    monkeypatch.setenv("NEM_AGENT_MODEL", "gpt-6.1-sol")
    assert "override" in RUN.refusal(f, 9.431365, ok, [], tmp_path)
    monkeypatch.delenv("NEM_AGENT_MODEL")
    monkeypatch.delenv("OPENAI_API_KEY")
    assert "no API key" in RUN.refusal(f, 9.431365, ok, [], tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-key")
    (tmp_path / "LC-route-v15-run").mkdir()
    (tmp_path / "LC-route-v15-run" / "07-D03.json").write_text("{}")
    assert "does not account for" in RUN.refusal(f, 9.431365, ok, [], tmp_path)


# ------------------------------------------------------------------------------------------------ the freeze
@pytest.mark.skipif(FREEZE is None, reason="FREEZE.json not written yet")
def test_the_freeze_matches_the_protocol():
    assert FREEZE["code_commit"].startswith("d38eb4d") and FREEZE["prompt_version"] == "prompts/v16"
    assert FREEZE["route_contract"] == "v15" and FREEZE["model"] == "gpt-5-mini"
    assert FREEZE["route_max_output_tokens"] == 2000
    assert FREEZE["src_tree"] == subprocess.run(["git", "rev-parse", "d38eb4d:src"], cwd=ROOT, capture_output=True,
                                                text=True, check=True).stdout.strip()
    assert (FREEZE["ledger_start_usd"], FREEZE["ledger_lines"], FREEZE["ledger_sha256_prefix"]) == (
        9.227365, 3158, "4250ef88a8ad3d35")
    assert FREEZE["call_cap_usd"] == 0.006 and FREEZE["runs"]["RT"]["run_cap_usd"] == 0.204
    assert FREEZE["required_task_cap_usd"] == 9.431365
    assert set(FREEZE["reservations_usd"]) == set(CASES) and max(FREEZE["reservations_usd"].values()) <= 0.006
    assert FREEZE["slots"] == FRZ.plan(random.Random(FREEZE["order_seed"]))
    for rel, want in FREEZE["files_sha256"].items():
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == want, rel
    assert RUN.plan_mismatch(FREEZE) is None
    head = subprocess.run(["git", "rev-parse", "HEAD:src"], cwd=ROOT, capture_output=True, text=True,
                          check=True).stdout.strip()
    if head != FREEZE["src_tree"]:  # once src/ moves on, the frozen runner refuses to start
        assert RUN.changed(FREEZE) == "the checkout's src/ is not the frozen tree"
