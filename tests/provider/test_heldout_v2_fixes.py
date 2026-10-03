"""Fixes for the failure modes found on held-out set v2 (now development data), each with neighbouring cases.

No network and no model: real pinned data through the dispatcher, the retriever and the validator, plus the
SYNTHETIC fake transport where the controller's context is under test.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from nem_agent.agent.dispatcher import Dispatcher
from nem_agent.agent.live import RouteDecision, checked_route
from nem_agent.agent.request import InvestigateRequest, forecast_issue_time, requested_measures, route
from nem_agent.evidence import EvidenceRegistry
from nem_agent.retrieval.search import defn_phrase, expand_query, search
from nem_agent.service import investigate, resolve_routed, route_policy
from nem_agent.timeutil import parse_iso
from nem_agent.trace import Trace
from tests.provider.fake_model import FakeModel, outputs

pytestmark = pytest.mark.synthetic


def _event(selection, region, kind):
    return next(e for e in selection.events if e.region == region and e.kind == kind)


def _decision(**kw: Any) -> RouteDecision:
    base = {"intent": "market_event_review", "region": "SA1", "event_date": "2026-07-31", "as_of_utc": None,
            "needs_clarification": False, "clarification_reason": None, "clarification": None, "out_of_scope": False}
    return RouteDecision(**{**base, **kw})


# ------------------------------------------------------------------------------------ uncitable interval counts
def test_interval_counts_are_citable_for_low_and_high_price_events(real_store, selection):
    """H02: the window's count of negative-price intervals was a bare number, so it could not be cited."""
    ev = _event(selection, "VIC1", "low_price")
    d = Dispatcher(real_store, selection, Trace(), EvidenceRegistry(), "market_event_review")
    w = {"region": "VIC1", "start_utc": ev.window_start_utc, "end_utc": ev.window_end_utc}
    fme = d.call("find_market_events", {**w, "kind": "low_price", "threshold_aud_per_mwh": None, "max_results": 5}).view
    total = fme["n_intervals_meeting_threshold"]
    assert total["value"] == 197 and d.registry.get(total["evidence_id"]).value == 197.0
    assert total["value"] >= sum(e["n_intervals"]["value"] for e in fme["episodes"])  # all episodes, not the top 5
    tl = d.call("get_price_timeline", {**w, "as_of_utc": None}).view
    lo = tl["intervals_below_low_threshold"]
    assert lo["value"] == 197 and d.registry.get(lo["evidence_id"]).metric == "intervals_meeting_threshold"
    assert tl["intervals_at_or_above_threshold"]["value"] == 0  # the high-price count is unchanged (Replay reads it)


# ------------------------------------------------------------------------------------ demand-measure substitution
def test_total_demand_is_available_at_and_around_both_extremes(real_store, selection):
    """H02 needed TOTALDEMAND at the trough and H03 over the half hour before the peak; only the peak was returned."""
    vic = _event(selection, "VIC1", "low_price")
    d = Dispatcher(real_store, selection, Trace(), EvidenceRegistry(), "market_event_review")
    v = d.call("get_price_timeline", {"region": "VIC1", "start_utc": vic.window_start_utc,
                                      "end_utc": vic.window_end_utc, "as_of_utc": None}).view
    assert v["totaldemand_at_minimum"]["value"] == pytest.approx(7052.43)
    assert d.registry.get(v["totaldemand_at_minimum"]["evidence_id"]).metric == "dispatch_totaldemand"
    tas = next(e for e in selection.events if e.region == "TAS1" and e.peak_interval_end_utc.startswith("2026-08-06"))
    v = d.call("get_price_timeline", {"region": "TAS1", "start_utc": tas.window_start_utc,
                                      "end_utc": tas.window_end_utc, "as_of_utc": None}).view
    around = {p["interval_end_utc"]: p["value"] for p in v["totaldemand_around_peak"]}
    assert around["2026-08-06T02:30:00Z"] == pytest.approx(1054.19) and around["2026-08-06T03:00:00Z"] == pytest.approx(1105.32)
    assert len(around) == 13 and "different measure" in v["totaldemand_note"]


