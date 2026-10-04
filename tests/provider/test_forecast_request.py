"""D28 (docs/decisions.md): the forecast request contract, offline. What a forecast review asks for, its operation
(a forecast value, a single-interval comparison or a window comparison) and its exact half-hour or period, is resolved
from the question parser's positive phrasings and the routing model's grounded reading (route contract v14), each
checked; anything unclear, unresolved, conflicting or over the supported limit is sent back before any tool.

- **Paraphrase and negative controls** for each operation and scope kind: analysis, run-issue, target and cutoff
  dates; several dates; narrower periods; negation, quoted background, mentions of actual demand's availability and
  conflicting readings. Grounded words do not by themselves prove a reading: every check still applies.
- **Windows** are used exactly: their interval counts are checked against independent calculations (zoneinfo for real
  days, synthetic 23- and 25-hour DST days), and the aggregates of whole days against an independent recomputation
  from the pinned source rows.
- **Targets:** only the resolved half-hour's values are stated, never the event peak's in their place.

These are design controls on SYNTHETIC questions and saved cases, not evidence of generalisation, and they make no
claim about how the routing model reads v15 prompts."""

from __future__ import annotations

import copy
import json
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from nem_agent.agent import forecast_compare as fc
from nem_agent.agent.dispatcher import Dispatcher
from nem_agent.agent.live import RouteDecision
from nem_agent.agent.request import InvestigateRequest, resolve
from nem_agent.agent.structured import (
    FORECAST_LIMIT_CLARIFICATION,
    FORECAST_OPERATION_CLARIFICATION,
    FORECAST_OPERATION_CONFLICT,
    FORECAST_SCOPE_CLARIFICATION,
    FORECAST_SCOPE_CONFLICT,
    Routed,
    RoutedForecast,
    RoutedForecastRun,
    RoutedMaximum,
    RoutedRequest,
    resolve_cutoff,
)
from nem_agent.evidence import EvidenceRegistry
from nem_agent.report import InvestigationReport, NumericClaim, Versions
from nem_agent.selection import load_selection
from nem_agent.service import investigate
from nem_agent.timeutil import iso_utc, parse_iso
from nem_agent.trace import Trace
from nem_agent.validation import validate
from tests.provider.fake_model import FakeModel

ROOT = Path(__file__).resolve().parents[2]
SEL = load_selection()
TZ = {"SA1": "Australia/Adelaide", "NSW1": "Australia/Sydney", "VIC1": "Australia/Melbourne", "TAS1": "Australia/Hobart",
      "QLD1": "Australia/Brisbane"}


def T(s: str) -> datetime:
    return parse_iso(s)


def _day(d: date, region: str) -> tuple[datetime, datetime]:
    """The local day's UTC bounds, computed independently of the code under test (zoneinfo, midnight to midnight)."""
    z, utc = ZoneInfo(TZ[region]), ZoneInfo("UTC")
    nxt = d + timedelta(days=1)
    return (datetime(d.year, d.month, d.day, tzinfo=z).astimezone(utc),
            datetime(nxt.year, nxt.month, nxt.day, tzinfo=z).astimezone(utc))


def _routed(op: str | None = None, op_text: str | None = None, scope: str | None = None, scope_text: str | None = None,
            run: dict[str, Any] | None = None) -> Routed:
    """A SYNTHETIC v14 routing reading."""
    return Routed(RoutedRequest(
        forecast_run=RoutedForecastRun(**({"selection": "none", "selection_text": None, "half_hour_text": None} | (run or {}))),
        maximum=RoutedMaximum(kind="none", measure=None, measure_text=None, peak_text=None, window=None, window_text=None),
        forecast=RoutedForecast(operation=op or "none", operation_text=op_text, scope=scope, scope_text=scope_text)),
        contract="v14")


def _fa(q: str, routed: Routed | None = None, **req: Any) -> tuple[Any, Any]:
    res = resolve(InvestigateRequest(question=q, intent="forecast_review", **req), SEL, routed)
    return res, res.requests.forecast


# ------------------------------------------------------------------------------------------------ the operation
VALUE = ["What did AEMO's operational demand forecasts say for SA1 on 31 July 2026?",
         "What POE50 values did AEMO's operational demand forecasts give for TAS1 on 6 August 2026?",
         "Give me the POE10, POE50 and POE90 operational demand forecasts for VIC1 on 20 August 2026.",
         "What was known at 06:00 about SA1 demand forecasts on 2026-07-31?",
         "What did AEMO expect operational demand to be in NSW1 on 31 July 2026?"]
