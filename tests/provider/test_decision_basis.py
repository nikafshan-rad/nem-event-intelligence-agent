"""Issue I-12 (docs/issue-tracker.md): a document answer that quotes AEMO's decision from a market notice also shows
the assessment that notice gives for it.

Held-out v5 Y14 (Live, 2026-10-02): "Was there an AEMO market notice about an unplanned Victorian network trip dated
2026-07-28, and what was AEMO's decision on reclassifying it?" The answer quoted notice 144667's decision, "AEMO will not
reclassify this event as a credible contingency event.", but not the sentence before it, "The cause of this non credible
contingency event has been identified and AEMO is satisfied that another occurrence of this event is unlikely under the
current circumstances." The check's two elements, cause identified and recurrence unlikely, were missing. Retrieval had
the whole notice; the model's selection of statements left the assessment out.

Now the controller shows that assessment, quoted from the same notice with the same citation, just before the quoted
decision. Nothing is written or inferred: no assessment in the notice, nothing added. Replays use saved Live records and
scripted drafts through the SYNTHETIC fake transport (no network, no key).
"""

from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path

import pytest

from nem_agent.agent.live import decision_basis
from nem_agent.agent.request import InvestigateRequest
from nem_agent.service import investigate
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "artifacts" / "live"
Y14 = json.loads((LIVE / "L3-holdout-v5" / "Y14.json").read_text())
_DB = sqlite3.connect(ROOT / "data" / "index" / "corpus.sqlite")
NOTICE = {cid: text for cid, text in _DB.execute("select chunk_id, text from chunks where doc_type='market_notice'")}

MOORABOOL = "market_notice_144667#0"
TRIP = "At 1729 hrs the Moorabool No. 2 220 kV Bus tripped."
NO_SHEDDING = "AEMO did not instruct load shedding."
NO_BULK = "AEMO has not been advised of any disconnection of bulk electrical load."
ASSESSMENT = ("The cause of this non credible contingency event has been identified and AEMO is satisfied that another "
              "occurrence of this event is unlikely under the current circumstances.")
DECISION = "AEMO will not reclassify this event as a credible contingency event."


def _events(res) -> list[dict]:
    return res.trace.as_dict()["events"]


def _shown(rep) -> str:
    return " ".join([rep.headline] + rep.summary + [f.statement for f in rep.published_findings])


def _y14_parts():
    trace = json.loads((LIVE / "L3-holdout-v5" / "traces" / f"{Y14['score']['trace_id']}.json").read_text())["events"]
    patch = next(e["patch"] for e in trace if e["name"] == "repair:scoped")
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in Y14["tools"]
             if not str(t["call_id"]).startswith("controller_")]
    return calls, Y14["drafts"]["synthesis:draft"], patch


def _run(question: str, route: dict, calls: list, draft: dict, patch: dict | None = None):
    fake = FakeModel(route, [calls], lambda kw: copy.deepcopy(draft), (lambda kw: copy.deepcopy(patch)) if patch else None)
    return investigate(InvestigateRequest(question=question, mode="live"), live_client=fake, write_trace=False)


def _doc_draft(statements: list[tuple[str, str]], headline: str, status: str = "answered",
               missing: list[str] | None = None, finding: str | None = None) -> dict:
    """A document answer quoting each (chunk_id, sentence); one citation per passage, cited by its passage ID."""
    first: dict[str, str] = {}
    for cid, quote in statements:
        first.setdefault(cid, quote)
    return {"status": status, "headline": headline, "summary": [],
            "document_statements": [{"citation_id": cid, "quote": q, "paraphrase": None} for cid, q in statements],
            "observation_evidence_ids": [], "numeric_claims": [], "possible_explanations": [],
            "published_findings": [{"citation_id": finding, "applies_to_event": True}] if finding else [],
            "citations": [{"citation_id": cid, "chunk_id": cid, "quote": q, "supports": "what the notice says"}
                          for cid, q in first.items()],
            "uncertainties": [], "missing_evidence": missing or [], "forecast_mae_evidence_id": None}


def _route(region: str, day: str) -> dict:
    return {"intent": "source_explanation", "region": region, "event_date": day, "as_of_utc": None,
            "needs_clarification": False, "clarification_reason": None, "clarification": None, "out_of_scope": False}


