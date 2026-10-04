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
            "needs_clarification": False, "clarification_reason": None, "clarification": None,
            "out_of_scope": False}


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
        "forecast_mae_evidence_id": None, "document_statements": [],
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
    # a blocked call stays reported unless a later call of the same tool succeeded; since I-4 it is shown in plain
    # words (the two tools that do not exist read the same, so once) and the controller's line is kept
    noted = " ".join(r["original"] for r in res.report.validation["display_rewrites"])
    assert "publish_case_note: blocked" in noted and "run_sql: blocked" in noted and "get_price_timeline: blocked" not in noted
    assert res.report.missing_evidence.count("A request for an action that is not one of the investigation's tools was "
                                             "blocked; nothing was run.") == 1
    assert "price timeline was blocked" not in " ".join(res.report.missing_evidence)


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
    assert "The investigation stopped early, at its limit on model calls." in res.report.missing_evidence  # since I-4
    assert any("model call cap" in r["original"] for r in res.report.validation["display_rewrites"])
    assert res.report.status in ("abstained", "answered_with_caveats")
    # the tool loop leaves room for synthesis and one repair turn instead of consuming every call
    from nem_agent.agent.live import RESERVED_CALLS

    assert res.usage["model_calls"] == config.MAX_MODEL_CALLS - RESERVED_CALLS + 1  # tool turns, then synthesis
    assert any("kept for synthesis and repair" in r["original"] for r in res.report.validation["display_rewrites"])


def test_validator_driven_repair_then_pass(ev):
    def bad(kw):
        r = _good_report(kw)
        r["headline"] = r["headline"].replace("peaked at", "peaked at 12,345 MW demand and")  # invented number
        return r

    def patch(kw):  # the scoped repair may change only the failing item: here the headline
        return {"edits": [{"target": "headline", "action": "replace", "text": _good_report(kw)["headline"],
                           "statement": None, "claim": None, "citation": None}],
                "new_numeric_claims": [], "new_citations": []}

    fake = FakeModel(_route(ev), [_required_turn(ev)], bad, repair_fn=patch)
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
    assert "A published finding the answer listed is not shown: its source passage was not retrieved in this " \
        "investigation." in rep.missing_evidence  # since I-4 in plain words; the controller's line is kept
    assert any("unknown or unretrieved citation c9" in r["original"] for r in rep.validation["display_rewrites"])


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


def test_every_call_is_capped_and_recorded_in_the_task_ledger(ev):
    from nem_agent import budget

    fake = FakeModel(_route(ev), [_required_turn(ev)], _good_report)
    res = investigate(InvestigateRequest(question="What happened around the SA1 price spike on 2026-07-31?", mode="live"),
                      live_client=fake, write_trace=False)
    stages = [e["name"] for e in res.trace.events if e["kind"] == "model" and e.get("max_output_tokens")]
    assert all(r["max_output_tokens"] == config.MAX_OUTPUT_TOKENS[s] for r, s in zip(fake.requests, stages, strict=True))
    assert len(stages) == len(fake.requests) == res.usage["model_calls"]
    entries = [json.loads(ln) for ln in budget.ledger_path().read_text().splitlines()]
    assert sum(e["kind"] == "reserve" for e in entries) == sum(e["kind"] == "settle" for e in entries) == len(fake.requests)
    assert budget.spent() == pytest.approx(res.usage["cost_usd"], abs=1e-6)
    # what the model was shown is in the trace: tool outputs and ranked retrieval candidates
    outs = [e for e in res.trace.events if e["kind"] == "tool_output"]
    assert len(outs) == len(res.records) and all(e["output"] for e in outs)
    assert any(e.get("candidates") and "score" in e["candidates"][0] for e in outs)


def test_task_budget_refuses_the_next_call_before_it_is_sent(ev, monkeypatch):
    from nem_agent import budget

    monkeypatch.setenv("NEM_AGENT_TOTAL_BUDGET_USD", "0.01")  # the route call fits; a tools call (8,000 tokens) cannot
    fake = FakeModel(_route(ev), [_required_turn(ev)], _good_report)
    res = investigate(InvestigateRequest(question="What happened around the SA1 price spike on 2026-07-31?", mode="live"),
                      live_client=fake, write_trace=False)
    assert len(fake.requests) == 1  # only the routing call was sent
    assert any("task budget 0.01 USD" in m for m in res.report.missing_evidence)
    assert res.report.status in ("abstained", "answered_with_caveats") and budget.spent() < 0.01