def test_requested_measures_come_from_the_question():
    assert list(requested_measures("what was Victorian total demand in that interval?")) == ["total demand"]
    assert list(requested_measures("how did TOTALDEMAND move?")) == ["total demand"]
    assert list(requested_measures("what counts towards operational demand?")) == ["operational demand"]
    assert requested_measures("what happened to prices?") == {}


def test_measure_substitution_is_rejected_unless_the_gap_is_stated(selection):
    from nem_agent.evaluation.adversarial import _base
    from nem_agent.validation import validate

    base = _base(selection)
    reg = base.registry
    claims = base.report.numeric_claims
    no_total = [c for c in claims if reg.get(c.evidence_id).metric != "dispatch_totaldemand"]
    assert len(no_total) < len(claims) and any(reg.get(c.evidence_id).metric == "opdemand_actual" for c in no_total)

    def codes(question, keep, **upd):
        r = base.report.model_copy(update={"question": question, "numeric_claims": keep, **upd})
        return {v.code for v in validate(r, reg, window=base.resolution.window, records=base.records).violations}
    q_total = "What was SA total demand at the peak?"
    assert "MEASURE_SUBSTITUTED" in codes(q_total, no_total)                     # H02/H03 mechanism
    assert "MEASURE_SUBSTITUTED" not in codes(q_total, claims)                   # TOTALDEMAND is reported
    assert "MEASURE_SUBSTITUTED" not in codes(q_total, no_total, missing_evidence=["Total demand was not returned."])
    assert "MEASURE_SUBSTITUTED" not in codes("What was total and operational demand?", no_total)  # both named
    assert "MEASURE_SUBSTITUTED" not in codes("What happened to SA prices?", no_total)            # neither named


# ------------------------------------------------------------------------------------ issue time vs as-of
def test_a_forecast_issue_time_is_not_an_as_of_cutoff(selection):
    """H05: 'the forecast AEMO issued at <time>' became the as-of cutoff, which hid the actuals asked about."""
    q = ("For NSW, what did the forecast AEMO issued at 2026-07-30T11:56:59Z predict for the half-hour ending "
         "2026-07-30T21:30:00Z, and how did actual demand turn out?")
    assert forecast_issue_time(q) == parse_iso("2026-07-30T11:56:59Z")
    req = InvestigateRequest(question=q, mode="live")
    # the cutoff is no longer taken from the routing decision (D26): the resolver reads it, and a v12 decision's cutoff
    # timestamp that is the forecast's issue time is not applied
    upd, _, _ = route_policy(req, _decision(intent="forecast_review", region="NSW1", as_of_utc="2026-07-30T11:56:59Z"))
    assert upd["as_of_utc"] is None
    res = resolve_routed(req, checked_route(_decision(intent="forecast_review", region="NSW1",
                                                      as_of_utc="2026-07-30T11:56:59Z")), selection)
    assert res.as_of is None and any("issue time" in n for n in res.requests.cutoff.notes)
    # neighbours: a real as-of question keeps its cutoff, and so does one that names both (read from its words)
    for q2 in ("As of 2026-07-30T12:00:00Z, what did the latest forecast say for SA1?",
               "As of 2026-07-30T12:00:00Z, what did the run issued at 2026-07-30T11:56:59Z say for SA1?"):
        res2 = resolve_routed(InvestigateRequest(question=q2, mode="live"),
                              checked_route(_decision(intent="forecast_review", as_of_utc="2026-07-30T12:00:00Z")),
                              selection)
        assert res2.as_of is not None and res2.as_of.isoformat() == "2026-07-30T12:00:00+00:00"
        assert forecast_issue_time(q2) is None


