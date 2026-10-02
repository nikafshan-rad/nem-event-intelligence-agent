"""Issue I-10 (docs/issue-tracker.md): an as-of forecast question is dated by its explicit cutoff.

Held-out v5 Y07 (Live, 2026-10-02): "As of 2026-08-19T20:00:00Z, looking only at runs already public, what was the
newest Victorian operational demand forecast for the 23:00 to 23:30 UTC half-hour, at POE10, POE50 and POE90?" was sent
back with "Which date (or UTC window) should be investigated?". The resolver finds no date inside an ISO timestamp, and
the routing policy applied the routing model's request for a date unchanged; either alone sends it back.

Now, for a forecast question with one region and no date, an explicit cutoff gives the day reviewed (its date in the
region's local calendar), and the model's request for a missing date is not applied. Every other clarification stays.
Replays use the saved Live record through the SYNTHETIC fake transport (no network, no key).
"""

from __future__ import annotations

import copy
import json
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


# ------------------------------------------------------------------------------------------------ Y07
def test_y07_is_dated_by_its_cutoff_and_not_sent_back():
    res = _run(Q07, ROUTE07)
    r = res.resolution
    assert r.status == "ok" and res.report.status != "needs_clarification"
    assert r.as_of is not None and r.as_of.isoformat() == "2026-08-19T20:00:00+00:00"
    assert r.routing["date_from_as_of"] == "2026-08-20"  # 06:00 AEST on 20 August
    assert r.window[0].isoformat() <= "2026-08-19T23:00:00+00:00" and r.window[1].isoformat() >= "2026-08-19T23:30:00+00:00"
    notes = next(e for e in _route_events(res) if e["name"] == "model_decision")["policy_notes"]
    assert any("explicit as-of cutoff gives the date" in n for n in notes)


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


def test_a_cutoff_given_with_the_request_dates_the_question_too():
    q = ("Looking only at runs already public, what was the newest Victorian operational demand forecast for the 23:00 "
         "to 23:30 UTC half-hour?")
    res = _run(q, {**ROUTE07, "as_of_utc": None}, as_of=CUTOFF)
    assert res.resolution.status == "ok" and res.resolution.routing["date_from_as_of"] == "2026-08-20"


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
    assert "date_from_as_of" not in (res.resolution.routing or {}) or why == "a clarification given for another reason"
