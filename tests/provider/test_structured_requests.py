"""Issue I-18 (docs/issue-tracker.md): forecast-run and demand-maximum requests resolved from the request, the question
parsers and the routing model's grounded reading, with provenance; a detected request that is not bound is sent back.

The targeted Live check of I-15–I-17 (2026-10-02) showed the bindings engaging only on the wording their patterns
read: K06 ("the final forecast run issued ahead of it") and K07 showed another run as the one asked for, K09 ("total
demand highest") and K10 ("hit its highest point") a wrong maximum, and K05 (an am/pm half-hour) was sent back.

Replays use saved Live records through the SYNTHETIC fake transport (no network, no key). Routing decisions marked
"scripted" add a ``requested`` field as a correct model following prompts v12 would; the controls use SYNTHETIC
registries where stated.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from nem_agent import config
from nem_agent.agent.live import RouteDecision, checked_route
from nem_agent.agent.request import InvestigateRequest, Resolution, resolve
from nem_agent.agent.structured import (
    MAXIMUM_UNREAD_CLARIFICATION,
    NAMED_RUN_HALF_HOUR_CLARIFICATION,
    RUN_RULE_CLARIFICATION,
    RoutedRequest,
    forecast_run_cue,
    half_hour_from_text,
    maximum_cue,
)
from nem_agent.evidence import EvidenceRegistry
from nem_agent.report import NumericClaim
from nem_agent.selection import load_selection
from nem_agent.service import investigate, resolve_routed
from nem_agent.validation import validate
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

ROOT = Path(__file__).resolve().parents[2]
FRESH = ROOT / "artifacts" / "live" / "LC-i15-17-fresh"
DEV = ROOT / "artifacts" / "live" / "LC-i15-17-dev"
GOLD = {c["case_id"]: c for c in json.loads((ROOT / "eval" / "livecheck_i15_17" / "GOLD.json").read_text())["cases"]}
NO_RUN = {"selection": "none", "selection_text": None, "half_hour_text": None, "target_half_hour_end_utc": None,
          "issued_at_utc": None}
NO_MAX = {"kind": "none", "measure": None, "measure_text": None, "window": None, "window_text": None,
          "window_start_utc": None, "window_end_utc": None}
# what a correct routing model following prompts v12 returns for the check's run and maximum questions (scripted)
SCRIPTED = {
    "K05": ({"selection": "last_issued_before", "selection_text": "the most recent forecast run issued before that half-hour",
             "half_hour_text": "the 5:30 to 6:00 pm (AEST) half-hour in Queensland on 6 August 2026",
             "target_half_hour_end_utc": "2026-08-06T08:00:00Z", "issued_at_utc": None}, NO_MAX),
    "K06": ({"selection": "last_issued_before", "selection_text": "the final forecast run issued ahead of it",
             "half_hour_text": "7:30-8:00 am half-hour (Adelaide time, ACST) on 20 August 2026",
             "target_half_hour_end_utc": "2026-08-19T22:30:00Z", "issued_at_utc": None}, NO_MAX),
    "K07": ({"selection": "last_issued_before",
             "selection_text": "the latest operational demand forecast run issued before it",
             "half_hour_text": "half-hour 5:00-5:30 pm AEST, 6 Aug 2026",
             "target_half_hour_end_utc": "2026-08-06T07:30:00Z", "issued_at_utc": None}, NO_MAX),
    "K09": (NO_RUN, {"kind": "maximum", "measure": "dispatch_total_demand",
                     "measure_text": "NSW dispatch total demand highest", "window": "whole_local_day",
                     "window_text": "across the whole day", "window_start_utc": None, "window_end_utc": None}),
    # K10's window words include the words that identify its event ("whose lowest price came at 9:20 pm AEST on 28
    # July 2026"), as the v13 contract asks (D26): a time held by no role's words would block the window. The shorter
    # reading first scripted here is kept below (K10_SHORT_WINDOW), and is sent back
    "K10": (NO_RUN, {"kind": "maximum", "measure": "dispatch_total_demand",
                     "measure_text": "dispatch total demand hit its highest point", "window": "event",
                     "window_text": "the full window of the Victorian negative-price event whose lowest price came at "
                                    "9:20 pm AEST on 28 July 2026", "window_start_utc": None,
                     "window_end_utc": None}),
}
K10_SHORT_WINDOW = "the full window of the Victorian negative-price event"


def _rec(cid: str) -> dict:
    return json.loads(((DEV if cid.startswith("Z") else FRESH) / f"{cid}.json").read_text())


# K05 was sent back in the Live check, so it has no saved tool calls or draft: the calls a model makes for it, scripted
K05_CALLS = [("get_forecast_runs", {"region": "QLD1", "target_start_utc": "2026-08-06T02:00:00Z",
                                    "target_end_utc": "2026-08-06T14:00:00Z", "as_of_utc": None, "max_runs": 8}),
             ("get_actual_demand", {"region": "QLD1", "start_utc": "2026-08-05T14:00:00Z", "end_utc": "2026-08-06T14:00:00Z",
                                    "revision_policy": "latest_available", "as_of_utc": None}),
             ("compare_forecast_actual", {"region": "QLD1", "target_start_utc": "2026-08-06T02:00:00Z",
                                          "target_end_utc": "2026-08-06T14:00:00Z", "run_selector": "latest_before_target",
                                          "min_lead_hours": None, "run_id": None, "as_of_utc": None,
                                          "actual_revision": "latest_available", "actual_metric": "OPERATIONAL_DEMAND"})]
BASE_DRAFT = {"status": "answered_with_caveats", "headline": "SYNTHETIC answer.", "summary": [],
              "document_statements": [], "observation_evidence_ids": [], "possible_explanations": [],
              "published_findings": [], "citations": [], "uncertainties": [], "missing_evidence": [],
              "forecast_mae_evidence_id": None, "numeric_claims": []}


def _calls(rec: dict) -> list:
    return [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
            if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"] or \
        (K05_CALLS if rec["question"].startswith("Looking at the 5:30 to 6:00 pm") else [])


def _draft_of(rec: dict) -> dict:
    return rec["drafts"].get("synthesis:draft") or BASE_DRAFT


def _replay(cid: str, *, scripted: bool = False, draft_fn=None):
    rec = _rec(cid)
    route = dict(rec["route"])
    if scripted:
        run, mx = SCRIPTED[cid]
        route["requested"] = {"forecast_run": run, "maximum": mx}
    draft = _draft_of(rec)
    fake = FakeModel(route, [_calls(rec)], draft_fn or (lambda kw: copy.deepcopy(draft)))
    res = investigate(InvestigateRequest(question=rec["question"], mode="live", **(rec.get("request") or {})),
                      live_client=fake, write_trace=False)
    return res, fake


def _codes(res) -> set[str]:
    v = res.report.validation
    return {x["code"] for x in (v.get("pre_repair") or v.get("initial") or {}).get("violations", [])}


# ------------------------------------------------------------------------------------------------ 1. the matrix
def _matrix() -> dict:
    spec = importlib.util.spec_from_file_location("run_matrix", ROOT / "eval" / "structured_requests" / "run_matrix.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.run()


def test_the_paraphrase_matrix_three_ways():
    """(a) no model fields: every item bound as expected or sent back, except P20, a recorded departure (it asks for
    "the forecast" for a half-hour without singling out a run, and keeps the documented default selection); (b) the
    independently written correct fields: every expected binding supplied; (c) mutated fields: no wrong binding."""
    s = _matrix()["summary"]
    assert s["a"]["failing"] == ["P20:a_absent:UNBOUND"]
    assert s["b"]["passes"] and s["b"]["supplied_of_expected_bound"] == "33/33"
    assert s["c"]["passes"] and "WRONG" not in s["c"]["counts"]


# ------------------------------------------------------------------------------------------------ 2. the check's records
@pytest.mark.parametrize("cid", ["K06", "K07", "K09", "K10"])
def test_with_their_saved_routes_the_failed_requests_are_sent_back_not_answered(cid):
    """Saved routes have no ``requested`` field ("not reported"): the cue detects the request, nothing binds it, and
    the question is sent back before any tool runs, so no other run or maximum is shown."""
    res, fake = _replay(cid)
    assert res.report.status == "needs_clarification" and not res.records and len(fake.requests) == 1
    assert res.resolution.requests.routed == "not reported"
    assert "cue" in (res.resolution.requests.forecast_run.detected_by + res.resolution.requests.maximum.detected_by)
    assert res.report.headline.startswith("Clarification needed: ") and (
        RUN_RULE_CLARIFICATION in res.report.headline or MAXIMUM_UNREAD_CLARIFICATION in res.report.headline)


def _gold_run(cid: str) -> str:
    return GOLD[cid]["gold_numbers"][0]["store_rows"][0]["run_id"]


def _faithful_run(cid: str):
    """A scripted answer citing the controller's comparison of the run asked for."""
    def draft_fn(kw):
        msg = next(i["content"] for i in kw["input"] if isinstance(i, dict) and
                   str(i.get("content", "")).startswith("Requested forecast run, compared by the controller"))
        pair = json.loads(msg.split("\n", 1)[1])["comparison"]
        claims = [("n1", "POE50", pair["poe50_mw"], pair["poe50_evidence_id"]),
                  ("n2", "actual operational demand", pair["actual_mw"], pair["actual_evidence_id"])]
        return {**copy.deepcopy(_draft_of(_rec(cid))), "forecast_mae_evidence_id": None,
                "uncertainties": [], "missing_evidence": [], "possible_explanations": [], "published_findings": [],
                "citations": [], "document_statements": [], "observation_evidence_ids": [c[3] for c in claims],
                "numeric_claims": [{"claim_id": i, "text": f"{name} {v:.1f} MW", "value": v, "unit": "MW",
                                    "evidence_id": e, "rounding": 0.0} for i, name, v, e in claims],
                "headline": f"For the half-hour ending {pair['target_end_utc']}, the run asked for gave POE50 "
                            f"{pair['poe50_mw']:.1f} MW; actual operational demand was {pair['actual_mw']:.1f} MW.",
                "summary": []}
    return draft_fn


