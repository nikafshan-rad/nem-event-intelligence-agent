"""Issue I-7c (docs/issue-tracker.md): an explanation the validated evidence rules out is shown apart from hypotheses.

W18, second development check (2026-09-30), replayed with its first draft and actual saved repair: the answer passes,
and its possible_explanations[0] is the repair's exclusion ("…so the notice's timing rules it out as an explanation for
the price extreme"), listed with two hedged hypotheses under "Possible explanations".

Now the validator records, for the shown answer, which items are evidence-backed exclusions (I-7b's timing condition)
with no hedge outside the rule-out wording, and the display moves exactly those to `ruled_out_explanations`. Wording
alone, missing timing evidence, mixed statements and fallbacks change nothing. Replays use saved Live records through
the SYNTHETIC fake transport (no network, no key).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from nem_agent.agent.request import InvestigateRequest
from nem_agent.report import Citation, Hypothesis
from nem_agent.service import investigate
from nem_agent.trace import Trace
from nem_agent.validation import validate, validate_and_finalize
from tests.provider.fake_model import FakeModel
from tests.validation.test_ruled_out_explanations import _notice

pytestmark = pytest.mark.synthetic

LIVE = Path(__file__).resolve().parents[2] / "artifacts" / "live"
DEV2, C0930 = LIVE / "live-check-dev2", LIVE / "live-check-p1-dev"
EXCLUSION_END = "so the notice's timing rules it out as an explanation for the price extreme."


def _replay(path: Path, *, delete: str | None = None):
    """A saved run's first draft and actual saved repair (or, with ``delete``, that patch deleting one item)."""
    rec = json.loads(path.read_text())
    trace = json.loads((path.parent / "traces" / f"{rec['score']['trace_id']}.json").read_text())
    draft = next(e for e in trace["events"] if e["name"] == "synthesis:draft")["report"]
    patch = next(e for e in trace["events"] if e["name"] == "repair:scoped")["patch"]
    if delete:
        patch = {**patch, "edits": [e for e in patch["edits"] if not e["target"].startswith(delete)] +
                 [{"target": delete, "action": "delete", "text": None, "statement": None, "claim": None, "citation": None}]}
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    fake = FakeModel(rec["route"], [calls], lambda kw: copy.deepcopy(draft), lambda kw: copy.deepcopy(patch))
    return investigate(InvestigateRequest(question=rec["question"], mode="live"), live_client=fake, write_trace=False)


# ------------------------------------------------------------------------------------------------ W18
@pytest.fixture(scope="module")
def w18():
    return _replay(DEV2 / "W18.json")


def test_w18s_exclusion_is_shown_apart_and_its_hypotheses_stay(w18):
    rep, v = w18.report, w18.report.validation
    assert v["final_passed"] and not v["fallback_applied"]
    assert v["ruled_out_explanations"] == [0]  # the validator's own outcome, recorded on the shown answer
    assert len(rep.ruled_out_explanations) == 1 and rep.ruled_out_explanations[0].statement.endswith(EXCLUSION_END)
    assert "[c1]" in rep.ruled_out_explanations[0].statement  # its citation, which resolves
    assert any(c.citation_id == "c1" and c.chunk_id == "market_notice_144893#0" for c in rep.citations)
    assert [h.statement[:24] for h in rep.possible_explanations] == ["Local supply tightness (", "Observed generator outpu"]
    moved = next(r for r in v["display_rewrites"] if r.get("moved_to"))
    assert moved["where"] == "possible_explanations[0]" and moved["moved_to"] == "ruled_out_explanations[0]"
    assert moved["original"].endswith(EXCLUSION_END)  # the diagnostic record keeps where it was


def test_nothing_is_lost_or_duplicated(w18):
    """The moved hypothesis is the same object: wording, test, evidence IDs; and the three items are all still shown."""
    rec = json.loads((DEV2 / "W18.json").read_text())
    trace = json.loads((DEV2 / "traces" / f"{rec['score']['trace_id']}.json").read_text())
    repaired = next(e for e in trace["events"] if e["name"] == "repair:scoped")["patch"]
    text = next(e["text"] for e in repaired["edits"] if e["target"] == "possible_explanations[0]")
    rep = w18.report
    assert rep.ruled_out_explanations[0].statement == text  # the repair's own wording
    statements = [h.statement for h in rep.possible_explanations] + [h.statement for h in rep.ruled_out_explanations]
    assert len(statements) == len(set(statements)) == 3


# ------------------------------------------------------------------------------------------------ controls
def test_f04s_still_possible_hypothesis_stays():
    rep = _replay(DEV2 / "F04.json").report
    assert rep.ruled_out_explanations == [] and "ruled_out_explanations" not in rep.validation
    assert any("might have reduced NSW1's interconnector capability" in h.statement for h in rep.possible_explanations)