WINDOW = ["How accurate were SA1's operational demand forecasts on 31 July 2026?",
          "What was the forecast error for TAS1 operational demand over 6 August 2026?",
          "Did the operational demand forecasts miss actual demand in VIC1 on 20 August 2026?",
          "Compare forecast and actual operational demand for NSW1 on 31 July 2026.",
          "How well did AEMO's forecasts track actual demand in QLD1 on 29 July 2026?"]
SINGLE = ["For SA1's half-hour ending 2026-07-30T17:00:00Z, how close did the forecast land to the actual operational demand?",
          "Was actual operational demand higher or lower than the forecast in NSW1 for the half-hour ending 2026-07-30T21:30:00Z?",
          "Forecast versus actual operational demand for TAS1, half-hour ending 2026-07-30T22:00:00Z?",
          "What was the forecast error for VIC1's half-hour ending 2026-08-19T23:30:00Z?",
          "How did the forecast compare with actual demand for QLD1's half-hour ending 2026-07-29T08:30:00Z?"]


@pytest.mark.parametrize("q", VALUE)
def test_forecast_value_paraphrases(q):
    res, fa = _fa(q)
    assert (fa.status, fa.operation) == ("bound", "forecast_value"), fa.as_dict()
    assert res.status == "ok" and fc.point_request(res) is None and not fc.window_review(res)


@pytest.mark.parametrize("q", WINDOW)
def test_window_comparison_paraphrases_scope_the_whole_local_day(q):
    res, fa = _fa(q)
    assert (fa.status, fa.operation, fa.scope) == ("bound", "window_comparison", "whole_local_day"), fa.as_dict()
    d = fa.window[0].astimezone(ZoneInfo(TZ[res.region])).date()
    assert str(d.day) in q and fa.window == _day(d, res.region) and fa.intervals == 48 and res.window == fa.window
    assert fc.window_review(res) and fc.window_identity(res, "x").window_utc == (iso_utc(fa.window[0]), iso_utc(fa.window[1]))


@pytest.mark.parametrize("q", SINGLE)
def test_single_interval_paraphrases_without_a_named_run_get_no_typed_result(q):
    res, fa = _fa(q)
    assert (fa.status, fa.operation, fa.scope, fa.intervals) == ("bound", "single_interval_comparison", "half_hour", 1)
    assert fc.point_request(res) is None and not fc.window_review(res)  # never an aggregate in its place


@pytest.mark.parametrize("q", VALUE)
def test_asking_for_the_actual_too_makes_a_comparison(q):
    _, fa = _fa(q.rstrip("?.") + ", and how did actual demand turn out?")
    assert fa.operation in ("window_comparison", "single_interval_comparison") or fa.status == "conflict", fa.as_dict()


@pytest.mark.parametrize("q,status,op,clar", [
    # absence of a comparison word is not "forecast value": nothing is read
    ("SA1 operational demand forecasts on 31 July 2026?", "unresolved", None, FORECAST_OPERATION_CLARIFICATION),
    # a declined comparison is not a request; declined and asked for is a conflict
    ("What did the forecasts say for SA1 on 31 July 2026? Do not compare them with actual demand.", "bound",
     "forecast_value", None),
    ("How accurate were SA1's forecasts on 31 July 2026, without comparing them with actual demand?", "conflict", None,
     FORECAST_OPERATION_CONFLICT),
    # quoted background is context, never the request
    ('A notice said "actual demand exceeded the forecast by 200 MW". What did the forecasts say for SA1 on '
     '31 July 2026?', "bound", "forecast_value", None),
    # actual demand mentioned for its availability is not asked for
    ("As of 2026-07-30T12:00:00Z, what was the latest forecast for SA1's half-hour ending 2026-07-30T17:00:00Z, and "
     "had any actual operational demand for it been published by then?", "bound", "forecast_value", None),
])
def test_negation_background_and_context(q, status, op, clar):
    res, fa = _fa(q)
    assert (fa.status, fa.operation) == (status, op), fa.as_dict()
    if clar:
        assert res.status == "needs_clarification" and clar in res.reasons


