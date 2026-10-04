"""Issue I-9 (docs/issue-tracker.md): the forecast run a question names, for the half-hour it asks about, is the run
compared and shown, and no other run stands in for it.

Held-out v5 Y05 and Y06 (Live, 2026-10-02) asked for the last forecast issued before a named half-hour. Both answers
gave the run available by then (run_selector="latest_before_target": published + 166 minutes before the half-hour),
issued about three hours earlier, as the run asked for. Validation passed: the values were traced to their own rows.

Now the question's run (named by issue time, or the last one issued before the half-hour starts) and half-hour are
parsed. The controller looks the run up by issue time, compares it with the actual before synthesis, and records it.
The validator rejects a forecast value for that half-hour from any other run (FORECAST_RUN_SUBSTITUTED), and the
facts-only fallback leaves such values out. Replays use saved Live records through the SYNTHETIC fake transport (no
network, no key).
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nem_agent.agent.request import (
    HALF_HOUR_CLARIFICATION,
    ISSUED_BEFORE_RE,
    InvestigateRequest,
    half_hour_asked,
    requested_forecast,
)
from nem_agent.service import investigate
from nem_agent.validation import validate
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

LIVE = Path(__file__).resolve().parents[2] / "artifacts" / "live"
V5 = LIVE / "L3-holdout-v5"
EVAL = Path(__file__).resolve().parents[2] / "eval"


def _utc(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


def _question(path: str, cid: str) -> str:
    return next(c["question"] for c in json.loads((EVAL / path).read_text())["cases"] if c["case_id"] == cid)


# ------------------------------------------------------------------------------------------------ request parsing
@pytest.mark.parametrize("path,cid,run,issued,end", [
    ("holdout_v5/cases.json", "Y05", "last_issued_before", None, "2026-07-30T21:30:00Z"),
    ("holdout_v5/cases.json", "Y06", "last_issued_before", None, "2026-07-29T08:00:00Z"),
    # named issue times, with the half-hour in each of its forms
    ("holdout_v4/cases.json", "W07", "issued_at", "2026-07-30T20:56:59Z", "2026-07-30T21:30:00Z"),
    ("holdout_v4/cases.json", "W08", "issued_at", "2026-08-19T11:26:58Z", "2026-08-19T23:30:00Z"),
    ("holdout_v2/cases.json", "H05", "issued_at", "2026-07-30T11:56:59Z", "2026-07-30T21:30:00Z"),
    ("holdout_v3/cases.json", "V07", "issued_at", "2026-07-28T07:57:00Z", "2026-07-29T08:00:00Z"),
    ("holdout_v3/cases.json", "V08", "issued_at", "2026-07-30T09:27:00Z", "2026-07-30T21:30:00Z"),
])
def test_the_run_and_half_hour_a_question_names_are_read(path, cid, run, issued, end):
    fr = requested_forecast(_question(path, cid))
    assert fr is not None and fr.run == run
    assert fr.issued_at == (_utc(issued) if issued else None)
    assert fr.half_hour is not None and fr.half_hour[1] == _utc(end)
    assert (fr.half_hour[1] - fr.half_hour[0]).total_seconds() == 1800


@pytest.mark.parametrize("path,cid", [("holdout_v4/cases.json", "W05"), ("holdout_v4/cases.json", "W06"),
                                      ("holdout_v5/cases.json", "Y07"), ("holdout_v5/cases.json", "Y08")])
def test_as_of_questions_name_no_run(path, cid):
    """As of a cutoff, the run public by then is chosen by availability: nothing is bound."""
    assert requested_forecast(_question(path, cid)) is None


@pytest.mark.parametrize("question", [
    "What did the last forecast issued before the half-hour from 21:00 to 21:30 say for NSW on 2026-07-30?",  # no zone
    "What did the last pre-interval forecast say for NSW for the 21:00 to 21:30 UTC half-hour?",  # no date
    "What did the last pre-interval forecast say for NSW for 21:00 to 22:00 UTC on 2026-07-30?",  # an hour
    "Was the last pre-interval forecast for 21:00 to 21:30 UTC or for 22:00 to 22:30 UTC on 2026-07-30 closer?",  # two
])
def test_a_run_named_relative_to_an_unclear_half_hour_is_ambiguous(question):
    fr = requested_forecast(question)
    assert fr is not None and fr.run == "last_issued_before" and fr.half_hour is None


@pytest.mark.parametrize("question", [
    "How did NSW's operational demand forecasts compare with actuals on 2026-07-30?",
    "What did the forecast issued before the evening peak say for NSW on 2026-07-30?",
])
def test_questions_naming_no_run_are_left_alone(question):
    assert requested_forecast(question) is None


def test_half_hours_in_a_local_zone_and_iso():
    assert half_hour_asked("the half-hour ending 07:30 AEST on 31 July 2026") == (
        _utc("2026-07-30T21:00:00Z"), _utc("2026-07-30T21:30:00Z"))
    assert half_hour_asked("the period that ends at 2026-07-29T08:00:00Z") == (
        _utc("2026-07-29T07:30:00Z"), _utc("2026-07-29T08:00:00Z"))
    assert ISSUED_BEFORE_RE.search("the final forecast issued before the half-hour")
    assert ISSUED_BEFORE_RE.search("the last pre-interval forecast")


# ------------------------------------------------------------------------------------------------ Y05, Y06 replayed
def _replay(cid: str, *, question: str | None = None, draft_fn=None, repair: bool = True):
    rec = json.loads((V5 / f"{cid}.json").read_text())
    trace = json.loads((V5 / "traces" / f"{rec['score']['trace_id']}.json").read_text())["events"]
    draft = rec["drafts"]["synthesis:draft"]
    patch = next((e.get("patch") for e in trace if e["name"] == "repair:scoped"), None) if repair else None
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    fake = FakeModel(rec["route"], [calls], draft_fn or (lambda kw: copy.deepcopy(draft)),
                     (lambda kw: copy.deepcopy(patch)) if patch else None)
    res = investigate(InvestigateRequest(question=question or rec["question"], mode="live"), live_client=fake,
                      write_trace=False)
    return res, fake, draft


def _forecast_values(rep) -> dict[str, tuple[float, str]]:
    """metric -> (value, run file) for the forecast values shown."""
    return {o.metric: (o.value, next((r.split(":")[1] for r in o.source_row_ids if r.startswith("OPDEM_FORECAST")), ""))
            for o in rep.observations if o.metric.startswith(("opdemand_forecast", "forecast_error"))}


@pytest.mark.parametrize("cid,shown_run,asked_run", [
    ("Y05", "202607310430_20260731040140", "PUBLIC_FORECAST_OPERATIONAL_DEMAND_HH_202607310730_20260731070129"),
    ("Y06", "202607291500_20260729143215", "PUBLIC_FORECAST_OPERATIONAL_DEMAND_HH_202607291800_20260729173204"),
])
def test_the_saved_answers_are_rejected_and_their_runs_not_shown(cid, shown_run, asked_run):
    res, _, _ = _replay(cid)
    v = res.report.validation
    pre = (v.get("pre_repair") or v["initial"])["violations"]
    sub = [x["detail"] for x in pre if x["code"] == "FORECAST_RUN_SUBSTITUTED"]
    assert sub and all(asked_run in d for d in sub)  # each names the run asked for
    assert v["fallback_applied"]  # the saved answer (and Y05's saved repair) kept the other run
    assert not any(shown_run in run for _, run in _forecast_values(res.report).values())


def _faithful(cid: str, region: str):
    """A scripted answer citing the controller's comparison of the run asked for."""
    def draft_fn(kw):
        msg = next(i["content"] for i in kw["input"] if isinstance(i, dict) and
                   str(i.get("content", "")).startswith("Requested forecast run, compared by the controller"))
        pair = json.loads(msg.split("\n", 1)[1])["comparison"]
        base = json.loads((V5 / f"{cid}.json").read_text())["drafts"]["synthesis:draft"]
        claims = [("n1", "POE50", pair["poe50_mw"], pair["poe50_evidence_id"]),
                  ("n2", "actual operational demand", pair["actual_mw"], pair["actual_evidence_id"]),
                  ("n3", "POE10", pair["poe10_mw"], pair["poe10_evidence_id"]),
                  ("n4", "POE90", pair["poe90_mw"], pair["poe90_evidence_id"])]
        return {**copy.deepcopy(base), "forecast_mae_evidence_id": None, "uncertainties": [], "missing_evidence": [],
                "possible_explanations": [], "published_findings": [], "citations": [], "document_statements": [],
                "observation_evidence_ids": [c[3] for c in claims],
                "numeric_claims": [{"claim_id": i, "text": f"{name} {v:.1f} MW", "value": v, "unit": "MW",
                                    "evidence_id": e, "rounding": 0.0} for i, name, v, e in claims],
                "headline": f"For the half-hour ending {pair['target_end_utc']}, the last run issued before it gave "
                            f"POE50 {pair['poe50_mw']:.1f} MW; actual {region} operational demand was "
                            f"{pair['actual_mw']:.1f} MW.",
                "summary": [f"POE10 {pair['poe10_mw']:.1f} MW, POE50 {pair['poe50_mw']:.1f} MW and POE90 "
                            f"{pair['poe90_mw']:.1f} MW, against an actual of {pair['actual_mw']:.1f} MW."]}
    return draft_fn


