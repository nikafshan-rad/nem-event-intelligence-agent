"""D37 amendment 1 (variant ``tool-turn-done/2``): the evidence limits given to synthesis and repair, and the status
lowered for shortfalls the tool records establish. SYNTHETIC fake model and scratch ledgers only (conftest).

What code enforces, and what stays an instruction to the model:

- code: the limits block (window and how it was given, each data tool's actual coverage, each tool's own caveats, gaps
  and failures); and an "answered" status lowered, with its reasons recorded, for a required tool without a result, a
  requested computed result not established or not verified, or, in a period the request explicitly asked for, a
  required tool that did not cover it or reports data absent within it. Nothing is raised; in a contextual window a
  narrower analysis or a gap in the data held is recorded, never a shortfall;
- instructions only (synthesis and repair): disclosing a limitation where it bears, keeping further investigation out of
  missing evidence, not reading missing evidence as evidence against an explanation, a stated basis for comparative
  words, and removing explanations that contradict the observations. The code does not check these.
"""

from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from nem_agent.agent import evidence_limits as el
from nem_agent.agent.live import EVIDENCE_LIMITS_HEADING, TOOL_TURN_DONE_ENV, TOOL_TURN_DONE_VARIANT
from nem_agent.agent.playbook import PLAYBOOKS
from nem_agent.agent.request import InvestigateRequest
from nem_agent.report import InvestigationReport, Versions
from nem_agent.service import investigate
from nem_agent.timeutil import iso_utc, parse_iso
from tests.provider.test_live_loop import _good_report, _required_turn, _w
from tests.provider.test_tool_turn_done import QUESTION, SYNTHESIS_LIMITS, Scripted, _kinds

pytestmark = pytest.mark.synthetic
EVENT_REVIEW = PLAYBOOKS["market_event_review"]


@pytest.fixture
def ev(selection):
    return selection.primary


def _answered(kw: dict[str, Any]) -> dict[str, Any]:
    return {**_good_report(kw), "status": "answered"}


def _run(fake: Scripted, on: bool, monkeypatch: pytest.MonkeyPatch, **fields: Any) -> Any:
    if on:
        monkeypatch.setenv(TOOL_TURN_DONE_ENV, "1")
    else:
        monkeypatch.delenv(TOOL_TURN_DONE_ENV, raising=False)
    return investigate(InvestigateRequest(question=QUESTION, mode="live", **fields), live_client=fake, write_trace=False)


def _limits(fake: Scripted) -> dict[str, Any]:
    synthesis = next(kw for kw, k in zip(fake.requests, _kinds(fake), strict=True) if k == "ModelReport")
    block = [it["content"] for it in synthesis["input"]
             if isinstance(it, dict) and str(it.get("content", "")).startswith(EVIDENCE_LIMITS_HEADING)]
    assert len(block) == 1
    return json.loads(block[0][len(EVIDENCE_LIMITS_HEADING):])


def _swap(turn: list[Any], name: str, **args: Any) -> list[Any]:
    return [(n, {**a, **args}) if n == name else (n, a) for n, a in turn]


# -- coverage: an intentional narrower analysis versus an incomplete requested period ---------------------------------
def test_a_narrower_analysis_around_the_event_is_recorded_not_a_shortfall(ev, monkeypatch):
    peak = parse_iso(ev.peak_interval_end_utc)
    start, end = max(parse_iso(ev.window_start_utc), peak - timedelta(hours=6)), peak + timedelta(hours=1)
    gen = [("get_generation_change", {**_w(ev), "start_utc": iso_utc(start), "end_utc": iso_utc(end), "top_n": 5,
                                      "as_of_utc": None})]
    fake = Scripted(ev, [_required_turn(ev), gen, "DONE"], report_fn=_answered)
    res = _run(fake, True, monkeypatch)
    limits = _limits(fake)
    assert limits["window"]["explicitly_requested"] is False and "event's window" in limits["window"]["source"]
    entry = next(c for c in limits["coverage"] if c["tool"] == "get_generation_change")
    assert entry["coverage"] == "part of the window, including the event's peak interval"
    assert entry["covered_utc"] == [[iso_utc(start), iso_utc(end)]] and entry["counts_for_status"] is False
    assert entry["max_hours_per_call"] == 12 and entry["hours_within_window"] == round((end - start).seconds / 3600, 2)
    assert {c["tool"]: c["coverage"] for c in limits["coverage"] if c["role"] == "required"} == {
        "find_market_events": "whole window", "get_price_timeline": "whole window", "get_actual_demand": "whole window"}
    assert limits["status_shortfalls"] == []
    assert res.report.status == "answered" and "status_lowered" not in res.report.validation