def test_the_routing_models_reading_is_checked_not_trusted():
    q = "What did the forecast say for SA1 on 31 July 2026, and how did actual demand turn out?"
    # a forecast-value reading against a comparison asked for in the question: a conflict
    _, fa = _fa(q, _routed("forecast_value", "What did the forecast say", "whole_local_day", "on 31 July 2026"))
    assert fa.status == "conflict"
    # a comparison whose quoted words show none: not evidenced, so the question parser's reading stands
    q2 = "What did the forecast say for SA1 on 31 July 2026?"
    _, fa = _fa(q2, _routed("window_comparison", "What did the forecast say", "whole_local_day", "on 31 July 2026"))
    assert (fa.status, fa.operation) == ("bound", "forecast_value") and any("shows no comparison" in n for n in fa.notes)
    # words that are not in the question, or are quoted background, are not a reading
    _, fa = _fa(q2, _routed("window_comparison", "how accurate it was", "whole_local_day", "on 31 July 2026"))
    assert fa.operation == "forecast_value"
    # the model unable to tell: sent back
    res, fa = _fa(q2, _routed("unclear", None, "whole_local_day", "on 31 July 2026"))
    assert fa.status == "unresolved" and FORECAST_OPERATION_CLARIFICATION in res.reasons
    # a single-interval reading for a period: a conflict
    _, fa = _fa("How accurate were SA1's forecasts on 31 July 2026?",
                _routed("single_interval_comparison", "How accurate", "whole_local_day", "on 31 July 2026"))
    assert fa.status == "conflict"


def test_an_unnamed_ordinal_run_is_sent_back_by_the_run_rule_first():
    """'The latest forecast' asks for one run (I-16/I-18): without its half-hour that run request is sent back, before
    the forecast request is read."""
    res, fa = _fa("What did AEMO's latest operational demand forecast say for SA1 on 31 July 2026?")
    assert res.requests.forecast_run.status == "unresolved" and fa.status == "absent" and res.status == \
        "needs_clarification"


def test_a_question_about_no_forecast_has_no_forecast_request():
    """A forecast review that asks about actual demand or a price only: no forecast request, today's handling."""
    _, fa = _fa("Give me New South Wales operational demand for the half-hours ending 9:00 am and 9:30 am AEST on "
                "20 August 2026, plus the NSW dispatch price.")
    assert fa.status == "absent"


# ------------------------------------------------------------------------------------------------ the scope: dates
def test_dates_by_role():
    # an analysis date: the whole local day
    res, fa = _fa("How accurate were SA1's forecasts on 31 July 2026?")
    assert fa.window == _day(date(2026, 7, 31), "SA1") and fa.intervals == 48
    # a run's publication date is not an analysis date
    res, fa = _fa("How did the forecast published on 30 July 2026 perform against actual demand in SA1?")
    assert fa.status == "unresolved" and FORECAST_SCOPE_CLARIFICATION in res.reasons
    # a target's date is the target's
    res, fa = _fa("What was the forecast error for SA1's half-hour ending 17:30 ACST on 31 July 2026?")
    assert (fa.scope, fa.target) == ("half_hour", (T("2026-07-31T07:30:00Z"), T("2026-07-31T08:00:00Z")))
    # a cutoff's date is the cutoff's
    res, fa = _fa("As of 6 pm ACST on 30 July 2026, how accurate had SA1's operational demand forecasts been?")
    assert fa.status == "unresolved" and FORECAST_SCOPE_CLARIFICATION in res.reasons
    # several dates: sent back by the existing check, before the forecast request is read
    res, fa = _fa("How accurate were SA1's forecasts on 30 July 2026 and on 31 July 2026?")
    assert res.status == "needs_clarification" and fa.status == "absent"
    assert any(r.startswith("Several dates are mentioned") for r in res.reasons)
    # a half-hour and a period that does not hold it: a conflict
    res, fa = _fa("For TAS1's half-hour ending 2026-08-07T03:00:00Z, how did the forecast compare with actual demand "
                  "during the price event on 6 August 2026?")
    assert fa.status == "conflict" and FORECAST_SCOPE_CONFLICT in res.reasons
    # a date whose role is not shown: sent back
    res, fa = _fa("SA1 operational demand forecasts versus actual demand, 31 July 2026.")
    assert fa.status == "unresolved" and FORECAST_SCOPE_CLARIFICATION in res.reasons


