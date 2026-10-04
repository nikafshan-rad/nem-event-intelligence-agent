"""D29 (docs/decisions.md): the forecast domain, offline. What a requested forecast is of (operational demand, weather,
price, other or unclear) is part of the structured request: the routing model reads it in the same single routing call
(route contract v15), with the words of the requested clause; code checks provenance (the words are located once, are
not quoted background, are not negated), consistency (the clause's own words do not name another kind; its operation
and scope words lie inside it) and tool eligibility. Replay has no model: its parser establishes the domain only from
the existing vocabularies (the forecast's own subject words, a POE level, a named run) and otherwise sends the
question back.

- **Through Replay and the fake transport (Live):** demand-only paraphrases in several regions, dates and wordings;
  weather-, temperature-, price- and other-only requests; mixed clauses; ambiguous references; negation; quoted
  background; event reviews; and scripted readings that are deliberately wrong.
- **What code cannot detect** (``test_misreadings_the_checks_cannot_detect``): a model reading whose words name no
  domain is accepted as given; a supported request misread as another kind is sent back (never answered with another
  kind's values, but not answered either); an unsupported part the model omits whose words lie outside the parser's
  vocabularies is not named as unanswered.
- **The two fallback tests D28 lacked:** a wrong-target value and an unrequested error value, rejected, are absent from
  the shown fallback, while the original drafts and violations stay in the diagnostics.

These are design controls on SYNTHETIC questions and scripted readings, not evidence of how a hosted model extracts
the domain or of generalisation."""

from __future__ import annotations

import copy
import difflib
import json
import re
from pathlib import Path
from typing import Any

import pytest

from nem_agent import config
from nem_agent.agent.dispatcher import Dispatcher
from nem_agent.agent.live import RouteDecision
from nem_agent.agent.request import InvestigateRequest, resolve
from nem_agent.agent.structured import (
    DEMAND_FORECAST_TOOLS,
    FORECAST_DOMAIN_CLARIFICATION,
    FORECAST_DOMAIN_CONFLICT,
    FORECAST_MIXED_CLARIFICATION,
    FORECAST_UNSUPPORTED_CLARIFICATION,
    Routed,
    RoutedForecast,
    RoutedForecastRun,
    RoutedMaximum,
    RoutedRequest,
    not_answered_note,
)
from nem_agent.evidence import EvidenceRegistry
from nem_agent.selection import load_selection
from nem_agent.service import investigate
from nem_agent.trace import Trace
from tests.provider.fake_model import FakeModel, outputs

pytestmark = pytest.mark.synthetic

ROOT = Path(__file__).resolve().parents[2]
SEL = load_selection()
DEMAND_TOOLS = set(DEMAND_FORECAST_TOOLS)
DRAFT = {"status": "answered", "headline": "SYNTHETIC.", "summary": ["SYNTHETIC."], "document_statements": [],
         "observation_evidence_ids": [], "possible_explanations": [], "published_findings": [], "citations": [],
         "uncertainties": [], "missing_evidence": [], "forecast_mae_evidence_id": None, "numeric_claims": []}


def _fc(domain: str | None, request_text: str | None, op: str = "none", op_text: str | None = None,
        scope: str | None = None, scope_text: str | None = None, unsupported_text: str | None = None) -> dict[str, Any]:
    """A SYNTHETIC v15 forecast reading."""
    return {"operation": op, "operation_text": op_text, "scope": scope, "scope_text": scope_text, "domain": domain,
            "request_text": request_text, "unsupported_text": unsupported_text}


def _route(intent: str, region: str, event_date: str | None, forecast: dict[str, Any] | None,
           run: dict[str, Any] | None = None) -> dict[str, Any]:
    """A SYNTHETIC v15 routing decision."""
    return {"intent": intent, "region": region, "event_date": event_date, "as_of_text": None,
            "needs_clarification": False, "clarification_reason": None, "clarification": None, "out_of_scope": False,
            "requested": {"forecast_run": run or {"selection": "none", "selection_text": None, "half_hour_text": None},
                          "maximum": {"kind": "none", "measure": None, "measure_text": None, "peak_text": None,
                                      "window": None, "window_text": None},
                          "forecast": forecast}}


