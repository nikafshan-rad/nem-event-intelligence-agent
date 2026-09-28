"""Fixes A–D for the L3 live failure modes, with a SYNTHETIC fake transport (no network, no key).

A: document sentences are written by the controller; only a verified verbatim quote is shown in quotation marks.
B: the one repair may change only the failing items. C: document searches report their scope and never widen or
narrow it silently; document questions get no event times. D: hourly price samples say they are an hour apart.
The DOC04 and ADV02 mechanisms are used as regression examples (those cases are regression data, not held out).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from nem_agent.agent.request import InvestigateRequest
from nem_agent.service import investigate
from tests.provider.fake_model import FakeModel, outputs

pytestmark = pytest.mark.synthetic

POE_QUOTE = "The 10% and 90% POE forecast are produced by multiplying the 50% POE forecast by a scaling factor."


def _doc_route(region=None, event_date=None):
    return {"intent": "source_explanation", "region": region, "event_date": event_date, "as_of_utc": None,
            "needs_clarification": False, "clarification_reason": None, "clarification": None, "out_of_scope": False}


def _retrieve(query, region=None, start=None, end=None, doc_types=("procedure",), top_k=5):
    return ("retrieve_public_evidence", {"query": query, "region": region, "event_start_utc": start,
                                         "event_end_utc": end, "as_of_utc": None, "top_k": top_k,
                                         "doc_types": list(doc_types)})


def _report(**kw: Any) -> dict[str, Any]:
    base = {"status": "answered", "headline": "How AEMO derives its exceedance forecasts", "summary": [],
            "document_statements": [], "observation_evidence_ids": [], "numeric_claims": [],
            "possible_explanations": [], "published_findings": [], "citations": [], "uncertainties": [],
            "missing_evidence": [], "forecast_mae_evidence_id": None}
    return base | kw


def _poe_hit(kw):
    for v in outputs(kw).values():
        for h in (v.get("result") or {}).get("results", []):
            if POE_QUOTE in h["text"]:
                return h
    raise AssertionError("the POE passage was not retrieved")


def _poe_investigation(statements_fn, repair_fn=None):
    def report(kw):
        h = _poe_hit(kw)
        cite = {"citation_id": "c1", "chunk_id": h["chunk_id"], "quote": POE_QUOTE, "supports": "method"}
        return _report(citations=[cite], document_statements=statements_fn(h))
    fake = FakeModel(_doc_route(), [[_retrieve("10% 90% POE forecast scaling factor 50% POE")]], report,
                     repair_fn=repair_fn)
    res = investigate(InvestigateRequest(question="How are the POE10 and POE90 demand forecasts derived?", mode="live"),
                      live_client=fake, write_trace=False)
    return res, fake


# ------------------------------------------------------------------------------------------------ A
def test_a_verbatim_quote_with_percentages_is_rendered_as_a_quote_and_passes():
    """DOC04 mechanism: the passage's own sentence, with its percentages, is shown as a quote with its citation."""
    res, _ = _poe_investigation(lambda h: [{"citation_id": "c1", "quote": POE_QUOTE, "paraphrase": None}])
    rep = res.report
    assert rep.summary == [f"“{POE_QUOTE}” [c1]"]
    assert rep.validation["initial"]["passed"] and not rep.validation["fallback_applied"]
    assert rep.status == "answered"


def test_a_quote_that_is_not_verbatim_is_shown_as_own_words_and_checked():
    """Quotation marks are never put around text the passage does not contain, so no check is bypassed."""
    altered = POE_QUOTE.replace("a scaling factor", "a scaling factor of 1.25")
    res, _ = _poe_investigation(lambda h: [{"citation_id": "c1", "quote": altered, "paraphrase": None}])
    rep = res.report
    flagged = [v["detail"] for v in rep.validation["initial"]["violations"] if v["code"] == "NUMERIC_UNTRACKED"]
    # the rendered statement (summary[0]) was shown without quotation marks, so its numbers are the model's own
    assert any(d.startswith("summary[0]: number 1.25") for d in flagged)
    assert any(d.startswith("summary[0]: number 10") for d in flagged)
    assert any(e["name"] == "statement_not_verbatim" for e in res.trace.events)


def test_a_statement_must_name_a_retrieved_citation():
    res, _ = _poe_investigation(lambda h: [{"citation_id": "c9", "quote": None,
                                            "paraphrase": "AEMO scales the median forecast"}])
    assert "DOC_CLAIM_UNCITED" in {v["code"] for v in res.report.validation["initial"]["violations"]}


# ------------------------------------------------------------------------------------------------ B
def test_b_scoped_repair_changes_only_the_failing_items():
    """EV09 mechanism: a full rewrite fixed four violations and added four. Now only failing items can change."""
    good = {"citation_id": "c1", "quote": POE_QUOTE, "paraphrase": None}
    bad = {"citation_id": "c1", "quote": None, "paraphrase": "AEMO multiplies the forecast by 1.25"}  # untracked 1.25

    def patch(kw):
        return {"edits": [
            {"target": "document_statements[0]", "action": "replace", "text": None, "claim": None, "citation": None,
             "statement": {"citation_id": "c1", "quote": None, "paraphrase": "a passing item rewritten"}},
            {"target": "document_statements[1]", "action": "delete", "text": None, "statement": None, "claim": None,
             "citation": None}], "new_numeric_claims": [], "new_citations": []}
    res, fake = _poe_investigation(lambda h: [good, bad], repair_fn=patch)
    rep = res.report
    assert rep.validation["repair_mode"] == "scoped" and not rep.validation["fallback_applied"]
    assert rep.summary == [f"“{POE_QUOTE}” [c1]"]  # the passing item is unchanged; the failing one was deleted
    scoped = next(e for e in res.trace.events if e["name"] == "repair:scoped")
    assert scoped["targets"] == ["document_statements[1]"]
    assert any("ignored an edit to document_statements[0]" in n for n in scoped["notes"])
    turn = str(fake.requests[-1]["input"][-1]["content"])
    assert "Items you may change" in turn and "document_statements[1]" in turn and "RepairPatch" in turn