@pytest.mark.parametrize("q", [
    "How accurate were SA1's forecasts on the evening of 31 July 2026?",
    "How did the operational demand forecasts compare with actual demand in SA1 between 18:00 and 21:00 ACST on "
    "31 July 2026?",
    "How accurate were SA1's forecasts after 6 pm ACST on 31 July 2026?",
    "How accurate were SA1's forecasts in the first 3 hours of 31 July 2026?",
])
def test_a_narrower_period_is_never_the_whole_day(q):
    res, fa = _fa(q)
    assert fa.status == "unresolved" and res.status == "needs_clarification", fa.as_dict()
    res = investigate(InvestigateRequest(question=q, intent="forecast_review"), write_trace=False)
    assert res.records == [] and res.report.results == []  # sent back before any tool


def test_a_stated_window_the_model_reads_is_used_exactly():
    q = ("How did the operational demand forecasts compare with actual demand in SA1 between 18:00 and 21:00 ACST on "
         "31 July 2026?")
    _, fa = _fa(q, _routed("window_comparison", "How did the operational demand forecasts compare with actual demand",
                             "explicit", "between 18:00 and 21:00 ACST on 31 July 2026"))
    assert (fa.status, fa.scope, fa.window, fa.intervals) == ("bound", "explicit", (T("2026-07-31T08:30:00Z"),
                                                                                   T("2026-07-31T11:30:00Z")), 6)


def test_event_scopes():
    # an event window of 24 hours, used exactly
    res, fa = _fa("How accurate were TAS1's operational demand forecasts during the price event on 6 August 2026?")
    assert (fa.status, fa.scope, fa.window, fa.intervals) == ("bound", "event", (T("2026-08-05T15:00:00Z"),
                                                                                T("2026-08-06T15:00:00Z")), 48)
    # an event window of 24.5 hours: over the limit, never clipped
    res, fa = _fa("How accurate were SA1's operational demand forecasts during the price event on 31 July 2026?")
    assert fa.status == "unresolved" and fa.missing == ["window_limit"] and FORECAST_LIMIT_CLARIFICATION in res.reasons
    # an event's peak half-hour (the held event's)
    res, fa = _fa("What did AEMO's forecasts say for SA1's peak half-hour on 31 July 2026?")
    assert (fa.scope, fa.target) == ("event_peak_half_hour", (T("2026-07-30T16:30:00Z"), T("2026-07-30T17:00:00Z")))


# ------------------------------------------------------------------------------------------------ windows
@pytest.mark.parametrize("day,count", [(date(2025, 10, 5), 46), (date(2026, 7, 31), 48)])
def test_whole_days_are_exact_including_a_short_dst_day(day, count):
    _, fa = _fa(f"How accurate were NSW1's operational demand forecasts on {day.day} {day:%B} {day.year}?")
    assert fa.window == _day(day, "NSW1") and fa.intervals == count
    assert (fa.window[1] - fa.window[0]) == timedelta(minutes=30 * count)


def test_a_long_dst_day_is_over_the_limit():
    res, fa = _fa("How accurate were NSW1's operational demand forecasts on 5 April 2026?")
    assert _day(date(2026, 4, 5), "NSW1")[1] - _day(date(2026, 4, 5), "NSW1")[0] == timedelta(hours=25)
    assert fa.missing == ["window_limit"] and FORECAST_LIMIT_CLARIFICATION in res.reasons


@pytest.mark.parametrize("start,end,ok", [("2026-07-31T08:30:00Z", "2026-07-31T11:30:00Z", 6),
                                          ("2026-07-30T14:30:00Z", "2026-07-31T14:30:00Z", 48),
                                          ("2026-07-30T08:30:00Z", "2026-07-31T14:30:00Z", None),  # 30 hours
                                          ("2026-07-31T08:35:00Z", "2026-07-31T11:30:00Z", None)])  # off the grid
def test_request_windows_are_used_exactly_or_sent_back(start, end, ok):
    res, fa = _fa("How accurate were SA1's operational demand forecasts?", window_start_utc=start, window_end_utc=end)
    if ok:
        assert (fa.status, fa.scope, fa.window, fa.intervals) == ("bound", "explicit", (T(start), T(end)), ok)
    else:
        assert (fa.status, fa.missing) == ("unresolved", ["window_limit"]) and FORECAST_LIMIT_CLARIFICATION in res.reasons


