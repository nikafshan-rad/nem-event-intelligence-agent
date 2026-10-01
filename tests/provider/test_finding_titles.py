"""Issue I-3f (docs/issue-tracker.md): separate findings with the same wording are told apart, not merged.

Live, second development check (2026-09-30), W19: eight findings, each "An AEMO market notice for SA1 [cN] says: “…”".
[c2] and [c3] showed the same STPASA LOR2 forecast title, and [c4], [c7] and [c8] the same cancellation title. They are
five different notices (144627, 144624; 144628, 144626, 144623), but read as repeats.

Now, after validation, a finding quoting the same words as an earlier one from a different passage is kept and marked
"(A separate notice, with the same wording as [c2].)". Only a finding citing the same passage with the same quote, one
finding shown twice, is shown once with all its citations. Replays use saved Live records through the SYNTHETIC fake
transport (no network, no key).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from nem_agent.agent.request import InvestigateRequest
from nem_agent.evaluation.runner import CAUSAL, _narrative_without_quotes_and_hypotheses
from nem_agent.report import Citation, PublishedFinding
from nem_agent.service import investigate
from nem_agent.validation import QUOTED_RE, narrative_numbers, validate
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

DEV2 = Path(__file__).resolve().parents[2] / "artifacts" / "live" / "live-check-dev2"
LOR2 = "“STPASA - Forecast Lack Of Reserve Level 2 (LOR2) in the SA Region on 29/07/2026.”"
CANCEL = "“STPASA - Cancellation of the Forecast Lack Of Reserve Level 2 (LOR2) in the SA Region on 29/07/2026.”"


def plain_display(report):
    from nem_agent.display import plain_display as display

    return display(report)


def _replay(path: Path):
    """A saved run's first draft and actual saved repair through the fake transport."""
    rec = json.loads(path.read_text())
    trace = json.loads((path.parent / "traces" / f"{rec['score']['trace_id']}.json").read_text())
    draft = next(e for e in trace["events"] if e["name"] == "synthesis:draft")["report"]
    patch = next(e for e in trace["events"] if e["name"] == "repair:scoped")["patch"]
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    fake = FakeModel(rec["route"], [calls], lambda kw: copy.deepcopy(draft), lambda kw: copy.deepcopy(patch))
    return investigate(InvestigateRequest(question=rec["question"], mode="live"), live_client=fake, write_trace=False)


@pytest.fixture(scope="module")
def w19():
    return _replay(DEV2 / "W19.json")


# ------------------------------------------------------------------------------------------------ the saved example
def test_w19s_eight_findings_are_all_kept_and_told_apart(w19):
    rep, v = w19.report, w19.report.validation
    assert v["final_passed"] and not v["fallback_applied"]  # validation as before
    ids = [f.citation_ids for f in rep.published_findings]
    assert ids == [[f"c{i}"] for i in range(1, 9)]  # every finding and citation kept, in order
    by = {f.citation_ids[0]: f.statement for f in rep.published_findings}
    assert by["c2"] == f"An AEMO market notice for SA1 [c2] says: {LOR2}"
    assert by["c3"] == f"An AEMO market notice for SA1 [c3] says: {LOR2} (A separate notice, with the same wording as [c2].)"
    assert by["c4"] == f"An AEMO market notice for SA1 [c4] says: {CANCEL}"
    for c in ("c7", "c8"):
        assert by[c] == f"An AEMO market notice for SA1 [{c}] says: {CANCEL} (A separate notice, with the same wording as [c4].)"
    chunks = {c.citation_id: c.chunk_id for c in rep.citations}
    assert len({chunks[f"c{i}"] for i in (2, 3, 4, 7, 8)}) == 5  # five different notices
    originals = {r["where"]: r["original"] for r in v["display_rewrites"]}
    assert originals["published_findings[2]"] == f"An AEMO market notice for SA1 [c3] says: {LOR2}"  # kept