@pytest.mark.parametrize("cid,region,poe50,actual", [("Y05", "NSW1", 11082.0, 11178.0), ("Y06", "SA1", 1816.0, 1872.0)])
def test_an_answer_citing_the_run_asked_for_passes(cid, region, poe50, actual):
    res, _, _ = _replay(cid, draft_fn=_faithful(cid, region), repair=False)
    v = res.report.validation
    assert v["final_passed"] and not v["fallback_applied"], v["initial"]["violations"]
    shown = _forecast_values(res.report)
    assert shown["opdemand_forecast_poe50"][0] == poe50
    assert any(o.metric == "opdemand_actual" and o.value == actual for o in res.report.observations)
    assert any(r.call_id == "controller_requested_run" and r.status == "ok" for r in res.records)


def test_the_controller_names_the_run_by_issue_time_before_the_tool_loop():
    _, fake, _ = _replay("Y05")
    ctx = json.loads(fake.requests[1]["input"][0]["content"].split("\n", 1)[1])["requested_forecast_run"]
    assert ctx["issued_at_utc"] == "2026-07-30T20:56:59Z" and ctx["half_hour_utc"] == ["2026-07-30T21:00:00Z",
                                                                                         "2026-07-30T21:30:00Z"]
    assert "latest_before_target" in ctx["note"]  # the model is told that selector gives another run


