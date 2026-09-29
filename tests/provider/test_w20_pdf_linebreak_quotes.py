"""Held-out v4 W20: a faithful quote was rejected because of a PDF line break (held-out v4 is development data from
this fix on).

The first draft quoted AEMO's Demand Terms paper verbatim: "… excludes demand met by non-scheduled wind/solar
generation of aggregate capacity < 30 MW, …". pypdf extracts that line as "non-\\nscheduled" and the corpus joins
lines with a space, so the stored passage aemo_demand_terms#p10c14 reads "non- scheduled". The quote check compared
the two strings literally: CITATION_QUOTE_NOT_FOUND, the statement was shown as the model's own words, its "30" became
NUMERIC_UNTRACKED, and the repair replaced the answer with "Figure 3 below shows the composition of operational
demand."

The fix is in the comparison only (validation._norm): the space after a hyphen between a letter or digit and a letter
is dropped on both sides. The stored passages, and so corpus_version, are unchanged. Altered numbers, words, negations
and citations still fail. The replay uses W20's saved tool calls and first draft through the SYNTHETIC fake transport
(no network, no key); the runner's SYNTHETIC injection passage is added as in the v4 run.
"""

from __future__ import annotations

import copy
import json
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any

import pytest

from nem_agent import paths
from nem_agent.agent.request import InvestigateRequest
from nem_agent.evaluation.runner import synthetic_injection_index
from nem_agent.service import investigate
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

REC = json.loads((Path(__file__).resolve().parents[2] / "artifacts" / "live" / "L3-holdout-v4" / "W20.json").read_text())
PASSAGE = "aemo_demand_terms#p10c14"
QUOTE = REC["drafts"]["synthesis:draft"]["document_statements"][3]["quote"]


def _row(chunk_id: str) -> sqlite3.Row:
    con = sqlite3.connect(paths.index_dir() / "corpus.sqlite")
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM chunks WHERE chunk_id=?", [chunk_id]).fetchone()
    con.close()
    return row


def _replay(draft: dict[str, Any]):
    """W20's own tool calls (the controller's question retrieval runs by itself) and the given draft."""
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"])
             for t in REC["tools"] if t["call_id"] != "controller_question_retrieval"]
    fake = FakeModel(REC["route"], [calls], lambda kw: copy.deepcopy(draft))  # a repair returns the same draft
    return investigate(InvestigateRequest(question=REC["question"], mode="live"), live_client=fake, write_trace=False)


def _first_codes(res) -> set[str]:
    v = res.report.validation
    if v.get("repair_attempted"):
        return set(v.get("pre_repair_codes") or [])
    return {x["code"] for x in v["initial"]["violations"] if x["severity"] == "critical"}


def _draft(quote: str | None = None, cited_chunk: str | None = None) -> dict[str, Any]:
    """The first draft with statement 3 and its citation quoting ``quote``, the citation pointing at ``cited_chunk``."""
    d = copy.deepcopy(REC["drafts"]["synthesis:draft"])
    if quote is not None:
        d["document_statements"][3]["quote"] = quote
    for c in d["citations"]:
        if c["citation_id"] == PASSAGE:
            c["quote"] = quote if quote is not None else c["quote"]
            c["chunk_id"] = cited_chunk or c["chunk_id"]
    return d


def _shown_as_quote(res, fragment: str) -> bool:
    return any(fragment in q for s in res.report.summary for q in re.findall(r"“[^”]*”", s))


# ------------------------------------------------------------------------------------------------ the W20 replay
def test_the_stored_passage_keeps_the_line_break():
    """The corpus is not edited: the passage still holds the extraction's "non- scheduled"."""
    text = _row(PASSAGE)["text"]
    assert "met by non- scheduled wind/solar" in text and QUOTE not in text
    assert "non-scheduled wind/solar" in QUOTE


def test_w20_first_draft_is_shown_after_the_fix():
    """Before: CITATION_QUOTE_NOT_FOUND and NUMERIC_UNTRACKED ("30"), a repair that dropped the substance. After: the
    first draft passes and the quote is shown, as in the v4 run's conditions (with the SYNTHETIC injection passage)."""
    with synthetic_injection_index():
        res = _replay(REC["drafts"]["synthesis:draft"])
    rep = res.report
    assert _first_codes(res) == set() and not rep.validation.get("repair_attempted"), rep.validation
    assert not rep.validation["fallback_applied"] and rep.status == "answered_with_caveats"
    assert _shown_as_quote(res, "non-scheduled wind/solar generation of aggregate capacity < 30 MW")
    assert not any(c.chunk_id == "synthetic_injection#0" for c in rep.citations)


def test_a_quote_copying_the_stored_line_break_still_passes():
    res = _replay(_draft(quote=QUOTE.replace("met by non-scheduled", "met by non- scheduled")))
    assert _first_codes(res) == set()


# ------------------------------------------------------------------------------------------------ still rejected
@pytest.mark.parametrize("label,old,new", [
    ("changed number", "< 30 MW", "< 25 MW"),
    ("omitted negation", "met by non-scheduled wind/solar", "met by scheduled wind/solar"),
    ("changed word", "generally excludes demand", "generally includes demand"),
])
def test_an_altered_quote_still_fails(label, old, new):
    q = QUOTE.replace(old, new)
    assert q != QUOTE
    res = _replay(_draft(quote=q))
    codes = _first_codes(res)
    assert "CITATION_QUOTE_NOT_FOUND" in codes, (label, codes)
    assert not _shown_as_quote(res, new), label  # shown as the model's own words, so every check applies
    if label == "changed number":
        assert "NUMERIC_UNTRACKED" in codes