def _notices(region: str, start: str, end: str) -> list:
    return [("retrieve_public_evidence", {"query": "market notice", "region": region, "event_start_utc": start,
                                          "event_end_utc": end, "as_of_utc": None, "doc_types": ["market_notice"],
                                          "top_k": 8})]


def _passed(rep) -> bool:
    return rep.validation["final_passed"] and not rep.validation["fallback_applied"]


# ------------------------------------------------------------------------------------------------ Y14
@pytest.fixture(scope="module")
def y14():
    calls, draft, patch = _y14_parts()
    return _run(Y14["question"], Y14["route"], calls, draft, patch)


def test_y14_shows_the_assessment_just_before_the_decision(y14):
    rep = y14.report
    assert _passed(rep), rep.validation["initial"]["violations"]
    assert rep.summary == [f"“{TRIP}” [c1] (Notice times are NEM market time, UTC+10.)", f"“{NO_SHEDDING}” [c1]",
                           f"“{ASSESSMENT}” [c1]", f"“{DECISION}” [c1]"]
    assert rep.headline == f"“{DECISION}” [c1]"  # still the model's statement, the decision
    assert {e["text"] for e in _events(y14) if e["name"] == "decision_basis"} == {ASSESSMENT}  # draft and repair


def test_y14_has_every_element_the_check_names(y14):
    """Frozen check: notice 144667; the trip at 1729 hrs (market time); cause identified; recurrence unlikely; not
    reclassified."""
    rep, shown = y14.report, _shown(y14.report)
    assert [c.doc_id for c in rep.citations] == ["market_notice_144667"]
    for element in (TRIP, "(Notice times are NEM market time, UTC+10.)", "has been identified",
                    "another occurrence of this event is unlikely", DECISION):
        assert element in shown, element


def test_the_headline_is_still_one_of_the_models_statements():
    """A model headline in the assessment's words (it shares all of them with the added line, and a fifth with the
    decision) still gets one of the model's own statements as the shown headline, not the line the controller added."""
    calls, draft, _ = _y14_parts()
    d = {**copy.deepcopy(draft), "headline": "AEMO is satisfied that another occurrence of the event is unlikely."}
    rep = _run(Y14["question"], Y14["route"], calls, d).report
    assert f"“{ASSESSMENT}” [c1]" in rep.summary
    assert rep.headline == f"“{DECISION}” [c1]"


def test_on_main_y14_answer_lacked_the_assessment():
    """The saved Live answer (and its replay on main): the decision without its assessment."""
    assert ASSESSMENT not in " ".join([Y14["report"]["headline"]] + Y14["report"]["summary"])
    assert DECISION in " ".join(Y14["report"]["summary"])


# ------------------------------------------------------------------------------------------------ the rule, on notices
@pytest.mark.parametrize("chunk,quote,basis", [
    (MOORABOOL, DECISION, ASSESSMENT),
    (MOORABOOL, "will not reclassify this event", ASSESSMENT),  # part of the decision sentence
    ("market_notice_144813#0", DECISION, ASSESSMENT.replace("non credible", "non-credible")),  # Braemar update
    ("market_notice_144651#0",  # "therefore"; the assessment shares a sentence with the title, and starts at "Based on"
     "AEMO has therefore cancelled the reclassification of this event as a credible contingency event.",
     "Based on the information provided by the participant, AEMO is satisfied that this non credible event is unlikely "
     "to re-occur."),
    ("market_notice_144775#0", "Accordingly AEMO has reclassified it as a credible contingency event.",
     "Based on advice from the participant, AEMO considers the simultaneous trip of the following elements to now be "
     "more likely and reasonably possible."),
    ("market_notice_144892#0",  # "Accordingly", two sentences after the assessment
     "Accordingly its classification has reverted to a non-credible contingency event.",
     "AEMO considers the simultaneous trip of the following circuits is no longer reasonably possible. There is no "
     "longer any lightning activity in the vicinity of the following lines."),
    # no assessment before the quoted sentence: nothing
    (MOORABOOL, TRIP, None),
    (MOORABOOL, NO_SHEDDING, None),
    (MOORABOOL, ASSESSMENT, None),
    ("market_notice_144692#0", "The cause of this non credible contingency event is not known at this stage.", None),
    ("market_notice_144652#0",  # a reserve-level declaration: a decision with no stated assessment
     "AEMO declares a Forecast LOR1 condition under clause 4.8.4(b) of the National Electricity Rules for the SA region",
     None),
    ("market_notice_144692#0", "Manager NEM Real Time Operations", None),  # a sign-off follows from nothing
])
def test_decision_basis_on_notices(chunk, quote, basis):
    assert decision_basis(quote, NOTICE[chunk], [quote]) == basis