def _routed(forecast: dict[str, Any]) -> Routed:
    return Routed(RoutedRequest(
        forecast_run=RoutedForecastRun(selection="none", selection_text=None, half_hour_text=None),
        maximum=RoutedMaximum(kind="none", measure=None, measure_text=None, peak_text=None, window=None,
                              window_text=None),
        forecast=RoutedForecast(**forecast)), contract="v15")


def _replay(q: str, **req: Any) -> Any:
    return investigate(InvestigateRequest(question=q, **req), write_trace=False)


def _live(q: str, route: dict[str, Any], turns: list[list[tuple[str, Any]]] | None = None, draft: Any = None,
          repair: Any = None) -> tuple[Any, FakeModel]:
    fake = FakeModel(route, turns or [], draft or (lambda kw: copy.deepcopy(DRAFT)), repair)
    return investigate(InvestigateRequest(question=q, mode="live"), live_client=fake, write_trace=False), fake


def _ran(res: Any) -> set[str]:
    return {r.name for r in res.records if r.status != "blocked"}


def _demand_values(res: Any) -> list[Any]:
    """Every operational-demand forecast value or comparison the answer gives."""
    rep = res.report
    return [o for o in rep.observations if o.metric.startswith(("opdemand_forecast", "forecast_"))] + \
        list(rep.answer) + list(rep.results) + ([rep.forecast_comparison] if rep.forecast_comparison else [])


def _sent_back(res: Any, clarification: str, live: FakeModel | None = None) -> None:
    """Sent back before any tool: no record, no demand value, the clarification given (and one model call in Live)."""
    assert res.resolution.status == "needs_clarification", res.resolution.requests.forecast.as_dict()
    assert clarification in res.resolution.reasons
    assert res.records == [] and _demand_values(res) == []
    if live is not None:
        assert len(live.requests) == 1


def _shown(rep: Any) -> str:
    return json.dumps([rep.headline, *rep.summary, *[a.statement for a in rep.answer],
                       *[h.statement for h in rep.possible_explanations], *rep.uncertainties, *rep.missing_evidence,
                       *[f"{o.metric} {o.value}" for o in rep.observations], *[c.text for c in rep.numeric_claims]])


# ------------------------------------------------------------------------------------------------ demand only
DEMAND = [  # (question, operation): regions, dates and wordings vary
    ("What did AEMO's operational demand forecasts say for QLD1 on 29 July 2026?", "forecast_value"),
    ("How accurate were Tasmania's demand forecasts on 6 August 2026?", "window_comparison"),
    ("Compare the load forecasts with actual load for NSW1 on 31 July 2026.", "window_comparison"),
    ("What did AEMO expect operational demand to be in Victoria on 20 August 2026?", "forecast_value"),
    ("What POE50 values did the forecasts give for SA1 on 31 July 2026?", "forecast_value"),
    ("For SA1's half-hour ending 2026-07-30T17:00:00Z, how close did the demand forecast land to the actual?",
     "single_interval_comparison"),
]


@pytest.mark.parametrize("q,op", DEMAND)
def test_demand_only_paraphrases_resolve_in_replay(q, op):
    res = resolve(InvestigateRequest(question=q, intent="forecast_review"), SEL)
    fa = res.requests.forecast
    assert (fa.status, fa.domain, fa.operation, fa.unsupported) == ("bound", "operational_demand", op, []), fa.as_dict()
    assert res.status == "ok" and not res.requests.ineligible_tools


@pytest.mark.parametrize("q,op", DEMAND)
def test_demand_only_paraphrases_resolve_in_live_from_the_models_grounded_reading(q, op):
    """The model's reading with its own words; a clause that names no domain is accepted as the model reads it."""
    clause = q.rstrip("?.")
    res = resolve(InvestigateRequest(question=q, intent="forecast_review"), SEL,
                  _routed(_fc("operational_demand", clause)))
    fa = res.requests.forecast
    assert (fa.status, fa.domain, fa.operation) == ("bound", "operational_demand", op), fa.as_dict()


