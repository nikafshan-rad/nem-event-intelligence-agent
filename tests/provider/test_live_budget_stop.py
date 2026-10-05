"""D34: Live budget stops. SYNTHETIC fake model and scratch ledgers only (conftest): nothing leaves the process.

- the preflight checks a conservative start requirement before the first paid call (every call's output at its cap,
  plus the routing request) and writes nothing to the ledger. It is not a complete bound on the run's cost: the input
  of later calls is not counted, and each call is still checked when it is reserved;
- a preflight refusal makes no call: the two runs saved on 2026-10-05 (TAS1 ``tr-6e226e92a8bc``, NSW1
  ``tr-c050b5983be0``) would not have started, and would have spent nothing. As before, a refusal before anything is
  sent is raised (``BudgetExceeded``), now with the not-started result to show;
- a later refusal (another session spending meanwhile) stops the run with no model answer, and says why;
- neither is shown as a model answer or as a passed validation, on the page or in the report.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nem_agent import budget, config
from nem_agent.agent.request import InvestigateRequest
from nem_agent.service import investigate
from nem_agent.ui_data import NO_MODEL_ANSWER, result_provenance
from tests.provider.fake_model import FakeModel
from tests.provider.test_live_loop import _good_report, _required_turn, _route

pytestmark = pytest.mark.synthetic
ROOT = Path(__file__).resolve().parents[2]
QUESTION = "What happened around the SA1 price spike on 2026-07-31?"


@pytest.fixture
def ev(selection):
    return selection.primary


def another_session_before(monkeypatch: pytest.MonkeyPatch, nth: int) -> None:
    """Another session spending meanwhile: just before this run's ``nth`` reservation, it reserves everything that
    remains under the cap but USD 0.005, and leaves it open."""
    real = budget.reserve
    seen = [0]

    def reserve(model: str, stage: str, usd: float) -> str:
        seen[0] += 1
        if seen[0] == nth:
            real("gpt-5-mini", "tools", budget.total_budget() - budget.spent() - 0.005)
        return real(model, stage, usd)

    monkeypatch.setattr(budget, "reserve", reserve)


def _kinds(fake: FakeModel) -> list[str]:
    return [((kw.get("text") or {}).get("format") or {}).get("name") or "tools" for kw in fake.requests]


def _entries() -> list[dict[str, Any]]:
    p = budget.ledger_path()
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def _run(fake: FakeModel) -> Any:
    return investigate(InvestigateRequest(question=QUESTION, mode="live"), live_client=fake, write_trace=False)


def _no_answer(res: Any, stage: str) -> dict[str, Any]:
    """What a budget stop must look like: abstained, no model answer, the stop recorded, and the page says so."""
    rep = res.report.model_dump()
    v = rep["validation"]
    assert rep["status"] == "abstained" and rep["answer"] == [] and rep["summary"] == []
    assert v["stopped"]["stage"] == stage and v["stopped"]["cause"] == "budget"
    assert v["interpretation"].startswith("absent")
    prov = result_provenance(rep, res.usage)
    assert prov["kind"] == "live_stopped" and prov["validation"] == NO_MODEL_ANSWER
    assert "answer written" not in prov["label"] and "passed" not in prov["validation"]
    return prov


def test_the_start_requirement_counts_every_output_cap_and_the_routing_request_and_writes_nothing(ev):
    fake = FakeModel(_route(ev), [_required_turn(ev)], _good_report)
    res = _run(fake)
    (pre,) = [e for e in res.trace.events if e["kind"] == "budget" and e["name"] == "preflight"]
    assert pre["passed"] and pre["cap_usd"] == budget.total_budget()
    assert [(c["stage"], c["calls"], c["max_output_tokens"]) for c in pre["calls"]] == [
        ("route", 1, 2000), ("tools", 5, 8000), ("synthesis", 1, 16000), ("repair", 1, 16000)]
    assert sum(c["calls"] for c in pre["calls"]) == config.MAX_MODEL_CALLS  # the loop's bound, nothing more
    sent = {k: v for k, v in fake.requests[0].items() if k not in ("model", "store", "max_output_tokens")}
    route = pre["calls"][0]
    assert route["input"] == "counted exactly" and route["input_chars"] == len(json.dumps(sent, default=str))
    assert route["counted_usd"] == budget.worst_case_cost("gpt-5-mini", route["input_chars"], 2000)
    assert all(c["input"].startswith("not counted") and c["input_chars"] == 0 for c in pre["calls"][1:])
    out = budget.prices("gpt-5-mini")[2] / 1e6
    assert pre["required_usd"] == pytest.approx(sum(c["counted_usd"] for c in pre["calls"]), abs=1e-6)
    assert pre["required_usd"] == pytest.approx(route["counted_usd"] + (5 * 8000 + 16000 + 16000) * out, abs=1e-6)
    assert "not a complete bound" in pre["basis"]
    # nothing is counted twice: one reservation and one settlement per call sent, and nothing left reserved
    entries = _entries()
    assert sum(e["kind"] == "reserve" for e in entries) == sum(e["kind"] == "settle" for e in entries) == len(
        fake.requests)
    assert budget.spent() == pytest.approx(res.usage["cost_usd"], abs=1e-6)


def test_the_start_requirement_is_not_a_complete_bound_on_the_runs_cost(ev):
    """A completed run's own reservations: each call after routing reserved input the start requirement did not count.
    That input is enforced call by call, when each call is reserved, not by the preflight."""
    fake = FakeModel(_route(ev), [_required_turn(ev)], _good_report)
    res = _run(fake)
    (pre,) = [e for e in res.trace.events if e["kind"] == "budget" and e["name"] == "preflight"]
    out = budget.prices("gpt-5-mini")[2] / 1e6
    later = [r for r in _entries() if r["kind"] == "reserve" and r["stage"] != "route"]
    assert later and all(r["usd"] > config.MAX_OUTPUT_TOKENS[r["stage"]] * out for r in later)
    uncounted = sum(r["usd"] - config.MAX_OUTPUT_TOKENS[r["stage"]] * out for r in later)  # their input, at cost
    assert uncounted > 0 and pre["required_usd"] == pytest.approx(
        pre["calls"][0]["counted_usd"] + sum(c["calls"] * c["max_output_tokens"] for c in pre["calls"][1:]) * out,
        abs=1e-6)  # no input of a later call in it


SAVED = {  # what the demo ledger held when each saved run started, from its settlements (USD)
    "TAS1 tr-6e226e92a8bc": 0.047619,
    "NSW1 tr-c050b5983be0": 0.065646,
    "a fresh ledger under the same cap": 0.0,
}


@pytest.mark.parametrize("name", list(SAVED))
def test_the_saved_runs_would_not_have_started_and_would_have_spent_nothing(name, ev, monkeypatch):
    """Under the demo's USD 0.10 cap, the start requirement (every output at its cap: USD 0.148, plus the routing
    request) does not fit, so the run is refused before any call: the saved runs spent USD 0.0171 and 0.0183 and
    stopped before an answer. It is refused on a fresh ledger under that cap too (intended)."""
    monkeypatch.setenv("NEM_AGENT_TOTAL_BUDGET_USD", "0.10")
    if SAVED[name]:
        budget.settle(budget.reserve("gpt-5-mini", "route", SAVED[name]), SAVED[name], {})
    before = _entries()
    fake = FakeModel(_route(ev), [_required_turn(ev)], _good_report)
    with pytest.raises(budget.BudgetExceeded) as refused:
        _run(fake)
    res = refused.value.result
    assert refused.value.stage == "preflight" and res is not None
    assert fake.requests == [] and res.usage["model_calls"] == 0 and res.records == []
    assert _entries() == before  # the preflight writes nothing
    prov = _no_answer(res, "preflight")
    assert "not started" in prov["label"] and "start requirement" in prov["label"]
    assert "no model call was made" in prov["label"]
    (note,) = res.report.missing_evidence
    assert note.startswith(f"Live run not started: task budget 0.10 USD: {SAVED[name]:.4f} spent or reserved")
    assert res.report.validation["interpretation"].startswith("absent: not started")


def test_a_refusal_of_the_routing_call_is_raised_with_its_no_answer_result(ev, monkeypatch):
    """Past the preflight, another session reserves before this run's routing call: that call is refused before it
    is sent, raised as before, with its result: nothing sent, and no model answer."""
    another_session_before(monkeypatch, 1)
    fake = FakeModel(_route(ev), [_required_turn(ev)], _good_report)
    with pytest.raises(budget.BudgetExceeded) as refused:
        _run(fake)
    assert refused.value.stage == "route" and fake.requests == []
    prov = _no_answer(refused.value.result, "route")
    assert "stopped at a budget limit before the model wrote an answer" in prov["label"]
    assert refused.value.result.report.headline.startswith("Not started: a budget limit refused the routing call")


def test_a_later_refusal_before_synthesis_stops_with_no_model_answer(ev, monkeypatch):
    """The TAS1 path: the preflight passes, two tool turns run, and the synthesis call is refused before it is sent
    (here because another session spent meanwhile)."""
    another_session_before(monkeypatch, 4)  # route, two tool turns, then synthesis
    fake = FakeModel(_route(ev), [_required_turn(ev)], _good_report)
    res = _run(fake)
    assert _kinds(fake) == ["RouteDecision", "tools", "tools"]  # synthesis was never sent
    prov = _no_answer(res, "synthesis")
    assert "stopped at a budget limit before the model wrote an answer" in prov["label"]
    assert any(m.startswith("Live run stopped: task budget") for m in res.report.missing_evidence)


def test_a_later_refusal_of_the_reminder_tool_turn_stops_with_no_model_answer(ev, monkeypatch):
    """The NSW1 path: a required tool's call is blocked (``max_results`` over its limit), the model asks for nothing
    more, the controller's reminder turn is refused before it is sent, and synthesis is never reached."""
    turn = [(n, {**a, "max_results": 100} if n == "find_market_events" else a) for n, a in _required_turn(ev)]
    another_session_before(monkeypatch, 4)  # route, two tool turns, then the reminder turn
    fake = FakeModel(_route(ev), [turn], _good_report)
    res = _run(fake)
    assert _kinds(fake) == ["RouteDecision", "tools", "tools"]
    assert [r.status for r in res.records if r.name == "find_market_events"] == ["blocked"]
    _no_answer(res, "tools")