def test_b_violations_that_name_no_item_use_the_full_repair():
    from nem_agent.agent.live import ModelReport, repair_targets
    from nem_agent.validation import ValidationResult, Violation

    m = ModelReport.model_validate(_report(summary=["x"], numeric_claims=[
        {"claim_id": "n1", "text": "t", "value": 1.0, "unit": "MW", "evidence_id": "ev0001", "rounding": 0.0}]))
    origin = [("summary", 0)]
    mapped = ValidationResult(violations=[Violation("NUMERIC_UNTRACKED", "critical", "summary[0]: number 2"),
                                          Violation("CLAIM_UNIT_MISMATCH", "critical", "n1: unit 'x' vs 'MW'"),
                                          Violation("ASOF_LEAK", "critical", "ev0001 (dispatch_rrp) available later")])
    assert repair_targets(mapped, m, origin) == ({"summary[0]", "numeric_claims[n1]"}, [])
    unmapped = ValidationResult(violations=[Violation("STATUS_OVERCLAIMS", "critical", "required tools not run: x")])
    assert repair_targets(unmapped, m, origin)[1] == ["STATUS_OVERCLAIMS"]


# ------------------------------------------------------------------------------------------------ C
def test_c_notice_search_scope_distinguishes_not_searched_none_held_and_found(real_store, selection):
    """ADV02 mechanism: a notice search without a region returned nothing, which read as 'no notices exist'."""
    from nem_agent.agent.dispatcher import Dispatcher
    from nem_agent.evidence import EvidenceRegistry
    from nem_agent.trace import Trace

    ev = selection.primary  # the SA1 event
    d = Dispatcher(real_store, selection, Trace(), EvidenceRegistry(), "source_explanation")
    w = {"event_start_utc": ev.window_start_utc, "event_end_utc": ev.window_end_utc, "as_of_utc": None, "top_k": 5,
         "doc_types": ["market_notice"], "query": "price constraint outage notice"}
    no_region = d.call("retrieve_public_evidence", {**w, "region": None})
    s = no_region.view["search_scope"]
    assert s["searched"] is False and "region" in s["reason"]
    assert any("not searched" in m for m in no_region.missing)
    assert not any(a.startswith("as_of") for a in no_region.policy_notes)  # nothing was injected
    assert no_region.args["region"] is None                                   # and the scope was not widened
    counts = {}
    for region in ("VIC1", "NSW1", "QLD1", "TAS1"):
        s = d.call("retrieve_public_evidence", {**w, "region": region}).view["search_scope"]
        assert s["searched"] and s["region"] == region
        counts[region] = s["held_for_region_and_window"]
        assert (s["returned"] > 0) == (s["held_for_region_and_window"] > 0)
        assert s["outcome"].startswith("no notice held") == (s["held_for_region_and_window"] == 0)
    assert any(counts.values())


def test_c_document_questions_get_no_event_times_and_report_their_search_scope(selection):
    ev = selection.primary
    turn = [_retrieve("SA1 price spike market notice", doc_types=("market_notice",)),
            _retrieve("price spike notices", region="VIC1", start=ev.window_start_utc, end=ev.window_end_utc,
                      doc_types=("market_notice",))]

    def report(kw):
        return _report(status="abstained", headline="Searched VIC1 notices only; others not searched")
    fake = FakeModel(_doc_route("SA1", "2026-07-31"), [turn], report)
    res = investigate(InvestigateRequest(question="What did AEMO notices from other regions say about the SA1 price "
                                                  "spike on 2026-07-31?", mode="live"),
                      live_client=fake, write_trace=False)
    ctx = json.loads(fake.requests[1]["input"][0]["content"].split("\n", 1)[1])
    assert ctx["event_peak_interval_end_utc"] is None and "peak_half_hour_end_utc" not in ctx
    scope = res.report.search_scope
    assert [s.region for s in scope] == [None, "VIC1"]
    assert scope[0].market_notices.startswith("not searched") and scope[1].market_notices.startswith("searched")


# ------------------------------------------------------------------------------------------------ D
def test_d_hourly_samples_say_they_are_an_hour_apart(real_store, selection):
    from nem_agent.agent.dispatcher import Dispatcher
    from nem_agent.agent.live import prompt
    from nem_agent.evidence import EvidenceRegistry
    from nem_agent.trace import Trace

    ev = selection.primary
    d = Dispatcher(real_store, selection, Trace(), EvidenceRegistry(), "market_event_review")
    v = d.call("get_price_timeline", {"region": ev.region, "start_utc": ev.window_start_utc,
                                      "end_utc": ev.window_end_utc, "as_of_utc": None}).view
    assert "one hour apart" in v["hourly_samples_note"]
    assert "immediately before and after" in prompt("synthesis") and "daytime" in prompt("synthesis")