@pytest.mark.parametrize("domain", [None, "operational_demand"])
def test_a_named_run_establishes_operational_demand(domain):
    """A forecast run asked for by its rule is one of AEMO's operational-demand runs (I-18): its question need not say
    "demand", whether the model reports the domain (v15) or not (an earlier decision)."""
    q = "What did the forecast run issued at 2026-07-30T18:56:59Z say for TAS1's half-hour ending 2026-07-30T22:00:00Z?"
    fc = RoutedForecast(**_fc(domain, q.rstrip("?") if domain else None, "forecast_value"))
    routed = Routed(RoutedRequest(
        forecast_run=RoutedForecastRun(selection="issued_at", selection_text="the forecast run issued at "
                                       "2026-07-30T18:56:59Z", half_hour_text="half-hour ending 2026-07-30T22:00:00Z"),
        maximum=RoutedMaximum(kind="none", measure=None, measure_text=None, peak_text=None, window=None,
                              window_text=None), forecast=fc), contract="v15" if domain else "v14")
    res = resolve(InvestigateRequest(question=q, intent="forecast_review"), SEL, routed)
    fa = res.requests.forecast
    assert res.requests.forecast_run.status == "bound" and res.status == "ok", res.reasons
    assert (fa.status, fa.domain, fa.operation) == ("bound", "operational_demand", "forecast_value")
    assert fa.provenance["domain"].source == ("route_model" if domain else "question")


# ------------------------------------------------------------------------------------------------ another kind only
OTHER_ONLY = [  # (question, the parser's reading, the model's reading)
    ("What was the weather forecast for Adelaide on 31 July 2026?", "weather", "weather"),
    ("What temperature was forecast for Sydney on 6 August 2026?", "weather", "weather"),
    ("How accurate was the temperature forecast for Melbourne on 20 August 2026?", "weather", "weather"),
    ("What were the price forecasts for SA1 on 31 July 2026?", "price", "price"),
    ("Show me the RRP forecasts for Queensland on 29 July 2026.", "price", "price"),
    ("What was the interconnector flow forecast for VIC1 on 20 August 2026?", None, "other"),
]


@pytest.mark.parametrize("q,parsed,_", OTHER_ONLY)
def test_another_kinds_forecast_never_gets_demand_values_in_replay(q, parsed, _):
    res = _replay(q, intent="forecast_review")
    _sent_back(res, FORECAST_UNSUPPORTED_CLARIFICATION if parsed else FORECAST_DOMAIN_CLARIFICATION)
    assert res.resolution.requests.forecast.domain == parsed


@pytest.mark.parametrize("q,_,read", OTHER_ONLY)
def test_another_kinds_forecast_never_gets_demand_values_in_live(q, _, read):
    region = resolve(InvestigateRequest(question=q, intent="forecast_review"), SEL).region
    clause = q.rstrip("?.")
    res, fake = _live(q, _route("forecast_review", region, None, _fc(read, clause, "forecast_value")),
                      [[("get_forecast_runs", {"region": region})]])
    _sent_back(res, FORECAST_UNSUPPORTED_CLARIFICATION, fake)
    assert res.resolution.requests.forecast.domain == read


def test_the_router_still_sends_weather_forecast_questions_to_a_forecast_review():
    """The scripted router is unchanged (it scores "forecast"): the forecast contract stops the question instead."""
    res = _replay("What was the weather forecast for Adelaide on 31 July 2026?")
    assert res.resolution.intent == "forecast_review" and res.records == []


# ------------------------------------------------------------------------------------------------ mixed clauses
MIXED = [
    ("What were the operational demand and temperature forecasts for NSW1 on 6 August 2026?"),
    ("How accurate was the temperature forecast for TAS1 on 6 August 2026, and how did the demand forecasts do?"),
    ("What did the demand forecasts say for SA1 on 31 July 2026, and what was the price forecast?"),
]


@pytest.mark.parametrize("q", MIXED)
def test_mixed_questions_are_sent_back_in_replay(q):
    """Replay cannot split the clauses: weather or price words never establish the demand request."""
    res = _replay(q, intent="forecast_review")
    _sent_back(res, FORECAST_MIXED_CLARIFICATION)
    assert res.resolution.requests.forecast.unsupported


