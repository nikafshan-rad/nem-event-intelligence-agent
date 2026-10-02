"""Issue I-8 (docs/issue-tracker.md): what a document answer says is included in, or left out of, something must agree
with its cited passage.

Held-out v5 Y20 (Live, 2026-10-02) said AEMO's operational demand "includes local demand of scheduled loads and
scheduled bidirectional units [c1]". Its passage [c1] is a figure's text, which subtracts them ("… − local demand of
(scheduled loads + scheduled BDUs)"), and the definition excludes them. The answer passed: the lexical support check
counts shared words, and "includes" and "excludes" share every other word.

Now the inclusion or exclusion a statement makes is compared with the wording that governs the same thing in its
cited passage. Faithful statements and paraphrases pass. Reversals, dropped negations and passages that do not
mention the thing fail. Real passages from several documents are used; nothing is specific to one case. Replays use
the saved Live record through the SYNTHETIC fake transport (no network, no key).
"""

from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path

import pytest

from nem_agent import paths
from nem_agent.agent.request import InvestigateRequest
from nem_agent.evaluation.runner import synthetic_injection_index
from nem_agent.evidence import ChunkItem
from nem_agent.report import Citation
from nem_agent.service import investigate
from nem_agent.validation import SUPPORT_MIN, polarity_claims, polarity_violations, support, validate
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

LIVE = Path(__file__).resolve().parents[2] / "artifacts" / "live"
Y20 = LIVE / "L3-holdout-v5" / "Y20.json"


def _passage(chunk_id: str) -> tuple[str, str]:
    con = sqlite3.connect(paths.index_dir() / "corpus.sqlite")
    return chunk_id, con.execute("SELECT text FROM chunks WHERE chunk_id = ?", [chunk_id]).fetchone()[0]


def _codes(statement: str, *chunk_ids: str) -> list[str]:
    cited = {f"c{i + 1}": _passage(c) for i, c in enumerate(chunk_ids)}
    return [v.code for v in polarity_violations("summary[0]", statement, cited)]


OP_DEF = "aemo_demand_terms#p9c11"  # "… excluding the demand of local scheduled loads and scheduled bidirectional
#                                     units, and including Wholesale Demand Response"
OP_FIGURE = "aemo_demand_terms#p10c16"  # figure text: "… − local demand of (scheduled loads + scheduled BDUs)"; and
#                                         "Operational demand adjustments include: • Activated RERT … exclude …"
NATIVE = "aemo_demand_terms#p9c13"  # "Native demand does not include the demand met by behind -the-meter generation"
SCHEDULED = "aemo_demand_terms#p12c20"  # "Scheduled demand … excludes the demand met by non -scheduled … generation"
SENT_OUT = "aemo_demand_terms#p7c5"  # "… therefore excludes generating unit auxiliary loads5 and transmission losses"
PROCEDURE = "aemo_so_op_3705#p12c34"  # "… excluding any wholesale demand response or scheduled network services"


# ------------------------------------------------------------------------------------------------ faithful statements
@pytest.mark.parametrize("statement,chunk", [
    ("Operational demand excludes the demand of local scheduled loads and scheduled bidirectional units [c1].", OP_DEF),
    ("Operational demand includes Wholesale Demand Response [c1].", OP_DEF),
    ("Native demand does not include the demand met by behind-the-meter generation such as rooftop PV [c1].", NATIVE),
    ("Scheduled demand excludes the demand met by non-scheduled generation [c1].", SCHEDULED),
    ("Sent-out energy excludes generating unit auxiliary loads and transmission losses [c1].", SENT_OUT),
    ("Aggregated dispatch conformance excludes any wholesale demand response or scheduled network services [c1].",
     PROCEDURE),
    ("Operational demand adjustments include activated RERT and involuntary load shedding [c1].", OP_FIGURE),
    ("The figure subtracts the local demand of scheduled loads and scheduled BDUs [c1].", OP_FIGURE),
])
def test_faithful_definitions_pass(statement, chunk):
    assert polarity_claims(statement)  # a claim is made, and checked
    assert _codes(statement, chunk) == []


@pytest.mark.parametrize("statement", [
    "Operational demand leaves out what local scheduled loads draw [c1].",
    "Scheduled loads are not counted in operational demand [c1].",
    "Scheduled loads aren't included in operational demand [c1].",
    "Operational demand is measured net of the demand of local scheduled loads [c1].",
    "Operational demand counts WDR [c1].",  # an acronym matches its spelled-out words
    "Wholesale Demand Response is also included [c1].",
])
def test_legitimate_paraphrases_pass(statement):
    assert polarity_claims(statement) and _codes(statement, OP_DEF) == []


