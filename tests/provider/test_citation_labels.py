"""Issue I-3g (docs/issue-tracker.md): citations are shown as [c1], [c2], … mapped from the answer's own citations.

Live, second development check (2026-09-30): F01 showed "“New South Wales 150” [aemo_so_op_3710#p7c12]", F03
"[market_notice_144693#0]", and F04 "(market_notice_144695#0)" and "[aemo_so_op_3705#p40c132]". The model had used each
passage ID as its citation ID, and the controller rendered whatever it was given.

Now, after validation and outside quotations, each citation ID that is not already a cN label is shown as the next
unused cN, in the citations list's order. The citations list and the findings take the same labels, so every displayed
label resolves. Passage IDs, document IDs, quotes and evaluation records are kept. Unknown IDs are left as written.
Replays use saved Live records through the SYNTHETIC fake transport (no network, no key).
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from nem_agent.agent.request import InvestigateRequest
from nem_agent.report import Citation, PublishedFinding
from nem_agent.service import investigate
from nem_agent.validation import CITE_RE, QUOTED_RE, narrative_numbers, validate
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

DEV2 = Path(__file__).resolve().parents[2] / "artifacts" / "live" / "live-check-dev2"


def plain_display(report):
    from nem_agent.display import plain_display as display

    return display(report)


def _replay(path: Path):
    """A saved run's first draft and actual saved repair (if any) through the fake transport."""
    rec = json.loads(path.read_text())
    trace = json.loads((path.parent / "traces" / f"{rec['score']['trace_id']}.json").read_text())
    draft = next(e for e in trace["events"] if e["name"] == "synthesis:draft")["report"]
    patch = next((e["patch"] for e in trace["events"] if e["name"] == "repair:scoped"), None)
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    fake = FakeModel(rec["route"], [calls], lambda kw: copy.deepcopy(draft), (lambda kw: copy.deepcopy(patch)) if patch else None)
    return investigate(InvestigateRequest(question=rec["question"], mode="live"), live_client=fake, write_trace=False)


def _shown(rep) -> list[str]:
    return [rep.headline, *rep.summary, *[h.statement for h in rep.possible_explanations],
            *[h.what_would_test_it for h in rep.possible_explanations], *[f.statement for f in rep.published_findings],
            *rep.uncertainties, *rep.missing_evidence]


def _markers(rep) -> set[str]:
    return {m for t in _shown(rep) for m in CITE_RE.findall(QUOTED_RE.sub(" ", t)) if not re.fullmatch(r"ev\d{4}", m)}


# ------------------------------------------------------------------------------------------------ the saved examples
@pytest.mark.parametrize("case,labels", [
    ("F01", {"aemo_so_op_3710#p7c12": "c1"}),
    ("F03", {"market_notice_144693#0": "c1"}),
    ("F04", {"market_notice_144695#0": "c1", "aemo_so_op_3705#p40c132": "c2"}),
])
def test_saved_answers_show_readable_labels_that_resolve(case, labels):
    res = _replay(DEV2 / f"{case}.json")
    rep, v = res.report, res.report.validation
    assert v["final_passed"] and not v["fallback_applied"]  # validation as before
    assert v["citation_labels"] == labels  # the mapping is kept with the record
    assert _markers(rep) == set(labels.values()) <= {c.citation_id for c in rep.citations}  # every label resolves
    assert not any(raw in QUOTED_RE.sub(" ", t) for t in _shown(rep) for raw in labels)
    assert {c.chunk_id for c in rep.citations} == set(labels)  # passage IDs kept
    for c in rep.citations:  # each label points at the passage its raw ID named
        assert labels[c.chunk_id] == c.citation_id
    for f in rep.published_findings:
        assert set(f.citation_ids) <= {c.citation_id for c in rep.citations}
    assert any(raw in r["original"] for r in v["display_rewrites"] for raw in labels)  # originals kept
    assert not validate(rep, res.registry, records=res.records).critical  # the displayed answer still validates


def test_f04s_parenthesised_id_becomes_a_label():
    rep = _replay(DEV2 / "F04.json").report
    assert "AEMO published a market notice reporting a planned outage of Directlink [c1]." in rep.summary


def test_the_live_records_are_unchanged():
    rec = json.loads((DEV2 / "F03.json").read_text())["report"]
    assert [c["citation_id"] for c in rec["citations"]] == ["market_notice_144693#0"]


# ------------------------------------------------------------------------------------------------ the mapping
def _report(citations: list[tuple[str, str]], lines: list[str], findings: list[tuple[str, str]] = ()):
    """A W19-shaped report with these (citation ID, passage ID) citations, summary lines and (citation ID, quote)
    findings."""
    base = _replay(DEV2 / "F03.json").report
    cites = [Citation(citation_id=cid, chunk_id=chunk, doc_id=chunk.split("#")[0], title="t", url="https://example.invalid",
                      doc_type="market_notice", quote="q", supports="test") for cid, chunk in citations]
    fs = [PublishedFinding(statement=f"An AEMO market notice for SA1 [{cid}] says: “{q}”", citation_ids=[cid],
                           doc_type="market_notice", applies_to_event=True) for cid, q in findings]
    validation = {k: v for k, v in base.validation.items() if k not in ("citation_labels", "display_rewrites")}
    return base.model_copy(update={"citations": cites, "summary": lines, "published_findings": fs,
                                   "headline": "Headline.", "possible_explanations": [], "uncertainties": [],
                                   "missing_evidence": [], "validation": validation})


def test_repeated_references_get_one_label():
    rep = _report([("doc_a#p1", "doc_a#p1")], ["First [doc_a#p1].", "Again [doc_a#p1] and (doc_a#p1)."])
    out, _ = plain_display(rep)
    assert out.summary == ["First [c1].", "Again [c1] and [c1]."]
    assert [c.citation_id for c in out.citations] == ["c1"]


