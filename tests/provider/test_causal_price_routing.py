"""Issue I-11 (docs/issue-tracker.md): a question asking whether something caused or explains a price event is an event
review, even when the routing model calls it a forecast question.

Held-out v5 Y18 (Live, 2026-10-02): "Was AEMO's forecast lack of reserve the reason South Australia's price spiked at
07:55 UTC on 29 July 2026?" was routed as forecast_review and applied unchanged. find_market_events was not run, and the
event-review features (notice timing, the I-1b cancellation sentence) never ran, so the answer did not say that the
day's reserve notices were each cancelled beforehand.

Now the routing policy sends such a question to the event review, unless it asks about forecast accuracy or is an
as-of question. Replays use saved Live records through the SYNTHETIC fake transport (no network, no key): Y18's question
and routing decision, with the same event's market-review tool calls and drafts from W19 (second development check).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from nem_agent.agent.playbook import PLAYBOOKS
from nem_agent.agent.request import InvestigateRequest
from nem_agent.evaluation.runner import CAUSAL, _narrative_without_quotes_and_hypotheses
from nem_agent.service import investigate, route_policy
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

LIVE = Path(__file__).resolve().parents[2] / "artifacts" / "live"
Y18 = json.loads((LIVE / "L3-holdout-v5" / "Y18.json").read_text())
Q18, ROUTE18 = Y18["question"], Y18["route"]  # the saved decision: forecast_review
CANCELLED = "AEMO later cancelled what these cited notices announced, each before the price extreme"


def _decision(**kw) -> SimpleNamespace:
    base = {"intent": "forecast_review", "region": "SA1", "event_date": "2026-07-29", "as_of_utc": None,
            "needs_clarification": False, "clarification_reason": None, "clarification": None, "out_of_scope": False}
    return SimpleNamespace(**{**base, **kw})


def _routed(question: str, **kw) -> tuple[str, list[str]]:
    upd, _, notes = route_policy(InvestigateRequest(question=question, mode="live"), _decision(**kw))
    return upd["intent"], notes


def _parts(path: Path):
    rec = json.loads(path.read_text())
    trace = json.loads((path.parent / "traces" / f"{rec['score']['trace_id']}.json").read_text())["events"]
    patch = next((e.get("patch") for e in trace if e["name"] == "repair:scoped"), None)
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    return calls, rec["drafts"]["synthesis:draft"], patch


def _without_the_demand_forecast(draft: dict) -> dict:
    """SYNTHETIC variant (D29): Y18's question mentions a forecast without showing which, so the demand-forecast tools
    are not eligible for it. W19's draft is used without the items resting on its demand forecast: the POE50 clause of
    summary[4], claim c8 and evidence ev1000 (the other items, and their indices for the saved patch, are kept)."""
    d = copy.deepcopy(draft)
    assert "POE50 2042.0 MW" in d["summary"][4]
    d["summary"][4] = ("The measured half-hour operational demand for the half-hour ending 2026-07-29T08:00:00Z was "
                       "1872.0 MW (ev0912).")
    d["numeric_claims"] = [c for c in d["numeric_claims"] if c["evidence_id"] != "ev1000"]
    d["observation_evidence_ids"] = [e for e in d["observation_evidence_ids"] if e != "ev1000"]
    for h in d["possible_explanations"]:
        h["supporting_evidence_ids"] = [e for e in h["supporting_evidence_ids"] if e != "ev1000"]
    return d


def _replay(source: Path, question: str = Q18, route: dict | None = None, variant=None):
    calls, draft, patch = _parts(source)
    draft = variant(draft) if variant else draft
    fake = FakeModel(route or ROUTE18, [calls], lambda kw: copy.deepcopy(draft),
                     (lambda kw: copy.deepcopy(patch)) if patch else None)
    return investigate(InvestigateRequest(question=question, mode="live"), live_client=fake, write_trace=False)


# ------------------------------------------------------------------------------------------------ Y18
def test_y18_is_routed_as_an_event_review():
    intent, notes = _routed(Q18, **{k: v for k, v in ROUTE18.items() if k != "intent"})
    assert intent == "market_event_review"
    assert notes == ["routed as market_event_review: the question asks whether something explains a price event"]


@pytest.fixture(scope="module")
def y18_on_the_event_route():
    """Y18's question and saved routing decision, with the same event's market-review tool calls and drafts (W19), less
    the draft items resting on the demand forecast that D29 makes ineligible for Y18's question."""
    return _replay(LIVE / "live-check-dev2" / "W19.json", variant=_without_the_demand_forecast)


def test_y18s_composite_as_saved_rests_on_a_demand_forecast_that_is_not_eligible():
    """D29: Y18 mentions a forecast ("AEMO's forecast lack of reserve") without showing which, so the demand-forecast
    tools are not eligible for it. W19's draft as saved states a POE50 from a forecast run: that call is blocked, the
    claim and the hypothesis citing it are rejected, and the answer falls back (validated); the controller still
    computes the cancellation sentence, and a note says no demand forecast is used for the forecast mentioned."""
    res = _replay(LIVE / "live-check-dev2" / "W19.json")
    (blocked,) = [r for r in res.records if r.name == "get_forecast_runs"]
    assert blocked.status == "blocked" and "not eligible for this request" in blocked.blocked_reason
    v = res.report.validation
    codes = {(x["code"], x["detail"]) for x in v["initial"]["violations"]}
    assert ("CLAIM_EVIDENCE_MISSING", "c8 cites unknown evidence ev1000") in codes
    assert v["fallback_applied"] and v["final_passed"] and "2042" not in json.dumps(res.report.summary)
    assert any(e["name"] == "cancellation_answer" for e in res.trace.as_dict()["events"])
    assert res.report.uncertainties[0].startswith("The question also mentions a forecast without showing which")


