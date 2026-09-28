"""One behaviour test per failure found in held-out set v3 (now development data).

Uses only interfaces that existed at commit 1020188 (the code v3 ran on), so the same file can be run against that
commit to show each failure and against the fixed code to show it pass (docs/live-gates.md records both runs). The
notice-timing tests replay the exact tool calls and draft sentences saved in artifacts/live/L3-holdout-v3/ through the
SYNTHETIC fake transport (no network, no key) and check the notice-timing codes only, since evidence IDs in a replay
may differ from the Live run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nem_agent.agent.dispatcher import Dispatcher
from nem_agent.agent.request import InvestigateRequest
from nem_agent.evidence import EvidenceRegistry
from nem_agent.report import Citation, Hypothesis, NumericClaim
from nem_agent.service import investigate
from nem_agent.trace import Trace
from nem_agent.validation import validate
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

V3 = Path(__file__).resolve().parents[2] / "artifacts" / "live" / "L3-holdout-v3"
NOTICE_CODES = {"NOTICE_TIMING_CONTRADICTED", "NOTICE_TIMING_UNVERIFIED", "NOTICE_TIMING_OMITTED",
                "NOTICE_TIME_ZONE_MISMATCH"}
ABSTAIN = {"status": "abstained", "headline": "x", "summary": [], "document_statements": [],
           "observation_evidence_ids": [], "numeric_claims": [], "possible_explanations": [], "published_findings": [],
           "citations": [], "uncertainties": [], "missing_evidence": [], "forecast_mae_evidence_id": None}


def _replay(case_id: str) -> tuple[Any, dict[str, Any]]:
    """Re-run a saved v3 case's own tool calls, and return the investigation and the case's final (repair) draft."""
    rec = json.loads((V3 / f"{case_id}.json").read_text())
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"])
             for t in rec["tools"] if t["status"] == "ok"]
    fake = FakeModel(rec["route"], [calls], lambda kw: ABSTAIN)
    res = investigate(InvestigateRequest(question=rec["question"], mode="live"), live_client=fake, write_trace=False)
    return res, rec["drafts"]["repair:draft"]


def _notice_codes(res: Any, draft: dict[str, Any], **parts: Any) -> list[tuple[str, str]]:
    """Validate the draft's own sentences (and its citations) against the replayed evidence; notice codes only."""
    cites = []
    for c in draft["citations"]:
        ch = res.registry.chunks[c["chunk_id"]]
        cites.append(Citation(citation_id=c["citation_id"], chunk_id=ch.chunk_id, doc_id=ch.doc_id, title=ch.title,
                              url=ch.url, doc_type=ch.doc_type, quote=c["quote"], supports=c["supports"]))
    # a neutral question, so that only the checks on these sentences are exercised (not the omission rule)
    rep = res.report.model_copy(update={"question": "What happened around this price event?", "summary": [],
                                        "uncertainties": [], "possible_explanations": [], "numeric_claims": [],
                                        "citations": cites, **parts})
    v = validate(rep, res.registry, window=res.resolution.window, records=res.records)
    return [(x.code, x.detail) for x in v.critical if x.code in NOTICE_CODES]


# 1 ------------------------------------------------------------------------ notice timing: false positives in v3
def test_1a_v18_correct_timing_statement_is_accepted():
    """V18: 'between the first and last … intervals: first interval ending 04:35Z = 14:05 ACST; last … 22:20Z = 07:50
    ACST; and before the price extreme …' is correct, but was rejected: the one instant written twice was read as a
    two-ended range, and the sentence was cut at ';'."""
    res, draft = _replay("V18")
    assert _notice_codes(res, draft, summary=draft["summary"][:2]) == []


def test_1b_v18_price_peak_time_in_a_whether_clause_is_not_a_notice_zone_slip():
    """V18: an uncertainty ('Whether … was binding at 2026-07-30T16:35:00Z …') named the price peak; its clock
    matched another notice's time in ACST two days later, and it was rejected as a zone slip."""
    res, draft = _replay("V18")
    assert _notice_codes(res, draft, uncertainties=draft["uncertainties"][:1]) == []


