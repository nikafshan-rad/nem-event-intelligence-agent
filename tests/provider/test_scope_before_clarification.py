"""Issue I-13 (docs/issue-tracker.md): a question the routing model judged out of scope is refused, even when it also
lacks a region or date.

Held-out v5 Y17 (Live, 2026-10-02): "Given how South Australian prices spiked in late July 2026, what price should I
expect in SA next Wednesday evening, and should I offer my battery's output into that peak?" The routing model marked it
out of scope and missing a date. route_policy returns the 'refused' override, but investigate applied routing overrides
only when the resolver could run the question; the resolver found no date, so its date question was shown instead of a
refusal.

Now scope comes before missing details, as in the resolver. What counts as out of scope is unchanged, and a question
the model did not judge out of scope keeps its clarification. Replays use saved Live routing decisions and scripted ones
through the SYNTHETIC fake transport (no network, no key).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from nem_agent.agent.request import InvestigateRequest
from nem_agent.service import investigate
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

LIVE = Path(__file__).resolve().parents[2] / "artifacts" / "live"
Y17 = json.loads((LIVE / "L3-holdout-v5" / "Y17.json").read_text())
ROUTING_REFUSAL = "Refused: The question was judged out of scope or ambiguous."
RESOLVER_REFUSAL = ("Refused: Out of scope: this is a read-only research assistant. It does not trade, bid, control "
                    "assets or forecast future prices.")


def _decision(**kw) -> dict:
    base = {"intent": "market_event_review", "region": "SA1", "event_date": None, "as_of_utc": None,
            "needs_clarification": False, "clarification_reason": None, "clarification": None, "out_of_scope": False}
    return {**base, **kw}


def _ask(question: str, decision: dict):
    fake = FakeModel(decision, [], lambda kw: {})
    return investigate(InvestigateRequest(question=question, mode="live"), live_client=fake, write_trace=False)


def _saved(path: Path):
    rec = json.loads(path.read_text())
    return rec, _ask(rec["question"], rec["route"])


def _shown(rep) -> str:
    return " ".join([rep.headline] + rep.summary + rep.uncertainties + rep.missing_evidence)


# ------------------------------------------------------------------------------------------------ Y17
def test_y17_is_refused():
    res = _ask(Y17["question"], Y17["route"])
    rep = res.report
    assert rep.status == "refused" and rep.headline == ROUTING_REFUSAL
    assert res.records == [] and res.usage["model_calls"] == 1  # the routing call only; no tool ran
    shown = _shown(rep)
    assert "?" not in shown and "date" not in shown.lower()  # no clarification question
    assert "$" not in shown and "MWh" not in shown and not rep.observations and not rep.numeric_claims  # no price
    assert not rep.summary and not rep.possible_explanations  # no bidding advice, nothing else


def test_on_main_y17_was_asked_for_a_date():
    """The saved Live answer: the resolver's date question, status needs_clarification."""
    assert Y17["route"]["out_of_scope"] and Y17["route"]["needs_clarification"]
    assert Y17["report"]["status"] == "needs_clarification"
    assert Y17["report"]["headline"] == "Clarification needed: Which date (or UTC window) should be investigated?"


# ------------------------------------------------------------------------------------------------ refused
def test_out_of_scope_without_a_date_is_refused_with_the_models_note_when_it_asked_nothing():
    q = "What price should I expect in South Australia next week?"
    rep = _ask(q, _decision(out_of_scope=True)).report
    assert rep.status == "refused" and rep.headline == ROUTING_REFUSAL
    note = "Predicting future prices is out of scope; I can review past South Australian price events instead."
    rep = _ask(q, _decision(out_of_scope=True, clarification=note)).report
    assert rep.status == "refused" and rep.headline == f"Refused: {note}"


@pytest.mark.parametrize("case", ["L3-holdout-v3/V17", "L3-holdout-v4/W17", "L3-regression/AMB05", "L3-run3/AMB05"])
def test_earlier_refusals_are_unchanged(case):
    """V17 and AMB05 are refused by the resolver's own scope guard ("buy", "sell"), with its reason; W17 by the routing
    decision on a question the resolver could run. Each shows the same headline as its saved Live answer. (The two
    earliest AMB05 decisions predate the clarification_reason field and replay as invalid routing output, on main too.)"""
    rec, res = _saved(LIVE / f"{case}.json")
    assert res.report.status == "refused" == rec["report"]["status"]
    assert res.report.headline == rec["report"]["headline"] or (  # W17's saved headline predates I-4c's plain wording
        case.endswith("W17") and res.report.headline == ROUTING_REFUSAL)
    if case.endswith(("V17", "AMB05")):
        assert res.report.headline == RESOLVER_REFUSAL


# ------------------------------------------------------------------------------------------------ clarification
@pytest.mark.parametrize("question,decision,asked", [
    ("What happened to South Australian prices in late July 2026?",
     _decision(needs_clarification=True, clarification_reason="missing_region_or_date",
               clarification="Which date in late July 2026?"), "Which date"),
    ("How did batteries offer into South Australia's price spike in late July 2026?",
     _decision(needs_clarification=True, clarification_reason="missing_region_or_date"), "Which date"),
    ("What happened to prices in SA and VIC on 2026-07-31?",
     _decision(region=None, event_date="2026-07-31", needs_clarification=True, clarification_reason="several_regions",
               clarification="Which region?"), "Several regions"),
])
def test_an_in_scope_question_missing_information_is_asked_not_refused(question, decision, asked):
    rep = _ask(question, decision).report
    assert rep.status == "needs_clarification" and asked in rep.headline


def test_the_scope_decision_alone_makes_the_difference():
    """The same date-less question: refused only when the routing model judged it out of scope."""
    q = "Given how South Australian prices spiked in late July 2026, what should I expect next Wednesday evening?"
    asked = _decision(needs_clarification=True, clarification_reason="missing_region_or_date")
    assert _ask(q, asked).report.status == "needs_clarification"
    assert _ask(q, {**asked, "out_of_scope": True}).report.status == "refused"


def test_the_saved_two_region_question_is_still_asked():
    rec, res = _saved(LIVE / "L3-fresh" / "AMB01.json")
    assert not rec["route"]["out_of_scope"]
    assert res.report.status == "needs_clarification" == rec["report"]["status"]


# ------------------------------------------------------------------------------------------------ answered
def test_an_answerable_question_proceeds():
    """W19 (second development check): region and date, not out of scope; its saved tool calls and drafts run and it is
    answered."""
    rec = json.loads((LIVE / "live-check-dev2" / "W19.json").read_text())
    trace = json.loads((LIVE / "live-check-dev2" / "traces" / f"{rec['score']['trace_id']}.json").read_text())["events"]
    patch = next((e.get("patch") for e in trace if e["name"] == "repair:scoped"), None)
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    assert not rec["route"]["out_of_scope"] and rec["route"]["event_date"]
    fake = FakeModel(rec["route"], [calls], lambda kw: copy.deepcopy(rec["drafts"]["synthesis:draft"]),
                     (lambda kw: copy.deepcopy(patch)) if patch else None)
    res = investigate(InvestigateRequest(question=rec["question"], mode="live"), live_client=fake, write_trace=False)
    assert res.report.status in ("answered", "answered_with_caveats") and res.records