def test_the_faithful_quote_under_the_wrong_passage_still_fails():
    res = _replay(_draft(cited_chunk="aemo_demand_terms#p10c15"))  # retrieved, same document, next passage
    codes = _first_codes(res)
    assert {"CITATION_QUOTE_NOT_FOUND", "NUMERIC_UNTRACKED"} <= codes, codes
    assert not _shown_as_quote(res, "non-scheduled wind/solar")


# ------------------------------------------------------------------------------------------------ other real passages
@pytest.fixture(scope="module")
def doc_answer():
    return investigate(InvestigateRequest(question="What does operational demand mean?", mode="replay"), write_trace=False)


def _codes(res, chunk_id: str, quote: str) -> set[str]:
    """The replay document answer plus one sentence quoting ``quote`` under a citation of the real ``chunk_id``."""
    from nem_agent.evidence import ChunkItem
    from nem_agent.report import Citation
    from nem_agent.validation import validate

    r = _row(chunk_id)
    reg = copy.deepcopy(res.registry)
    reg.add_chunk(ChunkItem(chunk_id=r["chunk_id"], doc_id=r["doc_id"], title=r["title"], url=r["url"], text=r["text"],
                            section=r["section"], page=r["page"], publication_date=r["publication_date"],
                            doc_type=r["doc_type"], event_region=None, event_date=None, eligible=True,
                            eligibility_reason="retrieved (test)", tool_call_id="call-test"))
    cit = Citation(citation_id="t1", chunk_id=r["chunk_id"], doc_id=r["doc_id"], title=r["title"], url=r["url"],
                   doc_type=r["doc_type"], quote=quote, supports="test")
    rep = res.report.model_copy(update={"citations": [*res.report.citations, cit],
                                        "summary": [*res.report.summary, f"“{quote}” [t1]"]})
    return {x.code for x in validate(rep, reg, records=res.records).violations if x.severity == "critical"}


CONFORMANCE = "aemo_so_op_3705#p23c65"  # Dispatch procedure: "… a non- conformance exists but does not cause …"
PREDISPATCH = "aemo_so_op_3704#p9c25"  # Pre-dispatch procedure: "… greater than two 30- minute periods …"
QUOTE_REJECTED = {"CITATION_QUOTE_NOT_FOUND", "QUOTE_NOT_IN_SOURCE"}


def test_other_real_passages_with_a_line_break_validate(doc_answer):
    assert "a non- conformance exists" in _row(CONFORMANCE)["text"] and "two 30- minute periods" in _row(PREDISPATCH)["text"]
    assert _codes(doc_answer, CONFORMANCE, "a non-conformance exists but does not cause power system security "
                                           "violations") == set()
    assert _codes(doc_answer, PREDISPATCH, "greater than two 30-minute periods AEMO may submit a revised forecast for "
                                           "that region") == set()


@pytest.mark.parametrize("label,chunk_id,quote", [
    ("omitted negation", CONFORMANCE, "a non-conformance exists but does cause power system security violations"),
    ("omitted negating prefix", CONFORMANCE, "a conformance exists but does not cause power system security violations"),
    ("changed number", PREDISPATCH, "greater than two 60-minute periods AEMO may submit a revised forecast"),
    ("changed word", PREDISPATCH, "greater than two 30-minute periods AEMO must submit a revised forecast"),
    ("wrong citation", "aemo_so_op_3705#p23c64", "a non-conformance exists but does not cause power system security"),
])
def test_altered_quotes_of_other_real_passages_still_fail(doc_answer, label, chunk_id, quote):
    assert _codes(doc_answer, chunk_id, quote) >= QUOTE_REJECTED, label


# ------------------------------------------------------------------------------------------------ the comparison
def test_only_the_space_after_a_joining_hyphen_is_dropped():
    from nem_agent.validation import _norm

    assert _norm("met by non- scheduled wind") == _norm("met by non-scheduled wind") == "met by non-scheduled wind"
    assert _norm("Non- Conforming") == "Non-Conforming" and _norm("two 30- minute periods") == "two 30-minute periods"
    for other in ("met by nonscheduled wind", "met by non scheduled wind", "met by scheduled wind"):
        assert _norm(other) != _norm("met by non- scheduled wind")
    for unchanged in ("10- 20 MW", "price - 5", "-5 MW", "non -scheduled", "August 2027 - July 2028", "-- July"):
        assert _norm(unchanged) == unchanged


def test_the_comparison_changes_no_character_but_spaces_in_any_passage():
    """Across the whole corpus the new comparison form differs from the old one only by removed spaces."""
    from nem_agent.validation import _norm

    def before(s: str) -> str:
        s = unicodedata.normalize("NFKC", s).replace("’", "'").replace("‘", "'")
        return re.sub(r"\s+", " ", s).strip()

    con = sqlite3.connect(paths.index_dir() / "corpus.sqlite")
    texts = [t for (t,) in con.execute("SELECT text FROM chunks")]
    con.close()
    joined = 0
    for t in texts:
        new, old = _norm(t), before(t)
        assert new.replace(" ", "") == old.replace(" ", "")
        joined += len(old) - len(new)
    assert joined > 0
