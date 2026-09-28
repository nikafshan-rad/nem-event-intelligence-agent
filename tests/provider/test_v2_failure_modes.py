"""One behaviour test per failure mode found on held-out set v2 (now development data).

These tests use only interfaces that already existed at commit 431b9d6 (before the fixes), so the same file can run
against that commit to show each failure, and against the fixed code to show it pass (docs/live-gates.md records
both runs). No network and no model: real pinned data through the dispatcher, retriever and validator, plus the
SYNTHETIC fake transport where the controller is under test.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from nem_agent.agent.dispatcher import Dispatcher
from nem_agent.agent.request import InvestigateRequest, route
from nem_agent.evidence import EvidenceRegistry
from nem_agent.retrieval.search import search
from nem_agent.service import investigate
from nem_agent.trace import Trace
from nem_agent.validation import validate
from tests.provider.fake_model import FakeModel, outputs

pytestmark = pytest.mark.synthetic

ABSTAIN = {"status": "abstained", "headline": "x", "summary": [], "document_statements": [],
           "observation_evidence_ids": [], "numeric_claims": [], "possible_explanations": [], "published_findings": [],
           "citations": [], "uncertainties": [], "missing_evidence": [], "forecast_mae_evidence_id": None}


def _route(intent: str, region: str | None, day: str | None, as_of: str | None = None) -> dict[str, Any]:
    return {"intent": intent, "region": region, "event_date": day, "as_of_utc": as_of, "needs_clarification": False,
            "clarification_reason": None, "clarification": None, "out_of_scope": False}


def _critical(report, base) -> set[str]:
    return {v.code for v in validate(report, base.registry, window=base.resolution.window,
                                     records=base.records).critical}


def _vic_low(selection):
    return next(e for e in selection.events if e.region == "VIC1" and e.kind == "low_price")


# 1 ------------------------------------------------------------------------ TOTALDEMAND vs operational demand
def test_1_total_demand_is_not_answered_with_operational_demand(real_store, selection):
    """H02, H03: asked for total demand, answered with operational demand only, and nothing rejected it."""
    from nem_agent.evaluation.adversarial import _base

    base = _base(selection)
    reg = base.registry
    keep = [c for c in base.report.numeric_claims if reg.get(c.evidence_id).metric != "dispatch_totaldemand"]
    drop = {c.claim_id for c in base.report.numeric_claims} - {c.claim_id for c in keep}
    lines = [s for s in base.report.summary if "TOTALDEMAND" not in s]
    answer = base.report.model_copy(update={"numeric_claims": keep, "summary": lines})
    assert drop and not _critical(answer, base)  # a valid answer to a question that names no measure
    asked = answer.model_copy(update={"question": "What was SA1 total demand at the price peak on 2026-07-31?"})
    assert "MEASURE_SUBSTITUTED" in _critical(asked, base)
    # and the measure the question names is returned at and around both price extremes
    ev = _vic_low(selection)
    d = Dispatcher(real_store, selection, Trace(), EvidenceRegistry(), "market_event_review")
    v = d.call("get_price_timeline", {"region": "VIC1", "start_utc": ev.window_start_utc,
                                      "end_utc": ev.window_end_utc, "as_of_utc": None}).view
    assert (v.get("totaldemand_at_minimum") or {}).get("evidence_id") and v.get("totaldemand_around_peak")


# 2 ------------------------------------------------------------------------ issue time vs as-of cutoff
def test_2_a_forecast_issue_time_is_not_used_as_the_as_of_cutoff():
    """H05: the router set as_of to the forecast's issue time, which hid the actual demand the question asked about."""
    q = ("For NSW on 2026-07-31, what did the operational-demand forecast AEMO issued at 2026-07-30T11:56:59Z say, "
         "and how did actual demand turn out?")
    fake = FakeModel(_route("forecast_review", "NSW1", "2026-07-31", "2026-07-30T11:56:59Z"), [[]], lambda kw: ABSTAIN)
    res = investigate(InvestigateRequest(question=q, mode="live"), live_client=fake, write_trace=False)
    assert res.resolution.as_of is None


# 3 ------------------------------------------------------------------------ the passage that answers
def test_3_the_passage_that_answers_a_document_question_is_retrieved():
    """H07 ('POE10' vs AEMO's '10% POE') and H14 ('operational demand' in single quotes) missed the answer."""
    ids = [h["chunk_id"] for h in search("When AEMO publishes POE10 and POE90 forecasts alongside the POE50, how "
                                         "are the outer bands obtained?", top_k=8)[0]]
    assert "aemo_so_op_3710#p7c14" in ids
    ids = [h["chunk_id"] for h in search("In plain terms, what counts towards 'operational demand' in a region, and "
                                         "are scheduled loads part of it?", top_k=5)[0]]
    assert "aemo_demand_terms#p9c11" in ids[:3]
    # and the controller retrieves for the question itself, so the answer does not depend on the model's queries
    seen: list[Any] = []

    def report(kw):
        seen.append(kw["input"])
        return ABSTAIN
    fake = FakeModel(_route("source_explanation", None, None), [[]], report)
    investigate(InvestigateRequest(question="What counts towards 'operational demand' in a region?", mode="live"),
                live_client=fake, write_trace=False)
    assert "aemo_demand_terms#p9c11" in json.dumps(seen[0])


