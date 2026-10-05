"""D35: early transition to synthesis after a clean tool turn, opt-in (``NEM_AGENT_LIVE_EARLY_SYNTHESIS``) and off by
default. SYNTHETIC fake transport and scratch ledgers only (conftest): nothing leaves the process.

- unset (or any value other than 1, true, yes or on), the tool loop is exactly as before;
- on, the loop goes to synthesis right after a turn whose calls all returned ok, once every required tool has an ok
  result and no correction or required-tool reminder is pending; every tool output collected is in the synthesis input;
- a blocked or failed call, or a missing required tool, keeps the existing loop;
- validation, repair and the budget guards are unchanged.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from nem_agent import budget
from nem_agent.agent.live import EARLY_SYNTHESIS_ENV, EARLY_SYNTHESIS_REASON, early_synthesis_enabled
from nem_agent.agent.request import InvestigateRequest
from nem_agent.service import investigate
from nem_agent.timeutil import iso_utc, parse_iso
from nem_agent.tools import TOOLS
from tests.provider.fake_model import FakeModel
from tests.provider.test_live_loop import _good_report, _required_turn, _route

pytestmark = pytest.mark.synthetic
ROOT = Path(__file__).resolve().parents[2]
QUESTION = "What happened around the SA1 price spike on 2026-07-31?"
DEFAULT_PATH = ["RouteDecision", "tools", "tools", "ModelReport"]  # route, the tool turn, the final no-call turn, synthesis


@pytest.fixture
def ev(selection):
    return selection.primary


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv(EARLY_SYNTHESIS_ENV, "1")


def _kinds(fake: FakeModel) -> list[str]:
    return [((kw.get("text") or {}).get("format") or {}).get("name") or "tools" for kw in fake.requests]


def _run(fake: FakeModel) -> Any:
    return investigate(InvestigateRequest(question=QUESTION, mode="live"), live_client=fake, write_trace=False)


def _early(res: Any) -> list[dict[str, Any]]:
    return [e for e in res.trace.events if e["kind"] == "model" and e["name"] == "early_synthesis"]


def _outputs_in(request: dict[str, Any]) -> set[str]:
    return {i["call_id"] for i in request["input"] if isinstance(i, dict) and i.get("type") == "function_call_output"}


@pytest.mark.parametrize("value", [None, "0", "off", "false", "", "early"])
def test_unset_or_not_enabled_the_tool_loop_is_exactly_as_before(value, ev, monkeypatch):
    if value is not None:
        monkeypatch.setenv(EARLY_SYNTHESIS_ENV, value)
    assert not early_synthesis_enabled()
    fake = FakeModel(_route(ev), [_required_turn(ev)], _good_report)
    res = _run(fake)
    assert _kinds(fake) == DEFAULT_PATH and _early(res) == []
    assert res.report.validation["final_passed"]


@pytest.mark.parametrize("value", ["1", "true", "YES", " on "])
def test_the_switch_turns_on_only_with_an_explicit_value(value, monkeypatch):
    monkeypatch.setenv(EARLY_SYNTHESIS_ENV, value)
    assert early_synthesis_enabled()


def test_on_a_clean_turn_goes_straight_to_synthesis_with_every_tool_output(ev, on):
    fake = FakeModel(_route(ev), [_required_turn(ev)], _good_report)
    res = _run(fake)
    assert _kinds(fake) == ["RouteDecision", "tools", "ModelReport"]  # the final no-call turn is not requested
    (early,) = _early(res)
    assert early["turn_calls"] == [n for n, _ in _required_turn(ev)] and early["reason"] == EARLY_SYNTHESIS_REASON
    assert "does not establish that the evidence is sufficient" in early["reason"]
    assert "optional follow-up calls" in early["reason"]
    assert any(t.get("stage") == "early_synthesis" for t in res.report.source_manifest["transcript"])
    issued = {i["call_id"] for i in fake.issued if i.get("type") == "function_call"}
    assert issued and issued <= _outputs_in(fake.requests[-1])  # every tool output reaches synthesis
    assert all(r.status == "ok" for r in res.records if r.origin == "model")
    assert res.report.validation["final_passed"] and res.report.status in ("answered", "answered_with_caveats")


def test_on_a_blocked_call_gets_its_correction_turn_and_only_then_transitions(ev, on):
    """The owner's run of 2026-10-05: a call blocked by its limit (``max_results`` over 20) is corrected in the next
    turn; the transition comes after the correction, never before it."""
    first = [(n, {**a, "max_results": 100} if n == "find_market_events" else a) for n, a in _required_turn(ev)]
    fixed = [(n, a) for n, a in _required_turn(ev) if n == "find_market_events"]
    fake = FakeModel(_route(ev), [first, fixed], _good_report)
    res = _run(fake)
    assert _kinds(fake) == ["RouteDecision", "tools", "tools", "ModelReport"]  # the correction turn, then synthesis
    assert [r.status for r in res.records if r.name == "find_market_events"] == ["blocked", "ok"]
    (early,) = _early(res)
    assert early["turn_calls"] == ["find_market_events"]


def test_on_an_uncorrected_blocked_call_is_a_pending_correction_even_for_an_optional_tool(ev, on):
    """A blocked call the model has not corrected is a correction still pending, even of an optional tool: a later
    clean turn that completes the required tools does not transition, and the model gets its usual further turn."""
    start = parse_iso(ev.window_start_utc)
    wide = ("get_generation_change", {"region": ev.region, "start_utc": iso_utc(start),
                                      "end_utc": iso_utc(start + timedelta(hours=24)), "top_n": 10, "as_of_utc": None})
    turn = [(n, a) for n, a in _required_turn(ev) if n != "retrieve_public_evidence"] + [wide]  # over its 12 h bound
    rest = [(n, a) for n, a in _required_turn(ev) if n == "retrieve_public_evidence"]
    fake = FakeModel(_route(ev), [turn, rest], _good_report)
    res = _run(fake)
    assert [r.status for r in res.records if r.name == "get_generation_change"] == ["blocked"]
    assert _early(res) == [] and _kinds(fake) == ["RouteDecision", "tools", "tools", "tools", "ModelReport"]


def test_on_a_turn_with_any_blocked_call_does_not_transition(ev, on):
    """Every call of the turn must have succeeded: this turn completes the required tools but also repeats a call with
    invalid arguments (blocked), though that tool already succeeded, so the model still gets its usual further turn."""
    turn = [(n, a) for n, a in _required_turn(ev) if n != "retrieve_public_evidence"]
    rest = [(n, a) for n, a in _required_turn(ev) if n == "retrieve_public_evidence"] + [
        ("get_price_timeline", {"region": ev.region})]  # invalid arguments: blocked
    fake = FakeModel(_route(ev), [turn, rest], _good_report)
    res = _run(fake)
    assert [r.status for r in res.records if r.name == "get_price_timeline"] == ["ok", "blocked"]
    assert _early(res) == [] and _kinds(fake) == ["RouteDecision", "tools", "tools", "tools", "ModelReport"]


def test_on_a_failed_call_keeps_the_existing_loop(ev, on, monkeypatch):
    def boom(ctx: Any, args: Any) -> Any:
        raise RuntimeError("SYNTHETIC tool failure")

    monkeypatch.setitem(TOOLS, "get_actual_demand", dataclasses.replace(TOOLS["get_actual_demand"], handler=boom))
    fake = FakeModel(_route(ev), [_required_turn(ev)], _good_report)
    res = _run(fake)
    assert [r.status for r in res.records if r.name == "get_actual_demand"] == ["error"]
    assert _kinds(fake) == DEFAULT_PATH and _early(res) == []


def test_on_a_missing_required_tool_waits_until_the_reminder_is_answered(ev, on):
    """A clean turn that leaves a required tool uncalled does not transition. The model's next turn asks for nothing,
    the controller's reminder follows, and the transition comes once the reminder is answered."""
    turn = [(n, a) for n, a in _required_turn(ev) if n != "retrieve_public_evidence"]
    rest = [(n, a) for n, a in _required_turn(ev) if n == "retrieve_public_evidence"]
    fake = FakeModel(_route(ev), [turn, [], rest], _good_report)
    res = _run(fake)
    assert _kinds(fake) == ["RouteDecision", "tools", "tools", "tools", "ModelReport"]
    assert "Required tools not yet called" in str(fake.requests[3]["input"][-1]["content"])  # the reminder
    (early,) = _early(res)
    assert early["turn_calls"] == ["retrieve_public_evidence"]


