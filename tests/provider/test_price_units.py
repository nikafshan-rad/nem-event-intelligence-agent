"""Issue I-3e (docs/issue-tracker.md): a price shown as "$845.0" gets its "/MWh" from its validated evidence.

Live, second development check (2026-09-30), W19: "… RRP spike of $845.0 at …", "Regional Reference Price $845.0 at …"
and "the analysis threshold of $300.0 in the window". The validated claims behind them are 845.0 and 300.0 `$/MWh`,
but nothing checked or completed the unit as the text writes it.

Now, after validation and outside quotations, a currency amount with no rate is completed from its evidence's own unit,
when every claim matching the amount cites evidence with one and the same "$/…" unit. No unit is taken from the dollar
sign, the question or another value. Replays use saved Live records through the SYNTHETIC fake transport (no network,
no key).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from nem_agent.agent.request import InvestigateRequest
from nem_agent.report import NumericClaim
from nem_agent.service import investigate
from nem_agent.validation import narrative_numbers
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

DEV2 = Path(__file__).resolve().parents[2] / "artifacts" / "live" / "live-check-dev2"
CLAIMS = [(845.0, 0.0, "$/MWh"), (300.0, 0.0, "$/MWh"), (26.0, 0.0, "intervals"), (1964.83, 0.01, "MW"),
          (-504.6525, 0.0, "$/MWh"), (4500.0, 0.0, "$")]


def complete_rates(text: str, claims=CLAIMS) -> str:
    from nem_agent.display import complete_rates as complete

    return complete(text, claims)


def plain_display(report, registry):
    from nem_agent.display import plain_display as display

    return display(report, registry)


def _replay(path: Path, summary_update=None):
    """A saved run's first draft and actual saved repair through the fake transport."""
    rec = json.loads(path.read_text())
    trace = json.loads((path.parent / "traces" / f"{rec['score']['trace_id']}.json").read_text())
    draft = next(e for e in trace["events"] if e["name"] == "synthesis:draft")["report"]
    patch = next(e for e in trace["events"] if e["name"] == "repair:scoped")["patch"]
    if summary_update:
        draft = {**draft, "summary": summary_update(draft["summary"])}
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    fake = FakeModel(rec["route"], [calls], lambda kw: copy.deepcopy(draft), lambda kw: copy.deepcopy(patch))
    return investigate(InvestigateRequest(question=rec["question"], mode="live"), live_client=fake, write_trace=False)


@pytest.fixture(scope="module")
def w19():
    return _replay(DEV2 / "W19.json")


# ------------------------------------------------------------------------------------------------ the saved example
def test_w19s_prices_are_shown_with_their_evidence_unit(w19):
    rep, v = w19.report, w19.report.validation
    assert v["final_passed"] and not v["fallback_applied"]  # validation as before
    assert "RRP spike of $845.0/MWh at 2026-07-29 17:25 ACST" in rep.headline
    assert any(s.startswith("The price extreme: Regional Reference Price $845.0/MWh at interval ending") for s in rep.summary)
    assert any("analysis threshold of $300.0/MWh in the window" in s for s in rep.summary)
    assert any("$845.0 at" in r["original"] for r in v["display_rewrites"] if r["where"] == "headline")  # kept
    units = {c.value: w19.registry.get(c.evidence_id).unit for c in rep.numeric_claims}
    assert units[845.0] == units[300.0] == "$/MWh"  # the evidence the units come from


def test_the_live_record_is_unchanged():
    rec = json.loads((DEV2 / "W19.json").read_text())
    assert "spike of $845.0 at" in rec["report"]["headline"]


# ------------------------------------------------------------------------------------------------ the rule
@pytest.mark.parametrize("before,after", [
    ("SA1 had a single five-minute RRP spike of $845.0 at 17:25 ACST.", "SA1 had a single five-minute RRP spike of $845.0/MWh at 17:25 ACST."),
    ("The minimum was −$504.6525 at 21:20.", "The minimum was −$504.6525/MWh at 21:20."),
    ("The minimum was $-504.6525.", "The minimum was $-504.6525/MWh."),
    ("RRP $845.0 [c1] and 1964.83 MW.", "RRP $845.0/MWh [c1] and 1964.83 MW."),  # a citation stays where it is
])
def test_an_amount_linked_to_rate_evidence_is_completed(before, after):
    assert complete_rates(before) == after