def test_the_controller_names_the_run_issued_at_that_time(selection):
    q = ("For NSW on 2026-07-31, what did the operational-demand forecast AEMO issued at 2026-07-30T11:56:59Z say, "
         "and how did actual demand turn out?")
    route_ = {"intent": "forecast_review", "region": "NSW1", "event_date": "2026-07-31", "as_of_utc": "2026-07-30T11:56:59Z",
              "needs_clarification": False, "clarification_reason": None, "clarification": None, "out_of_scope": False}
    fake = FakeModel(route_, [[]], lambda kw: {"status": "abstained", "headline": "x", "summary": [], "document_statements": [],
                                               "observation_evidence_ids": [], "numeric_claims": [], "possible_explanations": [],
                                               "published_findings": [], "citations": [], "uncertainties": [],
                                               "missing_evidence": [], "forecast_mae_evidence_id": None})
    res = investigate(InvestigateRequest(question=q, mode="live"), live_client=fake, write_trace=False)
    assert res.resolution.as_of is None                       # no cutoff was applied
    ctx = json.loads(fake.requests[1]["input"][0]["content"].split("\n", 1)[1])
    run = ctx["requested_forecast_run"]
    assert run["issued_at_utc"] == "2026-07-30T11:56:59Z" and run["run_id"] and "not an as-of cutoff" in run["note"]


# ------------------------------------------------------------------------------------ missing retrieval evidence
def test_poe_abbreviations_match_aemo_wording():
    """H07: 'POE10' is one keyword token; AEMO's procedure writes '10% POE'."""
    assert "10% POE" in expand_query("how are POE10 and POE 90 bands obtained") and \
        "90% POE" in expand_query("how are POE10 and POE 90 bands obtained")
    assert expand_query("what is operational demand") == "what is operational demand"
    hits = [h["chunk_id"] for h in search("When AEMO publishes POE10 and POE90 forecasts alongside the POE50, how are the "
                                          "outer bands obtained?", top_k=8)[0]]
    assert "aemo_so_op_3710#p7c14" in hits


def test_single_quoted_terms_and_plain_questions_get_the_definition():
    """H14: 'operational demand' in single quotes and 'what counts towards' missed the definitional boost."""
    assert defn_phrase("In plain terms, what counts towards 'operational demand' here?") == "operational demand"
    assert defn_phrase("What is AEMO's operational demand?") == "operational demand"  # an apostrophe is not a quote
    hits = [h["chunk_id"] for h in search("In plain terms, what counts towards 'operational demand' in a region, and "
                                          "are scheduled loads part of it?", top_k=5)[0]]
    assert hits.index("aemo_demand_terms#p9c11") <= 2


def test_document_questions_start_with_a_controller_retrieval_of_the_question():
    captured: dict[str, Any] = {}

    def report(kw):
        captured["input"] = kw["input"]
        return {"status": "abstained", "headline": "x", "summary": [], "document_statements": [],
                "observation_evidence_ids": [], "numeric_claims": [], "possible_explanations": [], "published_findings": [],
                "citations": [], "uncertainties": [], "missing_evidence": [], "forecast_mae_evidence_id": None}
    route_ = {"intent": "source_explanation", "region": None, "event_date": None, "as_of_utc": None,
              "needs_clarification": False, "clarification_reason": None, "clarification": None, "out_of_scope": False}
    fake = FakeModel(route_, [[]], report)
    res = investigate(InvestigateRequest(question="What counts towards 'operational demand' in a region?", mode="live"),
                      live_client=fake, write_trace=False)
    first = res.records[0]
    assert (first.name, first.origin, first.call_id) == ("retrieve_public_evidence", "controller",
                                                         "controller_question_retrieval")
    assert "aemo_demand_terms#p9c11" in first.source_row_ids
    assert any("retrieved by the controller for the question itself" in str(i.get("content", "")) for i in captured["input"])


