"""Request resolution from role spans, route contract v13 (D26).

Covered:
- the v13 contract and the v12 adapter;
- locating spans;
- the five reproductions of the demand-maxima Live check (D01, D02, F02, F06, F07);
- role consistency and conflicts;
- the unresolved-request gate;
- role-aware temporal coverage;
- the as-of cutoff converted by code.

Saved Live routing decisions are read as recorded. Decisions written here are SYNTHETIC, labelled as such, and are
not Live evidence. Replays go through the fake transport: no network, no key.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nem_agent.agent.live import RouteDecision, RouteDecisionV12, checked_route
from nem_agent.agent.request import InvestigateRequest
from nem_agent.agent.structured import (
    RoutedRequest,
    RoutedRequestV12,
    _first_instant,
    locate,
    span,
)
from nem_agent.selection import load_selection
from nem_agent.service import investigate, resolve_routed
from nem_agent.tools.args import strict_json_schema
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "artifacts" / "live"
SEL = load_selection()
GOLD = {c["case_id"]: c for c in json.loads((ROOT / "eval/livecheck_maxima/GOLD.json").read_text())["cases"]}
NO_RUN = {"selection": "none", "selection_text": None, "half_hour_text": None}
NO_MAX = {"kind": "none", "measure": None, "measure_text": None, "peak_text": None, "window": None, "window_text": None}
CORE = {"intent": "market_event_review", "needs_clarification": False, "clarification_reason": None,
        "clarification": None, "out_of_scope": False}


def _rec(cid: str) -> dict[str, Any]:
    return json.loads((LIVE / "LC-maxima-run" / f"{cid}.json").read_text())


def _v13(region: str, event_date: str | None, mx: dict | None = None, run: dict | None = None,
         as_of_text: str | None = None, intent: str = "market_event_review") -> dict[str, Any]:
    """A SYNTHETIC v13 routing decision."""
    return {**CORE, "intent": intent, "region": region, "event_date": event_date, "as_of_text": as_of_text,
            "requested": {"forecast_run": {**NO_RUN, **(run or {})}, "maximum": {**NO_MAX, **(mx or {})}}}


def _resolve(question: str, decision: dict[str, Any], **request: Any):
    req = InvestigateRequest(question=question, mode="live", **request)
    return resolve_routed(req, checked_route(RouteDecision.model_validate(decision)), SEL)


def _window(res) -> list[str]:
    return [t.isoformat().replace("+00:00", "Z") for t in res.requests.maximum.window]


def _matches_gold(res, cid: str) -> bool:
    g = GOLD[cid]["reading"]
    mx = res.requests.maximum
    as_of = res.as_of.isoformat().replace("+00:00", "Z") if res.as_of else None
    return (res.status == "ok" and mx.status == "bound" and mx.measures == [g["measure"]]
            and mx.window_kind == g["window_kind"] and _window(res) == g["window_utc"] and as_of == g["as_of_utc"])


# SYNTHETIC v13 readings of the three questions that were sent back although the model read them correctly
V13_MAX = {
    "D01": (dict(kind="maximum", measure="dispatch_total_demand", measure_text="NSW dispatch total demand",
                 peak_text="highest", window="whole_local_day", window_text="across the whole day"), None),
    "F06": (dict(kind="maximum", measure="dispatch_total_demand", measure_text="VIC1 dispatch total demand (TOTALDEMAND)",
                 peak_text="how high", window="event", window_text="that event's full window"), None),
    "F07": (dict(kind="maximum", measure="operational_demand", measure_text="operational demand", peak_text="highest",
                 window="whole_local_day", window_text="that entire local day"),
            "published by noon Brisbane time on Sunday 5 October 2025"),
}


# ------------------------------------------------------------------------------------------------ the contract
def test_the_v13_contract_has_spans_and_no_model_timestamps():
    schema = json.dumps(strict_json_schema(RouteDecision))
    for gone in ("as_of_utc", "target_half_hour_end_utc", "issued_at_utc", "window_start_utc", "window_end_utc"):
        assert f'"{gone}"' not in schema
    for span_field in ("as_of_text", "peak_text", "measure_text", "window_text", "half_hour_text", "selection_text"):
        assert f'"{span_field}"' in schema
    def leaves(o: Any) -> int:  # the fields the model writes
        if isinstance(o, dict) and "properties" in o:
            return sum(leaves(v) for v in o["properties"].values())
        if isinstance(o, dict) and "anyOf" in o:
            return max(leaves(v) for v in o["anyOf"])
        return 1
    v12 = strict_json_schema(RouteDecisionV12)
    assert (leaves(strict_json_schema(RouteDecision)), leaves(v12)) == (17, 20)  # a slimmer output contract
    assert "description" not in strict_json_schema(RouteDecision) and "description" not in v12  # no docstring leaks


def test_a_v12_decision_is_read_through_the_adapter_without_its_timestamps():
    rec = _rec("D01")
    dec = RouteDecision.model_validate(rec["route"])
    assert dec.contract == "v12" and dec.as_of_text is None
    assert dec.requested is not None and dec.requested.maximum.peak_text == rec["route"]["requested"]["maximum"]["measure_text"]
    routed = checked_route(dec).routed()
    assert routed.contract == "v12" and not routed.legacy_cutoff
    v12 = RoutedRequestV12.model_validate(_rec("F07")["route"]["requested"])  # the legacy shape still parses exactly
    assert v12.maximum.window_text == "that entire local day"
    with_cutoff = RouteDecision.model_validate(_rec("F07")["route"])
    assert with_cutoff.contract == "v12" and with_cutoff.routed().legacy_cutoff  # detection only, never its value
    v13 = RouteDecision.model_validate(_v13("NSW1", "2026-07-29", V13_MAX["D01"][0]))
    assert v13.contract == "v13" and isinstance(v13.requested, RoutedRequest)


# ------------------------------------------------------------------------------------------------ locating spans
def test_spans_are_located_by_offsets_that_hold_exactly_the_quoted_words():
    q = "Highest total demand over that entire local day — and again: that   ENTIRE local day."
    occ = locate("that entire local day", q)
    assert len(occ) == 2 and all(q[a:b].lower().split() == ["that", "entire", "local", "day"] for a, b in occ)
    assert span("window", "that entire local day", q).located is None  # repeated: read, but locates nothing
    assert span("window", "day - and", q).located == (q.index("day —"), q.index("day —") + len("day — and"))
    assert span("window", "not in it", q) is None and locate("da", q) == ()


# ------------------------------------------------------------------------------------------------ the reproductions
@pytest.mark.parametrize("cid", ["D01", "F06"])
def test_d01_and_f06_bind_gold_from_their_saved_v12_decisions_and_from_v13(cid):
    rec = _rec(cid)
    saved = _resolve(rec["question"], rec["route"], **rec["request"])
    assert _matches_gold(saved, cid)  # the saved reading was right: its peak is evidenced by the code's cue
    assert any(u.startswith("peak:") for u in saved.requests.maximum.unused)
    mx, cutoff = V13_MAX[cid]
    res = _resolve(rec["question"], _v13(rec["route"]["region"], rec["route"]["event_date"], mx, as_of_text=cutoff),
                   **rec["request"])
    assert _matches_gold(res, cid) and res.requests.maximum.unused == []


def test_f07_binds_gold_from_v13_and_its_v12_decision_stays_sent_back():
    rec = _rec("F07")
    mx, cutoff = V13_MAX["F07"]
    res = _resolve(rec["question"], _v13("QLD1", "2025-10-05", mx, as_of_text=cutoff), **rec["request"])
    assert _matches_gold(res, "F07")
    sp = res.requests.cutoff.spans
    assert any(s.source == "route_model" and s.located for s in sp)  # "noon" is the cutoff's, not the window's
    # the v12 decision quoted no cutoff words (v12 had no field for them): "noon" cannot be attributed, so it still
    # narrows the window and the question is sent back (D26: the adapter invents no span)
    saved = _resolve(rec["question"], rec["route"], **rec["request"])
    assert saved.status == "needs_clarification" and saved.requests.maximum.missing == ["window"]
    # the same question with the cutoff's words omitted from a v13 decision: sent back, never the whole day guessed
    omitted = _resolve(rec["question"], _v13("QLD1", "2025-10-05", mx), **rec["request"])
    assert omitted.status == "needs_clarification" and omitted.requests.maximum.status == "unresolved"


@pytest.mark.parametrize("cid", ["D01", "F06", "F07"])
def test_the_reproductions_compute_the_gold_result_through_the_fake_transport(cid):
    rec = _rec(cid)
    mx, cutoff = V13_MAX[cid]
    route = _v13(rec["route"]["region"], rec["route"]["event_date"], mx, as_of_text=cutoff)
    draft = {"status": "answered", "headline": "SYNTHETIC answer.", "summary": ["SYNTHETIC."], "document_statements": [],
             "observation_evidence_ids": [], "possible_explanations": [], "published_findings": [], "citations": [],
             "uncertainties": [], "missing_evidence": [], "forecast_mae_evidence_id": None, "numeric_claims": []}
    fake = FakeModel(route, [[]], lambda kw: dict(draft))
    res = investigate(InvestigateRequest(question=rec["question"], mode="live", **rec["request"]), live_client=fake,
                      write_trace=False)
    (r,) = res.report.results
    g = GOLD[cid]["result"]
    assert r.server_verification.outcome == "verified" and res.report.answer[0].verification == "verified"
    value = r.result.maximum if r.result.status == "established" else r.result.highest_held
    ends = r.result.interval_ends_utc or r.result.highest_held_interval_ends_utc
    assert (r.result.status, value, list(ends), list(r.result.source_row_ids)) == (
        g["status"], g["value"], g["interval_ends_utc"], g["source_row_ids"])
    assert r.result.coverage is not None and r.result.coverage.excluded_by_as_of == g["excluded_rows_by_as_of"]


@pytest.mark.parametrize("cid", ["D02", "F02"])
def test_an_incomplete_routing_response_is_rejected_before_parsing(cid):
    """SYNTHETIC: the saved diagnostics show valid JSON, then whitespace up to the 2,000-token cap. The response is
    incomplete, so it is rejected before parsing: no salvage, no retry and no other call."""
    trace_ev = json.loads((LIVE / "LC-maxima-run" / "traces" / f"{_rec(cid)['trace_id']}.json").read_text())["events"]
    diag = next(e for e in trace_ev if e["name"] == "route:incomplete_output")

    class Truncated(FakeModel):
        def create(self, **kw: Any) -> dict[str, Any]:
            self.requests.append(kw)
            return {"id": "resp_x", "status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
                    "output": [{"type": "message", "role": "assistant",
                                "content": [{"type": "output_text", "text": diag["head"] + " \r" * 400}]}],
                    "usage": {"input_tokens": 1513, "output_tokens": 2000,
                              "output_tokens_details": {"reasoning_tokens": 832}}}

    fake = Truncated({}, [], lambda kw: {})
    res = investigate(InvestigateRequest(question=_rec(cid)["question"], mode="live"), live_client=fake,
                      write_trace=False)
    assert res.report.status == "needs_clarification" and len(fake.requests) == 1
    assert res.report.results == [] and res.report.answer == []


# ------------------------------------------------------------------------------------------------ roles
Q_DAY = "On 29 July 2026 (Brisbane time), when did QLD1 operational demand peak across the whole day, and at what level?"
DAY_MX = dict(kind="maximum", measure="operational_demand", measure_text="QLD1 operational demand", peak_text="peak",
              window="whole_local_day", window_text="across the whole day")


def test_a_correct_v13_reading_binds_the_whole_day():
    res = _resolve(Q_DAY, _v13("QLD1", "2026-07-29", DAY_MX))
    assert res.requests.maximum.status == "bound" and _window(res) == ["2026-07-28T14:00:00Z", "2026-07-29T14:00:00Z"]
    assert {s.role for s in res.requests.maximum.spans} == {"measure", "peak", "window"}


@pytest.mark.parametrize("change,why", [
    (dict(measure="dispatch_total_demand"), "measure: the words 'QLD1 operational demand' name operational demand"),
    (dict(measure_text="across the whole day"), "measure: the words 'across the whole day' name no measure"),
])
def test_a_measure_whose_words_show_another_role_is_not_used(change, why):
    """SYNTHETIC: a verbatim span proves the words exist, not their role. Here the parser still reads the measure from
    the question, so the request binds by the parser, and the model's inconsistent reading is recorded as unused."""
    res = _resolve(Q_DAY, _v13("QLD1", "2026-07-29", {**DAY_MX, **change}))
    mx = res.requests.maximum
    assert any(u.startswith(why) for u in mx.unused)
    assert mx.status == "bound" and mx.measures == ["operational demand"] and mx.provenance["measure"].source == "question"


