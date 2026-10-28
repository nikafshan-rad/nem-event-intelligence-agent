"""Targeted tests for the confirmed-request workflow: DST boundaries, cutoff distinction, total demand,
clarification, actual tool arguments, and session lifecycle.

Every test is OFFLINE: no network, no API key.  The data store is the real pinned one, the ledger is scratch.
No routing model is needed — every draft is built from structured choices (``C.apply``) and compiled by code
(``C.executable``, ``C.issues``).  Test-first: documenting the contract as the code implements it.
"""

from __future__ import annotations

from typing import Any

import pytest

from nem_agent.agent import confirm as C
from nem_agent.timeutil import parse_iso

pytestmark = pytest.mark.synthetic


@pytest.fixture(scope="module")
def sel(real_store):
    from nem_agent.service import _shared

    return _shared()[1]


def _build(sel: Any, steps: list[tuple[str, Any]]) -> C.Draft:
    d = C.Draft(question="SYNTHETIC", origin="structured")
    for f, v in steps:
        d = C.apply(d, f, v, sel)
    return d


# ------------------------------------------------------------------------------------------------ DST: whole-day bounds
# Whole-day scopes use local_day_window (midnight to midnight): no user-supplied clock time, so DST
# transitions affect the window length correctly and no disambiguation is needed.

def test_spring_forward_day_produces_23_hour_window(sel):
    """NSW1 Oct 4 2026: clocks spring forward 02:00 AEST -> 03:00 AEDT.  The local day is 23 hours."""
    d = _build(sel, [("operation", "demand_maximum"), ("measure", "operational demand"),
                     ("region", "NSW1"), ("date", "2026-10-04"), ("scope_kind", "day")])
    x = C.executable(d, sel)
    assert x is not None
    assert (x.start_utc, x.end_utc) == ("2026-10-03T14:00:00Z", "2026-10-04T13:00:00Z")
    assert x.half_hours == 46


def test_fall_back_day_produces_25_hour_window(sel):
    """NSW1 Apr 5 2026: clocks fall back 03:00 AEDT -> 02:00 AEST.  The local day is 25 hours."""
    d = _build(sel, [("operation", "demand_maximum"), ("measure", "operational demand"),
                     ("region", "NSW1"), ("date", "2026-04-05"), ("scope_kind", "day")])
    x = C.executable(d, sel)
    assert x is not None
    assert (x.start_utc, x.end_utc) == ("2026-04-04T13:00:00Z", "2026-04-05T14:00:00Z")
    assert x.half_hours == 50


def test_qld1_no_dst_24_hours_on_spring_forward_date(sel):
    """QLD1 (Australia/Brisbane) has no DST: Oct 4 2026 is a normal 24-hour day."""
    d = _build(sel, [("operation", "demand_maximum"), ("measure", "operational demand"),
                     ("region", "QLD1"), ("date", "2026-10-04"), ("scope_kind", "day")])
    x = C.executable(d, sel)
    assert x is not None
    assert (x.start_utc, x.end_utc) == ("2026-10-03T14:00:00Z", "2026-10-04T14:00:00Z")
    assert x.half_hours == 48


# ------------------------------------------------------------------------------------------------ DST: half-hour at boundary
# A user-supplied local time that falls in a spring-forward gap (nonexistent) or a fall-back overlap
# (ambiguous) must not silently resolve: the workflow requires clarification.

def test_spring_forward_nonexistent_local_time_requires_clarification(sel):
    """NSW1 Oct 4 2026, half-hour ending 02:30: this local time does not exist (the clock jumps from 02:00
    to 03:00).  The workflow asks the user to give a time that exists; it does not silently resolve."""
    d = _build(sel, [("operation", "single_interval_comparison"), ("region", "NSW1"),
                     ("date", "2026-10-04"), ("half_hour_end", "02:30"),
                     ("run", "last_issued_before")])
    iss = C.issues(d, sel)
    assert len(iss) == 1 and iss[0].field == "half_hour_end"
    assert "does not exist" in iss[0].message
    assert C.executable(d, sel) is None


def test_spring_forward_valid_time_after_gap_compiles(sel):
    """03:30 AEDT is the first valid half-hour end after the gap: it compiles to the intended UTC interval."""
    d = _build(sel, [("operation", "single_interval_comparison"), ("region", "NSW1"),
                     ("date", "2026-10-04"), ("half_hour_end", "03:30"),
                     ("run", "last_issued_before")])
    assert C.issues(d, sel) == []
    x = C.executable(d, sel)
    assert x is not None
    assert (x.start_utc, x.end_utc) == ("2026-10-03T16:00:00Z", "2026-10-03T16:30:00Z")
    assert x.half_hours == 1
    assert "03:30 AEDT" in x.end_local