@pytest.mark.parametrize("cid", ["K05", "K06"])
def test_with_scripted_fields_the_run_asked_for_is_bound_and_supplied(cid):
    res, _ = _replay(cid, scripted=True, draft_fn=_faithful_run(cid))
    run = res.resolution.forecast_run
    assert run["run_id"] == _gold_run(cid)
    assert run["half_hour_end_utc"] == GOLD[cid]["gold_numbers"][0]["valid_at_utc"]
    v = res.report.validation
    assert v["final_passed"] and not v["fallback_applied"], v["initial"]["violations"]
    gold = {(g["metric"], g["value"]) for g in GOLD[cid]["gold_numbers"]}
    shown = {(o.metric, o.value) for o in res.report.observations}
    assert {("opdemand_forecast_poe50", g) for m, g in gold if m == "opdemand_forecast_poe50"} <= shown
    prov = res.resolution.requests.forecast_run.provenance
    assert prov["half_hour"].source == "route_model" and "->" in prov["half_hour"].conversion


@pytest.mark.parametrize("cid", ["K05", "K06"])
def test_with_scripted_fields_the_saved_answers_using_another_run_are_rejected(cid):
    res, _ = _replay(cid, scripted=True)
    if cid == "K06":  # the saved answer gave another run's values for the half-hour
        assert "FORECAST_RUN_SUBSTITUTED" in _codes(res) and res.report.validation["fallback_applied"]
    gold_run = _gold_run(cid)
    for o in res.report.observations:
        if o.metric.startswith("opdemand_forecast") and o.valid_at_utc == GOLD[cid]["gold_numbers"][0]["valid_at_utc"]:
            assert any(gold_run in r for r in o.source_row_ids)