@pytest.mark.parametrize("text", [
    "RRP was $845.0/MWh.", "RRP was 845.0 $/MWh.", "RRP was $845 per MWh.",  # already complete
    "The project analysis threshold is $300.0 ($/MWh); 26 intervals met it.",  # held-out v4 W19: unit in brackets
    "a $1.5 million cost", "costs of $4,500 in FCAS", "a payment of $4500.",  # money that is not a rate
    "$1964.83 of demand", "$26 intervals",  # evidence in other units: never a "$/…" from the dollar sign
    "$999.0 was paid",  # no matching claim
    "The notice says “prices reached $845” [c1].",  # a quotation
])
def test_complete_units_money_and_quotations_are_unchanged(text):
    assert complete_rates(text) == text


def test_ambiguous_or_missing_evidence_gives_no_unit():
    assert complete_rates("a threshold of $300.0", [(300.0, 0.0, "$/MWh"), (300.0, 0.0, "MW")]) == "a threshold of $300.0"
    assert complete_rates("a threshold of $300.0", [(300.0, 0.0, None)]) == "a threshold of $300.0"
    assert complete_rates("a threshold of $300.0", []) == "a threshold of $300.0"


def test_each_amount_takes_only_its_own_evidence():
    assert complete_rates("Prices of $845.0, $1964.83 and $26.") == "Prices of $845.0/MWh, $1964.83 and $26."


def test_no_number_is_added_or_removed():
    for t in ("SA1 had a single five-minute RRP spike of $845.0 at 17:25 ACST.", "The minimum was −$504.6525 at 21:20."):
        assert narrative_numbers(complete_rates(t)) == narrative_numbers(t)


# ------------------------------------------------------------------------------------------------ the evidence
def test_the_unit_comes_from_the_evidence_not_the_claim(w19):
    """A claim calling 845.0 "$/MWh" while citing evidence in MW would not validate; even so, the display reads the
    evidence's unit, so nothing is completed."""
    mw = next(ev for ev in w19.registry.items.values() if ev.unit == "MW")
    rep = w19.report.model_copy(update={
        "headline": "RRP spike of $845.0 at 17:25 ACST.",
        "numeric_claims": [NumericClaim(claim_id="x", text="RRP", value=845.0, unit="$/MWh", evidence_id=mw.evidence_id)]})
    assert plain_display(rep, w19.registry)[0].headline == "RRP spike of $845.0 at 17:25 ACST."


def test_the_question_and_an_unvalidated_answer_give_no_unit(w19):
    asked = w19.report.model_copy(update={"question": "Was SA's $845/MWh price driven by reserves?", "numeric_claims": [],
                                          "headline": "RRP spike of $845.0 at 17:25 ACST."})
    assert plain_display(asked, w19.registry)[0].headline == "RRP spike of $845.0 at 17:25 ACST."
    unvalidated = w19.report.model_copy(update={"headline": "RRP spike of $845.0 at 17:25 ACST.",
                                                "validation": {**w19.report.validation, "final_passed": False}})
    assert plain_display(unvalidated, w19.registry)[0].headline == "RRP spike of $845.0 at 17:25 ACST."
    assert plain_display(w19.report.model_copy(update={"headline": "RRP spike of $845.0 at 17:25 ACST."}), None)[0] \
        .headline == "RRP spike of $845.0 at 17:25 ACST."  # no registry, no unit


# ------------------------------------------------------------------------------------------------ validation first
def test_an_unsupported_amount_still_fails_validation():
    """Validation reads the answer as written: an unsupported "$999.0" is NUMERIC_UNTRACKED, the scripted repair repeats
    it, and the answer falls back without showing it."""
    res = _replay(DEV2 / "W19.json", summary_update=lambda s: [*s, "SA1's price later reached $999.0 at 18:00 ACST."])
    v = res.report.validation
    assert "NUMERIC_UNTRACKED" in set(v.get("pre_repair_codes") or [])
    shown = [res.report.headline, *res.report.summary, *res.report.uncertainties]
    assert not any("999" in t for t in shown)