def _obs(reg, ids):
    from nem_agent.report import Observation

    return [Observation(metric=ev.metric, value=float(ev.value), unit=ev.unit, valid_at_utc=ev.valid_at_utc,
                        evidence_id=e, source_row_ids=ev.source_row_ids or ["derived"], evidence_class=ev.evidence_class,
                        label=ev.label or ev.metric)
            for e in ids if (ev := reg.get(e)) is not None and ev.valid_at_utc]


# ------------------------------------------------------------------------------------------------ controls
@pytest.mark.parametrize("cid,named_run", [("W07", "PUBLIC_FORECAST_OPERATIONAL_DEMAND_HH_202607310730_20260731070129"),
                                           ("W08", "PUBLIC_FORECAST_OPERATIONAL_DEMAND_HH_202608192200_20260819213203")])
def test_a_named_issue_time_is_bound_and_an_answer_using_that_run_is_not_rejected(cid, named_run):
    """Held-out v4 W07 and W08 name the run by its issue time and gave its values: the run is compared by the
    controller and the answer is checked against it, with no substitution found (first drafts, replayed)."""
    rec = json.loads((LIVE / "L3-holdout-v4" / f"{cid}.json").read_text())
    draft = rec["drafts"]["synthesis:draft"]
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    res = investigate(InvestigateRequest(question=rec["question"], mode="live"), write_trace=False,
                      live_client=FakeModel(rec["route"], [calls], lambda kw: copy.deepcopy(draft)))
    v = res.report.validation
    codes = {x["code"] for x in (v.get("pre_repair") or v["initial"])["violations"]} | \
        {x["code"] for x in v["initial"]["violations"]}
    assert "FORECAST_RUN_SUBSTITUTED" not in codes
    ctl = next(r for r in res.records if r.call_id == "controller_requested_run")
    assert ctl.status == "ok" and ctl.args["run_id"] == named_run
    assert any(e["name"] == "requested_forecast_run" for e in res.trace.as_dict()["events"])


AMBIGUOUS_Q = "What POE10, POE50 and POE90 did the final NSW forecast issued before the half-hour from 21:00 to 21:30 carry?"


def test_an_ambiguous_request_binds_nothing_and_is_sent_back_for_its_half_hour():
    """No zone and no date: no run is chosen and nothing is bound. Since I-16 (held-out v6 Z05) a forecast review is
    sent back for the half-hour, instead of being answered with a note asking the answer to name its run, which the
    answer could ignore."""
    res, fake, _ = _replay("Y05", question=AMBIGUOUS_Q)
    assert res.report.status == "needs_clarification" and HALF_HOUR_CLARIFICATION in res.report.headline
    assert not res.records and len(fake.requests) == 1  # the routing call only
    assert res.resolution is not None and res.resolution.forecast_run is None


def test_outside_a_forecast_review_an_ambiguous_request_is_sent_back_too():
    """Until I-18 a question routed as an event review got the I-9 note (nothing bound, the answer asked to say which
    run it uses, not enforced). Since I-18 a detected request that is not bound is sent back whatever the data intent,
    naming what is missing, so no answer can use another run unchecked."""
    rec = json.loads((V5 / "Y05.json").read_text())
    draft = rec["drafts"]["synthesis:draft"]
    fake = FakeModel({**rec["route"], "intent": "market_event_review"}, [], lambda kw: copy.deepcopy(draft))
    res = investigate(InvestigateRequest(question=AMBIGUOUS_Q, mode="live"), live_client=fake, write_trace=False)
    assert res.report.status == "needs_clarification" and HALF_HOUR_CLARIFICATION in res.report.headline
    assert not res.records and len(fake.requests) == 1  # the routing call only
    assert res.resolution.requests.forecast_run.missing == ["half_hour"]