def test_with_scripted_fields_k07_is_answered_unavailable():
    """K07's run asked for was not public by the request's cutoff: it is reported unavailable, and the run that was
    public (issued an hour earlier) does not stand in for it."""
    res, _ = _replay("K07", scripted=True)
    run = res.resolution.forecast_run
    assert run["run_id"] is None and run["half_hour_end_utc"] == "2026-08-06T07:30:00Z"
    other = GOLD["K07"]["runs"]["must_not_substitute"]["run_id"]
    assert not any(other in r for o in res.report.observations for r in o.source_row_ids)
    assert not any(other in r for o in res.report.numeric_claims if (ev := res.registry.get(o.evidence_id))
                   for r in ev.source_row_ids)


def _faithful_max(cid: str):
    """A scripted answer stating the maximum the controller computed, with its evidence."""
    def draft_fn(kw):
        msg = next(i["content"] for i in kw["input"] if isinstance(i, dict) and
                   str(i.get("content", "")).startswith("Requested demand maximum, computed by the controller"))
        b = json.loads(msg.split("\n", 1)[1])[0]
        e, v = b["evidence_ids"][0], b["value"]
        return {**copy.deepcopy(_draft_of(_rec(cid))), "forecast_mae_evidence_id": None,
                "uncertainties": [], "missing_evidence": [], "possible_explanations": [], "published_findings": [],
                "citations": [], "document_statements": [], "observation_evidence_ids": [e],
                "numeric_claims": [{"claim_id": "n1", "text": f"{v} MW", "value": v, "unit": "MW", "evidence_id": e,
                                    "rounding": 0.005}],
                "headline": f"Dispatch total demand peaked at {v} MW in the interval ending {b['interval_ends_utc'][0]}.",
                "summary": []}
    return draft_fn