def test_ledger_counts_unsettled_reservations(monkeypatch):
    from nem_agent import budget

    a = budget.reserve("gpt-5-mini", "tools", 0.02)
    budget.reserve("gpt-5-mini", "synthesis", 0.03)  # never settled (e.g. a crash): stays counted
    budget.settle(a, 0.005, {"input_tokens": 10, "output_tokens": 2})
    assert budget.spent() == pytest.approx(0.035)
    monkeypatch.setenv("NEM_AGENT_TOTAL_BUDGET_USD", "0.04")
    with pytest.raises(budget.BudgetExceeded):
        budget.reserve("gpt-5-mini", "tools", 0.01)
    assert budget.call_cost("gpt-5-mini", {"input_tokens": 1_000_000, "output_tokens": 0,
                                           "input_tokens_details": {"cached_tokens": 1_000_000}}) == pytest.approx(0.025)


def _forecast_turn(ev):
    return [("get_forecast_runs", {"region": ev.region, "target_start_utc": "2026-07-30T11:00:00Z",
                                   "target_end_utc": "2026-07-30T23:00:00Z", "as_of_utc": None, "max_runs": 4}),
            ("get_actual_demand", {"region": ev.region, "start_utc": "2026-07-30T11:00:00Z",
                                   "end_utc": "2026-07-30T23:00:00Z", "revision_policy": "latest_available", "as_of_utc": None}),
            ("compare_forecast_actual", {"region": ev.region, "target_start_utc": "2026-07-30T11:00:00Z",
                                         "target_end_utc": "2026-07-30T23:00:00Z", "run_selector": "latest_before_target",
                                         "min_lead_hours": None, "run_id": None, "as_of_utc": None,
                                         "actual_revision": "latest_available", "actual_metric": "OPERATIONAL_DEMAND"}),
            ("retrieve_public_evidence", {"query": "operational demand definition", "region": None, "event_start_utc": None,
                                          "event_end_utc": None, "as_of_utc": None, "top_k": 3, "doc_types": ["definition"]})]


def _forecast_report(kw, mae_id=None):
    cmp_ = next(v["result"] for v in outputs(kw).values() if v["status"] == "ok" and "mae_mw" in v.get("result", {}))
    return {"status": "answered_with_caveats", "headline": "Forecast review for SA1 (synthetic).", "summary": [],
            "observation_evidence_ids": [], "numeric_claims": [], "possible_explanations": [], "published_findings": [],
            "citations": [], "uncertainties": ["synthetic test"], "missing_evidence": [],
            "forecast_mae_evidence_id": mae_id or cmp_["mae_mw"]["evidence_id"], "document_statements": []}


def test_forecast_context_and_comparison_built_from_the_named_mae(ev):
    def report(kw):
        return _forecast_report(kw)

    fake = FakeModel(_route(ev, "forecast_review"), [_forecast_turn(ev)], report)
    res = investigate(InvestigateRequest(question="Did AEMO's demand forecast miss in SA1 on 2026-07-31?", mode="live"),
                      live_client=fake, write_trace=False)
    ctx = json.loads(fake.requests[1]["input"][0]["content"].split("\n", 1)[1])
    assert ctx["forecast_targets_utc"] == ["2026-07-30T11:00:00Z", "2026-07-30T23:00:00Z"]
    assert ctx["event_peak_interval_end_local"].startswith("2026-07-31 02:05 ACST")
    assert ctx["peak_half_hour_end_utc"] == "2026-07-30T17:00:00Z"  # the half-hour containing the 16:35 UTC interval
    fc = res.report.forecast_comparison
    assert fc is not None and fc.n_pairs == 24 and fc.mae_mw == pytest.approx(32.88, abs=0.01)
    assert res.registry.get(fc.mae_evidence_id).value == fc.mae_mw  # copied from the tool, not from the model


def test_unknown_forecast_evidence_is_reported_not_invented(ev):
    def report(kw):
        return _forecast_report(kw, mae_id="ev9999")

    fake = FakeModel(_route(ev, "forecast_review"), [_forecast_turn(ev)], report)
    res = investigate(InvestigateRequest(question="Did AEMO's demand forecast miss in SA1 on 2026-07-31?", mode="live"),
                      live_client=fake, write_trace=False)
    # D27: the comparison shown is the controller's own (the review's aggregate primary), never the model's reference
    shown = res.report.forecast_comparison
    assert shown is None or shown.mae_evidence_id == res.resolution.forecast_primary["mae_evidence_id"] != "ev9999"
    assert "The forecast-versus-actual summary is not shown: the answer referred to a comparison that was not " \
        "returned." in res.report.missing_evidence  # since I-4 in plain words; the controller's line is kept
    assert any("ev9999" in r["original"] for r in res.report.validation["display_rewrites"])