def test_an_unavailable_run_is_said_and_no_other_run_stands_in():
    """Before the half-hour, no run is held: the context says so, and a forecast value for it is rejected."""
    q = ("In NSW, what POE10, POE50 and POE90 values did AEMO's final operational demand forecast issued before the "
         "half-hour from 21:00 to 21:30 UTC on 2026-07-30 carry?")
    res, _, draft = _replay("Y05", question=q)
    reg = res.registry
    gone = {"half_hour_utc": ["2026-07-30T21:00:00Z", "2026-07-30T21:30:00Z"],
            "half_hour_end_utc": "2026-07-30T21:30:00Z", "run_id": None, "issued_at_utc": None}
    # the saved draft's forecast values, re-validated as if no run the question asks for were held
    raw = res.report.model_copy(update={"observations": _obs(reg, draft["observation_evidence_ids"]),
                                        "numeric_claims": [], "validation": {}})
    codes = [v for v in validate(raw, reg, records=res.records, forecast_run=gone).critical
             if v.code == "FORECAST_RUN_SUBSTITUTED"]
    # POE10, POE50, POE90, error and error % for that half-hour (the actual is not a forecast), and the draft's 12-hour
    # MAE, whose pairs include another run for that half-hour
    assert len(codes) == 6 and sum(v.detail.split(":")[0] in ("ev0694",) for v in codes) == 1
    assert all("no run the question asks for holds this half-hour" in v.detail for v in codes)
    from nem_agent.validation import ValidationResult, facts_only

    shown = facts_only(raw, reg, ValidationResult(violations=codes), None)
    assert not any(o.metric.startswith(("opdemand_forecast", "forecast_error")) for o in shown.observations)
    assert any(o.metric == "opdemand_actual" for o in shown.observations)  # the actual is still shown


def test_other_half_hours_of_a_wider_comparison_are_not_bound():
    res, _, _ = _replay("Y05")
    reg = res.registry
    other = [eid for eid, ev in reg.items.items() if ev.metric == "opdemand_forecast_poe50" and ev.valid_at_utc and
             ev.valid_at_utc != "2026-07-30T21:30:00Z"][:3]
    assert other
    run = {"half_hour_end_utc": "2026-07-30T21:30:00Z", "run_id": "PUBLIC_FORECAST_OPERATIONAL_DEMAND_HH_x",
           "issued_at_utc": "2026-07-30T20:56:59Z"}
    rep = res.report.model_copy(update={"observations": _obs(reg, other), "numeric_claims": [], "validation": {}})
    out = validate(rep, reg, records=res.records, forecast_run=run)
    assert not [v for v in out.critical if v.code == "FORECAST_RUN_SUBSTITUTED"]


# ------------------------------------------------------------------------------------------------ review (before merge)
# Each scenario runs the question through the controller with chosen tool calls, an optional request-level as-of
# cutoff, and an answer built from the evidence IDs the tool outputs give (SYNTHETIC fake transport). At the PR's first
# head (01ab054), 1a/1b exposed a run not public by the cutoff, and 3a/3b passed (artifacts/logs/forecast_run_review.log).
Q05 = ("In NSW, what POE10, POE50 and POE90 values did AEMO's final operational demand forecast issued before the "
       "half-hour from 21:00 to 21:30 UTC on 2026-07-30 carry, and how did they stack up against the measured outturn?")
ROUTE = {"intent": "forecast_review", "region": "NSW1", "event_date": "2026-07-31", "as_of_utc": None,
         "needs_clarification": False, "clarification_reason": None, "clarification": None, "out_of_scope": False}
BOUND = "PUBLIC_FORECAST_OPERATIONAL_DEMAND_HH_202607310730_20260731070129"  # issued 20:56:59Z, public 23:47:29Z
OTHER = "PUBLIC_FORECAST_OPERATIONAL_DEMAND_HH_202607310430_20260731040140"  # issued 17:56:59Z, public 20:47:40Z
HALF = {"region": "NSW1", "target_start_utc": "2026-07-30T21:00:00Z", "target_end_utc": "2026-07-30T21:30:00Z"}
WINDOW = {"region": "NSW1", "target_start_utc": "2026-07-30T15:30:00Z", "target_end_utc": "2026-07-31T03:30:00Z"}
LATER = {"region": "NSW1", "target_start_utc": "2026-07-30T21:30:00Z", "target_end_utc": "2026-07-31T03:30:00Z"}