def test_y18_runs_the_event_review_and_its_required_tools(y18_on_the_event_route):
    res = y18_on_the_event_route
    assert res.resolution.intent == "market_event_review"
    ran = {r.name for r in res.records if r.status == "ok"}
    assert set(PLAYBOOKS["market_event_review"].required) <= ran  # find_market_events included (Q2)


def test_the_cancellation_handling_works_on_the_corrected_route(y18_on_the_event_route):
    """The controller's cancellation sentence (I-1b): each cited reserve notice, and when it was cancelled, before the
    price extreme; the answer passes, with the 845 $/MWh peak and no cause asserted."""
    rep = y18_on_the_event_route.report
    v = rep.validation
    assert v["final_passed"] and not v["fallback_applied"], v["initial"]["violations"]
    assert rep.summary[0].startswith(CANCELLED) and "was cancelled by one issued" in rep.summary[0]
    assert any(o.metric == "dispatch_rrp" and o.value == 845.0 for o in rep.observations)
    assert not CAUSAL.findall(_narrative_without_quotes_and_hypotheses(rep.model_dump()))


def test_y18s_forecast_route_answer_is_not_accepted_on_the_event_route():
    """Y18's own saved answer (written for a forecast review) now gets the cancellation sentence from the controller,
    and is held to the event review's checks: it never set the notices' times against the event, so it falls back."""
    res = _replay(LIVE / "L3-holdout-v5" / "Y18.json")
    assert res.resolution.intent == "market_event_review"
    assert any(e["name"] == "cancellation_answer" for e in res.trace.as_dict()["events"])
    codes = {x["code"] for x in res.report.validation["initial"]["violations"]}
    assert "NOTICE_TIMING_OMITTED" in codes and res.report.validation["fallback_applied"]


def test_on_main_the_same_material_stays_a_forecast_review_without_the_cancellation():
    """The defect, kept as a check on the rule itself: with the routing model's intent applied unchanged (an explicit
    forecast intent in the request bypasses the policy), the event-review features do not run."""
    calls, draft, patch = _parts(LIVE / "live-check-dev2" / "W19.json")
    fake = FakeModel(ROUTE18, [calls], lambda kw: copy.deepcopy(draft), lambda kw: copy.deepcopy(patch))
    res = investigate(InvestigateRequest(question=Q18, mode="live", intent="forecast_review"), live_client=fake,
                      write_trace=False)
    assert res.resolution.intent == "forecast_review"
    assert not any(e["name"] == "cancellation_answer" for e in res.trace.as_dict()["events"])


# ------------------------------------------------------------------------------------------------ controls
@pytest.mark.parametrize("question,model_intent,expected,why", [
    ("Did AEMO forecast a lack of reserve for South Australia on 29 July 2026, and was it later cancelled?",
     "forecast_review", "forecast_review", "a genuine reserve-forecast question: no price event"),
    ("What did AEMO forecast for South Australia's operational demand on 29 July 2026?",
     "forecast_review", "forecast_review", "a demand forecast question"),
    ("How accurate was the operational demand forecast during South Australia's price spike on 29 July 2026?",
     "forecast_review", "forecast_review", "forecast accuracy around a price spike"),
    ("Was a forecast error the reason South Australia's price spiked on 29 July 2026?",
     "forecast_review", "forecast_review", "ambiguous: forecast accuracy and cause; the model's route is kept"),
    ("What was South Australia's peak price on 29 July 2026?",
     "market_event_review", "market_event_review", "a non-causal market-event question"),
    ("As of 2026-07-29T06:00:00Z, was the forecast lack of reserve the reason SA prices were expected to spike?",
     "forecast_review", "forecast_review", "an as-of question"),
    ("What did AEMO's market notices say about why South Australia's price spiked on 29 July 2026?",
     "forecast_review", "source_explanation", "a question about what notices say (the existing rule first)"),
    ("Did cold weather drive South Australia's price spike on 29 July 2026?",
     "forecast_review", "market_event_review", "another causal price-event question"),
])
def test_routing_controls(question, model_intent, expected, why):
    assert _routed(question, intent=model_intent)[0] == expected, why


def test_an_ambiguous_causal_question_is_still_sent_back():
    """No region and no date: routed as an event review, and still asked about, not answered."""
    q = "Was the forecast lack of reserve the reason prices spiked?"
    route = {**ROUTE18, "region": None, "event_date": None, "needs_clarification": True,
             "clarification_reason": "missing_region_or_date", "clarification": "Which region and date?"}
    res = investigate(InvestigateRequest(question=q, mode="live"), live_client=FakeModel(route, [], lambda kw: {}),
                      write_trace=False)
    assert res.resolution.intent == "market_event_review" and res.report.status == "needs_clarification"