def test_a_refused_repair_is_not_reported_as_attempted(ev, monkeypatch):
    """The model's answer failed validation and its repair was refused before it was sent: the facts-only fallback is
    shown, and the page does not say a repair ran."""
    def bad(kw: Any) -> dict[str, Any]:
        r = _good_report(kw)
        r["headline"] = r["headline"].replace("peaked at", "peaked at 12,345 MW demand and")  # invented number
        return r

    another_session_before(monkeypatch, 5)  # route, two tool turns, synthesis, then the repair
    fake = FakeModel(_route(ev), [_required_turn(ev)], bad)
    res = _run(fake)
    assert _kinds(fake) == ["RouteDecision", "tools", "tools", "ModelReport"]  # no repair request
    v = res.report.validation
    assert v["repair_attempted"] is False and v["repair_stopped"]["stage"] == "repair" and v["fallback_applied"]
    prov = result_provenance(res.report.model_dump(), res.usage)
    assert prov["kind"] == "live_fallback" and "after one repair" not in prov["validation"]
    assert prov["validation"] == "rejected: facts-only fallback (the repair was not run: stopped at a budget limit)"


def test_invalid_model_output_without_a_computed_answer_is_not_shown_as_an_answer(ev):
    """The same missing marker (D34): a model report that did not match the schema, in an investigation with no
    computed answer, was labelled as a validated model answer."""
    fake = FakeModel(_route(ev), [_required_turn(ev)], lambda kw: {"status": "SYNTHETIC: not a status"})
    res = _run(fake)
    rep = res.report.model_dump()
    assert rep["status"] == "abstained" and rep["answer"] == []
    assert rep["validation"]["interpretation"] == "absent: the model produced no valid output"
    assert "stopped" not in rep["validation"]
    prov = result_provenance(rep, res.usage)
    assert prov["kind"] == "live_no_interpretation" and prov["validation"] == "no valid model output to validate"


def test_the_page_shows_a_budget_stop_as_no_answer(ev, monkeypatch):
    from streamlit.testing.v1 import AppTest

    import nem_agent.service as service

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-key")  # presence only: the model below is a scripted fake
    monkeypatch.setenv("NEM_AGENT_TOTAL_BUDGET_USD", "0.10")
    fake = FakeModel(_route(ev), [_required_turn(ev)], _good_report)
    real = service.investigate
    monkeypatch.setattr(service, "investigate", lambda req, **kw: real(req, live_client=fake, write_trace=False))
    at = AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"), default_timeout=180)
    at.run()
    at.sidebar.radio[0].set_value("live").run()
    next(b for b in at.button if b.label == "Investigate").click().run()
    assert not at.exception and fake.requests == []
    assert any("not started" in w.value for w in at.warning)
    assert not any("answer written" in s.value for s in at.success)
    tiles = {m.label: m.value for m in at.metric}
    assert tiles["Validation"] == "no answer" and "abstained" in tiles["Status"]