def _base(day: str = "2026-07-30") -> list:
    return [("get_forecast_runs", {**WINDOW, "max_runs": 8}),
            ("get_actual_demand", {"region": "NSW1", "start_utc": f"{day}T09:30:00Z", "end_utc": f"{day}T23:30:00Z"}),
            ("retrieve_public_evidence", {"query": "operational demand forecast POE", "region": "NSW1"})]


def _compared(kw) -> list[dict]:
    """The comparisons in the model's input: its own tool outputs, and the controller's comparison."""
    out = []
    for i in kw["input"]:
        if isinstance(i, dict) and i.get("type") == "function_call_output":
            v = json.loads(i["output"]).get("result") or {}
            if "pairs" in v:
                out.append(v)
        elif isinstance(i, dict) and str(i.get("content", "")).startswith("Requested forecast run, compared by"):
            c = json.loads(i["content"].split("\n", 1)[1])
            if "poe50_evidence_id" in (c.get("comparison") or {}):
                out.append({"pairs": [c["comparison"]], "mae_mw": None})
    return out


def _pair(outs, run: str, end: str = "2026-07-30T21:30:00Z") -> dict:
    return next(p for o in outs for p in o["pairs"] if p["target_end_utc"] == end and p["run_id"] == run)


def _vals(p: dict, *keys: str) -> list[tuple[str, str, float]]:
    return [(k, p[f"{k}_evidence_id"], p[f"{k}_mw"]) for k in keys]


def _run(calls, pick, *, question=Q05, route=ROUTE, as_of=None):
    """``pick(comparisons)`` gives the (label, evidence ID, value) items an answer shows, and the MAE evidence it names
    as its comparison (or None)."""
    base = json.loads((V5 / "Y05.json").read_text())["drafts"]["synthesis:draft"]

    def draft(kw):
        items, mae = pick(_compared(kw))
        return {**copy.deepcopy(base), "forecast_mae_evidence_id": mae, "uncertainties": [], "missing_evidence": [],
                "possible_explanations": [], "published_findings": [], "citations": [], "document_statements": [],
                "observation_evidence_ids": [e for _, e, _ in items],
                "numeric_claims": [{"claim_id": f"n{k + 1}", "text": f"{lab} {v:.1f}", "value": v, "unit": "MW",
                                    "evidence_id": e, "rounding": 0.0} for k, (lab, e, v) in enumerate(items)],
                "headline": "The forecast for the half-hour asked about, against the actual.",
                "summary": ["Values: " + ", ".join(f"{lab} {v:.1f}" for lab, _, v in items) + "."]}
    fake = FakeModel(route, [calls], draft)
    res = investigate(InvestigateRequest(question=question, mode="live", as_of_utc=as_of), live_client=fake,
                      write_trace=False)
    return res, fake


def _codes(res) -> set[str]:
    v = res.report.validation
    return {x["code"] for x in (v.get("pre_repair") or v["initial"])["violations"]} | \
        {x["code"] for x in v["initial"]["violations"]}


def _requests_text(fake) -> str:
    return json.dumps(fake.requests)


# -- 1. a run named alongside an as-of cutoff given with the request (not in the question's words). The run asked for
#    is chosen by issue time; if it was not public by the cutoff it cannot be supplied, and no earlier run that was
#    public then is put in its place (issue-time and availability-time selection are different requests)
CUTOFF = "2026-07-30T21:10:00Z"  # the run asked for (20:56:59Z) is public at 23:47:29Z; OTHER (17:56:59Z) at 20:47:40Z
LATE = "2026-08-02T00:00:00Z"  # after both, and after the actual


def _context(fake) -> dict:
    return json.loads(fake.requests[1]["input"][0]["content"].split("\n", 1)[1])


def test_a_requested_run_not_public_by_the_cutoff_is_not_replaced_by_an_earlier_one():
    """The last run issued before the half-hour (20:56:59Z) is public only after the 21:10Z cutoff. The answer may not
    present the run that was public by then (17:56:59Z, chosen by availability) as the run asked for, and nothing about
    the later run is named."""
    calls = _base() + [("compare_forecast_actual", {**HALF, "run_selector": "latest_available_as_of",
                                                    "as_of_utc": CUTOFF})]
    res, fake = _run(calls, lambda outs: ([], None), as_of=CUTOFF)
    ctx = _context(fake)["requested_forecast_run"]
    assert ctx["run_id"] is None and ctx["issued_at_utc"] is None and ctx["published_at_utc"] is None
    assert "cannot be supplied as public by the as-of cutoff" in ctx["note"] and "earlier run" in ctx["note"]
    assert BOUND not in _requests_text(fake) and "20:56:59" not in _requests_text(fake)
    assert OTHER not in json.dumps(_context(fake))  # no earlier run is named as the one asked for
    assert not any(r.call_id == "controller_requested_run" for r in res.records)


