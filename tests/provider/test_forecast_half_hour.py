"""Issue I-16 (docs/issue-tracker.md): a forecast run named relative to a half-hour is bound only to a half-hour the
question pins down, and is never silently replaced.

Held-out v6 Z05 (Live, 2026-10-02) asked for "the half-hour finishing at 07:30 on 31 July in market time (UTC
2026-07-30T21:30:00Z)" and "the last forecast run issued ahead of that half-hour". The run wording was recognised (I-9)
but the half-hour was not, so no run was bound: the answer gave the run issued 18:27:01Z (the latest available by the
half-hour's end) as that run. The run asked for, issued 20:56:59Z, gave POE50 11,082 MW against 11,178 MW.

Now the half-hour is read from the question's own words (its ending clock with its own date and zone, and an ISO
instant that restates it), without completing a missing year or zone. A run named relative to a half-hour that is still
not pinned down is sent back for it. Two runs that fit the rule equally are not chosen between. Replays use saved Live
records through the SYNTHETIC fake transport (no network, no key).
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from nem_agent.agent.live import TIED_RUNS, LiveController
from nem_agent.agent.request import (
    HALF_HOUR_CLARIFICATION,
    ForecastRequest,
    InvestigateRequest,
    Resolution,
    half_hour_asked,
    requested_forecast,
    resolve,
)
from nem_agent.evidence import EvidenceRegistry
from nem_agent.service import _shared, investigate
from nem_agent.validation import validate
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

ROOT = Path(__file__).resolve().parents[2]
V6 = ROOT / "artifacts" / "live" / "L3-holdout-v6"
BOUND = "PUBLIC_FORECAST_OPERATIONAL_DEMAND_HH_202607310730_20260731070129"  # issued 20:56:59Z
SHOWN = "202607310500_20260731043126"  # the run Z05 gave: issued 18:27:01Z, available 21:17:26Z
HALF = ("2026-07-30T21:00:00Z", "2026-07-30T21:30:00Z")


def _utc(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


def _z05_question() -> str:
    cases = json.loads((ROOT / "eval" / "holdout_v6" / "cases.json").read_text())["cases"]
    return next(c["question"] for c in cases if c["case_id"] == "Z05")


# ------------------------------------------------------------------------------------------------ reading the half-hour
def test_z05s_half_hour_and_run_are_read():
    fr = requested_forecast(_z05_question())
    assert fr is not None and fr.run == "last_issued_before"
    assert fr.half_hour == (_utc(HALF[0]), _utc(HALF[1]))


@pytest.mark.parametrize("phrase,end", [
    ("finishing at 07:30 on 31 July 2026 in market time", "2026-07-30T21:30:00Z"),  # its own full date
    ("finishing at 07:30 market time on 31 July 2026", "2026-07-30T21:30:00Z"),  # zone, then date
    ("that finished at 07:30 AEST on 2026-07-31", "2026-07-30T21:30:00Z"),
    ("finishing at 07:30 on July 31 in NEM time (i.e. 2026-07-30T21:30:00Z)", "2026-07-30T21:30:00Z"),
    ("finishing at 21:30 UTC on 30 July (= 2026-07-30T21:30:00Z)", "2026-07-30T21:30:00Z"),
    ("finishing at 07:30 (2026-07-30T21:30:00Z)", "2026-07-30T21:30:00Z"),  # no zone: the equivalent matches 07:30 AEST
    ("finishing at 2026-07-30T21:30:00Z", "2026-07-30T21:30:00Z"),
    ("finishing at 17:30 ACST on 29 July 2026", "2026-07-29T08:00:00Z"),
])
def test_an_ending_clock_with_its_own_date_and_zone_or_an_equivalent_is_read(phrase, end):
    assert half_hour_asked(f"NSW1, the half-hour {phrase}: what did the last forecast issued before it say?") == (
        _utc(end) - (_utc(HALF[1]) - _utc(HALF[0])), _utc(end))


@pytest.mark.parametrize("phrase", [
    "finishing at 08:00 on 31 July in market time (UTC 2026-07-30T21:30:00Z)",  # the equivalent is another clock
    "finishing at 07:30 on 30 July in market time (UTC 2026-07-30T21:30:00Z)",  # ... another date
    "finishing at 07:30 on 31 July UTC (2026-07-30T21:30:00Z)",  # ... another instant in the zone stated
    "finishing at 07:30 on 31 July 2026 in market time (2026-07-30T22:00:00Z)",  # two half-hours
    "finishing at 07:30 on 31 July in market time",  # a date without its year, and no equivalent: not completed
    "finishing at 07:30 on 31 July 2026",  # no zone, and no equivalent: not guessed
    "finishing at 07:30 on 31 July in market time (published 2026-07-30T21:01:29Z)",  # a publication time is not it
    "finishing at 07:30 or 08:00 AEST on 31 July 2026, or the one finishing at 08:30 AEST on 31 July 2026",  # several
    "finishing at 07:30 AEST or 08:00 AEST on 31 July 2026",  # alternatives after one ending word
    "finishing at 07:30 on 31 July 2026, or the one finishing at 08:00 AEST on 31 July 2026",  # one has no zone
    "ending 07:30 AEST or 08:00 AEST on 31 July 2026",  # on main, the first alternative was taken
    "ending 07:30 on 31 July 2026, or the one ending 08:00 AEST on 31 July 2026",  # on main, the zoned one was taken
    "finishing at 07:30 AEST on 31 July 2026 UTC",  # two zones for one clock
    "finishing at 07:45 AEST on 31 July 2026",  # not a half-hour boundary
])
def test_a_half_hour_not_pinned_down_is_not_read(phrase):
    assert half_hour_asked(f"NSW1, the half-hour {phrase}: what did the last forecast issued before it say?") is None


def test_issue_and_publication_times_are_not_the_half_hour():
    """A bracketed time labelled as an issue or publication time is that time, not the half-hour's restatement."""
    for label in ("published", "issued", "available"):
        q = (f"NSW1, the half-hour finishing at 07:30 on 31 July 2026 in market time ({label} 2026-07-30T18:31:26Z): "
             "what did that run forecast?")
        assert half_hour_asked(q) == (_utc(HALF[0]), _utc(HALF[1]))


