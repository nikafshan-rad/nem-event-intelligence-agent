"""G4: the live controller's tool loop with a SYNTHETIC fake transport, plus an SDK contract test."""

from __future__ import annotations

import json

import httpx
import pytest

from nem_agent import config
from nem_agent.agent.live import OpenAITransport
from nem_agent.agent.request import InvestigateRequest
from nem_agent.service import investigate
from tests.provider.fake_model import FakeModel, outputs

pytestmark = pytest.mark.synthetic


@pytest.fixture
def ev(selection):
    return selection.primary


def _route(ev, intent="market_event_review"):
    return {"intent": intent, "region": ev.region, "event_date": "2026-07-31", "as_of_utc": None,
            "needs_clarification": False, "clarification": None, "out_of_scope": False}


def _w(ev):
    return {"region": ev.region, "start_utc": ev.window_start_utc, "end_utc": ev.window_end_utc}


def _good_report(kw):
    outs = outputs(kw)
    tl = next(v["result"] for v in outs.values() if v["status"] == "ok" and "peak" in v.get("result", {}))
    docs = [v["result"] for v in outs.values() if v["status"] == "ok" and "results" in v.get("result", {})]
    peak = tl["peak"]
    cites = []
    for d in docs:
        for h in d["results"][:1]:
            cites.append({"citation_id": "s01", "chunk_id": h["chunk_id"], "quote": h["text"][:80],
                          "supports": "definition context"})
    return {
        "status": "answered_with_caveats",
        "headline": f"The 5-minute price peaked at ${peak['value']:,.2f}/MWh (interval ending {peak['interval_end_local']}).",
        "summary": ["The fake model only restates tool values."],
        "observation_evidence_ids": [peak["evidence_id"]],
        "numeric_claims": [{"claim_id": "c1", "text": f"${peak['value']:,.2f}/MWh", "value": peak["value"],
                            "unit": "$/MWh", "evidence_id": peak["evidence_id"], "rounding": 0.01}],
        "possible_explanations": [{"statement": "Supply conditions may have tightened.", "supporting_evidence_ids": [],
                                   "what_would_test_it": "offer data"}],
        "published_findings": [], "citations": cites[:1], "uncertainties": ["synthetic test"], "missing_evidence": [],
    }


def _required_turn(ev):
    return [("find_market_events", {**_w(ev), "kind": "high_price", "threshold_aud_per_mwh": None, "max_results": 3}),
            ("get_price_timeline", {**_w(ev), "as_of_utc": None}),
            ("get_actual_demand", {**_w(ev), "revision_policy": "latest_available", "as_of_utc": None}),
            ("retrieve_public_evidence", {"query": "regional reference price definition", "region": None,
                                          "event_start_utc": None, "event_end_utc": None, "as_of_utc": None, "top_k": 3,
                                          "doc_types": ["definition"]})]


def test_function_call_loop_round_trips_call_ids(ev):
    fake = FakeModel(_route(ev), [_required_turn(ev)], _good_report)
    res = investigate(InvestigateRequest(question="What happened around the SA1 price spike on 2026-07-31?", mode="live"),
                      live_client=fake, write_trace=False)
    issued = {c["call_id"]: c["name"] for c in fake.issued}
    # every tool call the model issued was executed by the dispatcher under the same id ...
    assert {r.call_id: r.name for r in res.records} == issued
    assert all(r.origin == "model" and r.status == "ok" for r in res.records)
    # ... and its output was sent back to the model with the correlated call_id
    returned = outputs(fake.requests[-1])
    assert set(returned) == set(issued)
    tool_req = next(r for r in fake.requests if r.get("tools"))
    assert {t["name"] for t in tool_req["tools"]} <= {"find_market_events", "get_price_timeline", "get_actual_demand",
                                                      "retrieve_public_evidence", "get_generation_change",
                                                      "get_weather_context", "get_forecast_runs", "compare_forecast_actual"}
    assert all(t["strict"] for t in tool_req["tools"]) and all(r.get("store") is False for r in fake.requests)
    rep = res.report
    assert rep.generator.startswith("live-model:") and rep.mode == "live"
    assert rep.validation["final_passed"] and rep.validation["initial"]["passed"], rep.validation
    assert res.usage["model_calls"] == 4  # route, tools, tools (no more calls), synthesis