Q_MIXED = ("For NSW1 on 6 August 2026, what did the operational demand forecasts say, and what was the temperature "
           "forecast for Sydney?")
CLAUSE = "For NSW1 on 6 August 2026, what did the operational demand forecasts say"


def test_a_separable_demand_clause_is_answered_and_the_other_part_named_in_live(real_store):
    fc = _fc("operational_demand", CLAUSE, "forecast_value", "what did the operational demand forecasts say",
             "whole_local_day", "on 6 August 2026", "what was the temperature forecast for Sydney")
    a, b = "2026-08-05T14:00:00Z", "2026-08-06T14:00:00Z"
    turn = [("get_forecast_runs", {"region": "NSW1", "target_start_utc": a, "target_end_utc": b, "as_of_utc": None,
                                   "max_runs": 4})]
    res, fake = _live(Q_MIXED, _route("forecast_review", "NSW1", "2026-08-06", fc), [turn])
    fa = res.resolution.requests.forecast
    assert (res.resolution.status, fa.status, fa.domain, fa.unsupported) == ("ok", "bound", "operational_demand",
                                                                             ["weather"])
    assert (fa.operation, fa.scope, fa.intervals) == ("forecast_value", "whole_local_day", 48)
    note = not_answered_note(["weather"])
    assert res.report.uncertainties[0] == note and "temperature forecast" not in note
    assert not re.search(r"\d", note)  # names the field only: no time, number or quotation
    ctx = json.loads(next(i["content"] for i in fake.requests[1]["input"] if isinstance(i, dict) and
                          str(i.get("content", "")).startswith("Investigation context")).split("\n", 1)[1])
    assert ctx["forecast_request"]["operation"] == "forecast_value"


def test_the_parser_names_an_other_part_the_model_omits():
    """Detected: the model gives the demand clause and omits the other part, which the parser reads outside it."""
    fc = _fc("operational_demand", CLAUSE, "forecast_value", "what did the operational demand forecasts say",
             "whole_local_day", "on 6 August 2026", None)
    res = resolve(InvestigateRequest(question=Q_MIXED, intent="forecast_review"), SEL, _routed(fc))
    assert res.requests.forecast.unsupported == ["weather"] and not_answered_note(["weather"]) in res.requests.notes


@pytest.mark.parametrize("fc,clar", [
    # a clause spanning both requests: its own words name another kind
    (_fc("operational_demand", Q_MIXED.rstrip("?"), "forecast_value", "what did the operational demand forecasts say",
         "whole_local_day", "on 6 August 2026"), FORECAST_DOMAIN_CONFLICT),
    # the scope's words outside the requested clause: not associated with it
    (_fc("operational_demand", "what did the operational demand forecasts say", "forecast_value",
         "what did the operational demand forecasts say", "whole_local_day", "on 6 August 2026",
         "what was the temperature forecast for Sydney"), FORECAST_DOMAIN_CONFLICT),
    # the clause's words are not in the question
    (_fc("operational_demand", "the operational demand forecast for NSW1", "forecast_value"), FORECAST_DOMAIN_CLARIFICATION),
])
def test_a_mixed_question_whose_clause_is_not_separable_is_sent_back_in_live(fc, clar):
    res, fake = _live(Q_MIXED, _route("forecast_review", "NSW1", "2026-08-06", fc))
    _sent_back(res, clar, fake)


# ------------------------------------------------------------------------------------------------ ambiguous references
AMBIGUOUS = ["How accurate were the forecasts for QLD1 on 29 July 2026?",
             "What did the forecast say for Victoria on 20 August 2026?",
             "As of 2026-07-30T14:35:00Z, what did the latest issued forecast say for the SA1 peak half-hour on "
             "2026-07-31?"]