def test_a_maximum_with_no_peak_evidence_is_sent_back_never_bound():
    """SYNTHETIC: the model claims a maximum, but nothing in the question asks for one (a value at a time). The gate
    sends it back; it does not take a generic path."""
    q = "What was QLD1 operational demand at 6 pm AEST on 29 July 2026?"
    res = _resolve(q, _v13("QLD1", "2026-07-29", {**DAY_MX, "measure_text": "QLD1 operational demand",
                                                  "peak_text": "at 6 pm AEST", "window_text": "29 July 2026"}))
    mx = res.requests.maximum
    assert mx.status == "unresolved" and res.status == "needs_clarification"
    assert any(u.startswith("peak:") for u in mx.unused)


def test_demand_at_the_price_peak_is_not_a_maximum_even_if_claimed():
    q = "On 29 July 2026, what was QLD1 operational demand at the price peak across the whole day?"
    res = _resolve(q, _v13("QLD1", "2026-07-29", {**DAY_MX, "peak_text": "price peak"}))
    assert res.requests.maximum.status != "bound" and res.status == "needs_clarification"


@pytest.mark.parametrize("q,mx", [
    ("When did QLD1 demand peak across the whole day on 29 July 2026?",
     dict(kind="maximum", measure="unspecified", measure_text="QLD1 demand", peak_text="peak",
          window="whole_local_day", window_text="across the whole day")),
    ("When did QLD1 operational demand peak in the evening of 29 July 2026?",
     dict(DAY_MX, window_text="29 July 2026")),
    ("When did QLD1 operational demand peak on 29 July 2026?", dict(DAY_MX, window="unspecified", window_text=None)),
])
def test_genuine_ambiguity_is_sent_back(q, mx):
    """SYNTHETIC: no measure named; a part of the day that narrows the window; no window kind given (the parser's
    whole-day wording "on 29 July 2026" binds the day here, so this one binds, as before)."""
    res = _resolve(q, _v13("QLD1", "2026-07-29", mx))
    if mx.get("window") == "unspecified":
        assert res.requests.maximum.status == "bound"  # the date wording is the parser's own whole-day reading
    else:
        assert res.status == "needs_clarification" and res.requests.maximum.status != "bound"