# ------------------------------------------------------------------------------------ notice routing and search limits
def test_questions_about_what_notices_said_are_document_questions(selection):
    """H10 (routed as a forecast review) and ADV02 (as an event review, where the 3-call bound blocked regions)."""
    q = "What did AEMO's market notices say about South Australia's reserve position on 29 July 2026?"
    upd, _, notes = route_policy(InvestigateRequest(question=q, mode="live"), _decision(intent="forecast_review"))
    assert upd["intent"] == "source_explanation" and any("notices said" in n for n in notes)
    assert route(q)[0] == "source_explanation"
    assert route("According to the market notice, which line was taken out in SA on 2026-07-30?")[0] == "source_explanation"
    # neighbours: an event question that mentions a notice stays an event review; an explicit user intent is kept
    q2 = "Was the VIC1 price spike on 2026-08-20 caused by the outage AEMO put out a notice about?"
    assert route_policy(InvestigateRequest(question=q2, mode="live"), _decision(region="VIC1"))[0]["intent"] == \
        "market_event_review"
    kept = route_policy(InvestigateRequest(question=q, mode="live", intent="forecast_review"),
                        _decision(intent="forecast_review"))[0]["intent"]
    assert kept == "forecast_review"


def test_document_questions_can_search_every_region(real_store, selection):
    ev = selection.primary
    d = Dispatcher(real_store, selection, Trace(), EvidenceRegistry(), "source_explanation")
    base = {"query": "notices", "event_start_utc": ev.window_start_utc, "event_end_utc": ev.window_end_utc,
            "as_of_utc": None, "top_k": 3, "doc_types": ["market_notice"]}
    recs = [d.call("retrieve_public_evidence", {**base, "region": r}) for r in (None, "NSW1", "QLD1", "SA1", "TAS1",
                                                                                "VIC1", "VIC1")]
    assert [r.status for r in recs][:6] == ["ok"] * 6 and recs[6].status == "blocked"  # six allowed, the seventh not


# ------------------------------------------------------------------------------------ quoted-text validator gap
def test_quotations_must_be_verbatim_in_a_cited_passage():
    from nem_agent.validation import validate

    res = investigate(InvestigateRequest(question="What does operational demand mean?", mode="replay"), write_trace=False)
    rep, reg = res.report, res.registry
    cid = rep.citations[0].citation_id
    passage = reg.chunks[rep.citations[0].chunk_id].text
    real = " ".join(passage.split()[:8])

    def codes(line):
        r = rep.model_copy(update={"summary": [line]})
        return {v.code for v in validate(r, reg, records=res.records).violations}
    assert "QUOTE_NOT_IN_SOURCE" in codes(f"“Operational demand is set by the Minister every 7 days.” [{cid}]")
    assert "QUOTE_NOT_IN_SOURCE" not in codes(f"“{real}” [{cid}]")
    assert "QUOTE_NOT_IN_SOURCE" not in codes(f"AEMO calls it “as generated” demand [{cid}].")  # under three words
    assert "QUOTE_NOT_IN_SOURCE" in codes("AEMO says “demand is measured by satellite daily” here.")  # uncited, not cited


# ------------------------------------------------------------------------------------ decisive notice timing
NOTICE_Q = "Did the Hazelwood bus tie outage in AEMO's notice cause the VIC1 price spike on 2026-08-20?"
HAZELWOOD = "At 1100 hrs 20/08/2026 there was a short notice outage of Hazelwood PS 4 6 bus tie 220kV."