FC_DAY = {c["case_id"]: c for c in json.loads((ROOT / "eval/cases.json").read_text())["cases"]
          if (c.get("expected") or {}).get("gold_forecast") and c["expected"]["gold_forecast"]["selector"] ==
          "latest_before_target" and not c.get("request")}


def _independent_day_aggregate(store: Any, region: str, lo: datetime, hi: datetime) -> tuple[int, float, float]:
    """The whole day's MAE, recomputed from the pinned rows without the tool's code: for each half-hour, the latest run
    available before it began (by publication), against the latest available actual revision."""
    errs = []
    t = lo + timedelta(minutes=30)
    while t <= hi:
        f = store.query("SELECT poe50_mw FROM opdemand_forecast WHERE region=? AND target_end_utc=? AND "
                        "available_at_utc<=? ORDER BY published_at_utc DESC LIMIT 1", [region, t, t - timedelta(minutes=30)])
        a = store.query("SELECT operational_demand_mw, revision FROM opdemand_actual WHERE region=? AND interval_end_utc=?",
                        [region, t])
        by = {r["revision"]: r["operational_demand_mw"] for r in a}
        act = by.get("updated", by.get("initial"))
        if f and act is not None:
            errs.append(f[0]["poe50_mw"] - act)
        t += timedelta(minutes=30)
    return len(errs), round(statistics.fmean(abs(e) for e in errs), 2), round(statistics.fmean(errs), 2)


@pytest.mark.parametrize("cid", sorted(FC_DAY))
def test_whole_day_aggregates_match_an_independent_recomputation(cid, real_store):
    """D28: a day comparison is the whole local day (FC gold encodes the former 12-hour slice and stays unchanged:
    the metric change is reported, never forced). The aggregate equals an independent recomputation."""
    c = FC_DAY[cid]
    res = investigate(InvestigateRequest(question=c["question"]), write_trace=False)
    (a,) = res.report.answer
    r = res.report.results[0].result
    lo, hi = T(r.identity.window_utc[0]), T(r.identity.window_utc[1])
    d = lo.astimezone(ZoneInfo(TZ[res.resolution.region])).date()
    assert (lo, hi) == _day(d, res.resolution.region) and r.targets_expected == 48
    n, mae, bias = _independent_day_aggregate(real_store, res.resolution.region, lo, hi)
    assert (len(r.pairs), r.mae_mw, r.mean_error_mw) == (n, mae, bias)
    assert a.kind == "forecast_aggregate" and a.verification == "verified"
    assert res.report.forecast_comparison.n_pairs == n


# ------------------------------------------------------------------------------------------------ one cutoff meaning
def test_one_cutoff_meaning_whatever_its_source():
    q = "how accurate were SA1's operational demand forecasts on 31 July 2026?"
    by_field, fa1 = _fa("How " + q[4:], as_of_utc="2026-07-31T06:00:00Z")
    by_words, fa2 = _fa("As of 2026-07-31T06:00:00Z, " + q)
    mq = "Looking only at what was public at 2026-07-31T06:00:00Z, " + q
    model = _routed("window_comparison", "how accurate were SA1's operational demand forecasts", "whole_local_day",
                    "on 31 July 2026")
    by_model, fa3 = _fa(mq, Routed(model.requested, as_of_text="what was public at 2026-07-31T06:00:00Z", contract="v14"))
    for res, fa in ((by_field, fa1), (by_words, fa2), (by_model, fa3)):
        assert res.as_of == T("2026-07-31T06:00:00Z"), res.requests.cutoff.as_dict()
        assert (fa.status, fa.operation, fa.scope, fa.window) == ("bound", "window_comparison", "whole_local_day",
                                                                 _day(date(2026, 7, 31), "SA1"))
        assert fc.window_identity(res, "x").run_selection == "latest_available_as_of"
    assert {by_field.requests.cutoff.provenance["as_of"].source, by_words.requests.cutoff.provenance["as_of"].source,
            by_model.requests.cutoff.provenance["as_of"].source} == {"request", "question", "route_model"}


