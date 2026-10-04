"""Issue I-10 (docs/issue-tracker.md): an as-of forecast question is dated by its explicit cutoff.

Held-out v5 Y07 (Live, 2026-10-02): "As of 2026-08-19T20:00:00Z, looking only at runs already public, what was the
newest Victorian operational demand forecast for the 23:00 to 23:30 UTC half-hour, at POE10, POE50 and POE90?" was sent
back with "Which date (or UTC window) should be investigated?". The resolver finds no date inside an ISO timestamp, and
the routing policy applied the routing model's request for a date unchanged; either alone sends it back.

Now the target half-hour and the availability cutoff are kept apart. The cutoff says what was public; the target is
the half-hour asked about. An explicit date or ISO time names the target. A clock-only half-hour (with its zone) is
dated by the cutoff only when its occurrence on the cutoff's own date falls after the cutoff; otherwise the question is
sent back. The window reviewed, and the forecast targets the model is given, contain the target. Replays use the saved
Live record through the SYNTHETIC fake transport (no network, no key).
"""

from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path

import pytest

from nem_agent.agent.request import InvestigateRequest
from nem_agent.service import investigate
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

V5 = Path(__file__).resolve().parents[2] / "artifacts" / "live" / "L3-holdout-v5"
REC = json.loads((V5 / "Y07.json").read_text())
Q07, ROUTE07 = REC["question"], REC["route"]  # the saved decision: needs_clarification, missing_region_or_date
CUTOFF = "2026-08-19T20:00:00Z"
HALF = {"region": "VIC1", "target_start_utc": "2026-08-19T23:00:00Z", "target_end_utc": "2026-08-19T23:30:00Z"}


def _run(question: str, route: dict, calls: list | None = None, draft_fn=None, as_of: str | None = None):
    fake = FakeModel(route, [calls] if calls else [], draft_fn or (lambda kw: {}))
    return investigate(InvestigateRequest(question=question, mode="live", as_of_utc=as_of), live_client=fake,
                       write_trace=False)


def _route_events(res) -> list[dict]:
    return [e for e in res.trace.as_dict()["events"] if e["kind"] == "route"]


def _targets(fake) -> list[str] | None:
    """The forecast targets the model was given in its context (None when no tool loop ran): since D28 the half-hour or
    period the forecast request asks about."""
    if len(fake.requests) < 2:
        return None
    ctx = json.loads(fake.requests[1]["input"][0]["content"].split("\n", 1)[1])
    fr = ctx.get("forecast_request")
    return [fr["start_utc"], fr["end_utc"]] if fr else ctx.get("forecast_targets_utc")


def _covers(span, target) -> bool:
    return span[0] <= target[0] and target[1] <= span[1]


def _run_f(question: str, route: dict, as_of: str | None = None):
    fake = FakeModel(route, [], lambda kw: {})
    res = investigate(InvestigateRequest(question=question, mode="live", as_of_utc=as_of), live_client=fake,
                      write_trace=False)
    return res, fake


# ------------------------------------------------------------------------------------------------ Y07
def test_y07_keeps_its_target_half_hour_and_its_cutoff():
    res, fake = _run_f(Q07, ROUTE07)
    r = res.resolution
    assert r.status == "ok" and res.report.status != "needs_clarification"
    assert [t.isoformat() for t in r.target] == ["2026-08-19T23:00:00+00:00", "2026-08-19T23:30:00+00:00"]
    assert r.as_of.isoformat() == "2026-08-19T20:00:00+00:00"  # the cutoff stays the availability cutoff
    assert r.routing["target_dated_by_cutoff"] == ["2026-08-19T23:00:00Z", "2026-08-19T23:30:00Z"]
    assert _covers(r.window, r.target)
    assert _covers(_targets(fake), ["2026-08-19T23:00:00Z", "2026-08-19T23:30:00Z"])  # the tools' targets too
    notes = next(e for e in _route_events(res) if e["name"] == "model_decision")["policy_notes"]
    assert any("dated by the explicit as-of cutoff" in n for n in notes)