@pytest.mark.parametrize("cid", ["K09", "K10"])
def test_with_scripted_fields_the_maximum_asked_for_is_computed_and_supplied(cid):
    res, _ = _replay(cid, scripted=True, draft_fn=_faithful_max(cid))
    b = res.resolution.demand_max[0]
    g = GOLD[cid]["gold_numbers"][0]
    assert (b["measure"], b["value"], b["interval_ends_utc"], b["complete"]) == ("total demand", g["value"],
                                                                                [g["valid_at_utc"]], True)
    assert b["window_utc"] == GOLD[cid]["window_utc"]
    v = res.report.validation
    assert v["final_passed"] and not v["fallback_applied"], v["initial"]["violations"]
    assert any(f"was highest at {g['value']:g} MW" in s or f"was highest at {g['value']} MW" in s
               for s in [a.statement for a in res.report.answer])  # the computed answer (D25)


def test_with_scripted_fields_k10s_window_without_its_identifying_time_is_sent_back():
    """D26: "9:20 pm AEST" is written outside the shorter window words, held by no role's words, so it may narrow the
    window: the event window is not bound and no maximum is computed in its place (the guarantee, not a phrase rule)."""
    run, mx = SCRIPTED["K10"]
    res = resolve_routed(InvestigateRequest(question=_rec("K10")["question"], mode="live"),
                         _route(run, {**mx, "window_text": K10_SHORT_WINDOW}, intent="market_event_review",
                                region="VIC1", event_date="2026-07-28"), SEL)
    assert res.requests.maximum.status == "unresolved" and res.status == "needs_clarification"
    assert any("9:20 pm" in u for u in res.requests.maximum.unused)


def test_with_scripted_fields_k09s_saved_wrong_maximum_is_rejected():
    res, _ = _replay("K09", scripted=True)
    assert {"REQUESTED_MAXIMUM_MISMATCH", "REQUESTED_MAXIMUM_MISSING"} & _codes(res)


def test_with_scripted_fields_k10s_answer_carries_the_computed_maximum():
    """K10's saved draft says only that total demand "reached 7711.58 MW" at 18:00: no maximum wording, so no
    lexical check ties it to the maximum (the backstops are bounded). With the request bound, the controller computes
    the maximum over the event window and it is in the answer; this replay ends in the facts-only fallback (for an
    unrelated document-claim failure), which shows it as a validated observation."""
    res, _ = _replay("K10", scripted=True)
    g = GOLD["K10"]["gold_numbers"][0]
    assert any(o.metric == "dispatch_totaldemand" and o.value == g["value"] and o.valid_at_utc == g["valid_at_utc"]
               for o in res.report.observations)
    assert "7711.58" not in res.report.headline


def test_z04_z05_and_k11_bind_as_before():
    """The question parsers still bind Z04's and K11's maxima and Z05's run, with saved routes (I-16, I-17)."""
    z04, _ = _replay("Z04")
    assert z04.resolution.demand_max[0]["value"] == 1367.32
    assert z04.resolution.requests.maximum.provenance["measure"].source == "question"
    z05, _ = _replay("Z05")
    assert z05.resolution.forecast_run and z05.resolution.forecast_run["half_hour_end_utc"] == "2026-07-30T21:30:00Z"
    k11, _ = _replay("K11")
    assert k11.resolution.demand_max[0]["measure"] == "operational demand"