def test_a_cutoff_never_changes_a_named_run_rule(real_store):
    """The run issued at a named time stays that run under a cutoff before it is public: an unavailable point, no
    other run in its place (Live, SYNTHETIC route)."""
    q = ("Take the forecast run issued at 2026-07-30T18:56:59Z. How did it compare with actual operational demand for "
         "TAS1's half-hour ending 2026-07-30T22:00:00Z?")
    res, fa = _fa(q, as_of_utc="2026-07-30T20:00:00Z")
    point = fc.point_request(res)
    assert (fa.operation, point.run, point.issued_at, point.half_hour) == (
        "single_interval_comparison", "issued_at", T("2026-07-30T18:56:59Z"), fa.target)
    out = investigate(InvestigateRequest(question=q, as_of_utc="2026-07-30T20:00:00Z"), write_trace=False)
    (rr,) = out.report.results
    assert rr.result.identity.run_selection == "issued_at" and rr.result.status == "unavailable"
    assert [x.reason for x in rr.result.excluded] == ["run_not_public_by_cutoff"]


# ------------------------------------------------------------------------------------------------ selection, targets
def test_forecast_values_and_unnamed_runs_get_no_comparison_result(real_store):
    for q in [VALUE[0], SINGLE[0]]:
        res = investigate(InvestigateRequest(question=q), write_trace=False)
        assert res.report.results == [] and res.report.answer == [] and res.report.forecast_comparison is None
        assert "mean absolute error" not in json.dumps([res.report.headline, *res.report.summary])


def test_the_resolved_target_is_stated_never_the_event_peak(real_store):
    """The reproduction: asked for the half-hour ending 18:30Z, Replay stated the event peak's (17:00Z)."""
    q = ("As of 2026-07-30T14:35:00Z, what did the latest issued forecast say for SA1's half-hour ending "
         "2026-07-30T18:30:00Z on 2026-07-31?")
    res = investigate(InvestigateRequest(question=q), write_trace=False)
    stated = {o.valid_at_utc for o in res.report.observations if o.metric.startswith("opdemand_forecast")}
    assert stated == {"2026-07-30T18:30:00Z"} and res.report.results == []


def _report(d: Dispatcher, claims: list[NumericClaim], summary: list[str]) -> InvestigationReport:
    v = Versions(code="x", data="x", corpus=None, prompt="x", model=None, controller="x")
    return InvestigationReport(
        schema_version="1", question="SYNTHETIC", mode="live", intent="forecast_review", region="SA1", as_of=None,
        event_window=None, headline="SYNTHETIC.", summary=summary, observations=[], search_scope=[],
        numeric_claims=claims, possible_explanations=[], published_findings=[], citations=[], uncertainties=[],
        missing_evidence=[], source_manifest={}, status="answered", trace_id="x", versions=v, generator="live-model:x")


@pytest.fixture(scope="module")
def tools(real_store):
    d = Dispatcher(real_store, SEL, Trace(), EvidenceRegistry(), "forecast_review", None)
    t = {"region": "SA1", "target_start_utc": "2026-07-30T16:00:00Z", "target_end_utc": "2026-07-30T19:00:00Z"}
    d.call("get_forecast_runs", {**t, "as_of_utc": None, "max_runs": 2})
    d.call("compare_forecast_actual", {**t, "run_selector": "latest_before_target"})
    return d


def _ev(d: Dispatcher, metric: str, end: str | None = None) -> Any:
    return next(e for e in d.registry.items.values() if e.metric == metric and (end is None or e.valid_at_utc == end))


@pytest.mark.parametrize("text", ["The forecasts missed by {v} MW on average.", "Its MAE was {v} MW.",
                                  "Across the day the mean absolute error was {v} MW."])