def test_an_earlier_public_run_given_as_the_run_asked_for_is_rejected():
    """The same request, answered with the run public by the cutoff for the half-hour (17:56:59Z): rejected."""
    calls = _base() + [("get_forecast_runs", {**HALF, "as_of_utc": CUTOFF, "max_runs": 8})]
    res, _ = _run(calls, lambda outs: ([], None), as_of=CUTOFF)
    reg = res.registry
    older = [e for e, ev in reg.items.items() if ev.metric == "opdemand_forecast_poe50" and ev.valid_at_utc ==
             "2026-07-30T21:30:00Z" and any(OTHER in r for r in ev.source_row_ids)]
    assert older  # the earlier run's value for the half-hour, public by the cutoff
    rep = res.report.model_copy(update={"observations": _obs(reg, older), "numeric_claims": [], "validation": {}})
    out = validate(rep, reg, records=res.records, as_of=_utc(CUTOFF), forecast_run={
        "half_hour_end_utc": "2026-07-30T21:30:00Z", "run_id": None, "issued_at_utc": None})
    rejected = {v.detail.split(":")[0] for v in out.critical if v.code == "FORECAST_RUN_SUBSTITUTED"}
    assert rejected == set(older)  # every value of the earlier run for the half-hour


def test_a_requested_run_public_by_the_cutoff_is_bound_and_compared():
    """Control: with a cutoff after the run asked for became public, it is named, compared under the cutoff, and an
    answer giving its values passes."""
    res, fake = _run(_base() + ONE_HALF_HOUR_LATE, lambda outs: (_vals(_pair(outs, BOUND), "poe50", "poe10", "poe90"),
                                                                 None), as_of=LATE)
    ctx = _context(fake)["requested_forecast_run"]
    assert ctx["run_id"] == BOUND and ctx["issued_at_utc"] == "2026-07-30T20:56:59Z"
    ctl = next(r for r in res.records if r.call_id == "controller_requested_run")
    assert ctl.status == "ok" and ctl.args["as_of_utc"] == LATE
    assert not _codes(res) and res.report.validation["final_passed"]


def test_a_named_run_not_public_by_the_cutoff_is_reported_unavailable():
    q = ("For NSW, what POE50 did the run issued 2026-07-30T20:56:59Z give for the half-hour ending 21:30 UTC on 30 "
         "July 2026, and how did it compare with the actual?")
    res, fake = _run(_base(), lambda outs: ([], None), question=q, as_of=CUTOFF)
    ctx = _context(fake)["requested_forecast_run"]
    assert ctx["run_id"] is None and ctx["issued_at_utc"] is None and "cannot be supplied" in ctx["note"]
    assert BOUND not in _requests_text(fake)
    assert not any(r.call_id == "controller_requested_run" for r in res.records)


@pytest.mark.parametrize("question,request_cutoff", [
    ("As of 2026-07-30T21:10:00Z, what POE50 did the latest available NSW forecast give for the half-hour ending 21:30 "
     "UTC on 30 July 2026?", None),
    ("What POE50 did the latest NSW forecast available before the half-hour from 21:00 to 21:30 UTC on 2026-07-30 give?",
     CUTOFF),
])
def test_an_explicit_latest_available_request_still_works(question, request_cutoff):
    """Availability-time selection is not issue-time selection: the latest run available by the cutoff (17:56:59Z) is
    what these ask for, nothing is bound, and the answer giving it passes."""
    assert requested_forecast(question) is None
    route = {**ROUTE, "as_of_utc": CUTOFF if request_cutoff is None else None}
    calls = _base() + [("compare_forecast_actual", {**HALF, "run_selector": "latest_available_as_of",
                                                    "as_of_utc": CUTOFF})]
    res, fake = _run(calls, lambda outs: ([], None), question=question, route=route, as_of=request_cutoff)
    assert "requested_forecast_run" not in _context(fake)
    reg = res.registry
    latest = [e for e, ev in reg.items.items() if ev.metric == "opdemand_forecast_poe50" and ev.valid_at_utc ==
              "2026-07-30T21:30:00Z" and any(OTHER in r for r in ev.source_row_ids)]
    rep = res.report.model_copy(update={"observations": _obs(reg, latest), "numeric_claims": [], "validation": {}})
    out = validate(rep, reg, records=res.records, as_of=_utc(CUTOFF), forecast_run=None)
    assert not [v for v in out.critical if v.code in ("FORECAST_RUN_SUBSTITUTED", "ASOF_LEAK")]