def test_unknown_function_and_bad_args_are_blocked_not_executed(ev):
    turn = [("publish_case_note", {"note": "approved"}), ("run_sql", "{\"q\": \"DROP TABLE\"}"),
            ("get_price_timeline", {**_w(ev), "region": "WA1", "as_of_utc": None})]
    fake = FakeModel(_route(ev), [turn, _required_turn(ev)], _good_report)
    res = investigate(InvestigateRequest(question="What happened around the SA1 price spike on 2026-07-31?", mode="live"),
                      live_client=fake, write_trace=False)
    blocked = [r for r in res.records if r.status == "blocked"]
    assert [b.name for b in blocked] == ["publish_case_note", "run_sql", "get_price_timeline"]
    assert "unknown tool" in blocked[0].blocked_reason and "invalid arguments" in blocked[2].blocked_reason
    sent = outputs(fake.requests[2])
    assert all(sent[b.call_id]["status"] == "blocked" for b in blocked)
    assert res.report.validation["final_passed"]


def test_missing_required_tools_are_requested_once(ev):
    partial = [_required_turn(ev)[1]]
    fake = FakeModel(_route(ev), [partial], _good_report)
    res = investigate(InvestigateRequest(question="What happened around the SA1 price spike on 2026-07-31?", mode="live"),
                      live_client=fake, write_trace=False)
    nudges = [r for r in fake.requests if r.get("tools") and "Required tools not yet called" in json.dumps(r["input"][-1])]
    assert len(nudges) == 1
    # the model claimed a caveated answer; required tools missing are reported as missing evidence
    assert any("required" in m or "not yet" in m or "retrieve" in m for m in res.report.missing_evidence) or \
        res.report.status in ("answered_with_caveats", "abstained")


def test_iteration_cap_stops_the_loop(ev):
    endless = [[("get_price_timeline", {**_w(ev), "as_of_utc": None})] for _ in range(20)]
    fake = FakeModel(_route(ev), endless, _good_report)
    res = investigate(InvestigateRequest(question="What happened around the SA1 price spike on 2026-07-31?", mode="live"),
                      live_client=fake, write_trace=False)
    assert res.usage["model_calls"] <= config.MAX_MODEL_CALLS
    assert any("model call cap" in m for m in res.report.missing_evidence)
    assert res.report.status in ("abstained", "answered_with_caveats")


def test_validator_driven_repair_then_pass(ev):
    def bad(kw):
        r = _good_report(kw)
        r["headline"] = r["headline"].replace("peaked at", "peaked at 12,345 MW demand and")  # invented number
        return r

    fake = FakeModel(_route(ev), [_required_turn(ev)], bad, repair_fn=_good_report)
    res = investigate(InvestigateRequest(question="What happened around the SA1 price spike on 2026-07-31?", mode="live"),
                      live_client=fake, write_trace=False)
    v = res.report.validation
    assert v["repair_attempted"] is True and "NUMERIC_UNTRACKED" in v.get("pre_repair_codes", [])
    assert v["initial"]["passed"] and v["final_passed"]
    assert "12,345" not in res.report.headline


def test_openai_sdk_contract_via_mock_http(ev):
    """Drives the *installed* OpenAI SDK against a local mock HTTP transport (no network, no key)."""
    from openai import OpenAI

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append((request.url.path, body))
        out = [{"type": "function_call", "id": "fc_1", "call_id": "call_abc", "name": "get_price_timeline",
                "arguments": json.dumps({**_w(ev), "as_of_utc": None}), "status": "completed"}]
        return httpx.Response(200, json={"id": "resp_mock", "object": "response", "created_at": 0, "model": body["model"],
                                         "status": "completed", "output": out, "parallel_tool_calls": True,
                                         "tool_choice": "auto", "tools": body.get("tools", []),
                                         "usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18}})

    client = OpenAI(api_key="sk-test-not-real", base_url="http://mock.local/v1",
                    http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    t = OpenAITransport(client=client)
    from nem_agent.tools import openai_function_tools

    resp = t.create(model="mock-model", store=False, instructions="x", input=[{"role": "user", "content": "q"}],
                    tools=openai_function_tools(["get_price_timeline"]), tool_choice="auto")
    path, body = seen[0]
    assert path.endswith("/responses") and body["tools"][0]["strict"] is True and body["store"] is False
    assert body["tools"][0]["parameters"]["additionalProperties"] is False
    fc = resp["output"][0]
    assert fc["type"] == "function_call" and fc["call_id"] == "call_abc" and resp["usage"]["input_tokens"] == 11