# ------------------------------------------------------------------------------------------------ what must fail
@pytest.mark.parametrize("statement,chunk", [
    ("Operational demand includes the demand of local scheduled loads and scheduled bidirectional units [c1].", OP_DEF),
    ("Operational demand excludes Wholesale Demand Response [c1].", OP_DEF),
    ("Scheduled loads are counted in operational demand [c1].", OP_DEF),
    ("Scheduled demand includes the demand met by non-scheduled generation [c1].", SCHEDULED),
    ("Sent-out energy includes generating unit auxiliary loads and transmission losses [c1].", SENT_OUT),
    ("Aggregated dispatch conformance includes any wholesale demand response or scheduled network services [c1].",
     PROCEDURE),
    ("Operational demand adjustments include under frequency load shedding [c1].", OP_FIGURE),
])
def test_reversing_includes_and_excludes_fails(statement, chunk):
    assert _codes(statement, chunk) == ["DOC_CLAIM_CONTRADICTED"]


@pytest.mark.parametrize("statement,chunk", [
    ("Native demand includes the demand met by behind-the-meter generation [c1].", NATIVE),
    ("Native demand does include the demand met by behind-the-meter generation [c1].", NATIVE),
    ("Wholesale Demand Response is not counted in operational demand [c1].", OP_DEF),
])
def test_dropping_or_adding_a_negation_fails(statement, chunk):
    assert _codes(statement, chunk) == ["DOC_CLAIM_CONTRADICTED"]


@pytest.mark.parametrize("statement,chunk", [
    ("Operational demand excludes the demand of local scheduled loads [c1].", PROCEDURE),
    ("Native demand does not include rooftop solar exports to neighbouring regions [c1].", SENT_OUT),
    ("Operational demand excludes generating unit auxiliary loads [c1].", OP_DEF),  # it is SENT_OUT that says so
    ("Native demand excludes interconnector losses [c1].", NATIVE),
])
def test_citing_a_passage_that_does_not_mention_it_fails(statement, chunk):
    assert _codes(statement, chunk) == ["DOC_CLAIM_UNSUPPORTED"]


# Faithful lines from saved Live answers that an earlier version of this check rejected (each replay is identical to
# main's now): a list spread across a formula table (H09), a list with words between its items (DOC03), field names
# (H07), and a list cut to one word at a comma (ADV04's headline).
@pytest.mark.parametrize("statement,chunk", [
    ("The Dispatch formula shows TotalDemand includes regional scheduled and semi-scheduled generation, subtracts "
     "scheduled-load demand and allocated interconnector losses [c1].", "aemo_demand_terms#p22c46"),
    ("Total Demand is the forecast demand at the Regional Reference Node that is met by local scheduled and "
     "semi-scheduled generation plus interconnector imports, excluding local scheduled loads and allocated "
     "interconnector losses [c1].", "aemo_demand_terms#p21c42"),
    ("The MMS data model includes distinct fields OPERATIONAL_DEMAND_POE10, OPERATIONAL_DEMAND_POE50 and "
     "OPERATIONAL_DEMAND_POE90 [c1].", "mms_dm_elec18#DEMANDOPERATIONALFORECAST#0"),
    ("Operational demand includes scheduled, semi-scheduled and significant non-scheduled generation [c1].", OP_DEF),
])
def test_faithful_lines_from_saved_answers_pass(statement, chunk):
    assert _codes(statement, chunk) == []


def test_one_supporting_passage_among_several_is_enough():
    statement = "Operational demand excludes the demand of local scheduled loads [c1] [c2]."
    assert _codes(statement, PROCEDURE, OP_DEF) == []


# ------------------------------------------------------------------------------------------------ not affected
@pytest.mark.parametrize("statement", [
    "Measured operational demand is field OPERATIONAL_DEMAND in the EMMS Data Model [c1].",
    "The passage does not say whether pumped-hydro pumps are included [c1].",  # unstated, not a claim
    "It is unclear whether Tumut 3 pumping is counted [c1].",
    "The definition reads “excluding the demand of local scheduled loads” [c1].",  # quoted: checked verbatim already
    "“Operational demand adjustments exclude all other events” [c1].",
])
def test_lines_without_an_inclusion_claim_are_not_checked(statement):
    assert polarity_claims(statement) == [] and _codes(statement, OP_FIGURE) == []


# ------------------------------------------------------------------------------------------------ Y20, replayed
def _replay(repair=None):
    rec = json.loads(Y20.read_text())
    draft = rec["drafts"]["synthesis:draft"]
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    fake = FakeModel(rec["route"], [calls], lambda kw: copy.deepcopy(draft), repair)
    with synthetic_injection_index():
        return investigate(InvestigateRequest(question=rec["question"], mode="live"), live_client=fake,
                           write_trace=False)


def _patch(statement: str, headline: str):
    return lambda kw: {"edits": [
        {"target": "headline", "action": "replace", "text": headline, "statement": None, "claim": None,
         "citation": None},
        {"target": "document_statements[0]", "action": "replace", "text": None, "claim": None, "citation": None,
         "statement": {"citation_id": "c1", "quote": None, "paraphrase": statement}}],
        "new_numeric_claims": [], "new_citations": []}


def _shown(rep) -> str:
    return " ".join([rep.headline, *rep.summary])


def test_y20s_saved_draft_is_rejected_and_its_reversal_not_shown():
    rep = _replay().report
    v = rep.validation
    pre = [(x["code"], x["detail"]) for x in v["pre_repair"]["violations"]]
    assert ("DOC_CLAIM_CONTRADICTED" in {c for c, _ in pre}) and any(
        d.startswith("summary[0]: says “local demand of scheduled loads") and "− local demand" in d for _, d in pre)
    assert v["repair_attempted"] and v["fallback_applied"]  # no repair available here: nothing reversed is shown
    assert "includes local demand" not in _shown(rep)