# ------------------------------------------------------------------------------------------------ temporal coverage
Q_CUT = ("Based only on data published by noon Brisbane time on 29 July 2026, what was the highest QLD1 operational "
         "demand over that entire local day, and at what time?")
CUT_MX = dict(kind="maximum", measure="operational_demand", measure_text="QLD1 operational demand", peak_text="highest",
              window="whole_local_day", window_text="that entire local day")


def test_a_cutoff_never_narrows_the_analysis_window():
    res = _resolve(Q_CUT, _v13("QLD1", "2026-07-29", CUT_MX,
                               as_of_text="published by noon Brisbane time on 29 July 2026"),
                   as_of_utc="2026-07-29T02:00:00Z")
    assert res.requests.maximum.status == "bound" and _window(res) == ["2026-07-28T14:00:00Z", "2026-07-29T14:00:00Z"]


def test_misplaced_and_overlapping_spans_are_conflicts():
    """SYNTHETIC: the window's words given as the cutoff's too; the cutoff's words given as the target half-hour."""
    clash = _resolve(Q_CUT, _v13("QLD1", "2026-07-29", {**CUT_MX, "window_text": "noon Brisbane time on 29 July 2026"},
                                 as_of_text="published by noon Brisbane time on 29 July 2026"))
    assert clash.requests.maximum.status == "conflict" and "as the window and as the cutoff" in \
        clash.requests.maximum.conflicts[0]
    q = ("As of 18:00 AEST on 6 August 2026, what POE50 did the last QLD1 operational demand forecast run issued before "
         "the 18:00 AEST half-hour give?")
    res = _resolve(q, _v13("QLD1", "2026-08-06", intent="forecast_review",
                           run=dict(selection="last_issued_before", selection_text="the last QLD1 operational demand "
                                    "forecast run issued before", half_hour_text="As of 18:00 AEST on 6 August 2026"),
                           as_of_text="As of 18:00 AEST on 6 August 2026"))
    assert res.requests.cutoff.status == "conflict" and res.status == "needs_clarification"