def test_spring_forward_valid_time_before_gap_compiles(sel):
    """01:30 AEST is the last valid half-hour end before the gap."""
    d = _build(sel, [("operation", "single_interval_comparison"), ("region", "NSW1"),
                     ("date", "2026-10-04"), ("half_hour_end", "01:30"),
                     ("run", "last_issued_before")])
    assert C.issues(d, sel) == []
    x = C.executable(d, sel)
    assert x is not None
    assert "01:30 AEST" in x.end_local


def test_fall_back_ambiguous_local_time_requires_disambiguation(sel):
    """NSW1 Apr 5 2026, half-hour ending 02:30: this local time exists twice (AEDT and AEST).
    The workflow offers two choices, one for each occurrence; it does not silently pick one."""
    d = _build(sel, [("operation", "single_interval_comparison"), ("region", "NSW1"),
                     ("date", "2026-04-05"), ("half_hour_end", "02:30"),
                     ("run", "last_issued_before")])
    iss = C.issues(d, sel)
    assert len(iss) == 1 and iss[0].field == "half_hour_end"
    assert "ambiguous" in iss[0].message
    assert len(iss[0].choices) == 2
    assert C.executable(d, sel) is None


def test_fall_back_disambiguated_first_occurrence_compiles(sel):
    """Choosing the first occurrence (AEDT, before the clocks fall back) gives the earlier UTC half-hour."""
    d = _build(sel, [("operation", "single_interval_comparison"), ("region", "NSW1"),
                     ("date", "2026-04-05"), ("half_hour_end", "02:30(0)"),
                     ("run", "last_issued_before")])
    assert C.issues(d, sel) == []
    x = C.executable(d, sel)
    assert x is not None
    assert (x.start_utc, x.end_utc) == ("2026-04-04T15:00:00Z", "2026-04-04T15:30:00Z")
    assert x.half_hours == 1


def test_fall_back_disambiguated_second_occurrence_compiles(sel):
    """Choosing the second occurrence (AEST, after the clocks fall back) gives the later UTC half-hour."""
    d = _build(sel, [("operation", "single_interval_comparison"), ("region", "NSW1"),
                     ("date", "2026-04-05"), ("half_hour_end", "02:30(1)"),
                     ("run", "last_issued_before")])
    assert C.issues(d, sel) == []
    x = C.executable(d, sel)
    assert x is not None
    assert (x.start_utc, x.end_utc) == ("2026-04-04T16:00:00Z", "2026-04-04T16:30:00Z")
    assert x.half_hours == 1


def test_explicit_period_with_nonexistent_boundary_requires_clarification(sel):
    """An explicit period starting at a time in the spring-forward gap requires clarification."""
    d = _build(sel, [("operation", "window_comparison"), ("region", "NSW1"),
                     ("date", "2026-10-04"), ("period", ("02:30", "05:00")),
                     ("run", "latest_before_each")])
    iss = C.issues(d, sel)
    assert len(iss) == 1 and iss[0].field == "period"
    assert "does not exist" in iss[0].message
    assert C.executable(d, sel) is None


def test_explicit_period_with_ambiguous_boundary_offers_occurrence_choices(sel):
    """NSW1 Apr 5 2026, period ending 02:30: the end boundary occurs twice.  The workflow offers two choices,
    one per occurrence, rather than forcing the user to pick a different time."""
    d = _build(sel, [("operation", "window_comparison"), ("region", "NSW1"),
                     ("date", "2026-04-05"), ("period", ("01:00", "02:30")),
                     ("run", "latest_before_each")])
    iss = C.issues(d, sel)
    assert len(iss) == 1 and iss[0].field == "period"
    assert "ambiguous" in iss[0].message
    assert len(iss[0].choices) == 2
    assert "first occurrence" in iss[0].choices[0].label
    assert "second occurrence" in iss[0].choices[1].label
    assert C.executable(d, sel) is None