def test_1c_v19_price_interval_time_in_a_hypothesis_is_not_a_notice_zone_slip():
    """V19: a hypothesis naming the Directlink notice and the price interval (07:30 AEST on 31 July) was rejected: the
    clock matched a notice time from 26 July under ACDT, which is not in force in July."""
    res, draft = _replay("V19")
    h = draft["possible_explanations"][0]
    hyp = Hypothesis(statement=h["statement"], supporting_evidence_ids=h["supporting_evidence_ids"],
                     what_would_test_it=h["what_would_test_it"])
    assert _notice_codes(res, draft, possible_explanations=[hyp]) == []


def test_1d_real_zone_slips_and_reversed_claims_are_still_rejected():
    """Guard (passes before and after): the fixes must not let a real slip or a reversed relation through."""
    res, draft = _replay("V18")
    slip = "The line outage notice gives 2026-07-30 16:00 AEST, after the price extreme."       # ACST clock as AEST
    reversed_ = ("The line outage notice gives 2026-07-30 16:00 ACST (2026-07-30T06:30:00Z), after the last 5-minute "
                 "interval at or above the analysis threshold.")
    assert "NOTICE_TIME_ZONE_MISMATCH" in {c for c, _ in _notice_codes(res, draft, summary=[slip])}
    assert "NOTICE_TIMING_CONTRADICTED" in {c for c, _ in _notice_codes(res, draft, summary=[reversed_])}


# 2 ------------------------------------------------------------------------ "issued at about <time>"
@pytest.mark.parametrize("case_id, issued", [("V07", "2026-07-28T07:57:01Z"), ("V08", "2026-07-30T09:26:58Z")])
def test_2_a_run_issued_at_about_a_time_is_not_an_as_of_cutoff(case_id, issued):
    """V07, V08: 'the run issued at about <time>' was read as an as-of cutoff, so the actual demand asked about was
    hidden and an earlier run was used."""
    rec = json.loads((V3 / f"{case_id}.json").read_text())
    assert rec["route"]["as_of_utc"]  # the model's route did set a cutoff
    seen: list[Any] = []

    def report(kw):
        seen.append(kw["input"])
        return ABSTAIN
    fake = FakeModel(rec["route"], [[]], report)
    res = investigate(InvestigateRequest(question=rec["question"], mode="live"), live_client=fake, write_trace=False)
    assert res.resolution.as_of is None
    ctx = json.loads(fake.requests[1]["input"][0]["content"].split("\n", 1)[1])
    run = ctx.get("requested_forecast_run") or {}
    assert run.get("run_id") and issued in json.dumps(run)


# 3 ------------------------------------------------------------------------ the low-price threshold
def test_3_the_low_price_threshold_is_citable_evidence(real_store, selection):
    """V01: the 0 $/MWh low-price threshold was a bare number in the price timeline, so 'below $0/MWh' was untraced."""
    ev = next(e for e in selection.events if e.region == "VIC1" and e.kind == "low_price")
    d = Dispatcher(real_store, selection, Trace(), EvidenceRegistry(), "market_event_review")
    v = d.call("get_price_timeline", {"region": "VIC1", "start_utc": ev.window_start_utc,
                                      "end_utc": ev.window_end_utc, "as_of_utc": None}).view
    thr = v["intervals_below_low_threshold"].get("threshold")
    assert isinstance(thr, dict) and thr.get("evidence_id"), thr
    item = d.registry.get(thr["evidence_id"])
    assert (item.value, item.unit) == (0.0, "$/MWh") and "project setting" in (item.derivation or "")