def test_a_repeated_cutoff_span_locates_nothing_and_so_masks_nothing():
    """SYNTHETIC: "noon" twice. The model's cutoff words are just "noon", which occurs twice, so they cover neither
    occurrence: the evening-or-noon wording still narrows the window, and the question is sent back."""
    q = ("As known by noon on 29 July 2026, when did QLD1 operational demand peak around noon across the whole day?")
    res = _resolve(q, _v13("QLD1", "2026-07-29", {**DAY_MX, "peak_text": "peak"}, as_of_text="noon"))
    assert span("cutoff", "noon", q).located is None
    assert res.requests.maximum.status != "bound" and res.status == "needs_clarification"


def test_a_mixed_question_binds_the_run_and_the_maximum_and_their_times_do_not_collide():
    """SYNTHETIC: a run named for one half-hour and a whole-day maximum, with the same clock time written twice."""
    q = ("For QLD1 on 6 August 2026 (AEST), what did the last forecast run issued before the 17:30-18:00 half-hour give "
         "as POE50, and when did operational demand peak across the whole day? Use 17:30-18:00 AEST.")
    res = _resolve(q, _v13("QLD1", "2026-08-06", intent="forecast_review",
                           run=dict(selection="last_issued_before", selection_text="the last forecast run issued before",
                                    half_hour_text="the 17:30-18:00 half-hour"),
                           mx=dict(kind="maximum", measure="operational_demand", measure_text="operational demand",
                                   peak_text="peak", window="whole_local_day", window_text="across the whole day")))
    fr, mx = res.requests.forecast_run, res.requests.maximum
    assert fr.status == "bound" and [t.isoformat() for t in fr.half_hour] == ["2026-08-06T07:30:00+00:00",
                                                                             "2026-08-06T08:00:00+00:00"]
    assert mx.status == "bound" and _window(res) == ["2026-08-05T14:00:00Z", "2026-08-06T14:00:00Z"]


