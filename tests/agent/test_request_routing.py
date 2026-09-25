"""Scripted router and request resolution (rule-based; labelled as such)."""

import pytest

from nem_agent.agent.request import InvestigateRequest, extract_dates, extract_regions, resolve, route


@pytest.mark.parametrize(("q", "intent"), [
    ("What happened around the SA1 price spike on 2026-07-31?", "market_event_review"),
    ("Did the demand forecast miss in Victoria on 20 Aug 2026?", "forecast_review"),
    ("What does operational demand mean?", "source_explanation"),
    ("What is the difference between TOTALDEMAND and operational demand?", "source_explanation"),
    ("Why were prices negative in VIC1 on 2026-07-28?", "market_event_review"),
])
def test_router(q, intent):
    assert route(q)[0] == intent


def test_extractors():
    assert extract_regions("price in South Australia and NSW") == ["SA1", "NSW1"]
    assert [str(d) for d in extract_dates("on 31 July 2026 and 2026-08-06")] == ["2026-07-31", "2026-08-06"]


def test_ambiguous_and_out_of_scope(selection):
    r = resolve(InvestigateRequest(question="What happened to prices in SA and VIC on 2026-07-31?"), selection)
    assert r.status == "needs_clarification" and "Several regions" in r.reasons[0]
    r = resolve(InvestigateRequest(question="What happened to the price spike?"), selection)
    assert r.status == "needs_clarification"
    r = resolve(InvestigateRequest(question="Should I buy electricity futures after the SA1 spike?"), selection)
    assert r.status == "refused"
    r = resolve(InvestigateRequest(question="What happened to WEM prices in Perth on 2026-07-31?"), selection)
    assert r.status == "refused"


def test_event_date_maps_to_selected_window(selection):
    ev = selection.primary
    r = resolve(InvestigateRequest(question="price spike review", region=ev.region, event_date="2026-07-31",
                                   intent="market_event_review"), selection)
    assert r.status == "ok" and r.event is not None and r.event.event_id == ev.event_id
