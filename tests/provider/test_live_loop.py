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
    # a blocked call stays reported unless a later call of the same tool succeeded
    miss = " ".join(res.report.missing_evidence)
    assert "publish_case_note: blocked" in miss and "get_price_timeline: blocked" not in miss


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
    # the tool loop leaves room for synthesis and one repair turn instead of consuming every call
    from nem_agent.agent.live import RESERVED_CALLS

    assert res.usage["model_calls"] == config.MAX_MODEL_CALLS - RESERVED_CALLS + 1  # tool turns, then synthesis
    assert any("kept for synthesis and repair" in m for m in res.report.missing_evidence)


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
    # the repair turn says how to fix each code, and both drafts stay inspectable in the trace
    repair_turn = str(fake.requests[-1]["input"][-1]["content"])
    assert "How to fix them" in repair_turn and "NUMERIC_UNTRACKED: Every number outside a quote" in repair_turn
    assert {e["name"] for e in res.trace.events} >= {"synthesis:draft", "repair:draft"}
    assert any("12,345" in str(e.get("report")) for e in res.trace.events if e["name"] == "synthesis:draft")
    assert v["pre_repair"]["n_critical"] >= 1


def _notice_turn(ev):
    return _required_turn(ev)[:3] + [("retrieve_public_evidence", {
        "query": "SA1 network events", "region": ev.region, "event_start_utc": ev.window_start_utc,
        "event_end_utc": ev.window_end_utc, "as_of_utc": None, "top_k": 4, "doc_types": ["market_notice"]})]


def test_findings_are_rendered_from_the_cited_quote(ev):
    """The model picks a citation; the controller renders the finding as its verbatim quote (numbers, AEMO's own
    wording and all), so notice text can no longer leak into a finding unquoted."""
    def report(kw):
        r = _good_report(kw)
        notices = [h for v in outputs(kw).values() if v["status"] == "ok" for h in v.get("result", {}).get("results", [])
                   if h["doc_type"] == "market_notice"]
        if not notices:
            pytest.skip("not in corpus: NEMWeb Current notices have rolling retention")
        r["citations"] = [{"citation_id": "c1", "chunk_id": notices[0]["chunk_id"], "quote": notices[0]["text"][:160],
                           "supports": "network event in the window"}]
        r["published_findings"] = [{"citation_id": "c1", "applies_to_event": True},
                                   {"citation_id": "c9", "applies_to_event": True}]  # unknown: dropped and reported
        return r

    fake = FakeModel(_route(ev), [_notice_turn(ev)], report)
    res = investigate(InvestigateRequest(question="What happened around the SA1 price spike on 2026-07-31?", mode="live"),
                      live_client=fake, write_trace=False)
    rep = res.report
    assert not rep.validation["fallback_applied"], rep.validation
    assert len(rep.published_findings) == 1 and rep.published_findings[0].citation_ids == ["c1"]
    assert f"“{rep.citations[0].quote}”" in rep.published_findings[0].statement
    assert any("unknown or unretrieved citation c9" in m for m in rep.missing_evidence)


def test_threshold_claim_resolves_to_its_own_evidence(ev):
    def report(kw):
        r = _good_report(kw)
        tl = next(v["result"] for v in outputs(kw).values() if v["status"] == "ok" and "peak" in v.get("result", {}))
        thr, n = tl["analysis_threshold"], tl["intervals_at_or_above_threshold"]
        r["summary"] = [f"{n['value']} five-minute intervals were at or above the ${thr['value']:,.2f}/MWh project threshold."]
        r["numeric_claims"] += [
            {"claim_id": "c2", "text": str(n["value"]), "value": n["value"], "unit": n["unit"],
             "evidence_id": n["evidence_id"], "rounding": 0},
            {"claim_id": "c3", "text": f"${thr['value']:,.2f}/MWh", "value": thr["value"], "unit": thr["unit"],
             "evidence_id": thr["evidence_id"], "rounding": 0.01}]
        return r

    fake = FakeModel(_route(ev), [_required_turn(ev)], report)
    res = investigate(InvestigateRequest(question="What happened around the SA1 price spike on 2026-07-31?", mode="live"),
                      live_client=fake, write_trace=False)
    assert res.report.validation["initial"]["passed"], res.report.validation["initial"]["violations"]
    assert not res.report.validation["fallback_applied"]


def test_model_facing_schemas_state_the_limits_the_server_enforces():
    from nem_agent.agent.live import ModelReport
    from nem_agent.tools import openai_function_tools
    from nem_agent.tools.args import strict_json_schema

    tools = {t["name"]: t["parameters"]["properties"] for t in openai_function_tools(
        ["retrieve_public_evidence", "find_market_events"])}
    assert "<= 8" in tools["retrieve_public_evidence"]["top_k"]["description"]
    assert "<= 20" in tools["find_market_events"]["max_results"]["description"]
    text = json.dumps(strict_json_schema(ModelReport))
    assert "never a chunk_id or citation_id" in text
    assert not any(f'"{k}"' in text for k in ("maximum", "minimum", "pattern", "default"))


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


def test_cost_uses_dated_price_table_or_env_override(monkeypatch):
    from nem_agent.agent.live import Usage

    monkeypatch.delenv("NEM_AGENT_PRICE_INPUT_PER_MTOK", raising=False)
    monkeypatch.delenv("NEM_AGENT_PRICE_OUTPUT_PER_MTOK", raising=False)
    u = Usage(model="gpt-5-mini")
    u.add({"usage": {"input_tokens": 1_000_000, "output_tokens": 100_000}})
    assert u.cost_usd == pytest.approx(0.25 + 0.20)
    monkeypatch.setenv("NEM_AGENT_PRICE_INPUT_PER_MTOK", "1")
    monkeypatch.setenv("NEM_AGENT_PRICE_OUTPUT_PER_MTOK", "10")
    u2 = Usage(model="gpt-5-mini")
    u2.add({"usage": {"input_tokens": 1_000_000, "output_tokens": 100_000}})
    assert u2.cost_usd == pytest.approx(2.0)


def test_unpriced_model_is_refused_before_any_call(ev, monkeypatch):
    """Without a price the budget cannot be enforced, so no request is sent at all (fail closed)."""
    from nem_agent.agent.live import BudgetExceeded

    monkeypatch.setenv("NEM_AGENT_MODEL", "unpriced-model")
    monkeypatch.delenv("NEM_AGENT_PRICE_INPUT_PER_MTOK", raising=False)
    monkeypatch.delenv("NEM_AGENT_PRICE_OUTPUT_PER_MTOK", raising=False)
    fake = FakeModel(_route(ev), [_required_turn(ev)], _good_report)
    with pytest.raises(BudgetExceeded, match="no price known"):
        investigate(InvestigateRequest(question="What happened around the SA1 price spike on 2026-07-31?", mode="live"),
                    live_client=fake, write_trace=False)
    assert fake.requests == []


def test_live_eval_budget_is_run_wide_and_estimated(tmp_path):
    from nem_agent.evaluation.runner import estimate_live_cost, load_cases, run

    est = estimate_live_cost(load_cases())
    assert est["questions_calling_the_model"] == 38 and est["expected_usd"] < est["high_usd"]
    res = run(mode="live", out=tmp_path / "live.json", budget_usd=0.0)  # exhausted before the first question
    assert res["incomplete"] and res["rows_completed"] == [] and not any(res["gate_checks"].values())
    assert not (tmp_path / "report.md").exists()  # never overwrites the committed offline report