@pytest.mark.parametrize("q", AMBIGUOUS)
def test_an_unnamed_forecast_is_sent_back_in_replay_and_read_by_the_model_in_live(q):
    """Replay: what is forecast is not shown, so the question is sent back. Live: the model's grounded reading decides
    (operational demand: resolved; unclear: sent back). The words establish provenance, not correctness."""
    _sent_back(_replay(q, intent="forecast_review"), FORECAST_DOMAIN_CLARIFICATION)
    clause = q.rstrip("?.")
    res = resolve(InvestigateRequest(question=q, intent="forecast_review"), SEL, _routed(_fc("unclear", clause)))
    assert res.status == "needs_clarification" and FORECAST_DOMAIN_CLARIFICATION in res.reasons
    res = resolve(InvestigateRequest(question=q, intent="forecast_review"), SEL,
                  _routed(_fc("operational_demand", clause)))
    assert (res.requests.forecast.status, res.requests.forecast.domain) == ("bound", "operational_demand")
    assert res.requests.forecast.provenance["domain"].source == "route_model"


# ------------------------------------------------------------------------------------------------ negation, background
@pytest.mark.parametrize("q,parsed", [
    ("Not the weather forecast: what did the operational demand forecasts say for SA1 on 31 July 2026?",
     "operational_demand"),
    ("What did the operational demand forecasts say for SA1 on 31 July 2026, rather than the weather forecast?",
     "operational_demand"),
    ('A report said "the temperature forecast was badly wrong". What did the operational demand forecasts say for SA1 '
     'on 31 July 2026?', "operational_demand"),
    ("I don't want the demand forecasts; what was the weather forecast for Adelaide on 31 July 2026?", "weather"),
    ("What was the temperature forecast for Sydney on 6 August 2026, not the demand forecast?", "weather"),
    ('A report said "the demand forecast was far too low". What was the temperature forecast for Adelaide on '
     '31 July 2026?', "weather"),
])
def test_negated_and_quoted_forecasts_are_not_requests(q, parsed):
    res = _replay(q, intent="forecast_review")
    fa = res.resolution.requests.forecast
    assert fa.domain == parsed and fa.unsupported == ([] if parsed == "operational_demand" else ["weather"])
    if parsed == "operational_demand":
        assert res.resolution.status == "ok" and not any(n.startswith("Not answered") for n in res.report.uncertainties)
    else:
        _sent_back(res, FORECAST_UNSUPPORTED_CLARIFICATION)


@pytest.mark.parametrize("q,clause", [
    ("I don't want the demand forecasts; what was the weather forecast for Adelaide on 31 July 2026?",
     "the demand forecasts"),
    ('A report said "the demand forecast was far too low". What was the temperature forecast for Adelaide on '
     '31 July 2026?', "the demand forecast was far too low"),
])
def test_a_negated_or_quoted_demand_clause_never_authorises_the_demand_workflow_in_live(q, clause):
    res, fake = _live(q, _route("forecast_review", "SA1", "2026-07-31", _fc("operational_demand", clause,
                                                                             "forecast_value")))
    _sent_back(res, FORECAST_DOMAIN_CLARIFICATION, fake)
    assert any(n.startswith("domain: the request's words are") for n in res.resolution.requests.forecast.notes)


# ------------------------------------------------------------------------------------------------ wrong readings
Q_WEATHER = "What was the weather forecast for Adelaide on 31 July 2026?"
Q_DEMAND = "What did the operational demand forecasts say for SA1 on 31 July 2026?"


@pytest.mark.parametrize("q,fc,clar", [
    # weather words read as operational demand: the clause's own words name another kind
    (Q_WEATHER, _fc("operational_demand", "the weather forecast for Adelaide", "forecast_value"),
     FORECAST_DOMAIN_CONFLICT),
    # demand words read as weather
    (Q_DEMAND, _fc("weather", "the operational demand forecasts", "forecast_value"), FORECAST_DOMAIN_CONFLICT),
    # the operation's words outside the requested clause
    (Q_DEMAND, _fc("operational_demand", "the operational demand forecasts", "forecast_value", "What did",
                   "whole_local_day", "on 31 July 2026"), FORECAST_DOMAIN_CONFLICT),
    # no forecast, when the question asks about one
    (Q_DEMAND, _fc("none", None), FORECAST_DOMAIN_CLARIFICATION),
    # words that are not the question's
    (Q_WEATHER, _fc("operational_demand", "the demand forecast for Adelaide", "forecast_value"),
     FORECAST_DOMAIN_CLARIFICATION),
])
def test_wrong_readings_the_checks_detect_are_sent_back_before_any_tool(q, fc, clar):
    res, fake = _live(q, _route("forecast_review", "SA1", "2026-07-31", fc),
                      [[("compare_forecast_actual", {"region": "SA1"})]])
    _sent_back(res, clar, fake)