def test_incomplete_coverage_of_an_explicitly_requested_window_lowers_answered(ev, monkeypatch):
    window = {"window_start_utc": ev.window_start_utc, "window_end_utc": ev.window_end_utc}
    half = iso_utc(parse_iso(ev.window_start_utc) + timedelta(hours=12))
    turn = _swap(_required_turn(ev), "get_price_timeline", end_utc=half)
    on_fake = Scripted(ev, [turn, "DONE"], report_fn=_answered)
    on = _run(on_fake, True, monkeypatch, **window)
    limits = _limits(on_fake)
    assert limits["window"]["explicitly_requested"] is True and limits["window"]["source"] == "the window given with the request"
    entry = next(c for c in limits["coverage"] if c["tool"] == "get_price_timeline")
    assert entry["coverage"] == "part of the explicitly requested period: incomplete" and entry["counts_for_status"] is True
    assert [s["rule"] for s in limits["status_shortfalls"]] == ["requested_period_not_covered"]
    assert on.report.validation["final_passed"] is True
    assert on.report.status == "answered_with_caveats"
    lowered = on.report.validation["status_lowered"]
    assert (lowered["from"], lowered["to"], lowered["variant"]) == ("answered", "answered_with_caveats", TOOL_TURN_DONE_VARIANT)
    assert [s["tool"] for s in lowered["shortfalls"]] == ["get_price_timeline"]
    assert on.report.uncertainties[-1] == (el.STATUS_NOTE + "the price timeline, a required tool, covered 12 of the "
                                           "24.5 hours of the requested period.")
    assert [(e["rules"], e["variant"]) for e in on.trace.events if e["name"] == "status_lowered"] == [
        (["requested_period_not_covered"], TOOL_TURN_DONE_VARIANT)]
    # the setting off: the same replies, the status as before
    off = _run(Scripted(ev, [turn, "DONE"], report_fn=_answered), False, monkeypatch, **window)
    assert off.report.status == "answered" and "status_lowered" not in off.report.validation


def test_an_explicitly_requested_window_covered_in_full_is_not_lowered(ev, monkeypatch):
    window = {"window_start_utc": ev.window_start_utc, "window_end_utc": ev.window_end_utc}
    fake = Scripted(ev, [_required_turn(ev), "DONE"], report_fn=_answered)
    res = _run(fake, True, monkeypatch, **window)
    assert _limits(fake)["status_shortfalls"] == [] and res.report.status == "answered"


# -- relevant versus optional gaps ---------------------------------------------------------------------------------------
def test_a_required_tool_without_a_result_lowers_answered(ev, monkeypatch):
    turn = _swap(_required_turn(ev), "get_actual_demand", start_utc="2020-01-01T00:00:00Z", end_utc="2020-01-02T00:00:00Z")
    on_fake = Scripted(ev, [turn, "DONE"], report_fn=_answered)
    on = _run(on_fake, True, monkeypatch)
    assert {r.name: r.status for r in on.records}["get_actual_demand"] == "unavailable"
    limits = _limits(on_fake)
    assert [(s["rule"], s["tool"]) for s in limits["status_shortfalls"]] == [("required_tool_without_result",
                                                                              "get_actual_demand")]
    assert any(t["tool"] == "get_actual_demand" and t["status"] == "unavailable" for t in limits["tool_limits"])
    assert on.report.status == "answered_with_caveats"
    assert on.report.uncertainties[-1] == (el.STATUS_NOTE + "the actual-demand data, a required tool, returned no "
                                           "result (unavailable).")
    off = _run(Scripted(ev, [turn, "DONE"], report_fn=_answered), False, monkeypatch)
    assert off.report.status == "answered"  # the validator counts an unavailable call as run: unchanged without the variant