def test_only_the_seven_decision_notices_have_a_basis():
    """Every sentence of every market notice in the corpus, quoted alone: only the notices that state a decision after
    an assessment give one (144892 twice: its decision, and the supporting sentence between)."""
    from nem_agent.agent.live import _SENTENCE_GAP_RE
    from nem_agent.validation import _norm

    fired = [cid for cid, text in NOTICE.items() for s in _SENTENCE_GAP_RE.split(_norm(text))
             if decision_basis(s, text, [s])]
    assert sorted(fired) == sorted(f"market_notice_{n}#0" for n in
                                   (144651, 144667, 144775, 144784, 144813, 144891, 144892, 144892))


def test_an_assessment_the_answer_already_quotes_is_not_repeated():
    for already in (ASSESSMENT, "The cause of this non credible contingency event has been identified",
                    "another occurrence of this event is unlikely"):
        assert decision_basis(DECISION, NOTICE[MOORABOOL], [DECISION, already]) is None
    # a quote of another passage, or of a different sentence of this one, does not count
    assert decision_basis(DECISION, NOTICE[MOORABOOL], [DECISION, NO_BULK, "unrelated text"]) == ASSESSMENT


# ------------------------------------------------------------------------------------------------ controls
def test_a_complete_answer_is_unchanged():
    """The draft already quotes the assessment (before or after the decision): nothing is added or repeated."""
    calls, _, _ = _y14_parts()
    for order in ([TRIP, NO_SHEDDING, ASSESSMENT, DECISION], [TRIP, DECISION, ASSESSMENT],
                  [TRIP, f"“{ASSESSMENT}”", DECISION]):  # a quote the model wrapped in quotation marks
        d = _doc_draft([(MOORABOOL, s) for s in order], "AEMO will not reclassify the Moorabool bus trip as credible.",
                       finding=MOORABOOL)
        res = _run(Y14["question"], Y14["route"], calls, d)
        rep = res.report
        assert _passed(rep), rep.validation["initial"]["violations"]
        assert [s.split("” [")[0].lstrip("“") for s in rep.summary] == [s.strip("“”") for s in order]
        assert not any(e["name"] == "decision_basis" for e in _events(res))


def test_a_multi_part_question_keeps_every_part():
    """What tripped, whether load was shed, and the reclassification decision: each part the draft answered is shown,
    and the assessment is added once, just before the decision."""
    calls, _, _ = _y14_parts()
    q = ("What tripped in Victoria on 28 July 2026, did AEMO instruct load shedding, and what did AEMO decide about "
         "reclassifying the event?")
    d = _doc_draft([(MOORABOOL, s) for s in (TRIP, NO_SHEDDING, NO_BULK, DECISION)],
                   "AEMO will not reclassify the Moorabool bus trip as credible.", finding=MOORABOOL)
    rep = _run(q, Y14["route"], calls, d).report
    assert _passed(rep), rep.validation["initial"]["violations"]
    assert [s.split("” [")[0].lstrip("“") for s in rep.summary] == [TRIP, NO_SHEDDING, NO_BULK, ASSESSMENT, DECISION]