def test_the_displayed_answer_still_validates_and_scores_the_same(w19):
    rep = w19.report
    assert not validate(rep, w19.registry, records=w19.records).critical
    rec = json.loads((DEV2 / "W19.json").read_text())["report"]  # the Live record, before this display step
    shown = rep.model_dump()
    assert len(CAUSAL.findall(_narrative_without_quotes_and_hypotheses(shown))) == \
        len(CAUSAL.findall(_narrative_without_quotes_and_hypotheses(rec)))
    assert [f["citation_ids"] for f in shown["published_findings"]] == [f["citation_ids"] for f in rec["published_findings"]]
    for f in rep.published_findings:  # quotes and numbers unchanged
        orig = next(x for x in rec["published_findings"] if x["citation_ids"] == f.citation_ids)["statement"]
        assert QUOTED_RE.findall(f.statement) == QUOTED_RE.findall(orig)
        assert narrative_numbers(f.statement) == narrative_numbers(orig)


# ------------------------------------------------------------------------------------------------ controls
def _with(res, findings: list[tuple[str, str, str, str]], *, region: str = "SA1"):
    """``findings``: (citation ID, chunk ID, quote, region). Citations are built from the registry's chunk IDs."""
    cites, out = [], []
    for cid, chunk, quote, reg in findings:
        ch = res.registry.chunks.get(chunk)
        cites.append(Citation(citation_id=cid, chunk_id=chunk, doc_id=chunk.split("#")[0], title=ch.title if ch else "t",
                              url="https://example.invalid", doc_type="market_notice", quote=quote, supports="test"))
        out.append(PublishedFinding(statement=f"An AEMO market notice for {reg} [{cid}] says: “{quote}”",
                                    citation_ids=[cid], doc_type="market_notice", applies_to_event=True))
    return res.report.model_copy(update={"citations": cites, "published_findings": out})


Q = "STPASA - Forecast Lack Of Reserve Level 2 (LOR2) in the SA Region on 29/07/2026."


@pytest.mark.parametrize("second,why", [
    (("x2", "market_notice_144624#0", Q, "SA1"), "different evidence (another notice) and a different time"),
    (("x2", "market_notice_144624#0", Q, "VIC1"), "a different region in the finding"),
])
def test_identical_wording_from_different_passages_is_kept_and_marked(w19, second, why):
    rep = _with(w19, [("x1", "market_notice_144627#0", Q, "SA1"), second])
    out, changed = plain_display(rep)
    assert [f.citation_ids for f in out.published_findings] == [["x1"], ["x2"]], why
    assert out.published_findings[0].statement == rep.published_findings[0].statement
    assert out.published_findings[1].statement.endswith(f"“{Q}” (A separate notice, with the same wording as [x1].)")
    assert [c["original"] for c in changed if c["where"] == "published_findings[1]"] == [rep.published_findings[1].statement]


def test_one_passage_quoted_twice_with_different_words_is_unchanged(w19):
    """2026-09-29 F03: two findings from notice 144693, each quoting a different sentence."""
    rep = _with(w19, [("x1", "market_notice_144627#0", Q, "SA1"),
                      ("x2", "market_notice_144627#0", "STPASA - a different sentence of the same notice.", "SA1")])
    out, _ = plain_display(rep)
    assert [f.statement for f in out.published_findings] == [f.statement for f in rep.published_findings]


def test_one_finding_repeated_is_shown_once_with_all_its_citations(w19):
    rep = _with(w19, [("x1", "market_notice_144627#0", Q, "SA1"), ("x2", "market_notice_144624#0", Q, "SA1"),
                      ("x3", "market_notice_144627#0", Q, "SA1")])
    out, changed = plain_display(rep)
    assert [f.citation_ids for f in out.published_findings] == [["x1", "x3"], ["x2"]]
    assert out.published_findings[0].statement == f"An AEMO market notice for SA1 [x1] [x3] says: “{Q}”"
    assert out.published_findings[1].statement.endswith("(A separate notice, with the same wording as [x1].)")
    hidden = next(c for c in changed if c["where"] == "published_findings[2]")
    assert hidden["shown"] is False and hidden["original"] == rep.published_findings[2].statement
    assert {c for f in out.published_findings for c in f.citation_ids} == {"x1", "x2", "x3"}  # no citation lost


def test_different_wording_is_unchanged(w19):
    rep = _with(w19, [("x1", "market_notice_144627#0", Q, "SA1"),
                      ("x2", "market_notice_144624#0", "STPASA - Cancellation of the Forecast LOR2.", "SA1")])
    out, changed = plain_display(rep)
    assert [f.statement for f in out.published_findings] == [f.statement for f in rep.published_findings]
    assert not [c for c in changed if c["where"].startswith("published_findings")]
