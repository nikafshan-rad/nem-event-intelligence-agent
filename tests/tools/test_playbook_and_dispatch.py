"""G2: intent playbooks, the optional-diagnostic budget (max 2) and pre-execution blocking."""

from __future__ import annotations

import pytest

from nem_agent import config
from nem_agent.agent.dispatcher import Dispatcher
from nem_agent.agent.playbook import PLAYBOOKS
from nem_agent.agent.request import InvestigateRequest
from nem_agent.evidence import EvidenceRegistry
from nem_agent.service import investigate
from nem_agent.tools import TOOLS, openai_function_tools
from nem_agent.trace import Trace


def test_playbooks_reference_only_registered_tools():
    assert len(TOOLS) == 8
    for pb in PLAYBOOKS.values():
        assert set(pb.required) | set(pb.optional) <= set(TOOLS)
        assert not set(pb.required) & set(pb.optional)
    assert "publish_case_note" not in TOOLS  # the write action is never a model-callable tool


def test_strict_function_schemas():
    for t in openai_function_tools():
        p = t["parameters"]
        assert t["strict"] is True and p["additionalProperties"] is False
        assert set(p["required"]) == set(p["properties"])


@pytest.fixture
def disp(real_store, selection):
    return Dispatcher(real_store, selection, Trace(), EvidenceRegistry(), "source_explanation")


def test_unknown_and_non_playbook_tools_blocked(disp):
    assert disp.call("run_sql", {"q": "select 1"}).status == "blocked"
    assert disp.call("get_forecast_runs", {}).blocked_reason.startswith("'get_forecast_runs' is not in")


def test_invalid_json_blocked(disp):
    rec = disp.call("retrieve_public_evidence", "{not json")
    assert rec.status == "blocked" and "valid JSON" in rec.blocked_reason


def test_optional_budget_is_two(real_store, selection):
    ev = selection.primary
    d = Dispatcher(real_store, selection, Trace(), EvidenceRegistry(), "source_explanation")
    w = {"region": ev.region, "start_utc": ev.window_start_utc, "end_utc": ev.window_end_utc}
    r1 = d.call("get_price_timeline", w)
    r2 = d.call("find_market_events", {**w, "kind": "high_price"})
    r3 = d.call("get_price_timeline", w)
    assert r1.optional and r2.optional and r1.status == "ok" and r2.status == "ok"
    assert r3.status == "blocked" and "budget" in r3.blocked_reason
    assert d.optional_used == config.MAX_OPTIONAL_DIAGNOSTICS == 2


@pytest.mark.parametrize("intent", ["market_event_review", "forecast_review", "source_explanation"])
def test_replay_executes_required_tools_and_at_most_two_extras(intent, selection):
    ev = selection.primary
    day = ev.peak_interval_end_market[:10].replace("/", "-")
    q = {"market_event_review": f"What happened around the SA1 price spike on {day}?",
         "forecast_review": f"How did the SA1 demand forecasts compare with actual demand on {day}?",
         "source_explanation": "What does operational demand mean?"}[intent]
    res = investigate(InvestigateRequest(question=q, region=None, intent=intent), write_trace=False)
    ran = [r for r in res.records if r.status != "blocked"]
    names = {r.name for r in ran}
    assert set(PLAYBOOKS[intent].required) <= names
    assert sum(r.optional for r in ran) <= 2
    assert not [r for r in res.records if r.status == "blocked"]
    assert res.report.generator == "scripted-replay-controller/1"