def test_misreadings_the_checks_cannot_detect():
    """Stated limits, demonstrated: (1) a clause naming no domain, read as operational demand, is accepted (a weather
    question worded without weather words would get demand values); (2) a demand request read as another kind is
    sent back as unsupported (no other kind's values, but not answered); (3) an unsupported part the model omits,
    worded outside the parser's vocabularies, is not named as unanswered."""
    q = "What did the forecast say for Adelaide on 31 July 2026?"
    res = resolve(InvestigateRequest(question=q, intent="forecast_review"), SEL,
                  _routed(_fc("operational_demand", q.rstrip("?"), "forecast_value")))
    assert (res.requests.forecast.status, res.requests.forecast.domain) == ("bound", "operational_demand")
    res = resolve(InvestigateRequest(question=q, intent="forecast_review"), SEL,
                  _routed(_fc("weather", q.rstrip("?"), "forecast_value")))
    assert res.status == "needs_clarification" and FORECAST_UNSUPPORTED_CLARIFICATION in res.reasons
    q = "For NSW1 on 6 August 2026, what did the operational demand forecasts say, and what was the rainfall outlook?"
    res = resolve(InvestigateRequest(question=q, intent="forecast_review"), SEL, _routed(
        _fc("operational_demand", CLAUSE, "forecast_value", "what did the operational demand forecasts say",
            "whole_local_day", "on 6 August 2026", None)))
    assert res.requests.forecast.status == "bound" and res.requests.forecast.unsupported == []
    assert not any(n.startswith("Not answered") for n in res.requests.notes)


# ------------------------------------------------------------------------------------------------ event reviews
Q_EVENT_WEATHER = "What happened to prices in SA1 on 31 July 2026, and what was the weather forecast?"


def test_an_event_review_asking_for_another_forecast_runs_no_demand_forecast_tool_in_replay():
    res = _replay(Q_EVENT_WEATHER)
    assert res.resolution.intent == "market_event_review" and res.resolution.status == "ok"
    assert set(res.resolution.requests.ineligible_tools) == DEMAND_TOOLS and not _ran(res) & DEMAND_TOOLS
    assert res.report.uncertainties[0] == not_answered_note(["weather"]) and _demand_values(res) == []
    assert "get_weather_context" in _ran(res)  # the event review's existing weather context is kept


def test_an_event_review_asking_for_another_forecast_is_not_offered_or_given_demand_forecast_tools_in_live(real_store):
    fc = _fc("weather", "what was the weather forecast", unsupported_text=None)
    a, b = "2026-07-30T14:30:00Z", "2026-07-31T14:30:00Z"
    turn = [("compare_forecast_actual", {"region": "SA1", "target_start_utc": a, "target_end_utc": b,
                                         "run_selector": "latest_before_target"}),
            ("get_price_timeline", {"region": "SA1", "start_utc": a, "end_utc": b})]
    res, fake = _live(Q_EVENT_WEATHER, _route("market_event_review", "SA1", "2026-07-31", fc), [turn])
    offered = {t["name"] for t in fake.requests[1]["tools"]}
    assert not offered & DEMAND_TOOLS and "get_weather_context" in offered
    ctx = next(i["content"] for i in fake.requests[1]["input"] if isinstance(i, dict) and
               str(i.get("content", "")).startswith("Investigation context"))
    assert "forecast_targets_utc" not in ctx and "compare_forecast_actual" not in json.loads(ctx.split("\n", 1)[1])[
        "optional_tools_max_2"]
    (blocked,) = [r for r in res.records if r.name == "compare_forecast_actual"]
    assert blocked.status == "blocked" and "not eligible for this request" in blocked.blocked_reason
    assert not_answered_note(["weather"]) in res.report.uncertainties and _demand_values(res) == []


