"""Held-out v4 W10: a correct document answer was discarded over its citation IDs (held-out v4 is development data
from this fix on).

The first draft quoted the gold sentence under a valid citation. It also named two citations of one passage
`aemo_so_op_3705#p12c33:supply` and `…:dt`, and two further statements cited that passage by its ID,
`aemo_so_op_3705#p12c33`. Two defects turned this into a facts-only fallback:
1. the controller matched a statement's citation only by exact citation ID, so those two verbatim quotes were
   shown as uncited own words;
2. the validator's citation-marker pattern rejected schema-valid IDs containing ':', so even the draft's own IDs
   could never be recognised.

The replay uses W10's saved tool calls and first draft through the SYNTHETIC fake transport (no network, no key).
The behaviour tests use only interfaces that existed before the fix; the resolver's unit tests import it lazily.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from nem_agent.agent.request import InvestigateRequest
from nem_agent.service import investigate
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

REC = json.loads((Path(__file__).resolve().parents[2] / "artifacts" / "live" / "L3-holdout-v4" / "W10.json").read_text())
GOLD = "When Wholesale Demand Response is dispatched, scheduled demand will decrease by the amount of dispatched WDR."
PASSAGE = "aemo_so_op_3705#p12c33"


def _replay(draft: dict[str, Any]):
    """W10's own tool calls (the controller's question retrieval runs by itself) and the given draft."""
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"])
             for t in REC["tools"] if t["call_id"] != "controller_question_retrieval"]
    fake = FakeModel(REC["route"], [calls], lambda kw: copy.deepcopy(draft))  # a repair returns the same draft
    return investigate(InvestigateRequest(question=REC["question"], mode="live"), live_client=fake, write_trace=False)


def _first_codes(res) -> set[str]:
    v = res.report.validation
    if v.get("repair_attempted"):
        return set(v.get("pre_repair_codes") or [])
    return {x["code"] for x in v["initial"]["violations"] if x["severity"] == "critical"}


def _draft(**edits: Any) -> dict[str, Any]:
    d = copy.deepcopy(REC["drafts"]["synthesis:draft"])
    for i, st in edits.get("statements", {}).items():
        d["document_statements"][i] = {**d["document_statements"][i], **st}
    for old, new in edits.get("rename_citations", {}).items():
        for c in d["citations"]:
            if c["citation_id"] == old:
                c["citation_id"] = new
    return d


# ------------------------------------------------------------------------------------------------ the W10 replay
def test_w10_first_draft_is_shown_after_the_fix():
    """Before: DOC_CLAIM_UNCITED on the two passage-ID statements, a repair that changed nothing, a fallback, and the
    gold sentence lost. After: the first draft passes, with the gold sentence shown under its citation."""
    draft = REC["drafts"]["synthesis:draft"]
    assert [s["citation_id"] for s in draft["document_statements"]][6:] == [PASSAGE, PASSAGE]  # the saved draft
    res = _replay(draft)
    rep = res.report
    assert _first_codes(res) == set() and not rep.validation["fallback_applied"], rep.validation
    assert rep.status == "answered" and not rep.validation.get("repair_attempted")
    shown = rep.validation.get("citation_labels", {})  # I-3g: raw passage IDs are shown as [cN]

    def marker(raw: str) -> str:
        return f"[{shown.get(raw, raw)}]"
    assert any(GOLD in s and marker("aemo_demand_terms#p12c20") in s for s in rep.summary)
    assert marker(f"{PASSAGE}:supply") in rep.summary[6] and marker(f"{PASSAGE}:dt") in rep.summary[7]
    by_label = {c.citation_id: c.chunk_id for c in rep.citations}
    assert by_label[shown.get(f"{PASSAGE}:supply", f"{PASSAGE}:supply")] == PASSAGE  # each label names its passage


# ------------------------------------------------------------------------------------------------ marker pattern
def test_citation_markers_with_colons_are_recognised():
    from nem_agent.validation import CITE_RE

    assert CITE_RE.findall("“q” [aemo_so_op_3705#p12c33:supply] and [c1]") == ["aemo_so_op_3705#p12c33:supply", "c1"]
    assert CITE_RE.findall("see [two words] or [09 30]") == []  # bracketed text is not a citation


# ------------------------------------------------------------------------------------------------ still rejected
def test_an_unknown_citation_id_still_fails():
    res = _replay(_draft(statements={6: {"citation_id": "aemo_so_op_3705#p99c99"}}))
    assert "DOC_CLAIM_UNCITED" in _first_codes(res) and res.report.validation["fallback_applied"]


def test_an_ambiguous_passage_reference_is_not_resolved():
    """Two citations of the passage; a paraphrase names neither, and a quote spanning both quotes names both."""
    both = ("(c) The central dispatch process determines Dispatch Targets for wholesale demand response units in a "
            "similar manner to scheduled generating units, on the basis of bid price bands and availability with both "
            "treated as a supply when balancing electricity supply and demand. (d) A Dispatch Target for a wholesale "
            "demand response unit is the required reduction in active power consumption (in MW) below the baseline "
            "consumption of the wholesale demand response unit, to be achieved at the end of the trading interval to "
            "which it relates.")
    for st in ({"quote": None, "paraphrase": "WDR units are dispatched much like scheduled generators"},
               {"quote": both, "paraphrase": None}):
        res = _replay(_draft(statements={6: {"citation_id": PASSAGE, **st}}))
        assert "DOC_CLAIM_UNCITED" in _first_codes(res), st


def test_a_non_verbatim_quote_under_a_passage_reference_is_checked_as_own_words():
    """One citation of the passage, so the reference resolves; the altered quote is still not shown as a quote."""
    q = REC["drafts"]["synthesis:draft"]["document_statements"][4]["quote"] + " by 25 MW"
    res = _replay(_draft(rename_citations={"aemo_demand_terms#p10c14": "aemo_demand_terms#p10c14:wdr"},
                         statements={4: {"citation_id": "aemo_demand_terms#p10c14", "quote": q}}))
    assert "NUMERIC_UNTRACKED" in _first_codes(res)
    assert not any("“" in s and "by 25 MW" in s for s in res.report.summary)


def test_an_unsupported_paraphrase_under_a_passage_reference_still_fails():
    res = _replay(_draft(rename_citations={"aemo_demand_terms#p10c14": "aemo_demand_terms#p10c14:wdr"},
                         statements={4: {"citation_id": "aemo_demand_terms#p10c14", "quote": None,
                                         "paraphrase": "Retailers are paid a bonus whenever customers switch plans"}}))
    assert "DOC_CLAIM_UNSUPPORTED" in _first_codes(res)


# ------------------------------------------------------------------------------------------------ the resolver
def _cite(cid: str, chunk: str, quote: str):
    from nem_agent.report import Citation
    return Citation(citation_id=cid, chunk_id=chunk, doc_id="d", title="t", url="u", doc_type="procedure",
                    quote=quote, supports="s")


def test_resolver_cases():
    from nem_agent.agent.live import resolve_statement_citation as resolve

    a = _cite("P#1:a", "P#1", "first sentence of the passage.")
    b = _cite("P#1:b", "P#1", "second sentence of the passage.")
    one = _cite("Q#2:x", "Q#2", "only sentence.")
    cites = [a, b, one]
    assert resolve("P#1:a", None, cites) == (a, "exact")
    assert resolve("Q#2", "anything", cites) == (one, "passage")                     # the only citation of Q#2
    assert resolve("P#1", "Text: second sentence of the passage.", cites) == (b, "passage")  # the quote names b
    assert resolve("P#1", None, cites) == (None, "ambiguous")                         # nothing names one of them
    assert resolve("P#1", "first sentence of the passage. second sentence of the passage.", cites) == (None, "ambiguous")
    assert resolve("Z#9", "x", cites) == (None, "unknown")