def test_a_multi_part_question_across_two_notices():
    """The Braemar busbar trip: the first notice (cause not known, no decision) and its update (returned to service,
    cause identified, not reclassified). The assessment comes from the decision's own notice; the first notice's
    sentences are shown as quoted, with nothing added."""
    first, update = "market_notice_144812#0", "market_notice_144813#0"
    not_known = "The cause of this non credible contingency event is not known at this stage."
    back = "At 1546 hrs the R2 Braemar No.1 275 kV Busbar was returned to service."
    q = ("What did AEMO's notices say about the Braemar busbar trip in Queensland on 18 August 2026, and did AEMO "
         "decide to reclassify it?")
    d = _doc_draft([(first, "At 1332 hrs the R2 Braemar No.1 275 kV Busbar tripped."), (first, not_known),
                    (update, back), (update, DECISION)],
                   "AEMO will not reclassify the Braemar busbar trip as credible.", finding=update)
    res = _run(q, _route("QLD1", "2026-08-18"), _notices("QLD1", "2026-08-17T14:00:00Z", "2026-08-18T14:00:00Z"), d)
    rep = res.report
    assert _passed(rep), rep.validation["initial"]["violations"]
    texts = [s.split("” [")[0].lstrip("“") for s in rep.summary]
    basis = ASSESSMENT.replace("non credible", "non-credible")  # the update's own wording
    assert texts == ["At 1332 hrs the R2 Braemar No.1 275 kV Busbar tripped.", not_known, back, basis, DECISION]
    cite = {c.chunk_id: c.citation_id for c in rep.citations}
    assert rep.summary[3].endswith(f"[{cite[update]}]")  # cited to the update, like the decision
    assert [e["citation_id"] for e in _events(res) if e["name"] == "decision_basis"] == [update]


def test_a_notice_without_the_requested_decision_gets_nothing_added():
    """Asked for AEMO's reclassification decision on the City West trip, whose notice says the cause is not known and
    states no decision: no decision or assessment is supplied, and the draft's caveat and status stand."""
    city_west = "market_notice_144692#0"
    trip = ("At 1140 hrs, the City West 275/66 kV transformer T_1 and the 275 kV circuit breaker 6675 tripped during "
            "restoration of City West 275/66 kV transformer T_2.")
    not_known = "The cause of this non credible contingency event is not known at this stage."
    caveat = "The City West notice states no reclassification decision for this event."
    q = "What did AEMO decide about reclassifying the City West transformer trip in South Australia on 30 July 2026?"
    d = _doc_draft([(city_west, trip), (city_west, not_known)],
                   "AEMO's notice reports the City West transformer trip and states no reclassification decision.",
                   status="answered_with_caveats", missing=[caveat], finding=city_west)
    res = _run(q, _route("SA1", "2026-07-30"), _notices("SA1", "2026-07-29T14:30:00Z", "2026-07-30T14:30:00Z"), d)
    rep = res.report
    assert _passed(rep), rep.validation["initial"]["violations"]
    assert [s.split("” [")[0].lstrip("“") for s in rep.summary] == [trip, not_known]
    assert "reclassif" not in " ".join(rep.summary + [f.statement for f in rep.published_findings]).lower()
    assert rep.status == "answered_with_caveats" and caveat in rep.missing_evidence
    assert not any(e["name"] == "decision_basis" for e in _events(res))


def test_a_declaration_with_no_stated_assessment_gets_nothing_added():
    """A reserve-level declaration is a decision, but its notice states no assessment for it: nothing is added."""
    lor = "market_notice_144652#0"
    declared = ("AEMO declares a Forecast LOR1 condition under clause 4.8.4(b) of the National Electricity Rules for "
                "the SA region")
    q = "What did AEMO's market notice declare about South Australia's reserves on 29 July 2026?"
    d = _doc_draft([(lor, declared)], "AEMO declared a forecast lack of reserve condition for South Australia.",
                   finding=lor)
    res = _run(q, _route("SA1", "2026-07-29"), _notices("SA1", "2026-07-28T14:30:00Z", "2026-07-29T14:30:00Z"), d)
    assert [s.split("” [")[0].lstrip("“") for s in res.report.summary] == [declared]
    assert not any(e["name"] == "decision_basis" for e in _events(res))


def test_an_event_review_is_unchanged():
    """Event reviews have no document statements: W19's saved market-event replay gets nothing added."""
    rec = json.loads((LIVE / "live-check-dev2" / "W19.json").read_text())
    trace = json.loads((LIVE / "live-check-dev2" / "traces" / f"{rec['score']['trace_id']}.json").read_text())["events"]
    patch = next((e.get("patch") for e in trace if e["name"] == "repair:scoped"), None)
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    res = _run(rec["question"], rec["route"], calls, rec["drafts"]["synthesis:draft"], patch)
    assert res.resolution.intent == "market_event_review"
    assert not any(e["name"] == "decision_basis" for e in _events(res))
