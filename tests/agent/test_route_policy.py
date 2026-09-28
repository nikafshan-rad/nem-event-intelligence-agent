"""L3 live routing failures and their neighbours: how a model's routing decision is applied (no network).

DOC03: a definition question was sent back for a region and date because the model's clarification request overrode
the resolver, which needs neither for a definition. AMB06: an as-of question about forecasts that also named an event
was routed as an event review. Questions here are paraphrases, not evaluation cases.
"""

from __future__ import annotations

from typing import Any

from nem_agent.agent.live import RouteDecision
from nem_agent.agent.request import InvestigateRequest, resolve, route
from nem_agent.service import route_policy


def decision(**kw: Any) -> RouteDecision:
    base = {"intent": "market_event_review", "region": "SA1", "event_date": "2026-07-31", "as_of_utc": None,
            "needs_clarification": False, "clarification_reason": None, "clarification": None, "out_of_scope": False}
    return RouteDecision(**{**base, **kw})


def applied(question: str, dec: RouteDecision, selection: Any, **req_kw: Any) -> tuple[Any, str, list[str]]:
    """The service's order: apply the policy, re-validate, resolve, then apply any override to an 'ok' resolution."""
    req = InvestigateRequest(question=question, mode="live", **req_kw)
    upd, override, notes = route_policy(req, dec)
    res = resolve(InvestigateRequest.model_validate({**req.model_dump(), **upd}), selection)
    return res, (override if override and res.status == "ok" else res.status), notes


def test_definition_question_is_not_sent_back_for_a_region(selection):
    dec = decision(intent="source_explanation", region=None, event_date=None, needs_clarification=True,
                   clarification_reason="missing_region_or_date", clarification="Which region and date?")
    res, status, notes = applied("What does AVAILABLEGENERATION mean in the region summary data?", dec, selection)
    assert status == "ok" and res.intent == "source_explanation"
    assert any("needs no region or date" in n for n in notes)


def test_unclear_definition_request_is_still_clarified(selection):
    dec = decision(intent="source_explanation", region=None, event_date=None, needs_clarification=True,
                   clarification_reason="unclear_question", clarification="What term do you mean?")
    assert applied("What does it mean?", dec, selection)[1] == "needs_clarification"


def test_data_question_without_region_or_date_is_still_clarified(selection):
    dec = decision(region=None, event_date=None, needs_clarification=True,
                   clarification_reason="missing_region_or_date", clarification="Which region and date?")
    assert applied("What happened during the price spike last week?", dec, selection)[1] == "needs_clarification"


def test_several_regions_are_found_in_the_question_not_left_to_the_model(selection):
    # the model picked one region and did not flag the second: the resolver still sees both in the question
    res, status, notes = applied("What happened to prices in NSW and QLD on 2026-07-31?", decision(region="NSW1"),
                                 selection)
    assert status == "needs_clarification" and any("Several regions" in r for r in res.reasons)
    assert any("left to the resolver" in n for n in notes)


def test_as_of_forecast_question_is_a_forecast_review_even_when_it_names_an_event(selection):
    dec = decision(as_of_utc="2026-07-30T08:00:00Z")
    res, status, notes = applied("As of 2026-07-30T08:00:00Z, what did the demand forecasts say for the SA1 event on "
                                 "2026-07-31?", dec, selection)
    assert status == "ok" and res.intent == "forecast_review"
    assert any("as-of question about forecasts" in n for n in notes)


def test_neighbours_keep_their_intent(selection):
    # an as-of question about prices (no forecasts) stays an event review
    res, _, _ = applied("As of 2026-07-30T08:00:00Z, what had happened to SA1 prices on 2026-07-31?",
                        decision(as_of_utc="2026-07-30T08:00:00Z"), selection)
    assert res.intent == "market_event_review"
    # a forecast question without an as-of time keeps the model's choice
    res, _, _ = applied("How far off were the SA1 demand forecasts on 2026-07-31?", decision(intent="forecast_review"),
                        selection)
    assert res.intent == "forecast_review"
    # an intent the user set explicitly is never overridden
    res, _, _ = applied("As of 2026-07-30T08:00:00Z, what did the demand forecasts say for the SA1 event on 2026-07-31?",
                        decision(as_of_utc="2026-07-30T08:00:00Z"), selection, intent="market_event_review")
    assert res.intent == "market_event_review"


def test_out_of_scope_is_still_refused(selection):
    assert applied("Should I buy SA1 caps tomorrow?", decision(out_of_scope=True), selection)[1] == "refused"


def test_scripted_router_applies_the_same_forecast_rule():
    assert route("As of 2026-07-30T08:00:00Z, what did the demand forecasts say for the SA1 event on 2026-07-31?")[0] \
        == "forecast_review"
    assert route("What happened around the SA1 price spike on 2026-07-31?")[0] == "market_event_review"
    assert route("How far off were the SA1 demand forecasts on 2026-07-31?")[0] == "forecast_review"