@pytest.mark.parametrize("cid", ["K13", "K14"])
def test_values_at_the_price_peak_and_named_issue_times_are_unchanged(cid):
    """K13 asks for total demand at the price peak (no maximum); K14 names a run by its issue time (read by the
    question parser, as before). Its half-hour ("8:00 am AEST") is not read without the routing model, so since D27
    Amendment 2 the request is sent back for it (it was bound without its half-hour)."""
    res, _ = _replay(cid)
    rq = res.resolution.requests
    assert rq.maximum.status == "absent"
    if cid == "K14":
        assert (rq.forecast_run.status, rq.forecast_run.missing, rq.forecast_run.selection) == (
            "unresolved", ["half_hour"], "issued_at")
        assert rq.forecast_run.provenance["selection"].source == "question"
        assert res.resolution.reasons == [NAMED_RUN_HALF_HOUR_CLARIFICATION] and res.records == []


# ------------------------------------------------------------------------------------------------ 3. adversarial
SEL = load_selection()
K06_Q = _rec("K06")["question"]


def _route(run: dict | None = None, mx: dict | None = None, **core) -> RouteDecision:
    base = {"intent": "forecast_review", "region": "SA1", "event_date": "2026-08-20", "as_of_utc": None,
            "needs_clarification": False, "clarification_reason": None, "clarification": None, "out_of_scope": False}
    base |= core
    base["requested"] = None if run is None and mx is None else {"forecast_run": run or NO_RUN, "maximum": mx or NO_MAX}
    return checked_route(RouteDecision.model_validate(base))


def _k06_run(**kw) -> dict:
    return {**SCRIPTED["K06"][0], **kw}


@pytest.mark.parametrize("change,what", [
    ({"selection_text": "the last run AEMO issued before the half-hour"}, "words not in the question"),
    ({"half_hour_text": "the 7:30 to 8:00 half-hour"}, "words not in the question"),
    ({"selection": "issued_at", "issued_at_utc": "2026-08-19T21:57:01Z"}, "an issue time the question does not state"),
    ({"selection_text": "South Australia"}, "a keyword with no order relation"),
])
def test_an_ungrounded_or_wrong_model_reading_binds_nothing(change, what):
    res = resolve_routed(InvestigateRequest(question=K06_Q, mode="live"), _route(_k06_run(**change)), SEL)
    assert res.status == "needs_clarification", what
    assert res.requests.forecast_run.status in ("unresolved", "conflict"), what


@pytest.mark.parametrize("claimed", ["2026-08-19T23:00:00Z", "2026-08-19T22:00:00Z", None])
def test_a_v12_timestamp_is_not_read_and_the_half_hour_is_codes_reading_of_the_words(claimed):
    """D26: historical model timestamps are not ground truth. Whatever the v12 decision's end (an end the words do not
    give, the start given as the end, none), the half-hour is code's reading of the model's quoted words, which is the
    independently checked gold (K06: the half-hour ending 2026-08-19T22:30Z). Under v12 these were sent back."""
    res = resolve_routed(InvestigateRequest(question=K06_Q, mode="live"),
                         _route(_k06_run(target_half_hour_end_utc=claimed)), SEL)
    fr = res.requests.forecast_run
    assert fr.status == "bound" and [t.isoformat() for t in fr.half_hour] == ["2026-08-19T22:00:00+00:00",
                                                                             "2026-08-19T22:30:00+00:00"]
    assert fr.half_hour[1].isoformat().replace("+00:00", "Z") == GOLD["K06"]["gold_numbers"][0]["valid_at_utc"]