# ------------------------------------------------------------------------------------------------ Z05 replayed
def _replay(*, question: str | None = None, draft_fn=None, repair: bool = True, as_of: str | None = None):
    rec = json.loads((V6 / "Z05.json").read_text())
    trace = json.loads((V6 / "traces" / f"{rec['score']['trace_id']}.json").read_text())["events"]
    draft = rec["drafts"]["synthesis:draft"]
    patch = next((e.get("patch") for e in trace if e["name"] == "repair:scoped"), None) if repair else None
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    fake = FakeModel(rec["route"], [calls], draft_fn or (lambda kw: copy.deepcopy(draft)),
                     (lambda kw: copy.deepcopy(patch)) if patch else None)
    res = investigate(InvestigateRequest(question=question or rec["question"], mode="live", as_of_utc=as_of),
                      live_client=fake, write_trace=False)
    return res, fake


def _forecasts_shown(rep) -> list[tuple[str, float, str]]:
    return [(o.metric, o.value, next((r for r in o.source_row_ids if r.startswith("OPDEM_FORECAST")), ""))
            for o in rep.observations if o.metric.startswith(("opdemand_forecast", "forecast_error"))]


def test_z05s_saved_answer_is_rejected_and_the_other_run_not_shown():
    res, fake = _replay()
    v = res.report.validation
    sub = [x["detail"] for x in (v.get("pre_repair") or v["initial"])["violations"]
           if x["code"] == "FORECAST_RUN_SUBSTITUTED"]
    assert sub and all(BOUND in d for d in sub)  # each names the run asked for
    assert v["fallback_applied"]  # the saved repair kept the other run
    assert not any(SHOWN in row for _, _, row in _forecasts_shown(res.report))
    assert any(o.metric == "opdemand_actual" for o in res.report.observations)  # the actual is still shown
    ctx = json.loads(fake.requests[1]["input"][0]["content"].split("\n", 1)[1])["requested_forecast_run"]
    assert ctx["run_id"] == BOUND and ctx["issued_at_utc"] == "2026-07-30T20:56:59Z"
    assert ctx["half_hour_utc"] == list(HALF)