def test_several_passages_of_one_document_get_their_own_labels():
    rep = _report([("aemo_so_op_3710#p7c12", "aemo_so_op_3710#p7c12"), ("aemo_so_op_3710#p8c14", "aemo_so_op_3710#p8c14")],
                  ["Rows [aemo_so_op_3710#p7c12]; review [aemo_so_op_3710#p8c14]."])
    out, _ = plain_display(rep)
    assert out.summary == ["Rows [c1]; review [c2]."]
    assert [(c.citation_id, c.chunk_id) for c in out.citations] == [("c1", "aemo_so_op_3710#p7c12"),
                                                                     ("c2", "aemo_so_op_3710#p8c14")]


def test_mixed_formats_reuse_existing_labels():
    """Existing labels stay; a raw ID takes the next unused number after them; a passage ID in the text maps to the one
    label citing that passage (held-out DOC03: "[mms_dm_elec22#DISPATCHREGIONSUM#0] [c3]")."""
    rep = _report([("c1", "doc_a#p1"), ("c3", "mms_dm_elec22#DISPATCHREGIONSUM#0"), ("doc_b#p2", "doc_b#p2")],
                  ["Field [mms_dm_elec22#DISPATCHREGIONSUM#0] [c3].", "Term [doc_a#p1], value [doc_b#p2], and [c1]."],
                  findings=[("doc_b#p2", "a quote")])
    out, _ = plain_display(rep)
    assert out.summary == ["Field [c3].", "Term [c1], value [c4], and [c1]."]
    assert [c.citation_id for c in out.citations] == ["c1", "c3", "c4"]
    assert out.published_findings[0].citation_ids == ["c4"] and "[c4]" in out.published_findings[0].statement
    assert out.validation["citation_labels"] == {"doc_b#p2": "c4"}


def test_lists_and_see_references():
    rep = _report([("doc_a#p1", "doc_a#p1"), ("doc_a#p2", "doc_a#p2")],
                  ["Defined there (see doc_a#p1; doc_a#p2).", "Both (doc_a#p1, doc_a#p2) agree."])
    out, _ = plain_display(rep)
    assert out.summary == ["Defined there (see [c1]; [c2]).", "Both ([c1], [c2]) agree."]


def test_unknown_or_ambiguous_ids_are_left_as_written():
    rep = _report([("c1", "doc_a#p1"), ("c2", "doc_a#p1"), ("doc_b#p2", "doc_b#p2")],
                  ["Unknown [made_up#p9]; shared passage [doc_a#p1]; known [doc_b#p2]."])
    out, _ = plain_display(rep)
    assert out.summary == ["Unknown [made_up#p9]; shared passage [doc_a#p1]; known [c3]."]  # nothing guessed


def test_source_ids_inside_quotations_are_unchanged():
    rep = _report([("doc_a#p1", "doc_a#p1")], ["The table says “see doc_a#p1 [doc_a#p1]” [doc_a#p1]."])
    out, _ = plain_display(rep)
    assert out.summary == ["The table says “see doc_a#p1 [doc_a#p1]” [c1]."]


def test_answers_already_using_labels_are_untouched():
    rep = _report([("c1", "doc_a#p1"), ("c2", "doc_b#p2")], ["One [c1]; two [c2]."])
    out, changed = plain_display(rep)
    assert out.summary == rep.summary and [c.citation_id for c in out.citations] == ["c1", "c2"]
    assert "citation_labels" not in out.validation and not changed


def test_short_labels_such_as_the_replay_controllers_are_kept():
    """The Replay controller labels citations s01, s02, …; a model may use its own short label. Only raw source IDs
    (passage ID, document ID, or a passage ID with a suffix) are relabelled, so these, and the evaluation records that
    show them, are unchanged."""
    rep = _report([("s01", "doc_a#p1"), ("c_doc1", "doc_b#p2"), ("doc_c#p3:def", "doc_c#p3")],
                  ["Replay [s01]; model label [c_doc1]; suffixed [doc_c#p3:def]."])
    out, _ = plain_display(rep)
    assert out.summary == ["Replay [s01]; model label [c_doc1]; suffixed [c1]."]
    assert [c.citation_id for c in out.citations] == ["s01", "c_doc1", "c1"]


def test_no_number_is_added_or_removed():
    rep = _report([("aemo_so_op_3710#p7c12", "aemo_so_op_3710#p7c12")],
                  ["“New South Wales 150” [aemo_so_op_3710#p7c12] is 150 MW over 2 periods."])
    out, _ = plain_display(rep)
    assert narrative_numbers(out.summary[0]) == narrative_numbers(rep.summary[0])


# ------------------------------------------------------------------------------------------------ scoring
def test_scoring_reads_the_same_passages_and_regions():
    """Gold-citation scoring reads doc_id and chunk_id; region scoring follows findings' citation_ids to citations."""
    res = _replay(DEV2 / "F03.json")
    rec = json.loads((DEV2 / "F03.json").read_text())["report"]
    shown = res.report
    assert sorted((c.doc_id, c.chunk_id) for c in shown.citations) == sorted((c["doc_id"], c["chunk_id"]) for c in rec["citations"])

    def regions(rep_findings, cites):
        by = {c.citation_id if hasattr(c, "citation_id") else c["citation_id"]: c for c in cites}
        return sorted(res.registry.chunks[(by[cid].chunk_id if hasattr(by[cid], "chunk_id") else by[cid]["chunk_id"])].event_region
                      for f in rep_findings for cid in (f.citation_ids if hasattr(f, "citation_ids") else f["citation_ids"]))
    assert regions(shown.published_findings, shown.citations) == regions(rec["published_findings"], rec["citations"])