# 4 ------------------------------------------------------------------------ citable interval counts
def test_4_interval_counts_carry_an_evidence_id(real_store, selection):
    """H02: the window's count of negative-price intervals was a bare number, so the answer could not cite it."""
    ev = _vic_low(selection)
    d = Dispatcher(real_store, selection, Trace(), EvidenceRegistry(), "market_event_review")
    w = {"region": "VIC1", "start_utc": ev.window_start_utc, "end_utc": ev.window_end_utc}
    total = d.call("find_market_events", {**w, "kind": "low_price", "threshold_aud_per_mwh": None,
                                          "max_results": 5}).view["n_intervals_meeting_threshold"]
    assert isinstance(total, dict) and d.registry.get(total["evidence_id"]).value == total["value"] == 197
    low = d.call("get_price_timeline", {**w, "as_of_utc": None}).view.get("intervals_below_low_threshold") or {}
    assert low.get("value") == 197 and d.registry.get(low.get("evidence_id", "")) is not None


# 5 ------------------------------------------------------------------------ notice questions and search capacity
def test_5_notice_questions_go_to_the_workflow_that_can_search_every_region(selection):
    """H10, ADV02: questions about what notices said were routed as forecast or event reviews, whose call bound
    stopped the per-region notice searches."""
    q = "What did AEMO's market notices from each region say about the SA1 price spike on 2026-07-31?"
    assert route(q)[0] == "source_explanation"
    ev = selection.primary
    turn = [("retrieve_public_evidence", {"query": "price notice", "region": r, "top_k": 3,
                                          "event_start_utc": ev.window_start_utc, "event_end_utc": ev.window_end_utc,
                                          "as_of_utc": None, "doc_types": ["market_notice"]})
            for r in ("NSW1", "QLD1", "SA1", "TAS1", "VIC1")]
    fake = FakeModel(_route("market_event_review", "SA1", "2026-07-31"), [turn], lambda kw: ABSTAIN)
    res = investigate(InvestigateRequest(question=q, mode="live"), live_client=fake, write_trace=False)
    assert res.resolution.intent == "source_explanation"
    searched = [r.args["region"] for r in res.records if r.name == "retrieve_public_evidence" and r.status == "ok"
                and r.origin == "model"]
    assert searched == ["NSW1", "QLD1", "SA1", "TAS1", "VIC1"]


# 6 ------------------------------------------------------------------------ decisive notice timing
def test_6_an_answer_that_omits_the_decisive_notice_time_is_rejected(selection):
    """H13: asked whether an outage in a notice caused the spike; the answer cited the notice but never said that its
    time came after every high-price interval."""
    from nem_agent.evaluation.adversarial import _base

    base = _base(selection)
    assert not _critical(base.report, base)
    asked = base.report.model_copy(update={"question": "Was the SA1 price spike on 2026-07-31 caused by the line "
                                                       "outage AEMO reported in a market notice?"})
    assert _critical(asked, base) == {"NOTICE_TIMING_OMITTED"}


def test_6_the_controller_sets_the_notice_time_against_the_event(selection):
    ev = next(e for e in selection.events if e.region == "VIC1" and e.peak_interval_end_utc.startswith("2026-08-19T23"))
    turn = [("get_price_timeline", {"region": "VIC1", "start_utc": ev.window_start_utc, "end_utc": ev.window_end_utc,
                                    "as_of_utc": None}),
            ("retrieve_public_evidence", {"query": "Hazelwood outage", "region": "VIC1", "top_k": 5,
                                          "event_start_utc": ev.window_start_utc, "event_end_utc": ev.window_end_utc,
                                          "as_of_utc": None, "doc_types": ["market_notice"]})]
    synthesis: list[Any] = []

    def report(kw):
        synthesis.append(kw["input"])
        assert any("Hazelwood" in json.dumps(v) for v in outputs(kw).values())
        return ABSTAIN
    fake = FakeModel(_route("market_event_review", "VIC1", "2026-08-20"), [turn], report)
    investigate(InvestigateRequest(question="Was the VIC1 price spike on 2026-08-20 caused by the Hazelwood outage "
                                            "in AEMO's notice?", mode="live"), live_client=fake, write_trace=False)
    text = json.dumps(synthesis[0])
    assert "after the last 5-minute interval at or above the analysis threshold" in text
    assert "2026-08-20T01:00:00Z" in text and "2026-08-19T23:45:00Z" in text


# 7 ------------------------------------------------------------------------ quotes absent from the cited passage
def test_7_a_quoted_sentence_absent_from_its_cited_passage_is_rejected():
    """Found in the PR #5 review: a wholly quoted sentence with a valid citation passed although the passage did not
    contain it (its words were inside quotation marks, so no other check read them)."""
    res = investigate(InvestigateRequest(question="What does operational demand mean?", mode="replay"), write_trace=False)
    rep, reg = res.report, res.registry
    cid = rep.citations[0].citation_id
    real = " ".join(reg.chunks[rep.citations[0].chunk_id].text.split()[:8])

    def critical(line: str) -> set[str]:
        return {v.code for v in validate(rep.model_copy(update={"summary": [line]}), reg, records=res.records).critical}
    assert not critical(f"“{real}” [{cid}]")
    assert critical(f"“Operational demand is set by the Minister every 7 days.” [{cid}]") == {"QUOTE_NOT_IN_SOURCE"}