def test_equivalent_times_agree_and_a_disagreement_is_sent_back_naming_both_readings():
    ok = resolve_routed(InvestigateRequest(question=K06_Q, mode="live"),
                        _route(_k06_run(target_half_hour_end_utc="2026-08-19T22:30:00+00:00")), SEL)
    assert ok.status == "ok" and ok.requests.forecast_run.status == "bound"
    hh, missing, conv = half_hour_from_text("7:30-8:00 am half-hour (Adelaide time, ACST) on 20 August 2026", K06_Q,
                                            "SA1")
    assert hh is not None and not missing and "Adelaide time" in conv and "ACST" in conv  # two names, one instant
    hh, missing, _ = half_hour_from_text("7:30-8:00 am half-hour (Adelaide time, AEST) on 20 August 2026", K06_Q, "SA1")
    assert hh is None and missing == ["time_zone"]  # two zones that disagree: not chosen between
    # two readings of the question's own words that disagree (D26: no model timestamp is a reading): the parser's
    # half-hour ending 22:30Z, and the model's quoted "starting 08:00 ACST" one, ending 23:00Z
    q = ("For SA1, what did the last forecast run issued before the half-hour ending 2026-08-19T22:30:00Z (the "
         "half-hour starting 08:00 ACST on 20 August 2026) give for POE50?")
    run = {"selection": "last_issued_before", "selection_text": "the last forecast run issued before the half-hour",
           "half_hour_text": "the half-hour starting 08:00 ACST on 20 August 2026", "target_half_hour_end_utc": None,
           "issued_at_utc": None}
    bad = resolve_routed(InvestigateRequest(question=q, mode="live"), _route(run), SEL)
    assert bad.requests.forecast_run.status == "conflict" and "target half-hour" in bad.reasons[0]
    assert not any(ch.isdigit() for ch in bad.reasons[0])  # the readings are in the trace, not the clarification
    conflict = bad.routing["requests"]["forecast_run"]["conflicts"][0]
    assert "2026-08-19T23:00:00Z" in conflict and "2026-08-19T22:30:00Z" in conflict


def test_parser_and_model_disagreeing_on_the_half_hour_is_a_conflict():
    q = ("For SA1, what did the last forecast run issued before the half-hour ending 2026-08-19T22:30:00Z give for "
         "POE50?")
    run = {"selection": "last_issued_before", "selection_text": "the last forecast run issued before the half-hour",
           "half_hour_text": "the half-hour ending 2026-08-19T22:30:00Z",
           "target_half_hour_end_utc": "2026-08-19T22:30:00Z", "issued_at_utc": None}
    assert resolve_routed(InvestigateRequest(question=q, mode="live"), _route(run), SEL).status == "ok"
    q2 = q.replace("ending 2026-08-19T22:30:00Z", "ending 2026-08-19T22:30:00Z (the half-hour starting 08:00 ACST on "
                                                  "20 August 2026)")
    run2 = {**run, "half_hour_text": "the half-hour starting 08:00 ACST on 20 August 2026",
            "target_half_hour_end_utc": "2026-08-19T23:00:00Z"}
    res = resolve_routed(InvestigateRequest(question=q2, mode="live"), _route(run2), SEL)
    assert res.requests.forecast_run.status == "conflict" and res.status == "needs_clarification"


def test_request_fields_are_authoritative_and_a_conflict_is_shown_with_the_answer():
    q = ("TAS1, half-hour 16:30–17:00 AEST on 31 July 2026: as of 14:00 AEST that day, which was the latest forecast "
         "run issued before it?")
    res = investigate(InvestigateRequest(question=q, as_of_utc="2026-07-31T06:00:00Z"), write_trace=False)
    assert res.resolution.as_of is not None and res.resolution.as_of.isoformat().startswith("2026-07-31T06:00")
    note = res.resolution.requests.notes[0]
    assert "2026-07-31T06:00:00Z, is applied" in note and "2026-07-31T04:00:00Z" in note
    if res.report.status not in ("needs_clarification", "refused"):
        assert note in res.report.uncertainties
    wq = "Over the whole of 20 August 2026, when did Victorian operational demand reach its highest?"
    mx = {"kind": "maximum", "measure": "operational_demand", "measure_text": "operational demand reach its highest",
          "window": "whole_local_day", "window_text": "the whole of 20 August 2026", "window_start_utc": None,
          "window_end_utc": None}
    r2 = resolve_routed(InvestigateRequest(question=wq, mode="live", window_start_utc="2026-08-19T20:00:00Z",
                                           window_end_utc="2026-08-20T04:00:00Z"),
                        _route(None, mx, intent="market_event_review", region="VIC1"), SEL)
    m = r2.requests.maximum
    assert m.status == "bound" and m.window_kind == "explicit" and m.provenance["window"].source == "request"
    assert "the whole local day" in r2.requests.notes[0]