def test_explicit_period_with_disambiguated_boundary_compiles(sel):
    """After selecting the first occurrence of the ambiguous end boundary, the period compiles."""
    d = _build(sel, [("operation", "window_comparison"), ("region", "NSW1"),
                     ("date", "2026-04-05"), ("period", "01:00-02:30(0)"),
                     ("run", "latest_before_each")])
    assert C.issues(d, sel) == []
    x = C.executable(d, sel)
    assert x is not None
    assert x.start_utc == "2026-04-04T14:00:00Z"
    assert x.end_utc == "2026-04-04T15:30:00Z"


# ------------------------------------------------------------------------------------------------ total demand
def test_total_demand_supported_for_demand_maximum(sel):
    """Total demand is a valid measure for demand_maximum: it compiles and maps to get_price_timeline."""
    d = _build(sel, [("operation", "demand_maximum"), ("measure", "total demand"),
                     ("region", "NSW1"), ("date", "2026-07-31"), ("scope_kind", "day")])
    x = C.executable(d, sel)
    assert x is not None and x.measure == "total demand"
    assert C.issues(d, sel) == []
    req = C.requirement(x)
    assert req.tools == ("get_price_timeline",)
    assert req.result_kind == "demand_maximum"


def test_forecast_ops_hardcode_operational_demand(sel):
    """Forecast operations always use 'operational demand' regardless of the draft; the measure field is not
    asked about for forecast ops."""
    d = _build(sel, [("operation", "window_comparison"), ("region", "NSW1"),
                     ("date", "2026-07-31"), ("scope_kind", "day"),
                     ("run", "latest_before_each")])
    x = C.executable(d, sel)
    assert x is not None and x.measure == "operational demand"
    req = C.requirement(x)
    assert req.tools == ("compare_forecast_actual",)


def test_measure_choice_offered_only_for_demand_maximum(sel):
    """issues() asks about measure only for demand_maximum; forecast ops skip the measure question entirely."""
    d_max = _build(sel, [("operation", "demand_maximum")])
    assert C.issues(d_max, sel)[0].field == "measure"

    d_win = _build(sel, [("operation", "window_comparison")])
    assert C.issues(d_win, sel)[0].field == "region"


# ------------------------------------------------------------------------------------------------ explicit vs absent cutoff
def test_explicit_cutoff_vs_absent_on_same_request(sel):
    """An explicit cutoff appears in the Executable; absent produces None.  Other fields are identical."""
    base = [("operation", "demand_maximum"), ("measure", "operational demand"),
            ("region", "QLD1"), ("date", "2026-07-29"), ("scope_kind", "day")]

    x_absent = C.executable(_build(sel, base), sel)
    x_cutoff = C.executable(_build(sel, base + [("cutoff", "2026-07-29T06:00:00Z")]), sel)

    assert x_absent.cutoff_utc is None
    assert x_cutoff.cutoff_utc == "2026-07-29T06:00:00Z"
    for f in ("operation", "measure", "region", "date", "scope_kind", "start_utc", "end_utc", "half_hours"):
        assert getattr(x_absent, f) == getattr(x_cutoff, f), f


def test_unresolved_cutoff_triggers_clarification(sel):
    """A cutoff that is 'unresolved' produces a clarification question; 'absent' is one of the choices."""
    d = _build(sel, [("operation", "demand_maximum"), ("measure", "operational demand"),
                     ("region", "QLD1"), ("date", "2026-07-29"), ("scope_kind", "day")])
    d = d.model_copy(update={"cutoff": "unresolved", "blocked": {"cutoff": "stated but not pinned down"}})
    iss = C.issues(d, sel)
    assert len(iss) == 1 and iss[0].field == "cutoff"
    assert any(c.value == "absent" for c in iss[0].choices)
    assert C.executable(d, sel) is None


# ------------------------------------------------------------------------------------------------ missing fields -> clarification
def test_missing_date_triggers_clarification(sel):
    """A draft with operation, measure, and region but no date asks for a date."""
    d = _build(sel, [("operation", "demand_maximum"), ("measure", "operational demand"),
                     ("region", "NSW1")])
    iss = C.issues(d, sel)
    assert len(iss) == 1 and iss[0].field == "date"
    assert C.executable(d, sel) is None


def test_missing_operation_asks_for_operation_first(sel):
    """With no operation set, the first issue is always the operation choice."""
    d = C.Draft(question="SYNTHETIC", origin="structured")
    iss = C.issues(d, sel)
    assert iss[0].field == "operation"
    assert {c.value for c in iss[0].choices} == set(C.OPERATIONS)
    assert C.executable(d, sel) is None