def _vic_notice_investigation(selection, summary_fn, *, repair=False, question=NOTICE_Q):
    ev = next(e for e in selection.events if e.region == "VIC1" and e.peak_interval_end_utc.startswith("2026-08-19T23"))
    w = {"region": "VIC1", "start_utc": ev.window_start_utc, "end_utc": ev.window_end_utc}
    turn = [("find_market_events", {**w, "kind": "high_price", "threshold_aud_per_mwh": None, "max_results": 5}),
            ("get_price_timeline", {**w, "as_of_utc": None}),
            ("get_actual_demand", {**w, "revision_policy": "latest_available", "as_of_utc": None}),
            ("retrieve_public_evidence", {"query": "Hazelwood outage", "region": "VIC1", "top_k": 5,
                                          "event_start_utc": ev.window_start_utc, "event_end_utc": ev.window_end_utc,
                                          "as_of_utc": None, "doc_types": ["market_notice"]})]

    def report(kw):
        results = [v.get("result", {}) for v in outputs(kw).values()]
        tl = next(r for r in results if "peak" in r)
        hit = next(h for r in results for h in r.get("results", []) if HAZELWOOD in h["text"])
        p = tl["peak"]
        return {"status": "answered", "headline": f"VIC1 RRP peaked at {p['value']} $/MWh at {p['interval_end_local']}.",
                "summary": summary_fn(tl, _timing(kw)), "document_statements": [],
                "observation_evidence_ids": [p["evidence_id"]],
                "numeric_claims": [{"claim_id": "n1", "text": "peak", "value": p["value"], "unit": "$/MWh",
                                    "evidence_id": p["evidence_id"], "rounding": 0.0}],
                "possible_explanations": [], "published_findings": [{"citation_id": "c1", "applies_to_event": True}],
                "citations": [{"citation_id": "c1", "chunk_id": hit["chunk_id"], "quote": HAZELWOOD,
                               "supports": "the outage notice"}],
                "uncertainties": [], "missing_evidence": [], "forecast_mae_evidence_id": None}
    fake = FakeModel({"intent": "market_event_review", "region": "VIC1", "event_date": "2026-08-20", "as_of_utc": None,
                      "needs_clarification": False, "clarification_reason": None, "clarification": None,
                      "out_of_scope": False}, [turn], report, repair_fn=report if repair else None)
    return investigate(InvestigateRequest(question=question, mode="live"), live_client=fake, write_trace=False), fake


def _timing(kw):
    return next((json.loads(i["content"].split("\n", 1)[1]) for i in kw["input"] if isinstance(i, dict)
                 and str(i.get("content", "")).startswith("Notice timing computed by the controller")), None)


def _timing_sentence(tl, timing):
    t = next(x for n in timing["notices"] if n["doc_id"] == "market_notice_144893" for x in n["times"])
    last = tl["last_interval_at_or_above_threshold"]
    return (f"The Hazelwood bus tie outage notice gives {t['local']} ({t['utc']}), after the last 5-minute interval at "
            f"or above the analysis threshold, which ended {last['interval_end_local']}.")


def test_the_controller_sets_notice_times_against_the_event(selection):
    """H13: the Hazelwood notice's 1100 hrs NEM time (01:00Z) is after every high-price interval (the last ends
    23:45Z), which the answer never said. The controller now computes it and hands it to the synthesis step."""
    res, fake = _vic_notice_investigation(selection, lambda tl, timing: [_timing_sentence(tl, timing)])
    timing = _timing(fake.requests[-1])
    assert timing["required_in_summary"] is True
    t = next(x for n in timing["notices"] if n["doc_id"] == "market_notice_144893" for x in n["times"])
    assert (t["utc"], t["local"]) == ("2026-08-20T01:00:00Z", "2026-08-20 11:00 AEST (UTC+1000)")
    assert t["relative_to_threshold_intervals"] == ("after the last 5-minute interval at or above the analysis "
                                                    "threshold: interval ending 2026-08-19T23:45:00Z = 2026-08-20 09:45 "
                                                    "AEST (UTC+1000)")
    assert t["relative_to_price_extreme"].startswith("after the price extreme: interval ending 2026-08-19T23:10:00Z")
    # a sentence built from it passes every check, and the report keeps it
    rep = res.report
    assert rep.validation["initial"]["passed"], rep.validation["initial"]["violations"]
    assert any("2026-08-20 11:00 AEST" in s and "after the last" in s for s in rep.summary)