@pytest.mark.parametrize("q,eligible,note", [
    ("What happened during the SA1 price event on 31 July 2026?", True, None),  # no forecast asked: as before
    ("What happened in SA1 on 31 July 2026, and did the demand forecasts miss the peak?", True, None),
    ("What happened in SA1 on 31 July 2026, and did the forecasts miss the peak?", False, []),
    ("What was the forecast price for SA1 on 31 July 2026?", False, []),
])
def test_event_reviews_use_demand_forecasts_only_for_no_forecast_or_a_demand_one(q, eligible, note):
    res = _replay(q)
    rq = res.resolution.requests
    assert res.resolution.intent == "market_event_review" and bool(rq.ineligible_tools) is not eligible
    if not eligible:
        assert not _ran(res) & DEMAND_TOOLS and not_answered_note(note) in res.report.uncertainties
    else:
        assert not any(n.startswith(("Not answered", "The question also mentions")) for n in res.report.uncertainties)


def test_the_dispatcher_blocks_an_ineligible_tool_whatever_its_origin(real_store):
    d = Dispatcher(real_store, SEL, Trace("x", "x"), EvidenceRegistry(), "forecast_review",
                   ineligible={"get_forecast_runs": "SYNTHETIC reason"})
    rec = d.call("get_forecast_runs", {"region": "SA1", "target_start_utc": "2026-07-30T14:30:00Z",
                                       "target_end_utc": "2026-07-31T14:30:00Z"}, origin="model")
    assert rec.status == "blocked" and rec.blocked_reason.endswith("SYNTHETIC reason") and not rec.source_row_ids


# ------------------------------------------------------------------------------------------------ compatibility
def test_a_decision_without_the_domain_is_not_reported_never_operational_demand():
    """A v14 decision (its forecast has no domain) and a v13 decision (no forecast): what is forecast is not reported,
    and the question parser alone decides; a v15 decision reports it."""
    base = _route("forecast_review", "SA1", "2026-07-31", None)
    v13 = copy.deepcopy(base)
    del v13["requested"]["forecast"]
    v14 = _route("forecast_review", "SA1", "2026-07-31", {k: v for k, v in _fc(None, None, "forecast_value").items()
                                                           if k in ("operation", "operation_text", "scope", "scope_text")})
    v15 = _route("forecast_review", "SA1", "2026-07-31", _fc("operational_demand", "the forecast", "forecast_value"))
    got = {name: RouteDecision.model_validate(r) for name, r in (("v13", v13), ("v14", v14), ("v15", v15))}
    assert {k: (d.contract, d.routed().contract) for k, d in got.items()} == {k: (k, k) for k in got}
    q = "What did the forecast say for SA1 on 31 July 2026?"
    for name in ("v13", "v14"):
        res = resolve(InvestigateRequest(question=q, intent="forecast_review"), SEL, got[name].routed())
        assert res.requests.contract == name and res.requests.forecast.domain is None
        assert FORECAST_DOMAIN_CLARIFICATION in res.reasons
    res = resolve(InvestigateRequest(question=Q_DEMAND, intent="forecast_review"), SEL, got["v14"].routed())
    assert (res.requests.forecast.status, res.requests.forecast.domain) == ("bound", "operational_demand")


def test_a_question_asking_no_forecast_keeps_its_handling():
    """No forecast asked about: no forecast request (D28), and no domain is asked for."""
    q = ("Give me New South Wales operational demand for the half-hours ending 9:00 am and 9:30 am AEST on "
         "20 August 2026, plus the NSW dispatch price.")
    res = resolve(InvestigateRequest(question=q, intent="forecast_review"), SEL)
    assert res.requests.forecast.status == "absent" and res.status == "ok"


def test_prompts_v16_add_only_the_domain_to_routing():
    v15, v16 = ROOT / "src/nem_agent/prompts/v15", ROOT / "src/nem_agent/prompts/v16"
    assert config.PROMPT_VERSION == "prompts/v16"
    for name in ("system.md", "synthesis.md"):
        assert (v15 / name).read_bytes() == (v16 / name).read_bytes()
    diff = [x for x in difflib.unified_diff((v15 / "route.md").read_text().splitlines(),
                                            (v16 / "route.md").read_text().splitlines(), lineterm="", n=0)
            if x[:1] in "+-" and x[:3] not in ("+++", "---")]
    assert not [x for x in diff if x.startswith("-")] and len(diff) == 6
    assert "`forecast.domain`" in diff[0] and any("`unsupported_text`" in x for x in diff)