def test_missing_run_triggers_clarification_for_single_interval(sel):
    """A single-interval comparison without a run asks for one; two choices are offered."""
    d = _build(sel, [("operation", "single_interval_comparison"), ("region", "SA1"),
                     ("date", "2026-08-20"), ("half_hour_end", "08:00")])
    iss = C.issues(d, sel)
    assert len(iss) == 1 and iss[0].field == "run"
    assert {c.value for c in iss[0].choices} == {"last_issued_before", "issued_at"}
    assert C.executable(d, sel) is None


# ------------------------------------------------------------------------------------------------ playbook tool vs actual arguments
# The parametrized test below verifies the PLAYBOOK: which tool is allowed and the result kind.
# The test_resolution_carries_actual_arguments test verifies the ACTUAL ARGUMENTS passed through
# to_resolution(): the window/target bounds, run selection, measures, and cutoff that the dispatcher
# passes to the tool.

@pytest.mark.parametrize("operation, measure, steps, expected_tool, expected_kind", [
    ("demand_maximum", "operational demand",
     [("region", "QLD1"), ("date", "2026-07-29"), ("scope_kind", "day")],
     "get_actual_demand", "demand_maximum"),
    ("demand_maximum", "total demand",
     [("region", "NSW1"), ("date", "2026-07-31"), ("scope_kind", "day")],
     "get_price_timeline", "demand_maximum"),
    ("single_interval_comparison", "operational demand",
     [("region", "SA1"), ("date", "2026-08-20"), ("half_hour_end", "08:00"),
      ("run", "last_issued_before")],
     "compare_forecast_actual", "forecast_point"),
    ("window_comparison", "operational demand",
     [("region", "NSW1"), ("date", "2026-07-31"), ("scope_kind", "day"),
      ("run", "latest_before_each")],
     "compare_forecast_actual", "forecast_aggregate"),
], ids=["opdemand maximum", "totaldemand maximum", "single-interval comparison", "window comparison"])
def test_playbook_allows_exactly_one_tool_and_kind(operation, measure, steps, expected_tool,
                                                   expected_kind, sel):
    """Each supported operation compiles to exactly one allowed tool and one result kind (the playbook)."""
    full = [("operation", operation)]
    if operation == "demand_maximum":
        full.append(("measure", measure))
    full.extend(steps)
    d = _build(sel, full)
    x = C.executable(d, sel)
    assert x is not None
    req = C.requirement(x)
    assert req.tools == (expected_tool,) and req.result_kind == expected_kind
    pb = C.confirmed_playbook(x)
    assert pb.required == (expected_tool,) and pb.max_calls_per_required_tool == 1


def test_resolution_carries_actual_arguments(sel):
    """to_resolution() builds the Resolution whose fields become the tool's actual arguments: the window or
    target bounds, the measure, the run selection, and the cutoff.  These are distinct from the playbook (which
    tool is allowed); they determine WHAT the tool computes."""
    # Demand maximum: the window and measure
    x_max = C.executable(_build(sel, [
        ("operation", "demand_maximum"), ("measure", "total demand"),
        ("region", "NSW1"), ("date", "2026-07-31"), ("scope_kind", "day")]), sel)
    res_max = C.to_resolution(x_max, sel)
    assert res_max.requests.maximum.window == (parse_iso(x_max.start_utc), parse_iso(x_max.end_utc))
    assert res_max.requests.maximum.measures == ["total demand"]
    assert res_max.as_of is None

    # Single-interval comparison: the target and the run selection
    x_pt = C.executable(_build(sel, [
        ("operation", "single_interval_comparison"), ("region", "SA1"), ("date", "2026-08-20"),
        ("half_hour_end", "08:00"), ("run", "last_issued_before")]), sel)
    res_pt = C.to_resolution(x_pt, sel)
    assert res_pt.requests.forecast.target == (parse_iso(x_pt.start_utc), parse_iso(x_pt.end_utc))
    assert res_pt.requests.forecast.operation == "single_interval_comparison"
    assert res_pt.requests.forecast_run.selection == "last_issued_before"
    assert res_pt.as_of is None

    # Window comparison with a cutoff: the window, run policy, and as-of
    x_agg = C.executable(_build(sel, [
        ("operation", "window_comparison"), ("region", "NSW1"), ("date", "2026-07-31"),
        ("scope_kind", "day"), ("run", "latest_before_each"),
        ("cutoff", "2026-07-31T02:00:00Z")]), sel)
    res_agg = C.to_resolution(x_agg, sel)
    assert res_agg.requests.forecast.window == (parse_iso(x_agg.start_utc), parse_iso(x_agg.end_utc))
    assert res_agg.requests.forecast.operation == "window_comparison"
    assert res_agg.as_of == parse_iso("2026-07-31T02:00:00Z")


