"""D33: the reasoning effort of routing calls only, opt-in (``NEM_AGENT_ROUTE_REASONING_EFFORT``). SYNTHETIC fake clients
only: no request leaves the process, and nothing is charged.

- unset, the routing request is exactly as before (no reasoning parameter);
- each supported value is sent on routing calls (a question's routing call and a reply the routing model reads), and
  nothing else in the request changes;
- an unsupported value is refused before any reservation or call;
- tool, synthesis and repair calls never send it;
- the requested and reported efforts are recorded in the trace;
- no frozen evaluation runner can send an effort its freeze does not record.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from nem_agent.agent import confirm as C
from nem_agent.agent.diagnostics import NOT_REPORTED, NOT_SENT
from nem_agent.agent.live import ROUTE_REASONING_EFFORT_ENV, ROUTE_REASONING_EFFORTS
from nem_agent.agent.request import InvestigateRequest
from nem_agent.service import interpret_request, investigate
from nem_agent.trace import Trace
from tests.provider.fake_model import FakeModel
from tests.provider.test_live_loop import _good_report, _required_turn, _route

pytestmark = pytest.mark.synthetic
ROOT = Path(__file__).resolve().parents[2]
QUESTION = "What was the highest operational demand in Queensland?"
PLAN = {"intent": "market_event_review", "region": "QLD1", "event_date": None, "needs_clarification": False,
        "clarification_reason": None, "clarification": None, "out_of_scope": False,
        "plan": {"operations": [{"id": "o1", "stance": "asked", "kind": "demand_maximum", "subject": "operational_demand",
                                 "subject_text": "operational demand",
                                 "operation_text": "What was the highest operational demand in Queensland",
                                 "scope_ref": None, "run_ref": None, "cutoff_ref": None}],
                 "scopes": [], "runs": [], "cutoffs": [], "cutoff_ref": None}}


class Recording:
    """SYNTHETIC routing model: returns a scripted plan decision, reports ``reported`` as its reasoning effort (when
    given), and records every request."""

    def __init__(self, reported: str | None = None) -> None:
        self.reported, self.requests = reported, []

    def create(self, **kw: Any) -> dict[str, Any]:
        self.requests.append(copy.deepcopy(kw))
        resp: dict[str, Any] = {
            "id": f"resp_{len(self.requests)}", "status": "completed", "model": kw["model"],
            "max_output_tokens": kw["max_output_tokens"], "usage": {"input_tokens": 2800, "output_tokens": 400},
            "output": [{"type": "message", "role": "assistant",
                        "content": [{"type": "output_text", "text": json.dumps(PLAN)}]}]}
        if self.reported:
            resp["reasoning"] = {"effort": self.reported}
        return resp


def _ledger() -> str:
    p = Path(os.environ["NEM_AGENT_BUDGET_LEDGER"])  # the test's own scratch ledger (conftest)
    return p.read_text() if p.exists() else ""


def test_unset_the_routing_request_is_exactly_as_before():
    assert ROUTE_REASONING_EFFORT_ENV not in os.environ  # cleared for every test (conftest)
    fake = Recording()
    interpret_request(QUESTION, live_client=fake, write_trace=False)
    (req,) = fake.requests
    assert set(req) == {"model", "store", "max_output_tokens", "instructions", "input", "text"}  # no reasoning
    assert (req["model"], req["store"], req["max_output_tokens"]) == ("gpt-5-mini", False, 2000)


@pytest.mark.parametrize("effort", ROUTE_REASONING_EFFORTS)
def test_a_supported_effort_is_sent_on_the_routing_call_and_nothing_else_changes(effort, monkeypatch):
    before = Recording()
    interpret_request(QUESTION, live_client=before, write_trace=False)
    monkeypatch.setenv(ROUTE_REASONING_EFFORT_ENV, effort)
    after = Recording()
    interpret_request(QUESTION, live_client=after, write_trace=False)
    (req,) = after.requests
    assert req.pop("reasoning") == {"effort": effort}
    assert req == before.requests[0]  # the model, the output cap, the prompt and the schema are unchanged


@pytest.mark.parametrize("value", ["", "LOW", " low", "low ", "turbo", "none", "xhigh"])
def test_an_unsupported_effort_is_refused_before_any_reservation_or_call(value, monkeypatch):
    monkeypatch.setenv(ROUTE_REASONING_EFFORT_ENV, value)
    fake = Recording()
    with pytest.raises(ValueError, match="is not supported"):
        interpret_request(QUESTION, live_client=fake, write_trace=False)
    assert fake.requests == [] and _ledger() == ""  # nothing sent, nothing reserved


def test_a_reply_the_routing_model_reads_sends_the_same_effort(selection, monkeypatch):
    monkeypatch.setenv(ROUTE_REASONING_EFFORT_ENV, "low")
    fake = Recording()
    state = C.new_state()

    def read(text: str) -> Any:
        return interpret_request(text, live_client=fake, write_trace=False)

    C.start(state, QUESTION, read)
    assert C.reply(state, "SYNTHETIC: an answer no parser reads", selection, read)  # read by the routing model
    assert [r["reasoning"] for r in fake.requests] == [{"effort": "low"}, {"effort": "low"}]


def test_the_requested_and_reported_efforts_are_recorded(monkeypatch):
    written: list[Trace] = []
    monkeypatch.setattr(Trace, "write", lambda self, directory=None: written.append(self))  # no file is written
    interpret_request(QUESTION, live_client=Recording(), write_trace=True)
    monkeypatch.setenv(ROUTE_REASONING_EFFORT_ENV, "low")
    interpret_request(QUESTION, live_client=Recording(reported="low"), write_trace=True)
    unset, low = (next(e for e in t.events if e["kind"] == "model" and e["name"] == "route") for t in written)
    assert (unset["requested"]["reasoning_effort"], unset["reported"]["reasoning_effort"]) == (NOT_SENT, NOT_REPORTED)
    assert (low["requested"]["reasoning_effort"], low["reported"]["reasoning_effort"]) == ("low", "low")
    assert low["requested"]["max_output_tokens"] == unset["requested"]["max_output_tokens"] == 2000


def test_only_routing_calls_send_it_never_tools_synthesis_or_repair(selection, monkeypatch):
    """A whole Live investigation with a validator-driven repair: route, tool turns, synthesis and repair. Only the
    routing call carries the effort, and the trace records it as requested there only."""
    monkeypatch.setenv(ROUTE_REASONING_EFFORT_ENV, "low")
    ev = selection.primary

    def bad(kw: Any) -> dict[str, Any]:
        r = _good_report(kw)
        r["headline"] = r["headline"].replace("peaked at", "peaked at 12,345 MW demand and")  # invented: repaired
        return r

    def patch(kw: Any) -> dict[str, Any]:
        return {"edits": [{"target": "headline", "action": "replace", "text": _good_report(kw)["headline"],
                           "statement": None, "claim": None, "citation": None}],
                "new_numeric_claims": [], "new_citations": []}

    fake = FakeModel(_route(ev), [_required_turn(ev)], bad, repair_fn=patch)
    res = investigate(InvestigateRequest(question="What happened around the SA1 price spike on 2026-07-31?", mode="live"),
                      live_client=fake, write_trace=False)
    assert res.report.validation["repair_attempted"] is True
    kind = [((kw.get("text") or {}).get("format") or {}).get("name") or "tools" for kw in fake.requests]
    assert {"RouteDecision", "tools", "ModelReport", "RepairPatch"} <= set(kind)
    assert [(k, kw["reasoning"]) for k, kw in zip(kind, fake.requests, strict=True) if "reasoning" in kw] == [
        ("RouteDecision", {"effort": "low"})]
    stages = [e for e in res.trace.events if e["kind"] == "model" and "requested" in e]
    assert {e["name"] for e in stages} >= {"route", "tools", "synthesis", "repair"}
    assert all((e["requested"]["reasoning_effort"] == "low") == (e["name"] == "route") for e in stages)
    assert all(e["requested"]["reasoning_effort"] == NOT_SENT for e in stages if e["name"] != "route")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def test_no_frozen_evaluation_runner_can_send_an_effort_its_freeze_does_not_record():
    """Every frozen evaluation runner refuses to start unless the code's src tree is its frozen one (frozen material is
    never edited here). Each freeze predates this setting, so with this code every one refuses before any call; at its
    own frozen commit the setting does not exist, so its frozen configuration (no effort sent) holds. A runner frozen
    on code that has the setting must list it among the overrides it refuses."""
    current = _git("rev-parse", "HEAD:src")
    freezes = sorted(ROOT.glob("eval/*/FREEZE.json"))
    assert len(freezes) >= 11
    for f in freezes:
        freeze = json.loads(f.read_text())
        runner = next(p for p in (f.parent / "run_eval.py", f.parent / "run_check.py") if p.exists())
        source = runner.read_text()
        assert 'rev-parse", "HEAD:src") != freeze["src_tree"]' in source, f"{runner} does not check its frozen code"
        if freeze["src_tree"] == current:
            assert ROUTE_REASONING_EFFORT_ENV in source, f"{runner} is frozen on code with the setting but allows it"