def _faithful(kw):
    """A scripted answer citing the controller's comparison of the run asked for."""
    msg = next(i["content"] for i in kw["input"] if isinstance(i, dict) and
               str(i.get("content", "")).startswith("Requested forecast run, compared by the controller"))
    pair = json.loads(msg.split("\n", 1)[1])["comparison"]
    base = json.loads((V6 / "Z05.json").read_text())["drafts"]["synthesis:draft"]
    claims = [("n1", "POE50", pair["poe50_mw"], pair["poe50_evidence_id"]),
              ("n2", "actual operational demand", pair["actual_mw"], pair["actual_evidence_id"])]
    return {**copy.deepcopy(base), "forecast_mae_evidence_id": None, "uncertainties": [], "missing_evidence": [],
            "possible_explanations": [], "published_findings": [], "citations": [], "document_statements": [],
            "observation_evidence_ids": [c[3] for c in claims],
            "numeric_claims": [{"claim_id": i, "text": f"{name} {v:.1f} MW", "value": v, "unit": "MW",
                                "evidence_id": e, "rounding": 0.0} for i, name, v, e in claims],
            "headline": f"For the half-hour ending {pair['target_end_utc']}, the last run issued before it gave POE50 "
                        f"{pair['poe50_mw']:.1f} MW; actual NSW1 operational demand was {pair['actual_mw']:.1f} MW.",
            "summary": [f"POE50 {pair['poe50_mw']:.1f} MW against an actual of {pair['actual_mw']:.1f} MW."]}


def test_an_answer_citing_the_run_asked_for_passes_with_its_run_and_half_hour_traceable():
    res, _ = _replay(draft_fn=_faithful, repair=False)
    v = res.report.validation
    assert v["final_passed"] and not v["fallback_applied"], v["initial"]["violations"]
    shown = {m: (val, row) for m, val, row in _forecasts_shown(res.report)}
    assert shown["opdemand_forecast_poe50"][0] == 11082.0 and BOUND in shown["opdemand_forecast_poe50"][1]
    assert any(o.metric == "opdemand_actual" and o.value == 11178.0 for o in res.report.observations)
    poe50 = next(o for o in res.report.observations if o.metric == "opdemand_forecast_poe50")
    ev = res.registry.get(poe50.evidence_id)
    assert ev is not None and ev.valid_at_utc == HALF[1] and ev.interval_minutes == 30
    ctl = next(r for r in res.records if r.call_id == "controller_requested_run")
    assert ctl.status == "ok" and ctl.args["run_id"] == BOUND and ctl.args["target_end_utc"] == HALF[1]


# ------------------------------------------------------------------------------------------------ not pinned down
UNPINNED = ("NSW1, the half-hour finishing at 07:30 on 31 July in market time: set the POE50 operational demand from "
            "the last forecast run issued ahead of that half-hour against the actual. How far apart were they?")


def test_a_run_named_relative_to_an_unread_half_hour_is_sent_back_in_live_mode():
    res, fake = _replay(question=UNPINNED)
    rep = res.report
    assert rep.status == "needs_clarification" and HALF_HOUR_CLARIFICATION in rep.headline
    assert not res.records and len(fake.requests) == 1  # the routing call only: no tool, no run chosen
    assert res.resolution is not None and res.resolution.forecast_run is None


def test_a_run_named_relative_to_an_unread_half_hour_is_sent_back_in_replay_mode():
    rep = investigate(InvestigateRequest(question=UNPINNED, mode="replay"), write_trace=False).report
    assert rep.status == "needs_clarification" and HALF_HOUR_CLARIFICATION in rep.headline


@pytest.mark.parametrize("question", [
    # no run named relative to the half-hour: nothing to choose, nothing sent back for it
    "How did NSW1's operational demand forecasts for the half-hour finishing at 07:30 on 31 July 2026 compare?",
    # a run named by its issue time is one run, half-hour or not
    "What did the NSW1 forecast issued at 2026-07-30T20:56:59Z say for the half-hour finishing at 07:30 on 31 July?",
    # as of a cutoff, the run public by then is chosen by availability (I-10)
    "As of 2026-07-30T21:10:00Z, what was the newest NSW1 forecast for the half-hour finishing at 07:30 on 31 July?",
])
def test_other_forecast_questions_are_not_sent_back_for_the_half_hour(question):
    _, sel = _shared()
    req = InvestigateRequest(question=question, region="NSW1", event_date="2026-07-31", intent="forecast_review")
    assert HALF_HOUR_CLARIFICATION not in resolve(req, sel).reasons