# ------------------------------------------------------------------------------------------------ the cutoff
@pytest.mark.parametrize("question,words,region,gold", [
    ("As at 9:00 pm AEST on 5 August 2026, which operational demand forecast for VIC1's 6:00–6:30 pm half-hour on "
     "6 August 2026 was the newest one the public could already see?", "As at 9:00 pm AEST on 5 August 2026", "VIC1",
     "2026-08-05T11:00:00Z"),
    ("Put yourself at 16:30 Adelaide time, 30 July 2026: what did the market know then about SA1 operational demand in "
     "the half-hour ending 19:00 market time?", "Put yourself at 16:30 Adelaide time, 30 July 2026", "SA1",
     "2026-07-30T07:00:00Z"),
])
def test_cutoff_words_are_converted_by_code_to_the_gold_time(question, words, region, gold):
    """The two cutoffs of the saved routes and the paraphrase matrix that only the v12 model's timestamp gave (Q23,
    P22): the words, quoted under v13, convert to the independently checked gold time."""
    t, conv = _first_instant(words, question, region)
    assert t is not None and t.isoformat().replace("+00:00", "Z") == gold, conv


def test_a_detected_cutoff_that_cannot_be_read_is_sent_back_never_dropped():
    res = _resolve(Q_CUT, _v13("QLD1", "2026-07-29", CUT_MX,
                               as_of_text="published by noon Brisbane time on 29 July 2026"))
    co = res.requests.cutoff
    assert co.status == "unresolved" and res.as_of is None and res.status == "needs_clarification"
    assert any("as-of cutoff" in r for r in res.reasons)


