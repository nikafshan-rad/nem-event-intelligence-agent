"""D31 Amendment 1, the integration review before merge (2026-10-05): the request plan through the Live entry point.

Every case here goes through ``service.investigate`` in Live mode with the SYNTHETIC fake transport, so routing,
resolution, the dispatcher, the controller, validation and the report are the real ones; only the model is scripted.

- **Fail-closed:** incomplete, invalid, conflicting and sent-back plans make the routing call only: no tool is offered or
  run, and nothing is computed or shown but the clarification.
- **The trust boundary:** what the compiler catches and what it accepts when the plan itself is wrong (an omitted run,
  maximum or cutoff; an asked, declined or background label that is wrong; a subject read wrongly), and what the
  report then shows. The accepted errors are the intentional semantic limitations recorded in the amendment, not
  failures of an acceptance criterion: no phrase rule is added for them, and none of this is semantic verification.
- **Two failures found by this review, fixed within the approved scope:** a cutoff that only an asked operation which
  does not run refers to was applied to the request that runs (decision 3); identical duplicate maxima were sent
  back, though the amendment consolidates identical duplicates (decision 1).
- **The echo** on the page (Streamlit AppTest): under uncertainties, labelled, never as the interpretation.
- **V0 and V1** on the same scripted plans, reported apart. No selection rule was applied.

Scripted plans show what the code does with a given reading; they say nothing about how a hosted model fills one."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from nem_agent.agent.plan import (
    ECHO_LABEL,
    PLAN_INVALID_CLARIFICATION,
    PLAN_OPERATION_CLARIFICATION,
    PLAN_OPERATIONS_CLARIFICATION,
)
from nem_agent.agent.request import InvestigateRequest
from nem_agent.agent.structured import (
    CUTOFF_CLARIFICATION,
    FORECAST_DOMAIN_CLARIFICATION,
    FORECAST_OPERATION_CLARIFICATION,
    FORECAST_SCOPE_CLARIFICATION,
    PLAN_CUTOFF_CLARIFICATION,
    not_answered_note,
)
from nem_agent.service import investigate
from nem_agent.ui_data import result_provenance
from tests.provider.fake_model import msg
from tests.provider.test_request_plan import (
    CORRECT,
    DRAFT,
    GOLD,
    Q_CUTOFF,
    Q_D01,
    Q_D08,
    Q_F07,
    Q_INCIDENTAL,
    Q_MIXED,
    Q_N03,
    Q_N04,
    Q_N06,
    ROOT,
    SAVED_PLANS,
    V15,
    PlanFake,
    _cutoff_plan,
    _d08,
    _f07,
    _incidental,
    _n03,
    _n04,
    _record,
    _saved_fake,
    decision,
    op,
    resolved,
)

pytestmark = pytest.mark.synthetic

TOOL_TURN = [("get_forecast_runs", {"region": "VIC1", "target_start_utc": "2026-08-17T08:00:00Z",
                                    "target_end_utc": "2026-08-17T08:30:00Z"})]


def _live(q: str, plan: dict[str, Any] | None, raw: dict[str, Any] | None = None, turns: Any = None,
          **request: Any) -> tuple[Any, PlanFake]:
    """A question through the Live entry point, its routing call answered with ``plan`` (or ``raw``)."""
    fake = PlanFake(plan, [TOOL_TURN] if turns is None else turns, lambda kw: copy.deepcopy(DRAFT), raw=raw)
    res = investigate(InvestigateRequest(question=q, mode="live", **request), live_client=fake, write_trace=False)
    return res, fake


def _echo(res: Any) -> list[str]:
    return [u for u in res.report.uncertainties if u.startswith(ECHO_LABEL)]


@pytest.fixture(autouse=True)
def _plan_on(monkeypatch):
    monkeypatch.setenv("NEM_AGENT_ROUTE_PLAN", "1")


# ------------------------------------------------------------------------------------------------ fail-closed (2)
Q_STRAY = ("As of 14:00 AEST on 17 August 2026, what was the weather forecast for Melbourne, and what did the last "
           "operational demand forecast issued before the half-hour ending 18:30 AEST that day give for Victoria?")


def _stray() -> dict[str, Any]:
    """The cutoff refers to the weather operation only (which does not run), not to the demand request."""
    return decision("forecast_review", "VIC1", "2026-08-17", [
        op("o1", "forecast_value", "weather", "the weather forecast", "what was the weather forecast for Melbourne",
           cutoff="c1"),
        op("o2", "forecast_value", "operational_demand", "operational demand forecast",
           "what did the last operational demand forecast issued before", "s1", "r1")],
        scopes={"s1": ("half_hour", "the half-hour ending 18:30 AEST that day")},
        runs={"r1": ("last_issued_before", "the last operational demand forecast issued before")},
        cutoffs={"c1": "As of 14:00 AEST on 17 August 2026"})


def _mixed() -> dict[str, Any]:
    return decision("forecast_review", "SA1", "2026-07-31", [
        op("o1", "forecast_comparison", "operational_demand", "the operational demand forecasts",
           "how did the operational demand forecasts compare with actual demand", "s1"),
        op("o2", "demand_maximum", "operational_demand", "operational demand", "when was operational demand highest",
           "s1")], scopes={"s1": ("whole_local_day", "on 31 July 2026")})


def _two_roles() -> tuple[str, dict[str, Any]]:
    q = "What did the operational demand forecast available by 18:00 AEST on 17 August 2026 give for Victoria?"
    return q, decision("forecast_review", "VIC1", "2026-08-17", [
        op("o1", "forecast_value", "operational_demand", "operational demand forecast",
           "What did the operational demand forecast available by 18:00 AEST on 17 August 2026 give", "s1",
           cutoff="c1")], scopes={"s1": ("half_hour", "18:00 AEST on 17 August 2026")},
        cutoffs={"c1": "available by 18:00 AEST on 17 August 2026"})


INCOMPLETE = {"id": "r", "status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
              "output": [{"type": "message", "content": [{"type": "output_text", "text": "{\"intent\": \"fore"}]}],
              "usage": {"output_tokens": 2000}}
INVALID_OUTPUT = "The routing model returned invalid output."
N07_Q = ("How did AEMO's operational demand forecast for Queensland compare with actual operational demand between "
         "06:00 and noon AEST on 4 August 2026?")
N07_PLAN = decision("forecast_review", "QLD1", "2026-08-04", [
    op("o1", "forecast_comparison", "operational_demand", "AEMO's operational demand forecast for Queensland",
       "How did AEMO's operational demand forecast for Queensland compare with actual operational demand", "s1")],
    scopes={"s1": ("explicit", "between 06:00 and noon AEST on 4 August 2026")})

FAIL_CLOSED: dict[str, tuple[str, Any, Any, str, list[str] | None]] = {
    # name: (question, plan, raw response, report status, reasons — None when the text is the model's own)
    "incomplete response": (Q_N04, None, INCOMPLETE, "needs_clarification", [INVALID_OUTPUT]),
    "unparsable response": (Q_N04, None, msg("{not json"), "needs_clarification", [INVALID_OUTPUT]),
    "schema-invalid plan": (Q_N04, None, msg(json.dumps({**_n04(), "as_of_text": None})), "needs_clarification",
                            [INVALID_OUTPUT]),
    "structurally invalid plan": (Q_N04, {**_n04(), "plan": {**_n04()["plan"], "cutoff_ref": "c9"}}, None,
                                  "needs_clarification", [PLAN_INVALID_CLARIFICATION]),
    "conflicting operations": (Q_MIXED, _mixed(), None, "needs_clarification", [PLAN_OPERATIONS_CLARIFICATION]),
    "one span in two roles": (*_two_roles(), None, "needs_clarification", None),
    "unreferenced cutoff": (Q_CUTOFF, _cutoff_plan(None), None, "needs_clarification", [PLAN_CUTOFF_CLARIFICATION]),
    "as-of words left out": (Q_CUTOFF, _cutoff_plan(None, with_cutoff=False), None, "needs_clarification",
                             [PLAN_CUTOFF_CLARIFICATION]),
    "cutoff of an operation that does not run": (Q_STRAY, _stray(), None, "needs_clarification",
                                                 [PLAN_CUTOFF_CLARIFICATION]),
    "unreadable active cutoff (F07N, noon)": (Q_F07, _f07(), None, "needs_clarification", [CUTOFF_CLARIFICATION]),
    "unnamed forecast under V1 (D08 misread)": (Q_D08, _d08("operational_demand", "the latest issued forecast"), None,
                                                "needs_clarification", [FORECAST_DOMAIN_CLARIFICATION]),
    "known unsupported scope (noon)": (N07_Q, N07_PLAN, None, "needs_clarification", [FORECAST_SCOPE_CLARIFICATION]),
    "the model's own clarification": (Q_N04, _n04(needs_clarification=True, clarification_reason="unclear_question",
                                                  clarification="Which forecast?"), None, "needs_clarification",
                                      ["Which forecast?"]),
    "out of scope": (Q_N04, _n04(out_of_scope=True), None, "refused", None),
}


@pytest.mark.parametrize("name", list(FAIL_CLOSED))
def test_fail_closed_through_the_live_entry_point(name, real_store):
    """Criterion 4 (and decisions 1 and 3), through the Live entry point: the routing call is the only model call; no
    tool is offered or run; nothing is computed, verified or shown but the send-back; no echo."""
    q, plan, raw, status, reasons = FAIL_CLOSED[name]
    res, fake = _live(q, plan, raw=raw)
    assert res.report.status == status, res.report.reasons if hasattr(res.report, "reasons") else res.report.headline
    if reasons is not None:
        assert res.resolution.reasons == reasons
    assert len(fake.requests) == 1 and fake.requests[0]["text"]["format"]["name"] == "PlanRouteDecision"
    assert fake.issued == [] and res.records == [] and "tools" not in fake.requests[0]
    rep = res.report
    assert not rep.answer and not rep.results and not rep.observations and not rep.summary and not _echo(res)
    assert rep.headline.startswith("Refused: " if status == "refused" else "Clarification needed: ")


# ------------------------------------------------------------------------------------------------ trust boundary (3)
Q_NO_RUN = "What did the last operational demand forecast issued before the half-hour ending 18:30 AEST on 17 August 2026 give for Victoria?"
S_1830 = {"s1": ("half_hour", "the half-hour ending 18:30 AEST on 17 August 2026")}
Q_NOON_CUTOFF = ("Using only data published by noon AEST on 17 August 2026, what did the last operational demand forecast "
                 "issued before the half-hour ending 18:30 AEST that day give for Victoria?")
Q_CLOCK_CUTOFF = Q_NOON_CUTOFF.replace("noon AEST", "14:00 AEST")
Q_SPIKE_MAX = ("What happened around the SA1 price spike on 31 July 2026, and when was South Australia's operational "
               "demand highest that day?")
Q_DECLINED_ASKED = ("I don't need AEMO's operational demand forecast for the half-hour ending 18:30 AEST on 17 August "
                    "2026 in Victoria. What was the weather forecast for then?")
Q_BACKGROUND_ASKED = ("Our operations team said AEMO's operational demand forecast for the half-hour ending 18:30 AEST on "
                      "17 August 2026 in Victoria was too low. What temperature had been forecast for Melbourne then?")


def _value(i: str, subject_text: str, op_text: str, stance: str = "asked", run: str | None = "r1",
           cutoff: str | None = None) -> dict[str, Any]:
    return op(i, "forecast_value", "operational_demand", subject_text, op_text, "s1", run, cutoff, stance)


def _run(text: str) -> dict[str, tuple[str, str]]:
    return {"r1": ("last_issued_before", text)}


TRUST: dict[str, dict[str, Any]] = {
    "omitted run, its issue time in the question": dict(
        kind="omitted operation part", q=Q_D01, caught=True, reasons=[FORECAST_SCOPE_CLARIFICATION],
        plan=decision("forecast_review", "TAS1", "2026-07-31", [op(
            "o1", "forecast_comparison", "operational_demand", "POE10, POE50 and POE90 operational demand values",
            "how much operational demand was actually recorded in that half-hour", "s1")],
            scopes={"s1": ("half_hour", "Tasmania's half-hour ending at 8:00 am AEST, 31 July 2026")}),
        why="the issue time is held by no plan entity: the time accounting sends the scope back"),
    "omitted run, no time of its own": dict(
        kind="omitted operation part", q=Q_NO_RUN, caught=False,
        plan=decision("forecast_review", "VIC1", "2026-08-17", [
            _value("o1", "operational demand forecast", "What did the last operational demand forecast issued before",
                   run=None)], scopes=S_1830),
        echo="what AEMO's operational demand forecast gave in VIC1, for the half-hour (2026-08-17T08:00:00Z, "
             "2026-08-17T08:30:00Z].",
        why="answered with no run rule: the echo states no run, which shows the omission"),
    "omitted demand maximum (event review)": dict(
        kind="omitted operation", q=Q_SPIKE_MAX, caught=False,
        plan=decision("market_event_review", "SA1", "2026-07-31", []), echo=None,
        why="the event review runs; no maximum is computed and no note says so (v15's parser would have bound it)"),
    "omitted cutoff, parser as-of words": dict(
        kind="omitted cutoff", q=Q_CUTOFF, caught=True, reasons=[PLAN_CUTOFF_CLARIFICATION],
        plan=_cutoff_plan(None, with_cutoff=False), why="the parser backstop (decision 5)"),
    "omitted cutoff with a clock time": dict(
        kind="omitted cutoff", q=Q_CLOCK_CUTOFF, caught=True, reasons=[FORECAST_SCOPE_CLARIFICATION],
        plan=decision("forecast_review", "VIC1", "2026-08-17", [
            _value("o1", "operational demand forecast", "what did the last operational demand forecast issued before")],
            scopes={"s1": ("half_hour", "the half-hour ending 18:30 AEST that day")},
            runs=_run("the last operational demand forecast issued before")),
        why="14:00 is held by no plan entity: sent back, though for its scope, not as a cutoff"),
    "omitted cutoff, no as-of words and no clock": dict(
        kind="omitted cutoff", q=Q_NOON_CUTOFF, caught=False,
        plan=decision("forecast_review", "VIC1", "2026-08-17", [
            _value("o1", "operational demand forecast", "what did the last operational demand forecast issued before")],
            scopes={"s1": ("half_hour", "the half-hour ending 18:30 AEST that day")},
            runs=_run("the last operational demand forecast issued before")),
        echo="what AEMO's operational demand forecast gave in VIC1, for the half-hour (2026-08-17T08:00:00Z, "
             "2026-08-17T08:30:00Z]; run: the last issued before that half-hour began.",
        why="answered with no cutoff (as v15 when its model omitted as_of_text): the echo states none"),
    "asked labelled declined (forecast review)": dict(
        kind="wrong stance", q=Q_N04, caught=True, reasons=[FORECAST_OPERATION_CLARIFICATION],
        plan=decision("forecast_review", "VIC1", "2026-08-17", [
            op("o1", "forecast_value", "weather", "the weather forecast", "Leave the weather forecast out of this one",
               stance="declined"),
            op("o2", "forecast_value", "operational_demand", "AEMO's operational demand forecast values",
               "What did they show?", "s1", stance="declined")],
            scopes={"s1": ("half_hour", "a single half-hour on 17 August 2026: the one ending at 18:30 AEST")}),
        why="nothing is asked, and a forecast review must ask something"),
    "asked labelled declined (event review)": dict(
        kind="wrong stance", q=Q_SPIKE_MAX, caught=False,
        plan=decision("market_event_review", "SA1", "2026-07-31", [
            op("o1", "demand_maximum", "operational_demand", "operational demand",
               "when was South Australia's operational demand highest that day", "s1", stance="declined")],
            scopes={"s1": ("whole_local_day", "that day")}), echo=None,
        why="the event review runs without the maximum; no note says so"),
    "declined labelled asked": dict(
        kind="wrong stance", q=Q_DECLINED_ASKED, caught=False,
        plan=decision("forecast_review", "VIC1", "2026-08-17", [
            _value("o1", "AEMO's operational demand forecast", "I don't need AEMO's operational demand forecast",
                   run=None),
            op("o2", "forecast_value", "weather", "the weather forecast", "What was the weather forecast for then?",
               "s1")], scopes=S_1830),
        echo="what AEMO's operational demand forecast gave in VIC1, for the half-hour (2026-08-17T08:00:00Z, "
             "2026-08-17T08:30:00Z].",
        notes=[not_answered_note(["weather"])],
        why="the declined forecast is answered; the echo states it, so a reader can see the misreading"),
    "background in quotation marks labelled asked": dict(
        kind="wrong stance", q=Q_N06, caught=True, reasons=[FORECAST_OPERATION_CLARIFICATION],
        plan=decision("forecast_review", "SA1", "2026-08-14", [
            op("o1", "forecast_comparison", "operational_demand", "AEMO's demand forecast for South Australia",
               "came in well below the actuals"),
            op("o2", "forecast_value", "weather", "minimum temperature", "What minimum temperature had been forecast",
               "s2")], scopes={"s2": ("whole_local_day", "for Adelaide on 14 August 2026")}),
        why="the quotation-mark check (decision 4)"),
    "background without quotation marks labelled asked": dict(
        kind="wrong stance", q=Q_BACKGROUND_ASKED, caught=False,
        plan=decision("forecast_review", "VIC1", "2026-08-17", [
            _value("o1", "AEMO's operational demand forecast", "AEMO's operational demand forecast for the half-hour",
                   run=None),
            op("o2", "forecast_value", "weather", "temperature", "What temperature had been forecast for Melbourne",
               "s1")], scopes=S_1830),
        echo="what AEMO's operational demand forecast gave in VIC1, for the half-hour (2026-08-17T08:00:00Z, "
             "2026-08-17T08:30:00Z].",
        notes=[not_answered_note(["weather"])], why="a background statement is answered as a request"),
    "asked labelled background": dict(
        kind="wrong stance", q=Q_NO_RUN, caught=True, reasons=[FORECAST_OPERATION_CLARIFICATION],
        plan=decision("forecast_review", "VIC1", "2026-08-17", [
            _value("o1", "operational demand forecast", "What did the last operational demand forecast issued before",
                   stance="background")], scopes=S_1830, runs=_run("the last operational demand forecast issued before")),
        why="nothing is asked"),
    "subject read from an incidental mention": dict(
        kind="wrong subject", q=Q_INCIDENTAL, caught=False, plan=_incidental("operational_demand", "Demand"),
        echo="what AEMO's operational demand forecast gave in VIC1, for the half-hour (2026-08-17T08:00:00Z, "
             "2026-08-17T08:30:00Z]; run: the last issued before that half-hour began.",
        why="the words hold the demand vocabulary, so V1 accepts them: provenance, not meaning"),
    "unnamed forecast read as demand (V1)": dict(
        kind="wrong subject", q=Q_D08, caught=True, reasons=[FORECAST_DOMAIN_CLARIFICATION],
        plan=_d08("operational_demand", "the latest issued forecast"), why="V1's frozen demand vocabulary"),
}


@pytest.mark.parametrize("name", list(TRUST))
def test_the_trust_boundary_and_what_is_shown(name, real_store):
    """Criterion 2's controls and the amendment's limitations, through the Live entry point. A caught error makes the
    routing call only and shows the send-back. An accepted error runs: the tools phase is reached and the answer is
    shown with the echo of the (wrong) reading, so the reader can see what was read; nothing claims it is right."""
    case = TRUST[name]
    res, fake = _live(case["q"], case["plan"], turns=[])
    rep = res.report
    if case["caught"]:
        assert rep.status == "needs_clarification" and res.resolution.reasons == case["reasons"]
        assert len(fake.requests) == 1 and res.records == [] and not _echo(res)
        return
    assert rep.status not in ("needs_clarification", "refused"), res.resolution.reasons
    assert len(fake.requests) > 1  # the tools phase was reached: the reading runs
    expected = case.get("echo")
    assert _echo(res) == ([ECHO_LABEL + expected] if expected else [])
    notes = [u for u in rep.uncertainties if u in res.resolution.requests.notes and not u.startswith(ECHO_LABEL)]
    assert notes == case.get("notes", [])


def test_an_accepted_stance_error_runs_its_tools_and_the_echo_states_the_reading(real_store):
    """The displayed consequence of an accepted error, with data held (R02's SA1 half-hour): a forecast the question
    declines, labelled asked, is read as the request; its demand-forecast tool runs over the pinned data, and the echo
    states that reading, labelled as controller metadata, beside the weather forecast named as not answered. Nothing
    detects the misreading: the model's stance is trusted (a recorded limitation)."""
    q = ("I don't need AEMO's operational demand forecast for South Australia's 7:30-8:00 am half-hour (Adelaide time, "
         "ACST) on 20 August 2026. What was the weather forecast for then?")
    plan = decision("forecast_review", "SA1", "2026-08-20", [
        op("o1", "forecast_value", "operational_demand", "AEMO's operational demand forecast",
           "I don't need AEMO's operational demand forecast", "s1"),
        op("o2", "forecast_value", "weather", "the weather forecast", "What was the weather forecast for then?", "s1")],
        scopes={"s1": ("half_hour", "South Australia's 7:30-8:00 am half-hour (Adelaide time, ACST) on 20 August 2026")})
    turn = [("get_forecast_runs", {"region": "SA1", "target_start_utc": "2026-08-19T22:00:00Z",
                                   "target_end_utc": "2026-08-19T22:30:00Z"})]
    res, _ = _live(q, plan, turns=[turn])
    assert [(r.name, r.status) for r in res.records] == [("get_forecast_runs", "ok")]
    assert _echo(res) == [ECHO_LABEL + "what AEMO's operational demand forecast gave in SA1, for the half-hour "
                          "(2026-08-19T22:00:00Z, 2026-08-19T22:30:00Z]."]
    assert not_answered_note(["weather"]) in res.report.uncertainties


# ------------------------------------------------------------------------------------------------ the two fixes
def test_a_cutoff_of_an_operation_that_does_not_run_is_sent_back_not_applied():
    """Found by this review (decision 3): the plan ties the cutoff to the weather operation, which does not run; it
    was applied to the demand request (and stated in its echo). Now it is sent back. Where the request that runs refers
    to the same cutoff (v15 D06, D07), or a cutoff naming the same time, nothing changes."""
    res = resolved(Q_STRAY, _stray())
    assert res.status == "needs_clarification" and res.reasons == [PLAN_CUTOFF_CLARIFICATION] and res.as_of is None
    assert any("does not run" in n for n in res.requests.cutoff.notes)
    shared = _stray()
    shared["plan"]["operations"][1]["cutoff_ref"] = "c1"  # the demand request refers to it too
    res = resolved(Q_STRAY, shared)
    assert res.status == "ok" and res.as_of is not None and res.as_of.isoformat() == "2026-08-17T04:00:00+00:00"
    same_time = copy.deepcopy(shared)
    same_time["plan"]["cutoffs"].append({"id": "c2", "text": "As of 14:00 AEST on 17 August 2026"})
    same_time["plan"]["operations"][0]["cutoff_ref"] = "c2"  # another entity, the same words and time
    assert resolved(Q_STRAY, same_time).status == "ok"
    q = ("Using only data published by 14:00 ACST on 31 July 2026, what happened to SA1 prices, and what was the "
         "weather forecast for Adelaide?")
    event = decision("market_event_review", "SA1", "2026-07-31", [
        op("o1", "forecast_value", "weather", "the weather forecast", "what was the weather forecast", cutoff="c1")],
        cutoffs={"c1": "published by 14:00 ACST on 31 July 2026"})
    assert resolved(q, event).reasons == [PLAN_CUTOFF_CLARIFICATION]  # the event review that runs refers to none
    event["plan"]["cutoff_ref"] = "c1"
    res = resolved(q, event)  # the plan's cutoff_ref: the whole question's
    assert res.status == "ok" and res.as_of is not None and res.as_of.isoformat() == "2026-07-31T04:30:00+00:00"
    assert res.requests.notes == [not_answered_note(["weather"])]
    assert resolved(Q_STRAY, _stray(), as_of_utc="2026-08-17T04:00:00Z").status == "ok"  # a request cutoff stands


def test_identical_duplicate_maxima_are_one_operation_and_distinct_ones_are_not():
    """Found by this review (decision 1): identical duplicates are consolidated for maxima too; two measures, or one
    measure over two windows, are still sent back."""
    q = "On 29 July 2026, when was Queensland's operational demand highest?"
    dup = decision("market_event_review", "QLD1", "2026-07-29", [
        op(i, "demand_maximum", "operational_demand", "operational demand",
           "when was Queensland's operational demand highest", "s1") for i in ("o1", "o2")],
        scopes={"s1": ("whole_local_day", "On 29 July 2026")})
    res = resolved(q, dup)
    assert res.status == "ok" and res.requests.maximum.measures == ["operational demand"]
    assert res.requests.plan["consolidated"] == ["o2"]
    other = copy.deepcopy(dup)
    other["plan"]["operations"][1].update(subject="dispatch_total_demand", subject_text="demand")
    assert resolved(q, other).reasons == [PLAN_OPERATIONS_CLARIFICATION]


# ------------------------------------------------------------------------------------------------ consolidation (5)
Q_R02 = V15["D02"]["question"]


@pytest.mark.parametrize("change, consolidated", [
    (None, True),
    ("another scope", False), ("another run", False), ("another cutoff", False), ("no named run", False),
])
def test_consolidation_requires_identical_subject_scope_run_and_cutoff(change, consolidated):
    """Decision 1, one change at a time: R02's value and comparison are one comparison only while they read the same
    subject, scope, run and cutoff; otherwise the question is sent back, never one of them chosen."""
    d = copy.deepcopy(CORRECT["D02"])
    ops = d["plan"]["operations"]
    if change == "another scope":
        d["plan"]["scopes"].append({"id": "s2", "kind": "whole_local_day", "text": "on 20 August 2026"})
        ops[1]["scope_ref"] = "s2"
    elif change == "another run":
        d["plan"]["runs"].append({"id": "r2", "selection": "issued_at", "text": "the final forecast run issued ahead of it"})
        ops[1]["run_ref"] = "r2"
    elif change == "another cutoff":
        d["plan"]["cutoffs"].append({"id": "c1", "text": "Taking South Australia's 7:30-8:00 am half-hour"})
        ops[1]["cutoff_ref"] = "c1"
    elif change == "no named run":
        for o in ops:
            o["run_ref"] = None
        d["plan"]["runs"] = []
    res = resolved(Q_R02, d)
    if consolidated:
        assert res.status == "ok" and res.requests.plan["consolidated"] == ["o1"]
        assert res.requests.forecast.operation == "single_interval_comparison"
    else:
        assert res.status == "needs_clarification" and res.requests.forecast.status == "absent"
        assert res.requests.plan["primary"] is None or res.requests.cutoff.status != "bound"


# ------------------------------------------------------------------------------------------------ the echo on the page (6)
@pytest.mark.parametrize("cid", ["R02", "D02"])
def test_the_echo_on_the_page_is_controller_metadata_and_not_the_interpretation(cid, real_store, monkeypatch):
    """R02 (a fallback) and D02 (validated) on the Streamlit page: the echo is a bullet under 'Uncertainties and missing
    evidence', not under the interpretation; the banner, the validation tile and the interpretation status are the
    ones the saved v15 decision gives for the same record."""
    from streamlit.testing.v1 import AppTest

    rec = _record(cid)
    res = investigate(InvestigateRequest(question=rec["question"], mode="live", **rec["request"]),
                      live_client=_saved_fake(cid, SAVED_PLANS[cid]), write_trace=False)
    (said,) = _echo(res)
    at = AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"), default_timeout=120)
    at.session_state["result"] = res
    at.run()
    assert not at.exception
    shown = [m.value for m in at.markdown]
    head = shown.index("#### Uncertainties and missing evidence")
    assert f"- {said}" in shown[head:] and not any(said in s for s in shown[:head])
    monkeypatch.delenv("NEM_AGENT_ROUTE_PLAN")
    old = investigate(InvestigateRequest(question=rec["question"], mode="live", **rec["request"]),
                      live_client=_saved_fake(cid, None), write_trace=False)
    new_p, old_p = (result_provenance(r.report.model_dump(), r.usage) for r in (res, old))
    assert {k: v for k, v in new_p.items() if k != "prompt"} == {k: v for k, v in old_p.items() if k != "prompt"}
    assert (new_p["prompt"], old_p["prompt"]) == ("prompts/v17", "prompts/v16")
    if cid == "R02":  # a fallback: the interpretation is withheld, and the echo does not stand in for it
        assert res.report.validation["fallback_applied"] and new_p["kind"] == "live_fallback"
        assert any("Result shown" in w.value for w in at.warning)
        assert said not in json.dumps(res.report.summary) and said not in res.report.headline


# ------------------------------------------------------------------------------------------------ V0 and V1 (7)
MISREAD = {"D08 misread": (Q_D08, _d08("operational_demand", "the latest issued forecast")),
           "N03 misread": (Q_N03, _n03("operational_demand", "the forecasts")),
           "incidental, forecast's own words": (Q_INCIDENTAL, _incidental("operational_demand", "the last forecast")),
           "incidental, the mention's words": (Q_INCIDENTAL, _incidental("operational_demand", "Demand"))}


def _outcome(q: str, d: dict[str, Any], **req: Any) -> tuple[str, tuple[str, ...]]:
    res = resolved(q, d, **req)
    return res.status, tuple(res.reasons)


def test_v0_and_v1_reported_apart(monkeypatch):
    """The 17 scripted correct plans give the same outcome under V0 and V1 (their subject words name demand where they
    claim it). The misreadings split: V1 sends back the three whose words hold no demand vocabulary; V0 accepts all
    four; both accept the reading taken from an incidental 'Demand'. No selection rule was applied: V1 is the opt-in
    default by the owner's decision, and no held-out outcome is used here."""
    results: dict[str, dict[str, Any]] = {"V0": {}, "V1": {}}
    for pol in ("V0", "V1"):
        monkeypatch.setenv("NEM_AGENT_PLAN_POLICY", pol)
        for cid, d in CORRECT.items():
            results[pol][cid] = _outcome(V15[cid]["question"], d, **V15[cid]["request"])
        for name, (q, d) in MISREAD.items():
            results[pol][name] = _outcome(q, d)
    assert all(results["V0"][cid] == results["V1"][cid] for cid in CORRECT)
    assert sum(results["V1"][cid][0] == "ok" for cid in CORRECT) == sum(
        GOLD[cid]["outcome"] == "resolved" for cid in CORRECT) - 1  # N07 (noon)
    assert [results["V1"][n][0] for n in MISREAD] == ["needs_clarification"] * 3 + ["ok"]
    assert [results["V0"][n][0] for n in MISREAD] == ["ok"] * 4
    assert all(results["V1"][n][1] == (FORECAST_DOMAIN_CLARIFICATION,) for n in list(MISREAD)[:3])


# ------------------------------------------------------------------------------------------------ cutoffs and roles (4)
def test_contextual_entities_never_become_requests_and_an_active_unresolved_cutoff_never_disappears():
    """Declined and background operations, and the scopes, runs and cutoffs only they refer to, create no request; an
    active cutoff that cannot be read is sent back whatever else the plan holds, for every intent, unless the request
    gives a cutoff (F07)."""
    contextual = decision("forecast_review", "VIC1", "2026-08-17", [
        _value("o1", "operational demand forecast", "What did the last operational demand forecast issued before",
               stance="declined", cutoff="c1")], scopes=S_1830,
        runs=_run("the last operational demand forecast issued before"), cutoffs={"c1": "issued before"})
    res = resolved(Q_NO_RUN, contextual)
    assert res.reasons == [FORECAST_OPERATION_CLARIFICATION]
    assert (res.requests.forecast_run.status, res.requests.cutoff.status) == ("absent", "absent")
    for intent, ops in (("forecast_review", _f07()["plan"]["operations"]), ("market_event_review", []),
                        ("source_explanation", [])):
        d = _f07()
        d["intent"], d["plan"]["operations"], d["plan"]["cutoff_ref"] = intent, ops, "c1"
        res = resolved(Q_F07, d)
        assert res.status == "needs_clarification" and res.reasons == [CUTOFF_CLARIFICATION], intent
        assert resolved(Q_F07, d, as_of_utc="2025-10-05T02:00:00Z").status == "ok", intent


def test_an_invalid_plan_reads_nothing_and_a_document_question_reads_only_its_cutoff():
    assert resolved(Q_N04, {**_n04(), "plan": {**_n04()["plan"], "cutoff_ref": "c9"}}).reasons == [
        PLAN_INVALID_CLARIFICATION]
    q = "What does operational demand mean, as of 14:00 AEST on 17 August 2026?"
    doc = decision("source_explanation", None, None, [], cutoffs={"c1": "as of 14:00 AEST on 17 August 2026"},
                   cutoff_ref="c1")
    res = resolved(q, doc)
    assert res.status == "ok" and res.as_of is not None and res.as_of.isoformat() == "2026-08-17T04:00:00+00:00"
    doc["plan"]["cutoff_ref"] = None
    assert resolved(q, doc).reasons == [PLAN_CUTOFF_CLARIFICATION]  # unreferenced: never applied globally
    # a document question's operations are not read (as under v15): an operation the plan cannot place sends nothing
    # back there, while in a forecast review it would (PLAN_OPERATION_CLARIFICATION)
    kindless = [op("o1", "not_stated", "not_stated", None, "What does operational demand mean")]
    assert resolved(q.split(",")[0] + "?", decision("source_explanation", None, None, kindless)).status == "ok"
    assert resolved(Q_N04, decision("forecast_review", "VIC1", "2026-08-17", [
        op("o1", "not_stated", "not_stated", None, "What did they show?")])).reasons == [PLAN_OPERATION_CLARIFICATION]