def test_y20_with_a_faithful_repair_passes():
    rep = _replay(_patch("AEMO's operational demand subtracts the local demand of scheduled loads and scheduled "
                         "BDUs [c1].",
                         "AEMO's operational demand leaves out electricity drawn by scheduled loads and scheduled "
                         "BDUs.")).report
    v = rep.validation
    assert v["repair_attempted"] and not v["fallback_applied"] and v["final_passed"]
    assert "subtracts the local demand of scheduled loads" in _shown(rep)


def test_y20_with_a_repair_that_keeps_the_reversal_falls_back():
    rep = _replay(_patch("AEMO's operational demand counts the local demand of scheduled loads and scheduled "
                         "BDUs [c1].",
                         "AEMO's operational demand includes electricity drawn by scheduled loads.")).report
    assert rep.validation["fallback_applied"] and "counts the local demand" not in _shown(rep)


# ------------------------------------------------------------------------------------------------ the full validator
@pytest.fixture(scope="module")
def answered():
    """A document answer to vary: Y20 with a faithful scripted repair."""
    return _replay(_patch("AEMO's operational demand subtracts the local demand of scheduled loads and scheduled "
                          "BDUs [c1].", "AEMO's operational demand leaves out scheduled loads."))


def _validate_line(res, statement: str, chunk: str) -> set[str]:
    """The document-claim codes the full validator gives a one-line answer citing ``chunk`` as [c1]."""
    cols = ("chunk_id", "doc_id", "title", "url", "doc_type", "publication_date", "event_region", "event_date", "page",
            "section", "text", "instruction_like")
    con = sqlite3.connect(paths.index_dir() / "corpus.sqlite")
    row = dict(zip(cols, con.execute(f"SELECT {', '.join(cols)} FROM chunks WHERE chunk_id = ?", [chunk]).fetchone(), strict=True))
    reg = copy.deepcopy(res.registry)
    reg.add_chunk(ChunkItem(tool_call_id="test", eligible=True, eligibility_reason="test",
                            **{**row, "instruction_like": bool(row["instruction_like"])}))
    cite = Citation(citation_id="c1", chunk_id=chunk, doc_id=row["doc_id"], title=row["title"], url=row["url"],
                    doc_type=row["doc_type"], quote=row["text"][:40], supports="test")
    rep = res.report.model_copy(update={"summary": [statement], "citations": [cite], "published_findings": [],
                                        "headline": "What the cited passage defines.", "validation": {}})
    return {v.code for v in validate(rep, reg, records=res.records).violations if v.code.startswith("DOC_CLAIM")}


@pytest.mark.parametrize("statement,chunk,code", [
    ("Operational demand includes the demand of local scheduled loads and scheduled bidirectional units [c1].", OP_DEF,
     "DOC_CLAIM_CONTRADICTED"),
    ("Native demand includes the demand met by behind-the-meter generation [c1].", NATIVE, "DOC_CLAIM_CONTRADICTED"),
    ("Operational demand excludes generating unit auxiliary loads [c1].", OP_DEF, "DOC_CLAIM_UNSUPPORTED"),
])
def test_lines_the_lexical_check_accepts_are_now_rejected(answered, statement, chunk, code):
    """Each line shares enough words with its passage for the lexical check (which is unchanged)."""
    assert support(statement, _passage(chunk)[1]) >= SUPPORT_MIN
    assert _validate_line(answered, statement, chunk) == {code}


@pytest.mark.parametrize("statement,chunk", [
    ("Operational demand excludes the demand of local scheduled loads and scheduled bidirectional units [c1].", OP_DEF),
    ("Scheduled loads are not counted in operational demand [c1].", OP_DEF),
    ("Wholesale Demand Response is also included [c1].", OP_DEF),
    ("Native demand does not include the demand met by behind-the-meter generation such as rooftop PV [c1].", NATIVE),
])
def test_faithful_lines_pass_the_full_validator(answered, statement, chunk):
    assert _validate_line(answered, statement, chunk) == set()


# ------------------------------------------------------------------------------------------------ scope
def test_only_document_answers_are_checked():
    """The check runs on source_explanation answers; a market-event answer with the same line is not checked."""
    res = _replay(_patch("AEMO's operational demand subtracts the local demand of scheduled loads and scheduled "
                         "BDUs [c1].", "AEMO's operational demand leaves out scheduled loads."))
    rep = res.report
    reversed_line = "Operational demand includes the local demand of scheduled loads and scheduled BDUs [c1]."
    doc = rep.model_copy(update={"summary": [reversed_line], "validation": {}})
    assert "DOC_CLAIM_CONTRADICTED" in {v.code for v in validate(doc, res.registry, records=res.records).critical}
    market = doc.model_copy(update={"intent": "market_event_review"})
    assert "document_polarity" not in validate(market, res.registry, records=res.records).checks_run