def test_an_issue_time_is_never_a_cutoff_and_the_request_field_is_authoritative():
    q = ("Take the forecast run issued at 2026-07-30T18:56:59Z. For TAS1's half-hour ending at 8:00 am AEST on "
         "31 July 2026, which POE50 did it give?")
    res = _resolve(q, _v13("TAS1", "2026-07-31", intent="forecast_review",
                           run=dict(selection="issued_at", selection_text="the forecast run issued at "
                                                                          "2026-07-30T18:56:59Z",
                                    half_hour_text="half-hour ending at 8:00 am AEST on 31 July 2026"),
                           as_of_text="issued at 2026-07-30T18:56:59Z"))
    assert res.as_of is None and any("issue time" in n for n in res.requests.cutoff.notes)
    assert res.requests.forecast_run.status == "bound"
    given = _resolve(Q_CUT, _v13("QLD1", "2026-07-29", CUT_MX,
                                 as_of_text="published by noon Brisbane time on 29 July 2026"),
                     as_of_utc="2026-07-29T02:00:00Z")
    assert given.requests.cutoff.provenance["as_of"].source == "request" and given.status == "ok"


def test_the_parser_and_the_models_cutoff_words_disagreeing_is_a_conflict():
    """SYNTHETIC: the parser reads "As of 14:00 AEST" (04:00Z); the model quotes other words of the question as the
    cutoff, which convert to 06:00Z. The two readings disagree: sent back, neither applied. Words that hold no time
    are not a reading at all, and the parser's cutoff stands."""
    q = ("As of 14:00 AEST on 31 July 2026, with data published by 16:00 AEST, when did TAS1 operational demand peak "
         "across the whole day?")
    mx = dict(DAY_MX, measure_text="TAS1 operational demand")
    clash = _resolve(q, _v13("TAS1", "2026-07-31", mx, as_of_text="data published by 16:00 AEST"))
    assert clash.requests.cutoff.status == "conflict" and clash.as_of is None and clash.status == "needs_clarification"
    same = _resolve(q, _v13("TAS1", "2026-07-31", mx, as_of_text="As of 14:00 AEST on 31 July 2026"))
    assert same.requests.cutoff.status == "bound" and same.as_of.isoformat() == "2026-07-31T04:00:00+00:00"
    no_time = _resolve(q, _v13("TAS1", "2026-07-31", mx, as_of_text="31 July 2026"))
    assert no_time.requests.cutoff.status == "bound" and no_time.as_of.isoformat() == "2026-07-31T04:00:00+00:00"