# ------------------------------------------------------------------------------------------------ as of a cutoff
def test_a_cutoff_with_the_request_keeps_the_run_chosen_by_issue_time_and_says_it_cannot_be_supplied():
    """The run asked for (issued 20:56:59Z) is public at 23:47:29Z, after the 21:10Z cutoff: it cannot be supplied,
    nothing about it is named, and no run public by then is put in its place."""
    res, fake = _replay(as_of="2026-07-30T21:10:00Z")
    run = res.resolution.forecast_run if res.resolution else None
    assert run is not None and run["run_id"] is None and run["half_hour_end_utc"] == HALF[1]
    ctx = json.loads(fake.requests[1]["input"][0]["content"].split("\n", 1)[1])["requested_forecast_run"]
    assert ctx["note"].startswith("The run the question asks for cannot be supplied as public by the as-of cutoff")
    assert BOUND not in json.dumps(ctx)
    assert not any(o.valid_at_utc == HALF[1] for o in res.report.observations
                   if o.metric.startswith(("opdemand_forecast", "forecast_error")))


# ------------------------------------------------------------------------------------------------ not one run
class _Store:
    """SYNTHETIC store: the run lookup returns the rows given."""

    def __init__(self, rows):
        self.rows = rows

    def query(self, sql, params):
        return self.rows if "GROUP BY run_id" in sql else [{"1": 1}]


def _controller(rows) -> LiveController:
    return LiveController(SimpleNamespace(store=_Store(rows)), EvidenceRegistry(), SimpleNamespace(), client=object())


def _row(run: str, issued: str) -> dict:
    t = _utc(issued)
    return {"run_id": run, "issued_at_utc": t, "published_at_utc": t, "available_at_utc": t}


@pytest.mark.parametrize("wanted,rows", [
    (ForecastRequest("last_issued_before", None, (_utc(HALF[0]), _utc(HALF[1]))),
     [_row("RUN_A", "2026-07-30T20:56:59Z"), _row("RUN_B", "2026-07-30T20:56:59Z")]),  # the same latest issue time
    (ForecastRequest("issued_at", _utc("2026-07-30T20:57:00Z"), (_utc(HALF[0]), _utc(HALF[1]))),
     [_row("RUN_A", "2026-07-30T20:55:00Z"), _row("RUN_B", "2026-07-30T20:59:00Z")]),  # equally near the time named
])
def test_two_runs_that_fit_the_rule_equally_are_not_chosen_between(wanted, rows):
    res = Resolution(InvestigateRequest(question="SYNTHETIC"), "forecast_review", "NSW1", None, None, None)
    out = _controller(rows)._requested_run(res, wanted)
    assert out["run_id"] is None and "RUN_A" not in json.dumps(out) and "RUN_B" not in json.dumps(out)
    assert out["note"].startswith(TIED_RUNS)
    assert res.forecast_run is not None and res.forecast_run["unavailable"] == TIED_RUNS
    # any forecast value for the half-hour is then rejected, saying why
    reg = EvidenceRegistry()
    ev = reg.add(evidence_class="aemo_forecast", metric="opdemand_forecast_poe50", value=11082.0, unit="MW",
                 region="NSW1", valid_at_utc=HALF[1], interval_minutes=30,
                 source_row_ids=["OPDEM_FORECAST:RUN_A:NSW1:2026-07-30T21:30:00Z"], source_urls=[], tool_call_id="t")
    from nem_agent.report import Observation

    report = investigate(InvestigateRequest(question=UNPINNED, mode="replay"), write_trace=False).report
    report = report.model_copy(update={"observations": [Observation(
        metric=ev.metric, value=11082.0, unit="MW", valid_at_utc=HALF[1], evidence_id=ev.evidence_id,
        source_row_ids=ev.source_row_ids, evidence_class=ev.evidence_class, label="POE50")]})
    sub = [v for v in validate(report, reg, forecast_run=res.forecast_run).critical
           if v.code == "FORECAST_RUN_SUBSTITUTED"]
    assert sub and "cannot be told which one is meant" in sub[0].detail