def test_a_forecast_value_request_states_no_comparison(text, tools):
    mae = _ev(tools, "mae_mw")
    claim = NumericClaim(claim_id="c1", text=f"{mae.value} MW", value=mae.value, unit="MW", evidence_id=mae.evidence_id,
                         rounding=0.005)
    rep = _report(tools, [claim], [text.format(v=mae.value)])
    request = {"operation": "forecast_value", "scope": "whole_local_day", "target_utc": None,
               "window_utc": ["2026-07-30T14:30:00Z", "2026-07-31T14:30:00Z"]}
    out = validate(rep, tools.registry, records=tools.records, forecast_request=request)
    assert [v.code for v in out.violations if v.code == "FORECAST_SCOPE_NOT_PRIMARY"] == ["FORECAST_SCOPE_NOT_PRIMARY"]
    f = _ev(tools, "opdemand_forecast_poe50", "2026-07-30T17:00:00Z")  # a forecast value itself is fine
    ok = _report(tools, [NumericClaim(claim_id="c2", text=f"{f.value} MW", value=f.value, unit="MW",
                                      evidence_id=f.evidence_id, rounding=0.5)], [f"The POE50 was {f.value} MW."])
    assert not [v for v in validate(ok, tools.registry, records=tools.records, forecast_request=request).violations
                if v.code == "FORECAST_SCOPE_NOT_PRIMARY"]


def test_a_single_half_hour_states_only_its_own_values(tools):
    request = {"operation": "forecast_value", "scope": "half_hour",
               "target_utc": ["2026-07-30T18:00:00Z", "2026-07-30T18:30:00Z"], "window_utc": None}
    peak = _ev(tools, "opdemand_forecast_poe50", "2026-07-30T17:00:00Z")  # the event peak's value: another half-hour
    own = _ev(tools, "opdemand_forecast_poe50", "2026-07-30T18:30:00Z")
    for ev, bad in ((peak, True), (own, False)):
        rep = _report(tools, [NumericClaim(claim_id="c", text=f"{ev.value} MW", value=ev.value, unit="MW",
                                           evidence_id=ev.evidence_id, rounding=0.5)], [f"The POE50 was {ev.value} MW."])
        v = validate(rep, tools.registry, records=tools.records, forecast_request=request).violations
        assert bool([x for x in v if x.code == "FORECAST_SCOPE_NOT_PRIMARY"]) == bad


# ------------------------------------------------------------------------------------------------ the cutoff's words
def test_the_cutoffs_words_hold_its_own_time():
    for q, words in [("As of 2026-07-30T14:35:00Z, what did the latest issued forecast say?", "As of 2026-07-30T14:35:00Z"),
                     ("What was known at 07:00 about TAS1 demand forecasts on 2026-08-06?", "known at 07:00"),
                     ("As of 18:00 AEST on 29 July 2026, what was the highest demand?", "As of 18:00 AEST on 29 July 2026")]:
        assert [s.text for s in resolve_cutoff(q, None, "QLD1", None, None).spans] == [words]
    a = resolve(InvestigateRequest(question="As of 18:00 AEST on 29 July 2026, what was the highest operational "
                                            "demand recorded in QLD1 over that whole day?"), SEL)
    b = resolve(InvestigateRequest(question="As of 6 pm AEST on 29 July 2026, what was the highest operational "
                                            "demand recorded in QLD1 over that whole day?"), SEL)
    assert (a.status, a.requests.maximum.status, a.requests.maximum.window) == \
        (b.status, b.requests.maximum.status, b.requests.maximum.window)
    assert not any("18:00" in n for n in a.requests.maximum.unused)


def test_every_saved_cutoff_in_the_questions_words_holds_its_time():
    from nem_agent.agent.request import AS_OF_Q_RE
    from nem_agent.agent.structured import _time_expressions

    n = 0
    for f in sorted((ROOT / "eval").glob("**/cases.json")):
        for c in json.loads(f.read_text()).get("cases", []):
            q = c.get("question") or ""
            m = AS_OF_Q_RE.search(q)
            if m is None or not _time_expressions(q[m.end():m.end() + 30]):
                continue
            (sp,) = [s for s in resolve_cutoff(q, None, None, None, None).spans if s.source == "question"]
            a, b = sp.located
            first = next(t for t in _time_expressions(q) if t[0] >= m.end())
            assert a <= first[0] and first[1] <= b, (c.get("case_id"), sp.text)
            n += 1
    assert n >= 14


# ------------------------------------------------------------------------------------------------ Live
def _v14_route(rec_route: dict, forecast: dict) -> dict:
    route = copy.deepcopy(rec_route)
    route["requested"]["forecast"] = forecast
    return route