@pytest.fixture(scope="module")
def base():
    """A valid W18 answer to vary: the first check's run, its reliance hypothesis deleted (a scripted repair)."""
    res = _replay(C0930 / "W18.json", delete="possible_explanations[1]")
    assert res.report.validation["final_passed"] and not res.report.validation["fallback_applied"]
    return res


def _finalize(res, statement: str, notices: list = (), **update):
    """The base answer with ``statement`` added as a hypothesis (fixture notices cited as [t<n>]), through the full
    validate-and-finalize step."""
    reg = copy.deepcopy(res.registry)
    for ch in notices:
        reg.add_chunk(ch)
    cites = [Citation(citation_id=f"t{ch.doc_id.rsplit('_', 1)[1]}", chunk_id=ch.chunk_id, doc_id=ch.doc_id, title=ch.title,
                      url=ch.url, doc_type="market_notice", quote=ch.text[:60], supports="test fixture") for ch in notices]
    hyp = Hypothesis(statement=statement, supporting_evidence_ids=[], what_would_test_it="Check the constraint logs.")
    clean = {k: v for k, v in res.report.validation.items() if k in ("repair_attempted",)}
    rep = res.report.model_copy(update={"possible_explanations": [*res.report.possible_explanations, hyp],
                                        "citations": [*res.report.citations, *cites], "validation": clean,
                                        "ruled_out_explanations": [], **update})
    return validate_and_finalize(rep, reg, res.records, res.resolution, Trace())


def test_a_pure_exclusion_the_timing_backs_is_moved(base):
    out = _finalize(base, "The Hazelwood bus-tie outage [c1] is ruled out by its timing: the notice gives 2026-08-20 "
                          "11:00 AEST (2026-08-20T01:00:00Z), after every interval.")
    assert out.validation["final_passed"] and not out.validation["fallback_applied"]
    assert [h.statement[:40] for h in out.ruled_out_explanations] == ["The Hazelwood bus-tie outage [c1] is rul"]
    assert len(out.possible_explanations) == len(base.report.possible_explanations)


@pytest.mark.parametrize("statement,notices,why", [
    ("The outage in the notice [t812] may be ruled out by its timing.",
     [_notice(812, "At 0925 hrs 20/08/2026 there was a short notice outage of a 220 kV line in the VIC region.")],
     "uncertain timing: a notice within the event"),
    ("The outage in the notice [t813] may be ruled out by its timing.",
     [_notice(813, "A short notice outage of a 220 kV line in the VIC region, time to be advised.")],
     "uncertain timing: no stated time"),
    ("Timing rules out the Hazelwood outage [c1]; rebidding by marginal units may have raised the price.", [],
     "a mixed statement: an exclusion and an open hypothesis"),
    ("The Hazelwood notice [c1] might not correspond to the 09:10 AEST price spike.", [],
     "negation without the timing outcome"),
    ("Rebidding by marginal units may have raised the price.", [], "an unrelated hypothesis"),
])
def test_ambiguous_or_unbacked_items_stay_with_the_hypotheses(base, statement, notices, why):
    out = _finalize(base, statement, notices)
    assert out.validation["final_passed"] and not out.validation["fallback_applied"], why
    assert out.ruled_out_explanations == [] and "ruled_out_explanations" not in out.validation, why
    assert out.possible_explanations[-1].statement == statement, why


def test_a_fallback_moves_nothing(base):
    """An exclusion beside a violation: the answer falls back, and nothing is recorded or shown as ruled out."""
    out = _finalize(base, "The Hazelwood bus-tie outage [c1] is ruled out by its timing.",
                    summary=[*base.report.summary, "VIC1 also reached 999.0 $/MWh."])
    assert out.validation["fallback_applied"] and out.ruled_out_explanations == []
    assert "ruled_out_explanations" not in out.validation


def test_w18_first_check_actual_repair_falls_back_with_nothing_ruled_out():
    rep = _replay(C0930 / "W18.json").report
    assert rep.validation["fallback_applied"] and rep.ruled_out_explanations == [] and rep.possible_explanations == []


# ------------------------------------------------------------------------------------------------ validation, scoring
def test_validation_codes_are_unchanged_by_recording_the_outcome(w18):
    """The record is additive: the validator's codes for the shown answer are the same with or without it."""
    rep = w18.report.model_copy(update={"possible_explanations": [*w18.report.ruled_out_explanations,
                                                                  *w18.report.possible_explanations],
                                        "ruled_out_explanations": []})
    res = validate(rep, w18.registry, records=w18.records)
    assert not res.critical and res.ruled_out == [0]


def test_only_market_event_answers_can_have_exclusions(base):
    """Hypotheses reach scoring only in the synthetic-injection document case; the timing check that backs an
    exclusion runs only for market-event answers, so a document answer never has one."""
    rep = base.report.model_copy(update={"intent": "source_explanation", "possible_explanations": [
        Hypothesis(statement="The Hazelwood bus-tie outage [c1] is ruled out by its timing.", supporting_evidence_ids=[],
                   what_would_test_it="-")]})
    assert validate(rep, base.registry, records=base.records).ruled_out == []