def test_large_tool_outputs_stay_valid_json():
    """L1 live run: a 112,364-character forecast output was cut mid-JSON before it reached the model."""
    from nem_agent.agent.live import compact_json

    big = {"status": "ok", "result": {"mae_mw": {"value": 32.88, "evidence_id": "ev0001"},
                                      "runs": [{"run_id": i, "targets": [{"poe50": j, "evidence_id": f"ev{j:04d}"}
                                                                         for j in range(48)]} for i in range(40)]}}
    text, omitted = compact_json(big, 6000)
    data = json.loads(text)  # valid JSON
    assert len(text) <= 6000 and omitted > 0 and data["result"]["mae_mw"]["value"] == 32.88
    assert any(isinstance(x, dict) and "_omitted_items" in x for x in data["result"]["runs"])
    assert compact_json({"a": [1, 2]}, 100) == ('{"a": [1, 2]}', 0)


def test_repair_message_quotes_the_failing_sentence(ev):
    from nem_agent.agent.live import repair_message
    from nem_agent.validation import ValidationResult, Violation

    rep = type("R", (), {"headline": "h", "summary": ["ok", "AEMO reported a line outage of No 2 line [c2]."],
                         "possible_explanations": [], "published_findings": []})()
    res = ValidationResult(violations=[Violation("NUMERIC_UNTRACKED", "critical", "summary[1]: number 2 is not a "
                                                                                   "registered claim")])
    msg = repair_message(res, rep)
    assert "failed independent validation" in msg and 'in: "AEMO reported a line outage of No 2 line [c2]."' in msg


def test_repair_says_what_counts_as_a_quote():
    """L2 run 3: the repair put notice text in single quotes, which the validator (rightly) does not treat as a quote."""
    from nem_agent.agent.live import REPAIR_HINTS, prompt

    assert "double quotation marks" in REPAIR_HINTS["NUMERIC_UNTRACKED"]
    assert "single quotes" in REPAIR_HINTS["NUMERIC_UNTRACKED"]
    assert "own sentence" in REPAIR_HINTS["DOC_CLAIM_UNSUPPORTED"]
    assert "single quotes is not a quote" in prompt("system")


def test_tool_outputs_reach_the_model_with_real_characters():
    """L3 run 1 (DOC03): the model saw '\\u2013' instead of an en dash and could not quote the passage verbatim."""
    from nem_agent.agent.live import compact_json

    text, omitted = compact_json({"text": "units – Sum of InitialMW; ≥ 30 MW; 12 °C; “quoted”"}, 10_000)
    assert omitted == 0 and "–" in text and "≥" in text and "°C" in text and "“quoted”" in text
    assert "\\u2013" not in text and json.loads(text)["text"].startswith("units – Sum")


def test_every_repair_states_the_quote_rule_and_forbids_new_details():
    from nem_agent.agent.live import REPAIR_HINTS, repair_message
    from nem_agent.validation import ValidationResult, Violation

    msg = repair_message(ValidationResult(violations=[Violation("CITATION_QUOTE_NOT_FOUND", "critical", "c1: x")]))
    assert "double quotation marks" in msg and "Do not add numbers, times or notice details" in msg
    assert "published_findings already shows" in REPAIR_HINTS["DOC_CLAIM_UNSUPPORTED"]
    assert "5MPD" in REPAIR_HINTS["NUMERIC_UNTRACKED"]