def test_live_gets_the_forecast_request_not_a_default_window(real_store):
    rec = json.loads((ROOT / "artifacts/live/LC-e2e-v13-run/R02.json").read_text())
    route = copy.deepcopy(rec["route"]) | {"event_date": "2026-07-31"}
    route["requested"]["forecast_run"] = {"selection": "none", "selection_text": None, "half_hour_text": None}
    route = _v14_route(route, {"operation": "forecast_value", "operation_text": "What did AEMO's operational demand "
                               "forecasts say", "scope": "whole_local_day", "scope_text": "on 31 July 2026"})
    assert RouteDecision.model_validate(route).contract == "v14"
    draft = {"status": "answered", "headline": "SYNTHETIC.", "summary": ["SYNTHETIC."], "document_statements": [],
             "observation_evidence_ids": [], "possible_explanations": [], "published_findings": [], "citations": [],
             "uncertainties": [], "missing_evidence": [], "forecast_mae_evidence_id": None, "numeric_claims": []}
    fake = FakeModel(route, [[]], lambda kw: copy.deepcopy(draft))
    res = investigate(InvestigateRequest(question=VALUE[0], mode="live"), live_client=fake, write_trace=False)
    context = next(i["content"] for i in fake.requests[1]["input"] if isinstance(i, dict)
                   and str(i.get("content", "")).startswith("Investigation context"))
    ctx = json.loads(context.split("\n", 1)[1])
    assert "forecast_targets_utc" not in ctx and "forecast_note" not in ctx
    assert ctx["forecast_request"] | {"note": ""} == {
        "operation": "forecast_value", "scope": "whole_local_day", "start_utc": "2026-07-30T14:30:00Z",
        "end_utc": "2026-07-31T14:30:00Z", "start_local": ctx["forecast_request"]["start_local"],
        "end_local": ctx["forecast_request"]["end_local"], "half_hours": 48, "cutoff_utc": None, "note": ""}
    assert res.report.results == [] and res.resolution.requests.forecast.provenance["operation"].source == "route_model"


def test_live_sends_an_unread_window_back_before_any_tool(real_store):
    rec = json.loads((ROOT / "artifacts/live/LC-e2e-v13-run/R02.json").read_text())
    q = ("How did the operational demand forecasts compare with actual demand in SA1 between 18:00 and 21:00 ACST on "
         "31 July 2026?")
    route = copy.deepcopy(rec["route"]) | {"event_date": "2026-07-31"}
    route["requested"]["forecast_run"] = {"selection": "none", "selection_text": None, "half_hour_text": None}
    route = _v14_route(route, {"operation": "window_comparison", "operation_text": "compare with actual demand",
                               "scope": "whole_local_day", "scope_text": "on 31 July 2026"})
    fake = FakeModel(route, [], lambda kw: (_ for _ in ()).throw(AssertionError("no synthesis")))
    res = investigate(InvestigateRequest(question=q, mode="live"), live_client=fake, write_trace=False)
    assert res.resolution.status == "needs_clarification" and res.records == [] and len(fake.requests) == 1


def test_prompts_v15_extend_routing_and_correct_one_synthesis_bullet():
    """Route contract v14 in one routing call: route.md gains the forecast request and its intent line says "said, or
    how they compared"; synthesis.md's forecast bullet follows the forecast request; system.md is byte-identical."""
    import difflib

    from nem_agent import config

    v14, v15 = ROOT / "src/nem_agent/prompts/v14", ROOT / "src/nem_agent/prompts/v15"
    assert config.PROMPT_VERSION == "prompts/v15"
    assert (v14 / "system.md").read_bytes() == (v15 / "system.md").read_bytes()

    def changed(name: str) -> list[str]:
        a, b = (v14 / name).read_text().splitlines(), (v15 / name).read_text().splitlines()
        return [x for x in difflib.unified_diff(a, b, lineterm="", n=0) if x[:1] in "+-" and x[:3] not in ("+++", "---")]
    route = changed("route.md")
    assert [x for x in route if x.startswith("-")] == [
        "-- forecast_review: what AEMO's issued operational-demand forecasts said and how they compared with actual demand."]
    assert all("forecast" in x or "unclear" in x or "copies" in x or "are asked for" in x or "event's window" in x
               for x in route if x.startswith("+"))
    synth = changed("synthesis.md")
    assert sum(x.startswith("-") for x in synth) == 3 and all("forecast" in x or "MAE" in x or "comparison" in x or
                                                              "end_utc" in x for x in synth)
