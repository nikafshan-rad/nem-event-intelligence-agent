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

from nem_agent.agent.request import ISSUED_BEFORE_RE, InvestigateRequest, half_hour_asked, requested_forecast
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


def test_an_ambiguous_request_binds_nothing_and_asks_the_answer_to_name_its_run():
    q = "What POE10, POE50 and POE90 did the final NSW forecast issued before the half-hour from 21:00 to 21:30 carry?"
    res, fake, _ = _replay("Y05", question=q)
    ctx = json.loads(fake.requests[1]["input"][0]["content"].split("\n", 1)[1])["requested_forecast_run"]
    assert "run_id" not in ctx and "say which run you use" in ctx["note"]
    assert not any(r.call_id == "controller_requested_run" for r in res.records)
    assert "requested_forecast_run" not in res.report.validation.get("initial", {}).get("checks_run", [])
    assert res.report.validation["final_passed"]  # nothing bound: the saved answer is judged as before


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
    assert len(codes) == 5  # POE10, POE50, POE90, error and error % for that half-hour (the actual is not a forecast)
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