@pytest.mark.parametrize("question", [
    "What did the latest forecast available before the half-hour from 21:00 to 21:30 UTC on 2026-07-30 say for NSW?",
    "What did the last forecast published before the half-hour from 21:00 to 21:30 UTC on 2026-07-30 say for NSW?",
    "What did the last publicly known NSW forecast before the half-hour from 21:00 to 21:30 UTC on 2026-07-30 say?",
])
def test_availability_or_publication_wording_is_not_read_as_issue_time(question):
    assert requested_forecast(question) is None


def test_an_as_of_cutoff_in_the_question_skips_the_binding_but_keeps_the_as_of_protection():
    """'Binds nothing' means only that this binding is skipped. The existing as-of protection still applies: the
    request's cutoff is injected into every tool call, so the model's comparison of the run named (public only after
    the cutoff) finds nothing, and no value of that run reaches the answer's evidence."""
    q = ("As of 2026-07-30T21:10:00Z, what POE50 had the run issued 2026-07-30T20:56:59Z given for the half-hour "
         "ending 21:30 UTC on 30 July 2026?")
    calls = _base() + [("compare_forecast_actual", {**HALF, "run_selector": "run_id", "run_id": BOUND})]
    res, fake = _run(calls, lambda outs: ([], None), question=q, route={**ROUTE, "as_of_utc": CUTOFF})
    assert "requested_forecast_run" not in _context(fake)
    assert not any(r.call_id == "controller_requested_run" for r in res.records)
    model = next(r for r in res.records if r.name == "compare_forecast_actual")
    assert model.args["as_of_utc"] == CUTOFF and any("injected from request cutoff" in n for n in model.policy_notes)
    assert model.status != "ok" or not model.view.get("pairs")
    assert not any(BOUND in r for ev in res.registry.items.values() for r in ev.source_row_ids)


# -- 2. every forecast value for the half-hour comes from the run asked for
ONE_HALF_HOUR = [("compare_forecast_actual", {**HALF, "run_selector": "latest_before_target"})]
ONE_HALF_HOUR_LATE = [("compare_forecast_actual", {**HALF, "run_selector": "run_id", "run_id": BOUND,
                                                   "as_of_utc": "2026-08-02T00:00:00Z"})]


def test_a_mixed_run_answer_is_rejected():
    res, _ = _run(_base() + ONE_HALF_HOUR,
                  lambda outs: (_vals(_pair(outs, BOUND), "poe50") + _vals(_pair(outs, OTHER), "poe10", "poe90"), None))
    assert "FORECAST_RUN_SUBSTITUTED" in _codes(res) and res.report.validation["fallback_applied"]
    # only the bound run's values: its POE50 and (D27) the computed answer's own comparison of it with the actual
    obs = res.report.observations
    assert not any(OTHER in r for o in obs for r in o.source_row_ids)
    assert {o.metric for o in obs} <= {"opdemand_forecast_poe50", "opdemand_actual", "forecast_error_mw",
                                       "forecast_error_pct"}
    assert all(BOUND in r for o in obs if o.metric.startswith("opdemand_forecast") for r in o.source_row_ids)


def test_all_three_values_of_the_run_asked_for_pass():
    res, _ = _run(_base() + ONE_HALF_HOUR, lambda outs: (_vals(_pair(outs, BOUND), "poe50", "poe10", "poe90"), None))
    assert not _codes(res) and res.report.validation["final_passed"]


SAME_VALUE_Q = ("In NSW, what POE50 did AEMO's final operational demand forecast issued before the half-hour from 21:00 "
                "to 21:30 UTC on 2026-07-28 give, and how did it compare with the actual?")
SAME_ROUTE = {**ROUTE, "event_date": "2026-07-29"}
SAME_HALF = {"region": "NSW1", "target_start_utc": "2026-07-28T21:00:00Z", "target_end_utc": "2026-07-28T21:30:00Z"}
SAME_BOUND = "PUBLIC_FORECAST_OPERATIONAL_DEMAND_HH_202607290730_20260729070144"  # issued 20:56:59Z, POE50 10,243
SAME_OTHER = "PUBLIC_FORECAST_OPERATIONAL_DEMAND_HH_202607281300_20260728123224"  # issued 02:27:03Z, POE50 10,243


@pytest.mark.parametrize("cite,codes", [(SAME_OTHER, {"FORECAST_RUN_SUBSTITUTED"}), (SAME_BOUND, set())])
def test_two_runs_with_the_same_value_are_told_apart_by_their_rows(cite, codes):
    """Held in the store: both runs forecast POE50 10,243 MW for this half-hour. Citing the other run's value is a
    substitution even though the number is the same."""
    calls = _base("2026-07-28") + [("compare_forecast_actual", {**SAME_HALF, "run_selector": "run_id",
                                                                "run_id": SAME_OTHER})]
    res, _ = _run(calls, lambda outs: (_vals(_pair(outs, cite, "2026-07-28T21:30:00Z"), "poe50"), None),
                  question=SAME_VALUE_Q, route=SAME_ROUTE)
    assert _codes(res) & {"FORECAST_RUN_SUBSTITUTED"} == codes
    if not codes:
        assert [o.value for o in res.report.observations if o.metric == "opdemand_forecast_poe50"] == [10243.0]