def test_on_validation_repair_and_budget_guards_are_unchanged(ev, on):
    def bad(kw: Any) -> dict[str, Any]:
        r = _good_report(kw)
        r["headline"] = r["headline"].replace("peaked at", "peaked at 12,345 MW demand and")  # invented number
        return r

    def patch(kw: Any) -> dict[str, Any]:
        return {"edits": [{"target": "headline", "action": "replace", "text": _good_report(kw)["headline"],
                           "statement": None, "claim": None, "citation": None}],
                "new_numeric_claims": [], "new_citations": []}

    fake = FakeModel(_route(ev), [_required_turn(ev)], bad, repair_fn=patch)
    res = _run(fake)
    assert _kinds(fake) == ["RouteDecision", "tools", "ModelReport", "RepairPatch"]
    v = res.report.validation
    assert v["repair_attempted"] and "NUMERIC_UNTRACKED" in v["pre_repair_codes"] and v["final_passed"]
    rows = [json.loads(x) for x in budget.ledger_path().read_text().splitlines()]
    assert sum(r["kind"] == "reserve" for r in rows) == sum(r["kind"] == "settle" for r in rows) == len(fake.requests)
    assert budget.spent() == pytest.approx(res.usage["cost_usd"], abs=1e-6)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def test_no_frozen_evaluation_runner_can_run_with_the_option_its_freeze_does_not_record():
    """Every frozen evaluation runner refuses to start unless the code's src tree is its frozen one (frozen material is
    never edited here). Each freeze predates this setting; a runner frozen on code that has it must refuse it."""
    current = _git("rev-parse", "HEAD:src")
    freezes = sorted(ROOT.glob("eval/*/FREEZE.json"))
    assert len(freezes) >= 11
    for f in freezes:
        freeze = json.loads(f.read_text())
        runner = next(p for p in (f.parent / "run_eval.py", f.parent / "run_check.py") if p.exists())
        source = runner.read_text()
        assert 'rev-parse", "HEAD:src") != freeze["src_tree"]' in source, f"{runner} does not check its frozen code"
        if freeze["src_tree"] == current:
            assert EARLY_SYNTHESIS_ENV in source, f"{runner} is frozen on code with the option but allows it"