def _faithful(kw):
    """An answer from the run public by the cutoff, as the forecast-runs tool returned it under the cutoff."""
    runs = next(json.loads(i["output"])["result"]["runs"] for i in kw["input"]
                if isinstance(i, dict) and i.get("type") == "function_call_output"
                and "runs" in (json.loads(i["output"]).get("result") or {}))
    latest = max(runs, key=lambda r: r["published_at_utc"])
    v = next(x for x in latest["values"] if x["target_end_utc"] == "2026-08-19T23:30:00Z")
    items = [("POE10", v["poe10_evidence_id"], v["poe10_mw"]), ("POE50", v["poe50_evidence_id"], v["poe50_mw"]),
             ("POE90", v["poe90_evidence_id"], v["poe90_mw"])]
    base = json.loads((V5 / "Y08.json").read_text())["drafts"]["synthesis:draft"]
    return {**copy.deepcopy(base), "forecast_mae_evidence_id": None, "uncertainties": [], "missing_evidence": [],
            "possible_explanations": [], "published_findings": [], "citations": [], "document_statements": [],
            "observation_evidence_ids": [e for _, e, _ in items],
            "numeric_claims": [{"claim_id": f"n{k + 1}", "text": f"{lab} {val:.1f} MW", "value": val, "unit": "MW",
                                "evidence_id": e, "rounding": 0.0} for k, (lab, e, val) in enumerate(items)],
            "headline": f"The newest run public by the cutoff gave POE50 {v['poe50_mw']:.1f} MW for the half-hour.",
            "summary": [f"POE10 {v['poe10_mw']:.1f} MW, POE50 {v['poe50_mw']:.1f} MW, POE90 {v['poe90_mw']:.1f} MW."]}


def test_y07_answered_from_the_run_public_by_the_cutoff_passes():
    calls = [("get_forecast_runs", {**HALF, "max_runs": 3}),
             ("get_actual_demand", {"region": "VIC1", "start_utc": "2026-08-19T14:00:00Z", "end_utc": "2026-08-20T14:00:00Z"}),
             ("compare_forecast_actual", {**HALF, "run_selector": "latest_available_as_of", "as_of_utc": CUTOFF}),
             ("retrieve_public_evidence", {"query": "operational demand forecast POE", "region": "VIC1"})]
    res = _run(Q07, ROUTE07, calls, _faithful)
    v = res.report.validation
    assert v["final_passed"] and not v["fallback_applied"], v["initial"]["violations"]
    shown = {o.metric: o.value for o in res.report.observations}
    assert (shown["opdemand_forecast_poe10"], shown["opdemand_forecast_poe50"], shown["opdemand_forecast_poe90"]) == \
        (6689.0, 6447.0, 6204.0)
    assert "opdemand_actual" not in shown  # no actual was public by the cutoff
    runs = next(r for r in res.records if r.name == "get_forecast_runs")
    assert runs.args["as_of_utc"] == CUTOFF  # the cutoff still applies to every tool call
    assert max(runs.view["runs"], key=lambda r: r["published_at_utc"])["issued_at_utc"] == "2026-08-19T16:56:58Z"


def test_a_cutoff_given_with_the_request_dates_a_clock_only_half_hour_after_it():
    q = ("Looking only at runs already public, what was the newest Victorian operational demand forecast for the 23:00 "
         "to 23:30 UTC half-hour?")
    res = _run(q, {**ROUTE07, "as_of_utc": None}, as_of=CUTOFF)
    assert res.resolution.status == "ok"
    assert [t.isoformat() for t in res.resolution.target] == ["2026-08-19T23:00:00+00:00", "2026-08-19T23:30:00+00:00"]


# ------------------------------------------------------------------------------------------------ explicit target dates
ANSWER = {**ROUTE07, "needs_clarification": False, "clarification_reason": None, "clarification": None}


@pytest.mark.parametrize("question,cutoff,event_date,target,window_day", [
    # the target date is two days after the cutoff's local date (20 August in VIC1)
    ("As of 2026-08-19T20:00:00Z, looking only at runs already public, what was the newest Victorian operational demand "
     "forecast for the half-hour ending 09:30 AEST on 21 August 2026?", "2026-08-19T20:00:00Z", "2026-08-21",
     ("2026-08-20T23:00:00Z", "2026-08-20T23:30:00Z"), None),
    # a UTC date whose half-hour falls on the next local day (00:30-01:00 AEST on the 22nd): the date's local day
    # would miss it, so the window moves to the target's day
    ("As of 2026-08-21T12:00:00Z, looking only at runs already public, what was the newest Victorian operational demand "
     "forecast for the half-hour ending 15:00 UTC on 21 August 2026?", "2026-08-21T12:00:00Z", "2026-08-21",
     ("2026-08-21T14:30:00Z", "2026-08-21T15:00:00Z"), "2026-08-22"),
])
def test_an_explicit_target_date_is_used_not_the_cutoffs(question, cutoff, event_date, target, window_day):
    res, fake = _run_f(question, {**ANSWER, "event_date": event_date, "as_of_utc": cutoff})
    r = res.resolution
    t = (datetime.fromisoformat(target[0].replace("Z", "+00:00")), datetime.fromisoformat(target[1].replace("Z", "+00:00")))
    assert r.status == "ok" and r.target == t and r.as_of.isoformat() == cutoff.replace("Z", "+00:00")
    assert "target_dated_by_cutoff" not in r.routing  # the date came from the question, not the cutoff
    assert _covers(r.window, r.target) and _covers(_targets(fake), list(target))
    assert r.routing.get("window_from_target") == window_day