def test_a_cutoff_the_routing_model_read_from_the_question_is_no_request_field_to_note():
    """L3 FC08: the routing model reads 'known at 07:00' as the as-of cutoff; that is the question's own cutoff, not a
    request field the user gave, so nothing is noted."""
    q = "What was known at 07:00 about TAS1 demand forecasts on 2026-08-06?"
    res = resolve_routed(InvestigateRequest(question=q, mode="live"),
                         _route(intent="forecast_review", region="TAS1", event_date="2026-08-06",
                                as_of_utc="2026-08-05T21:00:00Z"), SEL)
    assert res.as_of is not None and not res.requests.notes


@pytest.mark.parametrize("question", [
    "Victoria's high-price event on 20 August 2026: what was its highest dispatch price, and what was VIC1 dispatch "
    "total demand during that same five-minute interval?",
    "What was SA1 total demand at the price peak on 29 July 2026?",
    "What was the peak dispatch price in TAS1 on 6 August 2026, and the operational demand in that half-hour?",
    "Which half-hour was the peak half-hour of the SA1 price event, and what was demand then?",
    "What was the largest forecast error for NSW1 operational demand on 30 July 2026?",
    "When the price peaked in VIC1 on 20 August 2026, what was total demand?",
])
def test_value_at_peak_and_price_wording_is_not_a_maximum_request(question):
    assert not maximum_cue(question)


@pytest.mark.parametrize("question,cue", [
    ("What did the operational demand forecasts issued before the SA1 event say?", None),  # several runs
    ("What was the newest available forecast run for SA1 before 18:00 AEST?", None),  # availability (I-10)
    ("Under AEMO's procedure, how far can a pre-dispatch demand forecast miss before AEMO steps in?", None),
    (K06_Q, "last_issued_before"),
    ("Take the forecast run with issue time 2026-08-19T22:26:58Z for VIC1.", "issued_at"),
])
def test_the_run_cue_and_its_contextual_controls(question, cue):
    assert forecast_run_cue(question) == cue


# ------------------------------------------------------------------------------------------------ backstops (SYNTHETIC)
def _report(summary: list[str], claims: list[tuple[str, float]], reg: EvidenceRegistry, *, as_of=None):
    from nem_agent.report import InvestigationReport, Versions

    return InvestigationReport(
        question="SYNTHETIC", mode="replay", intent="market_event_review", region="TAS1", as_of=as_of,
        event_window=None, headline="SYNTHETIC answer.", summary=summary, status="answered", trace_id="t",
        versions=Versions(code="x", data="x", corpus=None, prompt=config.PROMPT_VERSION, model=None, controller="x"),
        generator="x", numeric_claims=[NumericClaim(claim_id=f"n{i}", text=f"{v} MW", value=v, unit="MW",
                                                    evidence_id=e, rounding=0.005) for i, (e, v) in enumerate(claims)])


def _reg() -> EvidenceRegistry:
    reg = EvidenceRegistry()
    for t, v in (("2026-07-29T07:55:00Z", 1300.0), ("2026-07-29T08:00:00Z", 1400.0)):
        reg.add(evidence_class="observed", metric="dispatch_totaldemand", value=v, unit="MW", region="TAS1",
                valid_at_utc=t, interval_minutes=5, source_row_ids=[f"SYN:{t}"], source_urls=["https://example.invalid"],
                tool_call_id="c1", label="SYNTHETIC")
    return reg


def _backstop_codes(summary: list[str], claims, **kw) -> list[str]:
    reg = _reg()
    rep = _report(summary, claims, reg, **kw)
    return [v.code for v in validate(rep, reg).critical if v.code in ("DEMAND_EXTREME_UNVERIFIED",
                                                                       "RUN_SELECTION_UNVERIFIED")]


def test_an_unverified_demand_extreme_is_rejected_and_a_value_at_a_time_is_not():
    assert _backstop_codes(["TAS1 total demand peaked at 1300.0 MW."], [("ev0001", 1300.0)]) == \
        ["DEMAND_EXTREME_UNVERIFIED"]
    assert _backstop_codes(["TAS1 total demand was lowest at 1300.0 MW."], [("ev0001", 1300.0)]) == \
        ["DEMAND_EXTREME_UNVERIFIED"]
    assert _backstop_codes(["TAS1 total demand was 1300.0 MW at the price peak."], [("ev0001", 1300.0)]) == []
    assert _backstop_codes(["At the 5-minute peak, total demand was 1300.0 MW, and the price was highest then."],
                           [("ev0001", 1300.0)]) == []


