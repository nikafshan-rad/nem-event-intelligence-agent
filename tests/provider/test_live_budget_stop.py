"""D34: Live budget stops shown truthfully. SYNTHETIC fake model and scratch ledgers only (conftest): nothing leaves
the process.

Per-call enforcement is unchanged: each call is reserved at its worst case and refused before it is sent when the
task-wide cap would be passed. What changes is what such a refusal shows:

- a refusal before the model wrote an answer is an abstention with no model answer, recorded with the stage refused,
  and never shown as a written answer or a passed validation. The two runs saved on 2026-10-05 stopped this way:
  TAS1 ``tr-6e226e92a8bc`` at synthesis, NSW1 ``tr-c050b5983be0`` at the reminder tool turn after a blocked required
  tool (reproduced here with another session reserving meanwhile);
- a routing call refused by its own reservation is raised, exactly as before, now with its no-answer result to show;
- a repair the budget refused is not reported as attempted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nem_agent import budget
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


def _run(fake: FakeModel) -> Any:
    return investigate(InvestigateRequest(question=QUESTION, mode="live"), live_client=fake, write_trace=False)


def _no_answer(res: Any, stage: str) -> dict[str, Any]:
    """What a budget stop must look like: abstained, no model answer, the stop recorded, and the page says so."""
    rep = res.report.model_dump()
    v = rep["validation"]
    assert rep["status"] == "abstained" and rep["answer"] == [] and rep["summary"] == []
    assert v["stopped"]["stage"] == stage and v["stopped"]["cause"] == "budget"
    assert v["interpretation"] == "absent: the run stopped at a budget limit before the model wrote an answer"
    prov = result_provenance(rep, res.usage)
    assert prov["kind"] == "live_stopped" and prov["validation"] == NO_MODEL_ANSWER
    assert "stopped at a budget limit before the model wrote an answer" in prov["label"]
    assert "answer written" not in prov["label"] and "passed" not in prov["validation"]
    return prov


def test_the_tas1_path_a_refusal_before_synthesis_stops_with_no_model_answer(ev, monkeypatch):
    """TAS1 ``tr-6e226e92a8bc``: two tool turns run, then the synthesis call is refused before it is sent."""
    another_session_before(monkeypatch, 4)  # route, two tool turns, then synthesis
    fake = FakeModel(_route(ev), [_required_turn(ev)], _good_report)
    res = _run(fake)
    assert _kinds(fake) == ["RouteDecision", "tools", "tools"]  # synthesis was never sent
    _no_answer(res, "synthesis")
    assert any(m.startswith("Live run stopped: task budget") for m in res.report.missing_evidence)


def test_the_nsw1_path_a_refusal_of_the_reminder_tool_turn_stops_with_no_model_answer(ev, monkeypatch):
    """NSW1 ``tr-c050b5983be0``: a required tool's call is blocked (``max_results`` over its limit), the model asks for
    nothing more, the controller's reminder turn is refused before it is sent, and synthesis is never reached."""
    turn = [(n, {**a, "max_results": 100} if n == "find_market_events" else a) for n, a in _required_turn(ev)]
    another_session_before(monkeypatch, 4)  # route, two tool turns, then the reminder turn
    fake = FakeModel(_route(ev), [turn], _good_report)
    res = _run(fake)
    assert _kinds(fake) == ["RouteDecision", "tools", "tools"]
    assert [r.status for r in res.records if r.name == "find_market_events"] == ["blocked"]
    _no_answer(res, "tools")


def test_a_routing_call_refused_by_its_reservation_is_raised_with_its_no_answer_result(ev, monkeypatch):
    another_session_before(monkeypatch, 1)
    fake = FakeModel(_route(ev), [_required_turn(ev)], _good_report)
    with pytest.raises(budget.BudgetExceeded) as refused:
        _run(fake)
    assert refused.value.stage == "route" and fake.requests == []
    res = refused.value.result
    assert res is not None and res.usage["model_calls"] == 0 and res.records == []
    _no_answer(res, "route")
    assert res.report.headline.startswith("Not started: a budget limit refused the routing call")
    assert res.report.missing_evidence == [f"Live run not started: {refused.value}"]


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
    """The same missing marker: a model report that did not match the schema, in an investigation with no computed
    answer, was labelled as a validated model answer."""
    fake = FakeModel(_route(ev), [_required_turn(ev)], lambda kw: {"status": "SYNTHETIC: not a status"})
    res = _run(fake)
    rep = res.report.model_dump()
    assert rep["status"] == "abstained" and rep["answer"] == []
    assert rep["validation"]["interpretation"] == "absent: the model produced no valid output"
    assert "stopped" not in rep["validation"]
    prov = result_provenance(rep, res.usage)
    assert prov["kind"] == "live_no_interpretation" and prov["validation"] == "no valid model output to validate"


@pytest.mark.parametrize("nth, sent", [(4, 3), (1, 0)], ids=["refused before synthesis", "routing call refused"])
def test_the_page_shows_a_budget_stop_as_no_answer(nth, sent, ev, monkeypatch):
    from streamlit.testing.v1 import AppTest

    import nem_agent.service as service

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-key")  # presence only: the model below is a scripted fake
    another_session_before(monkeypatch, nth)
    fake = FakeModel(_route(ev), [_required_turn(ev)], _good_report)
    real = service.investigate
    monkeypatch.setattr(service, "investigate", lambda req, **kw: real(req, live_client=fake, write_trace=False))
    at = AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"), default_timeout=180)
    at.run()
    at.sidebar.radio[0].set_value("live").run()
    next(b for b in at.button if b.label == "Investigate").click().run()
    assert not at.exception and len(fake.requests) == sent
    assert any("stopped at a budget limit before the model wrote an answer" in w.value for w in at.warning)
    assert not any("answer written" in s.value for s in at.success)
    tiles = {m.label: m.value for m in at.metric}
    assert tiles["Validation"] == "no answer" and "abstained" in tiles["Status"]