# ------------------------------------------------------------------------------------------------ the fallback
Q_POINT = ("How did the operational demand forecast compare with actual demand for SA1's half-hour ending "
           "2026-07-30T17:00:00Z?")
Q_VALUE = "What did the operational demand forecast say for SA1's half-hour ending 2026-07-30T17:00:00Z?"
CMP = ("compare_forecast_actual", {"region": "SA1", "target_start_utc": "2026-07-30T15:30:00Z",
                                   "target_end_utc": "2026-07-30T18:30:00Z", "run_selector": "latest_before_target",
                                   "min_lead_hours": None, "run_id": None, "as_of_utc": None,
                                   "actual_revision": "latest_available", "actual_metric": "OPERATIONAL_DEMAND"})


def _fallback_case(q: str, op: str, op_text: str, pick: Any) -> tuple[Any, float, str]:
    """A SYNTHETIC draft stating one value of the model's own wider comparison, and a repair that states it again."""
    fc = _fc("operational_demand", q.rstrip("?"), op, op_text, "half_hour", "half-hour ending 2026-07-30T17:00:00Z")
    seen: dict[str, Any] = {}

    def draft(kw: dict) -> dict:
        cmp = next(v["result"] for v in outputs(kw).values() if "pairs" in v.get("result", {}))
        value, eid = pick(cmp)
        seen.update(value=value, eid=eid)
        text = f"SYNTHETIC: the forecast was off by {value:g} MW."
        return copy.deepcopy(DRAFT) | {"summary": [text], "numeric_claims": [
            {"claim_id": "n1", "text": text, "value": value, "unit": "MW", "evidence_id": eid, "rounding": 0.01}]}
    res, _ = _live(q, _route("forecast_review", "SA1", None, fc), [[CMP]], draft, draft)
    return res, seen["value"], seen["eid"]


@pytest.mark.parametrize("q,op,op_text,pick,why", [
    # a wrong target: the pair of another half-hour (16:30Z, not the 17:00Z asked about)
    (Q_POINT, "single_interval_comparison", "How did the operational demand forecast compare with actual demand",
     lambda r: next((p["error_mw"], p["error_evidence_id"]) for p in r["pairs"]
                    if p["target_end_utc"] == "2026-07-30T16:30:00Z"), "another half-hour"),
    # an unrequested error: the question asks what the forecast said
    (Q_VALUE, "forecast_value", "What did the operational demand forecast say",
     lambda r: (r["mae_mw"]["value"], r["mae_mw"]["evidence_id"]), "not how it compared"),
])
def test_a_rejected_value_is_absent_from_the_shown_fallback_and_kept_in_diagnostics(q, op, op_text, pick, why,
                                                                                    real_store):
    res, value, eid = _fallback_case(q, op, op_text, pick)
    rep, v = res.report, res.report.validation
    assert res.resolution.requests.forecast.status == "bound" and res.resolution.requests.forecast.operation == op
    # rejected: the draft and its repair both state it, so the answer falls back
    assert v["repair_attempted"] and v["fallback_applied"] and "FORECAST_SCOPE_NOT_PRIMARY" in v["pre_repair_codes"]
    initial = [x for x in v["initial"]["violations"] if x["code"] == "FORECAST_SCOPE_NOT_PRIMARY"]
    assert initial and all(eid in x["detail"] and why in x["detail"] for x in initial)
    # absent from what is shown: no sentence, claim or observation gives it
    assert f"{value:g} MW" not in _shown(rep) and all(o.evidence_id != eid for o in rep.observations)
    assert all(c.evidence_id != eid for c in rep.numeric_claims)
    # the original drafts stay in the diagnostics (the local trace)
    drafts = [e for e in res.trace.events if e["name"] in ("synthesis:draft", "repair:draft")]
    assert len(drafts) == 2 and all(f"{value:g} MW" in json.dumps(e) for e in drafts)