# ------------------------------------------------------------------------------------------------ across local midnight
@pytest.mark.parametrize("half_hour,target", [
    ("23:30 to 00:00 AEST", ("2026-08-19T13:30:00Z", "2026-08-19T14:00:00Z")),  # ends at local midnight
    ("14:00 to 14:30 UTC", ("2026-08-19T14:00:00Z", "2026-08-19T14:30:00Z")),  # starts the next local day
])
def test_a_target_across_local_midnight_is_kept_with_its_window(half_hour, target):
    """Cutoff 2026-08-19T12:00Z is 22:00 AEST on the 19th; the half-hour asked about ends at, or starts after, local
    midnight. The window and the forecast targets contain it."""
    q = (f"As of 2026-08-19T12:00:00Z, looking only at runs already public, what was the newest Victorian operational "
         f"demand forecast for the {half_hour} half-hour?")
    res, fake = _run_f(q, {**ROUTE07, "as_of_utc": "2026-08-19T12:00:00Z"})
    r = res.resolution
    assert r.status == "ok", r.reasons
    assert [x.isoformat().replace("+00:00", "Z") for x in r.target] == list(target)
    assert _covers(r.window, r.target) and _covers(_targets(fake), list(target))


# ------------------------------------------------------------------------------------------------ ambiguous targets
@pytest.mark.parametrize("question,why", [
    ("As of 2026-08-19T20:00:00Z, looking only at runs already public, what was the newest Victorian operational demand "
     "forecast for the 10:00 to 10:30 UTC half-hour?", "on the cutoff's date it is before the cutoff: today or tomorrow"),
    ("As of 2026-08-19T20:00:00Z, looking only at runs already public, what was the newest Victorian operational demand "
     "forecast for the 23:00 to 23:30 half-hour?", "no time zone"),
    ("As of 2026-08-19T20:00:00Z, what were the newest Victorian operational demand forecasts?", "no half-hour at all"),
])
@pytest.mark.parametrize("model_asks", [True, False])
def test_an_ambiguous_target_date_is_asked_about_not_taken_from_the_cutoff(question, why, model_asks):
    route = ROUTE07 if model_asks else {**ANSWER, "as_of_utc": CUTOFF}
    res, fake = _run_f(question, route)
    assert res.report.status == "needs_clarification", why
    assert res.resolution.target is None and _targets(fake) is None
    if not model_asks:  # the resolver itself asks, saying why the cutoff does not give the date
        assert any("not which day the forecast is for" in x for x in res.resolution.reasons)


# ------------------------------------------------------------------------------------------------ still sent back
def _asks(reason: str, **route) -> dict:
    return {**ROUTE07, "needs_clarification": True, "clarification_reason": reason,
            "clarification": "Which date do you mean?", **route}


@pytest.mark.parametrize("question,route,why", [
    ("As of 2026-08-19T20:00:00Z, looking only at runs already public, what was the newest operational demand forecast "
     "for the 23:00 to 23:30 UTC half-hour?", _asks("missing_region_or_date", region=None), "no region"),
    ("As of 2026-08-19T20:00:00Z, what were the newest Victorian and South Australian operational demand forecasts for "
     "the 23:00 to 23:30 UTC half-hour?", _asks("several_regions", region=None), "several regions"),
    ("As of 2026-08-19T20:00:00Z, compare the newest Victorian operational demand forecasts for 20 August 2026 and 21 "
     "August 2026.", _asks("several_dates"), "several dates"),
    ("As of 20:00, looking only at runs already public, what was the newest Victorian operational demand forecast for "
     "the 23:00 to 23:30 UTC half-hour?", _asks("missing_region_or_date", as_of_utc=None), "a cutoff without a date"),
    ("What was the newest Victorian operational demand forecast for the 23:00 to 23:30 UTC half-hour?",
     _asks("missing_region_or_date", as_of_utc=None), "no cutoff and no date"),
    (Q07, _asks("unclear_question"), "a clarification given for another reason"),
    ("As of 2026-08-19T20:00:00Z, what was the highest Victorian spot price so far?",
     _asks("missing_region_or_date", intent="market_event_review"), "a market-event question"),
])
def test_other_clarifications_are_still_asked(question, route, why):
    res = _run(question, route)
    assert res.report.status == "needs_clarification", why