# ------------------------------------------------------------------------------------------------ session lifecycle
def test_new_question_resets_session_completely(sel):
    """Calling start() with a new question replaces the entire session: draft, results, confirmation."""
    state = C.new_state()
    d = _build(sel, [("operation", "demand_maximum"), ("measure", "operational demand"),
                     ("region", "QLD1"), ("date", "2026-07-29"), ("scope_kind", "day")])
    state["draft"] = d.model_dump()
    state["results"]["fake_rid"] = "placeholder"
    state["confirmed"] = "fake_rid"
    state["history"].append({"role": "user", "text": "first question"})

    C.start(state, "A completely different question", None)
    d2 = C.draft_of(state)
    assert d2 is not None and d2.question == "A completely different question"
    assert state["results"] == {} and state["confirmed"] is None
    assert d2.operation is None
    assert not any(h["text"] == "first question" for h in state["history"])


def test_draft_provenance_tracks_field_source(sel):
    """Every field set by structured choice records source 'you'."""
    d = _build(sel, [("operation", "demand_maximum"), ("measure", "operational demand"),
                     ("region", "NSW1"), ("date", "2026-07-31"), ("scope_kind", "day")])
    for f in ("operation", "measure", "region", "date", "scope_kind"):
        assert d.sources[f] == "you", f


# ------------------------------------------------------------------------------------------------ fake-tool execution
# This test goes beyond to_resolution(): it confirms a draft, executes it with execute_confirmed(), and verifies
# that the resolution passed to the actual tool carries the intended region, UTC interval, measure, forecast-run
# policy, and cutoff.

def _confirm_and_execute(d: C.Draft, sel: Any) -> Any:
    """Confirm a complete draft and execute it with the real offline tool chain (no routing model)."""
    from nem_agent.service import execute_confirmed

    x = C.executable(d, sel)
    assert x is not None, f"draft not complete: {C.issues(d, sel)}"
    state = C.new_state()
    state["draft"] = d.model_dump()
    rid = C.revision_id(x)
    assert C.confirm(state, rid, sel)
    pending = C.take_pending(state, sel)
    assert pending is not None and pending == x
    return execute_confirmed(pending, original=None, write_trace=False)


def test_execution_passes_intended_arguments_to_tool(sel):
    """A confirmed demand-maximum request with a cutoff passes the intended region, UTC interval,
    measure, and cutoff through to the tool's resolution — verified by executing with fake ledger."""
    d = _build(sel, [("operation", "demand_maximum"), ("measure", "total demand"),
                     ("region", "NSW1"), ("date", "2026-07-31"), ("scope_kind", "day"),
                     ("cutoff", "2026-07-31T02:00:00Z")])
    res = _confirm_and_execute(d, sel)
    r = res.resolution
    assert r.region == "NSW1"
    assert r.requests.maximum.window == (parse_iso("2026-07-30T14:00:00Z"), parse_iso("2026-07-31T14:00:00Z"))
    assert r.requests.maximum.measures == ["total demand"]
    assert r.as_of == parse_iso("2026-07-31T02:00:00Z")
    assert res.report.answer[0].kind == "demand_maximum"


def test_execution_passes_forecast_run_policy_to_tool(sel):
    """A confirmed single-interval comparison passes the run selection and target interval to the tool."""
    d = _build(sel, [("operation", "single_interval_comparison"), ("region", "SA1"),
                     ("date", "2026-08-20"), ("half_hour_end", "08:00"),
                     ("run", "last_issued_before")])
    res = _confirm_and_execute(d, sel)
    r = res.resolution
    assert r.region == "SA1"
    fa = r.requests.forecast
    assert fa.target == (parse_iso("2026-08-19T22:00:00Z"), parse_iso("2026-08-19T22:30:00Z"))
    assert fa.operation == "single_interval_comparison"
    assert r.requests.forecast_run.selection == "last_issued_before"
    assert r.as_of is None
    assert res.report.answer[0].kind == "forecast_point"