def test_an_optional_tool_without_a_result_is_disclosed_not_a_shortfall(ev, monkeypatch):
    gen = [("get_generation_change", {**_w(ev), "start_utc": "2020-01-01T00:00:00Z", "end_utc": "2020-01-01T06:00:00Z",
                                      "top_n": 5, "as_of_utc": None})]
    fake = Scripted(ev, [_required_turn(ev), gen, "DONE"], report_fn=_answered)
    res = _run(fake, True, monkeypatch)
    limits = _limits(fake)
    assert any(t["tool"] == "get_generation_change" and t["role"] == "optional" and t["status"] != "ok"
               for t in limits["tool_limits"])
    assert limits["status_shortfalls"] == [] and res.report.status == "answered"


# -- instructions the code does not check ----------------------------------------------------------------------------------
def test_hypotheses_and_comparisons_are_instructions_not_code_checks(ev, monkeypatch):
    """A comparative word without its basis, and an explanation contradicting an observation, are not detected by code:
    the variant changes no check, removes nothing and lowers nothing for them. The rules reach synthesis only."""
    def written(kw: dict[str, Any]) -> dict[str, Any]:
        r = _answered(kw)
        r["summary"] = ["Operational demand was elevated in the spike half-hour.",
                        "SA1 was exporting at the price peak."]
        r["possible_explanations"] = [{"statement": "Limited imports into SA1 may have raised the price.",
                                       "supporting_evidence_ids": [], "what_would_test_it": "interconnector limits"}]
        return r

    on_fake = Scripted(ev, [_required_turn(ev), "DONE"], report_fn=written)
    on = _run(on_fake, True, monkeypatch)
    off = _run(Scripted(ev, [_required_turn(ev), "DONE"], report_fn=written), False, monkeypatch)
    for field in ("summary", "possible_explanations", "status"):
        assert getattr(on.report, field) == getattr(off.report, field)
    assert on.report.validation["initial"] == off.report.validation["initial"]  # the same checks, the same findings
    synthesis = next(kw for kw, k in zip(on_fake.requests, _kinds(on_fake), strict=True) if k == "ModelReport")
    rules = synthesis["input"][-1]["content"]
    assert rules.endswith(SYNTHESIS_LIMITS)
    for line in ("- Comparisons:", "- Explanations:", "- missing_evidence:", "- Limitations:", "- Coverage:"):
        assert line in rules


def test_the_repair_turn_sees_the_limits_and_its_rules(ev, monkeypatch):
    def bad(kw: dict[str, Any]) -> dict[str, Any]:
        r = _answered(kw)
        r["headline"] = r["headline"].replace("peaked at", "peaked at 12,345 MW demand and")
        return r

    def patch(kw: dict[str, Any]) -> dict[str, Any]:
        return {"edits": [{"target": "headline", "action": "replace", "text": _good_report(kw)["headline"],
                           "statement": None, "claim": None, "citation": None}],
                "new_numeric_claims": [], "new_citations": []}

    fake = Scripted(ev, [_required_turn(ev), "DONE"], report_fn=bad, repair_fn=patch)
    res = _run(fake, True, monkeypatch)
    assert _kinds(fake)[-1] == "RepairPatch" and res.report.validation["repair_attempted"] is True
    repair = fake.requests[-1]["input"]
    assert [it for it in repair if str(it.get("content", "")).startswith(EVIDENCE_LIMITS_HEADING)]
    assert any(str(it.get("content", "")).endswith(SYNTHESIS_LIMITS) for it in repair)


# -- the status rule: unit checks on records --------------------------------------------------------------------------
W0, W1 = parse_iso("2026-07-30T04:30:00Z"), parse_iso("2026-07-31T04:30:00Z")


def _rec(name: str, status: str = "ok", start: Any = W0, end: Any = W1, view: dict[str, Any] | None = None,
         data: dict[str, Any] | None = None, missing: tuple[str, ...] = ()) -> Any:
    keys = el.WINDOW_ARGS.get(name, ("event_start_utc", "event_end_utc"))
    return SimpleNamespace(name=name, status=status, args={keys[0]: iso_utc(start), keys[1]: iso_utc(end)},
                           view=view or {}, data=data or {}, missing=list(missing), policy_notes=[], call_id="c1",
                           origin="model", blocked_reason=None)