def test_omitting_the_decisive_notice_time_is_rejected_and_repaired(selection):
    """H13 mechanism: the notice was cited and quoted (with its bare '1100 hrs'), but its time was never set against
    the event. The draft is rejected, and the one repair (a full one: the violation names no item) adds the sentence.
    The question names no incident, so the controller writes no timing answer of its own (docs/issue-tracker.md I-1a;
    a question naming Hazelwood gets one, tests/provider/test_causal_question_answer.py)."""
    drafts: list[int] = []

    def summary(tl, timing):
        drafts.append(1)
        return [] if len(drafts) == 1 else [_timing_sentence(tl, timing)]
    res, _ = _vic_notice_investigation(selection, summary, repair=True, question="Did the transmission outage in "
                                       "AEMO's notice cause the VIC1 price spike on 2026-08-20?")
    v = res.report.validation
    assert v["pre_repair_codes"] == ["NOTICE_TIMING_OMITTED"] and v["repair_mode"] == "full"
    assert v["initial"]["passed"] and not v["fallback_applied"]
    assert any("after the last 5-minute interval" in s for s in res.report.summary)


def test_notice_timing_is_required_only_when_the_question_asks_about_a_notice_reported_event(selection):
    from nem_agent.agent.request import asks_if_notice_event_caused

    assert asks_if_notice_event_caused(NOTICE_Q)
    for q in ("Did low wind cause the SA1 price spike on 2026-07-31?",                  # ADV01: no notice-reported event
              "What happened to VIC1 prices on 2026-08-20?",                            # no causal question
              "What did AEMO's market notice say about the City West transformer?"):    # a document question
        assert not asks_if_notice_event_caused(q)
    # otherwise the synthesis input is unchanged, and the same draft without a timing sentence passes
    res, fake = _vic_notice_investigation(selection, lambda tl, timing: [],
                                          question="What happened to VIC1 prices on 2026-08-20?")
    assert _timing(fake.requests[-1]) is None
    assert res.report.validation["initial"]["passed"], res.report.validation["initial"]["violations"]


def test_notice_times_before_and_between_the_threshold_intervals(selection):
    """SA1, 2026-07-31: one notice time falls before the first high-price interval, and one between the first and last
    (not 'during': the 214 intervals form several episodes)."""
    ev = selection.primary
    turn = [("get_price_timeline", {"region": "SA1", "start_utc": ev.window_start_utc, "end_utc": ev.window_end_utc,
                                    "as_of_utc": None}),
            ("retrieve_public_evidence", {"query": "line outage transformer trip", "region": "SA1", "top_k": 8,
                                          "event_start_utc": ev.window_start_utc, "event_end_utc": ev.window_end_utc,
                                          "as_of_utc": None, "doc_types": ["market_notice"]})]
    fake = FakeModel({"intent": "market_event_review", "region": "SA1", "event_date": "2026-07-31", "as_of_utc": None,
                      "needs_clarification": False, "clarification_reason": None, "clarification": None,
                      "out_of_scope": False}, [turn],
                     lambda kw: {"status": "abstained", "headline": "x", "summary": [], "document_statements": [],
                                 "observation_evidence_ids": [], "numeric_claims": [], "possible_explanations": [],
                                 "published_findings": [], "citations": [], "uncertainties": [], "missing_evidence": [],
                                 "forecast_mae_evidence_id": None})
    investigate(InvestigateRequest(question="Was the SA1 price spike on 2026-07-31 caused by the line outage in AEMO's "
                                            "notice?", mode="live"), live_client=fake, write_trace=False)
    times = {n["doc_id"]: n["times"][0] for n in _timing(fake.requests[-1])["notices"]}
    assert times["market_notice_144692"]["utc"] == "2026-07-30T01:40:00Z"
    assert times["market_notice_144692"]["relative_to_threshold_intervals"].startswith("before the first 5-minute")
    assert times["market_notice_144693"]["utc"] == "2026-07-30T06:30:00Z"
    assert times["market_notice_144693"]["relative_to_threshold_intervals"].startswith("between the first and last")
    assert times["market_notice_144693"]["relative_to_price_extreme"].startswith("before the price extreme")