def test_definition_question_runs_retrieval_although_the_model_asked_for_a_region():
    """L3 live, DOC03: the model's request for a region and date made a definition question end in
    needs_clarification. End to end through the service, the definition is now answered from retrieval."""
    route = {"intent": "source_explanation", "region": None, "event_date": None, "as_of_utc": None,
             "needs_clarification": True, "clarification_reason": "missing_region_or_date",
             "clarification": "Which region and date?", "out_of_scope": False}
    turn = [("retrieve_public_evidence", {"query": "operational demand definition", "region": None,
                                          "event_start_utc": None, "event_end_utc": None, "as_of_utc": None,
                                          "top_k": 3, "doc_types": ["definition"]})]

    def report(kw):
        hit = next(v["result"] for v in outputs(kw).values() if v["status"] == "ok")["results"][0]
        quote = hit["text"][:80]
        return {"status": "answered", "headline": "AEMO's definition", "summary": [f"“{quote}” [s01]"],
                "observation_evidence_ids": [], "numeric_claims": [], "possible_explanations": [],
                "published_findings": [], "citations": [{"citation_id": "s01", "chunk_id": hit["chunk_id"],
                                                         "quote": quote, "supports": "definition"}],
                "uncertainties": [], "missing_evidence": [], "forecast_mae_evidence_id": None, "document_statements": []}
    fake = FakeModel(route, [turn], report)
    res = investigate(InvestigateRequest(question="What does operational demand mean in the dispatch data?",
                                         mode="live"), live_client=fake, write_trace=False)
    assert res.resolution.status == "ok" and res.resolution.intent == "source_explanation"
    # the controller's retrieval for the question itself, then the model's own
    assert [(r.name, r.origin) for r in res.records] == [("retrieve_public_evidence", "controller"),
                                                         ("retrieve_public_evidence", "model")]
    assert res.report.status in ("answered", "answered_with_caveats") and res.report.citations
    notes = next(e["policy_notes"] for e in res.trace.as_dict()["events"] if e["name"] == "model_decision")
    assert any("needs no region or date" in n for n in notes)


def test_repair_shows_the_failing_hypothesis_test_and_hints_for_time_codes():
    from nem_agent.agent.live import REPAIR_HINTS, repair_message
    from nem_agent.validation import ValidationResult, Violation

    rep = type("R", (), {"headline": "h", "summary": [], "published_findings": [],
                         "possible_explanations": [type("H", (), {"statement": "s", "what_would_test_it":
                                                                  "Check unit trips from 11:00."})()]})()
    res = ValidationResult(violations=[Violation("TIME_ZONE_MISSING", "critical",
                                                 "possible_explanations[0].what_would_test_it: '11:00' has no time zone")])
    msg = repair_message(res, rep)
    assert 'in: "Check unit trips from 11:00."' in msg and "clock_times" in msg
    assert {"TIME_ZONE_MISSING", "TIME_OF_DAY_UNVERIFIED"} <= set(REPAIR_HINTS)


class _Failing:
    """A transport whose call fails after (timeout) or without (HTTP 4xx) the provider processing it."""

    def __init__(self, status_code=None):
        self.status_code = status_code

    def create(self, **kw):
        exc = RuntimeError("Request timed out." if self.status_code is None else "Bad request")
        if self.status_code is not None:
            exc.status_code = self.status_code  # type: ignore[attr-defined]
        raise exc


@pytest.mark.parametrize("status_code, billed", [(None, True), (500, True), (400, False)])
def test_a_failed_call_stays_counted_unless_the_provider_rejected_it(status_code, billed):
    """L3 run 3: a synthesis call timed out after the request was sent and was settled at USD 0. A timeout, a
    connection error or a 5xx may still be billed, so the reservation stays at its worst case; only a 4xx is not."""
    from nem_agent import budget
    from nem_agent.agent.live import LiveController
    from nem_agent.evidence import EvidenceRegistry
    from nem_agent.report import Versions
    from nem_agent.trace import Trace

    live = LiveController(None, EvidenceRegistry(), Versions(code="t", data="t", corpus="t", prompt="t", model=None,
                                                             controller="live"), client=_Failing(status_code))
    trace = Trace()
    with pytest.raises(RuntimeError):
        live._call(trace, "synthesis", input=[{"role": "user", "content": "x"}])
    entries = [json.loads(ln) for ln in budget.ledger_path().read_text().splitlines()]
    worst = next(e["usd"] for e in entries if e["kind"] == "reserve")
    assert budget.spent() == pytest.approx(worst if billed else 0.0, abs=1e-9)
    err = next(e for e in trace.events if e["name"] == "synthesis:error")
    assert err["settled_usd"] == (worst if billed else 0.0)


def test_charges_count_towards_the_task_budget():
    from nem_agent import budget

    budget.charge("gpt-5-mini", "synthesis", 0.04, "hidden SDK retry")
    assert budget.spent() == pytest.approx(0.04)


def test_the_sdk_never_retries_behind_the_ledger(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "placeholder-not-a-key")  # the client is only constructed; no request is sent
    monkeypatch.delenv("NEM_AGENT_API_TIMEOUT_S", raising=False)
    t = OpenAITransport()
    assert t.client.max_retries == 0 and t.client.timeout == 300