def _res(explicit: bool = False, forecast: Any = None, event: Any = None, intent: str = "market_event_review") -> Any:
    given = iso_utc(W0) if explicit else None
    return SimpleNamespace(window=(W0, W1), request=SimpleNamespace(window_start_utc=given, window_end_utc=given and iso_utc(W1)),
                           requests=SimpleNamespace(forecast=forecast) if forecast is not None else None, event=event,
                           region="SA1", intent=intent, target=None)


def _all_required(**views: dict[str, Any]) -> list[Any]:
    return [_rec(t, view=views.get(t)) for t in EVENT_REVIEW.required]


def _rules(records: list[Any], res: Any = None, results: tuple[Any, ...] = ()) -> list[str]:
    return [s["rule"] for s in el.status_shortfalls(records, res or _res(), EVENT_REVIEW, list(results))]


def test_window_basis_tells_requested_periods_from_contextual_windows():
    event = SimpleNamespace(window_start_utc=iso_utc(W0), window_end_utc=iso_utc(W1),
                            peak_interval_end_utc="2026-07-30T08:00:00Z")
    bound = SimpleNamespace(status="bound", window=(W0, W1))
    assert el.window_basis(_res(explicit=True))["explicitly_requested"] is True
    assert el.window_basis(_res(forecast=bound, intent="forecast_review"))["source"] == \
        "the forecast period the question asks about"
    assert el.window_basis(_res(forecast=SimpleNamespace(status="absent", window=None)))["explicitly_requested"] is False
    assert "event's window" in el.window_basis(_res(event=event))["source"]
    assert el.window_basis(_res())["explicitly_requested"] is False


def test_data_absent_within_a_requested_period_is_a_shortfall_in_a_contextual_window_a_disclosure():
    full = {"intervals_in_store": 288, "intervals_expected": 288}
    gap = {"intervals_in_store": 200, "intervals_expected": 288}
    asked = _res(explicit=True)
    assert _rules(_all_required(find_market_events={"coverage": full}, get_price_timeline={"n_intervals": 288},
                                get_actual_demand={"n_intervals": 48}), asked) == []
    assert _rules(_all_required(find_market_events={"coverage": gap}, get_price_timeline={"n_intervals": 288},
                                get_actual_demand={"n_intervals": 48}), asked) == ["required_data_absent"]
    # intervals withheld by the question's as-of cutoff are not absent data
    assert _rules(_all_required(find_market_events={"coverage": full},
                                get_price_timeline={"n_intervals": 200, "excluded_not_yet_available_at_as_of": 88},
                                get_actual_demand={"n_intervals": 48}), asked) == []
    short = _all_required(find_market_events={"coverage": full}, get_price_timeline={"n_intervals": 200},
                          get_actual_demand={"n_intervals": 42})
    assert _rules(short, asked) == ["required_data_absent", "required_data_absent"]
    # the same gaps in the event's or the day's window: disclosed in the limits, not a shortfall
    assert _rules(short) == []
    notes = {t["tool"]: t["notes"] for t in el.tool_limits(short, EVENT_REVIEW)}
    assert notes["get_price_timeline"] == ["the price timeline: 88 of 288 5-minute intervals in its period are not in "
                                           "the data held"]
    assert notes["get_actual_demand"] == ["the actual-demand data: 6 of 48 30-minute intervals in its period are not in "
                                          "the data held"]


def test_a_gap_outside_the_requested_period_or_in_an_optional_tool_is_not_a_shortfall():
    wide = _rec("find_market_events", start=W0 - timedelta(days=3),
                view={"coverage": {"intervals_in_store": 100, "intervals_expected": 1152}})
    records = [wide, *(_rec(t, view={"n_intervals": 288 if t == "get_price_timeline" else 48})
                       for t in ("get_price_timeline", "get_actual_demand")), _rec("retrieve_public_evidence")]
    assert _rules(records, _res(explicit=True)) == []
    gen = _rec("get_generation_change", status="unavailable", missing=("No dispatch SCADA rows",))
    assert _rules([*records, gen], _res(explicit=True)) == []
    assert {"tool": "get_generation_change", "role": "optional", "status": "unavailable",
            "notes": ["No dispatch SCADA rows"]} in el.tool_limits([*records, gen], EVENT_REVIEW)