# -- 3. window figures: a mean (absolute) error that includes another run for the half-hour is not this run's error
def test_a_one_half_hour_error_from_another_run_is_rejected():
    res, _ = _run(_base() + ONE_HALF_HOUR, lambda outs: (
        _vals(_pair(outs, BOUND), "poe50") + [("mae", outs[0]["mae_mw"]["evidence_id"], outs[0]["mae_mw"]["value"])],
        None))
    assert "FORECAST_RUN_SUBSTITUTED" in _codes(res)
    assert not any(o.metric == "mae_mw" for o in res.report.observations)  # not shown in the fallback


def test_a_window_comparison_using_another_run_for_the_half_hour_is_not_shown():
    """D27: a point request's answer is the controller's comparison of the run asked for, and ``forecast_comparison`` is
    never built from the MAE the model names. The model's window comparison, which uses another run for the half-hour,
    is therefore not shown at all (before D27 it was shown as the comparison and rejected, FORECAST_RUN_SUBSTITUTED)."""
    calls = _base() + [("compare_forecast_actual", {**WINDOW, "run_selector": "latest_before_target"})]
    res, _ = _run(calls, lambda outs: (_vals(_pair(outs, BOUND), "poe50"), outs[0]["mae_mw"]["evidence_id"]))
    window = next(r for r in res.records if r.name == "compare_forecast_actual" and r.origin == "model")
    assert res.report.forecast_comparison is None
    assert not any(o.evidence_id == window.view["mae_mw"]["evidence_id"] for o in res.report.observations)
    assert res.report.answer and res.report.answer[0].kind == "forecast_point"


@pytest.mark.parametrize("calls_extra,what", [
    ([("compare_forecast_actual", {**HALF, "run_selector": "run_id", "run_id": BOUND})], "the run asked for"),
    ([("compare_forecast_actual", {**LATER, "run_selector": "latest_before_target"})], "a window without the half-hour"),
])
def test_window_figures_of_the_run_asked_for_or_of_other_half_hours_pass(calls_extra, what):
    res, _ = _run(_base() + calls_extra, lambda outs: (_vals(_pair(outs, BOUND), "poe50"),
                                                       outs[0]["mae_mw"]["evidence_id"]))
    assert not _codes(res), what
    # D27: the answer is the controller's comparison of the half-hour asked about; the window figures the model names
    # are not shown as the comparison (before D27 they were, as forecast_comparison)
    assert res.report.forecast_comparison is None and res.report.validation["final_passed"]
    assert res.report.answer and res.report.answer[0].kind == "forecast_point"


def test_y05s_fallback_no_longer_shows_the_window_error_of_the_other_run():
    res, _, _ = _replay("Y05")
    obs, prim = res.report.observations, res.resolution.forecast_primary
    # no window error: only the actual and (D27) the computed answer's own comparison of the run asked for
    assert not any(o.metric in ("mae_mw", "mean_error_mw") for o in obs)
    assert all(o.metric == "opdemand_actual" or o.evidence_id in prim["evidence_ids"] for o in obs)


# -- 4. the comparison tool's call budget used up by the model
THREE = [("compare_forecast_actual", {**WINDOW, "run_selector": "latest_before_target"}),
         ("compare_forecast_actual", {**HALF, "run_selector": "latest_before_target"})]


@pytest.mark.parametrize("last,cite,rejected", [
    (("compare_forecast_actual", {**HALF, "run_selector": "min_lead_hours", "min_lead_hours": 1}), OTHER, True),
    (("compare_forecast_actual", {**HALF, "run_selector": "run_id", "run_id": BOUND}), BOUND, False),
])
def test_an_exhausted_tool_budget_keeps_its_limit_and_the_binding(last, cite, rejected):
    res, _ = _run(_base() + THREE + [last], lambda outs: (_vals(_pair(outs, cite), "poe50"), None))
    ctl = next(r for r in res.records if r.call_id == "controller_requested_run")
    assert ctl.status == "blocked" and "already called 3 times" in ctl.blocked_reason  # the limit holds
    assert sum(r.name == "compare_forecast_actual" and r.status != "blocked" for r in res.records) == 3
    assert ("FORECAST_RUN_SUBSTITUTED" in _codes(res)) is rejected