def test_3_a_sentence_citing_the_low_threshold_passes(real_store, selection):
    res = investigate(InvestigateRequest(question="What happened to VIC1 prices on 2026-07-28?", mode="replay"),
                      write_trace=False)
    ev = next(e for e in selection.events if e.region == "VIC1" and e.kind == "low_price")
    d = Dispatcher(real_store, selection, Trace(), res.registry, "market_event_review")
    v = d.call("get_price_timeline", {"region": "VIC1", "start_utc": ev.window_start_utc,
                                      "end_utc": ev.window_end_utc, "as_of_utc": None}).view
    low = v["intervals_below_low_threshold"]
    thr_id = low["threshold"]["evidence_id"] if isinstance(low.get("threshold"), dict) else "ev9999"
    rep = res.report.model_copy(update={
        "headline": "VIC1 prices were negative for much of the window.",
        "summary": [f"There were {low['value']} five-minute intervals below $0/MWh."],
        "numeric_claims": [NumericClaim(claim_id="n1", text="count", value=float(low["value"]), unit="intervals",
                                        evidence_id=low["evidence_id"], rounding=0.0),
                           NumericClaim(claim_id="n2", text="threshold", value=0.0, unit="$/MWh", evidence_id=thr_id,
                                        rounding=0.0)]})
    codes = {x.code for x in validate(rep, res.registry, window=res.resolution.window, records=res.records).critical}
    assert not codes & {"NUMERIC_UNTRACKED", "CLAIM_EVIDENCE_MISSING", "CLAIM_VALUE_MISMATCH", "CLAIM_UNIT_MISMATCH"}


# 4 ------------------------------------------------------------------------ document answers and forecast ranges
def test_4a_document_answers_cannot_carry_uncited_summary_sentences():
    """Regression H14 (and v3 V13, V14 first drafts): document answers written as free summary sentences without
    citations were rejected (DOC_CLAIM_UNCITED), and H14 fell back. The synthesis schema for a document question now
    has no free summary: every sentence is a document statement tied to a citation."""
    route = {"intent": "source_explanation", "region": None, "event_date": None, "as_of_utc": None,
             "needs_clarification": False, "clarification_reason": None, "clarification": None, "out_of_scope": False}
    fake = FakeModel(route, [[]], lambda kw: {k: v for k, v in ABSTAIN.items()
                                              if k in kw["text"]["format"]["schema"]["properties"]})
    investigate(InvestigateRequest(question="What counts towards operational demand?", mode="live"), live_client=fake,
                write_trace=False)
    synth = next(r for r in fake.requests if (r.get("text") or {}).get("format", {}).get("name") not in
                 (None, "RouteDecision"))
    props = synth["text"]["format"]["schema"]["properties"]
    assert "summary" not in props and "document_statements" in props


def test_4b_a_named_forecast_run_reports_its_poe10_and_poe90(real_store, selection):
    """Regression H05: for the run named by its issue time, compare_forecast_actual gave POE50 only, so the answer said
    POE10/POE90 'were not returned' and could not place the actual against the range."""
    rows = real_store.query("SELECT DISTINCT run_id FROM opdemand_forecast WHERE region='NSW1' AND "
                            "issued_at_utc = TIMESTAMPTZ '2026-07-30 11:56:59+00'")
    d = Dispatcher(real_store, selection, Trace(), EvidenceRegistry(), "forecast_review")
    v = d.call("compare_forecast_actual", {"region": "NSW1", "target_start_utc": "2026-07-30T19:00:00Z",
                                           "target_end_utc": "2026-07-30T23:00:00Z", "run_selector": "run_id",
                                           "run_id": rows[0]["run_id"], "min_lead_hours": None, "as_of_utc": None,
                                           "actual_revision": "latest_available",
                                           "actual_metric": "OPERATIONAL_DEMAND"}).view
    p = next(x for x in v["pairs"] if x["target_end_utc"] == "2026-07-30T21:30:00Z")
    assert p.get("poe10_evidence_id") and p.get("poe90_evidence_id"), sorted(p)
    assert d.registry.get(p["poe10_evidence_id"]).metric == "opdemand_forecast_poe10"
    assert d.registry.get(p["poe90_evidence_id"]).metric == "opdemand_forecast_poe90"
    assert p["poe90_mw"] <= p["poe50_mw"] <= p["poe10_mw"]
    assert p.get("actual_vs_poe_band") in ("above POE10", "within POE90-POE10", "below POE90")