def test_notices_not_held_are_disclosed_not_a_shortfall():
    """Whether a notice that is not held matters depends on the question: the tool's own note is passed on."""
    base = _all_required(get_price_timeline={"n_intervals": 288}, get_actual_demand={"n_intervals": 48})
    rolled_off = _rec("retrieve_public_evidence", view={"search_scope": {"searched": True, "outcome": "no notice held",
                                                                         "selected_not_held": 2}},
                      missing=("2 market notice(s) selected for SA1 in this window are not in the local corpus",))
    for res in (_res(), _res(explicit=True)):
        assert _rules([*base[:-1], rolled_off], res) == []
    notes = next(t["notes"] for t in el.tool_limits([rolled_off], EVENT_REVIEW))
    assert notes == ["market notices: no notice held",
                     "2 market notice(s) selected for SA1 in this window are not in the local corpus"]


def test_forecast_pairs_missing_from_a_requested_period_are_a_shortfall_not_those_lost_to_the_cutoff():
    pb = PLAYBOOKS["forecast_review"]
    period = _res(forecast=SimpleNamespace(status="bound", window=(W0, W1)), intent="forecast_review")
    records = [_rec("get_forecast_runs"), _rec("get_actual_demand", view={"n_intervals": 48}),
               _rec("retrieve_public_evidence")]
    for excluded, want in (([{"reason": "not_public_by_cutoff"}], []), ([{"reason": "no_actual"}], ["required_data_absent"])):
        compare = _rec("compare_forecast_actual", data={"excluded": excluded})
        assert [s["rule"] for s in el.status_shortfalls([*records, compare], period, pb, [])] == want
        assert el.status_shortfalls([*records, compare], _res(intent="forecast_review"), pb, []) == []


def test_a_requested_result_not_established_or_not_verified_is_a_shortfall():
    base = _all_required(get_price_timeline={"n_intervals": 288}, get_actual_demand={"n_intervals": 48})

    def result(status: str, outcome: str) -> Any:
        return SimpleNamespace(result=SimpleNamespace(result_id="r1", status=status,
                                                      identity=SimpleNamespace(kind="demand_maximum")),
                               server_verification=SimpleNamespace(outcome=outcome))

    assert _rules(base, results=(result("established", "verified"),)) == []
    assert _rules(base, results=(result("not_established", "verified"),)) == ["requested_result_not_established"]
    assert _rules(base, results=(result("established", "failed"),)) == ["requested_result_not_established"]


def test_a_blocked_call_retried_successfully_is_neither_a_limit_nor_a_shortfall():
    blocked = _rec("get_price_timeline", status="blocked")
    records = [blocked, *_all_required(get_price_timeline={"n_intervals": 288}, get_actual_demand={"n_intervals": 48})]
    assert _rules(records) == []
    assert not [t for t in el.tool_limits(records, EVENT_REVIEW) if t["status"] == "blocked"]


# -- the status is only ever lowered ----------------------------------------------------------------------------------------
def _report(status: str) -> InvestigationReport:
    return InvestigationReport(question="q", mode="live", intent="market_event_review", region="SA1", as_of=None,
                               event_window=None, headline="h", status=status, trace_id="t", uncertainties=["u"],
                               validation={"final_passed": True}, generator="live-model:test",
                               versions=Versions(code="c", data=None, corpus=None, prompt="p", model=None,
                                                 controller="live"))


@pytest.mark.parametrize("status", ["answered_with_caveats", "abstained", "needs_clarification", "refused"])
def test_a_status_other_than_answered_is_never_changed(status):
    rep = _report(status)
    assert el.lower_status(rep, [{"rule": "required_tool_without_result", "detail": "x"}], TOOL_TURN_DONE_VARIANT) is rep


def test_answered_is_lowered_only_with_a_shortfall_and_its_reasons_are_recorded():
    rep = _report("answered")
    assert el.lower_status(rep, [], TOOL_TURN_DONE_VARIANT) is rep
    found = [{"rule": "required_tool_without_result", "tool": "get_actual_demand", "detail": "a"},
             {"rule": "required_data_absent", "tool": "find_market_events", "detail": "b"}]
    out = el.lower_status(rep, found, TOOL_TURN_DONE_VARIANT)
    assert out.status == "answered_with_caveats" and out.uncertainties == ["u", el.STATUS_NOTE + "a; b."]
    assert out.validation == {"final_passed": True, "status_lowered": {
        "from": "answered", "to": "answered_with_caveats", "variant": TOOL_TURN_DONE_VARIANT, "shortfalls": found}}