def test_an_unbound_final_run_is_rejected_unless_it_is_worded_by_availability():
    assert _backstop_codes(["The final forecast run issued before the half-hour gave 1300.0 MW."],
                           [("ev0001", 1300.0)]) == ["RUN_SELECTION_UNVERIFIED"]
    assert _backstop_codes(["The latest forecast run available before the half-hour gave 1300.0 MW."],
                           [("ev0001", 1300.0)]) == []
    assert _backstop_codes(["The final forecast run issued before the half-hour gave 1300.0 MW."],
                           [("ev0001", 1300.0)], as_of="2026-07-29T08:00:00Z") == []


def _window_controls() -> list[dict]:
    spec = importlib.util.spec_from_file_location(
        "backstop_window_controls", ROOT / "eval" / "structured_requests" / "backstop_window_controls.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.controls()


def test_an_extreme_is_certified_only_for_the_window_it_names_with_every_interval_held():
    """Review before merging PR #56: a subset's maximum or minimum, another window's, or a partial one under an as-of
    cutoff is not certified as the whole day's or the event window's extreme; correctly scoped extremes, and the
    highest value held said as such, pass (SYNTHETIC; eval/structured_requests/backstop_window_controls.py)."""
    rows = _window_controls()
    assert len(rows) == 9 and [r["control"] for r in rows if not r["agrees"]] == []
    assert sum(r["expected"] == "rejected" for r in rows) == 5


def test_clarifications_are_not_checked_by_the_backstops():
    res, _ = _replay("K05")  # its clarification text names "the last forecast run issued before a half-hour"
    assert res.report.status == "needs_clarification" and not _codes(res)


# ------------------------------------------------------------------------------------------------ 4. provenance, prompts
def test_every_bound_field_records_its_source_text_and_conversion_in_the_resolution_and_trace():
    res, _ = _replay("K06", scripted=True, draft_fn=_faithful_run("K06"))
    rq = res.resolution.requests
    assert rq.routed == "reported"
    for name in ("selection", "half_hour"):
        p = rq.forecast_run.provenance[name]
        assert p.source == "route_model" and p.text in res.resolution.request.question
    routed = [e for e in res.trace.as_dict()["events"] if "requests" in json.dumps(e.get("routing") or {})]
    assert routed and "route_model" in json.dumps(routed[0])


def test_a_resolution_built_elsewhere_still_uses_the_question_parsers():
    res = Resolution(InvestigateRequest(question=_rec("Z04")["question"]), "market_event_review", "TAS1", None, None,
                     None)
    from nem_agent.agent.demand_max import requested_measures

    assert res.requests is None and requested_measures(res) == ["total demand"]


def test_prompts_v12_described_the_new_fields_and_v13_keeps_the_other_prompts():
    """v12 (I-18) added the `requested` fields to v11's route prompt; v13 (D26) replaces its timestamps with quoted
    words and changes nothing else: the synthesis and system prompts are byte-identical."""
    pr = ROOT / "src" / "nem_agent" / "prompts"
    v11, v12, v13 = pr / "v11", pr / "v12", pr / "v13"
    # D27: v14 differs from v13 only in one synthesis bullet; D28: v15 adds the forecast request to route.md and
    # corrects that bullet (tests/provider/test_forecast_request.py)
    assert config.PROMPT_VERSION == "prompts/v15"
    for name in ("synthesis.md", "system.md"):
        assert (v11 / name).read_bytes() == (v12 / name).read_bytes() == (v13 / name).read_bytes()
    route = (v12 / "route.md").read_text()
    assert route.startswith((v11 / "route.md").read_text())
    assert "`requested`" in route and "never guess" in " ".join(route.split())
    r13 = " ".join((v13 / "route.md").read_text().split())
    assert "`as_of_text`" in r13 and "`peak_text`" in r13 and "Do not convert dates or times" in r13
    assert "ISO-8601 UTC" not in r13 and "_utc" not in r13
    assert "requested" in RouteDecision.model_json_schema()["properties"]
    assert RoutedRequest.model_json_schema()["required"] == ["forecast_run", "maximum"]


def test_replay_mode_reports_no_structured_reading():
    res = resolve(InvestigateRequest(question=K06_Q), SEL)
    assert res.requests.routed == "not reported" and res.status == "needs_clarification"
