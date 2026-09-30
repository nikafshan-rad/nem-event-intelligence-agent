"""Issue I-6 (docs/issue-tracker.md): an exact title of a cited market notice is title text, not numbers.

Live check 2026-09-30, W19: the controller's cancellation sentence was correct, but the model's own lines named the
notices by their titles in single quotes ('STPASA - Forecast Lack Of Reserve Level 2 (LOR2) in the SA Region on
29/07/2026'). The numeric check read the "2" of "Level 2" as an untracked number, and the "1" of a LOR1 title tied its
line to an unrelated one-interval claim, so the answer fell back and nothing was shown.

Now only an exact, whole title of an eligible, unflagged market notice the report cites, of at least four words, is
removed before numbers are read. A line carrying citation markers must cite that notice itself (review of PR #21: a
retrieved but uncited notice, or a line citing another notice, gave the same cover). A number outside the title, an
altered, shortened or invented title, the title of a notice not retrieved, not cited, ineligible or flagged, and every
numeric claim are checked as before. The notice titles are AEMO's; the extra chunks and lines are test fixtures.
"""

from __future__ import annotations

import copy

import pytest

from nem_agent.agent.request import InvestigateRequest
from nem_agent.evidence import ChunkItem
from nem_agent.report import Citation, NumericClaim
from nem_agent.service import investigate
from nem_agent.validation import narrative_numbers, validate

LOR2 = "STPASA - Forecast Lack Of Reserve Level 2 (LOR2) in the SA Region on 29/07/2026"
LOR2_CANCEL = "STPASA - Cancellation of the Forecast Lack Of Reserve Level 2 (LOR2) in the SA Region on 29/07/2026"
LOR1 = "PDPASA - Forecast Lack Of Reserve Level 1 (LOR1) in the SA Region on 29/07/2026"


def _chunk(n: int, title: str, *, eligible: bool = True, flagged: bool = False,
           doc_type: str = "market_notice") -> ChunkItem:
    return ChunkItem(chunk_id=f"market_notice_{n}#0", doc_id=f"market_notice_{n}",
                     title=f"AEMO market notice {n} (RESERVE NOTICE): {title}", url=f"https://example.invalid/{n}",
                     text=f"{title}. AEMO ELECTRICITY MARKET NOTICE (test fixture).", section="RESERVE NOTICE", page=None,
                     publication_date="2026-07-26T21:51:13Z", doc_type=doc_type, event_region="SA1",
                     event_date="2026-07-29", eligible=eligible, eligibility_reason="test fixture", tool_call_id="call-t",
                     instruction_like=flagged)


def _cite(cid: str, n: int, title: str) -> Citation:
    return Citation(citation_id=cid, chunk_id=f"market_notice_{n}#0", doc_id=f"market_notice_{n}",
                    title=f"AEMO market notice {n} (RESERVE NOTICE): {title}", url=f"https://example.invalid/{n}",
                    doc_type="market_notice", quote=f"{title}.", supports="test fixture")


# ------------------------------------------------------------------------------------------------ the titles
def test_titles_are_the_notices_own_titles_of_eligible_unflagged_retrieved_notices():
    from nem_agent.evidence import EvidenceRegistry
    from nem_agent.validation import notice_titles

    reg = EvidenceRegistry()
    for c in (_chunk(1, LOR2), _chunk(2, LOR1, eligible=False), _chunk(3, LOR2_CANCEL, flagged=True),
              _chunk(4, "Demand Level 2 definition page", doc_type="definition"), _chunk(5, "Level 2 (LOR2)")):
        reg.add_chunk(c)
    assert notice_titles(reg, reg.chunks) == {LOR2}  # prefix removed; ineligible, flagged, non-notice, short left out
    assert notice_titles(reg, ["market_notice_5#0", "market_notice_9#0"]) == set()  # only the chunks given, if held


# ------------------------------------------------------------------------------------------------ the numbers
TITLES = frozenset({LOR2, LOR2_CANCEL, LOR1, "Reserve notice for SA Level 2"})


@pytest.mark.parametrize("text", [
    f"The notice titled '{LOR2}' lists 2026-07-29 10:00 ACST.",
    f"The notice {LOR2} lists 2026-07-29 10:00 ACST.",  # unquoted
    f"The notice titled '{LOR2.replace('-', chr(0x2011))}' lists 2026-07-29 10:00 ACST.",  # non-breaking hyphens
    f"'{LOR2_CANCEL}' cancelled '{LOR2}', and '{LOR1}' was cancelled later.",
])
def test_an_exact_title_is_title_text(text):
    assert narrative_numbers(text, titles=TITLES) == []


@pytest.mark.parametrize("text,numbers", [
    (f"The notice titled '{LOR2}' said reserves were 2 MW short.", [2.0]),  # a number outside the title
    (f"The notice titled '{LOR2.replace('Level 2 (LOR2)', 'Level 3 (LOR3)')}' lists 10:00.", [3.0]),  # altered digit
    (f"The notice titled '{LOR2.replace('SA Region', 'VIC Region')}' lists 10:00.", [2.0]),  # altered word
    ("The notice titled 'Forecast Lack Of Reserve Level 2 (LOR2)' lists 10:00.", [2.0]),  # shortened
    ("The notice titled 'SA reserve warning number 7 for July' lists 10:00.", [7.0]),  # invented
    ("The Reserve notice for SA Level 20 was issued.", [20.0]),  # a title is only removed whole, not inside a number
])
def test_anything_but_an_exact_title_is_still_read(text, numbers):
    assert narrative_numbers(text, titles=TITLES) == numbers


# ------------------------------------------------------------------------------------------------ the validator
@pytest.fixture(scope="module")
def answer():
    res = investigate(InvestigateRequest(question="What happened to SA1 prices on 29 July 2026?", mode="replay"),
                      write_trace=False)
    assert not validate(res.report, res.registry, records=res.records).critical
    assert not {2.0, 3.0} & {c.value for c in res.report.numeric_claims}
    return res


def _codes(res, line: str, chunks: list[ChunkItem], cites: list[Citation] = (), claims: list[NumericClaim] = ()) -> set[str]:
    reg = copy.deepcopy(res.registry)
    for c in chunks:
        reg.add_chunk(c)
    rep = res.report.model_copy(update={"summary": [*res.report.summary, line],
                                        "citations": [*res.report.citations, *cites],
                                        "numeric_claims": [*res.report.numeric_claims, *claims]})
    return {x.code for x in validate(rep, reg, records=res.records).violations if x.severity == "critical"}


LINE = f"Market notice timing: the notice titled '{LOR2}' was issued before the price extreme"
OTHER = "Inter-regional transfer limit variation - Heywood Interconnector - SA region - 29/07/2026"
BOTH = [_chunk(144624, LOR2), _chunk(900, OTHER)]
CITE_LOR2, CITE_OTHER = _cite("t1", 144624, LOR2), _cite("t9", 900, OTHER)


@pytest.mark.parametrize("line,cites", [
    (LINE + ".", [CITE_LOR2]),  # no marker: the report cites the titled notice (W19's lines)
    (LINE + " [t1].", [CITE_LOR2]),  # the line cites it
    (LINE + " [t9][t1].", [CITE_OTHER, CITE_LOR2]),  # the line cites it among others
    (LINE + " [market_notice_144624#0].", [CITE_LOR2]),  # by the cited passage's ID
    (LINE + " [ev0457].", [CITE_LOR2]),  # an evidence marker is not a citation
])
def test_a_title_supported_by_the_matching_cited_notice_is_title_text(answer, line, cites):
    assert "NUMERIC_UNTRACKED" not in _codes(answer, line, BOTH, cites)


@pytest.mark.parametrize("line,cites,why", [
    (LINE + ".", [], "retrieved, but not cited anywhere"),
    (LINE + ".", [CITE_OTHER], "retrieved; the report cites only another notice"),
    (LINE + " [t9].", [CITE_OTHER], "the line cites another notice"),
    (LINE + " [t9].", [CITE_OTHER, CITE_LOR2], "the line cites another notice; the titled one is cited elsewhere"),
    (LINE + " [c99].", [CITE_LOR2], "the line's marker points to nothing the report cites"),
    (LINE + " [market_notice_900#0].", [CITE_OTHER, CITE_LOR2], "the line names another cited passage"),
])
def test_a_title_without_the_matching_cited_notice_gives_no_cover(answer, line, cites, why):
    assert "NUMERIC_UNTRACKED" in _codes(answer, line, BOTH, cites), why


@pytest.mark.parametrize("chunk,why", [
    (None, "not retrieved in this request"),
    (_chunk(144624, LOR2, eligible=False), "retrieved but not eligible"),
    (_chunk(144624, LOR2, flagged=True), "flagged as instruction-like"),
])
def test_the_title_of_a_cited_notice_not_usable_as_evidence_gives_no_cover(answer, chunk, why):
    assert "NUMERIC_UNTRACKED" in _codes(answer, LINE + " [t1].", [chunk] if chunk else [], [CITE_LOR2]), why


def test_numbers_outside_the_title_and_altered_titles_are_still_untracked(answer):
    assert "NUMERIC_UNTRACKED" in _codes(answer, LINE + " and reported 2 MW short [t1].", BOTH, [CITE_LOR2])
    assert "NUMERIC_UNTRACKED" in _codes(answer, LINE.replace("Level 2 (LOR2)", "Level 3 (LOR3)") + " [t1].", BOTH,
                                         [CITE_LOR2])


def test_numeric_claims_are_checked_as_before(answer):
    """A claim of the title's "2" is still a claim: its value must match its evidence."""
    ev = answer.report.numeric_claims[0].evidence_id
    claim = NumericClaim(claim_id="t1", text="Level 2", value=2.0, unit="$/MWh", evidence_id=ev)
    assert "CLAIM_VALUE_MISMATCH" in _codes(answer, LINE + " [t1].", BOTH, [CITE_LOR2], [claim])
    ghost = claim.model_copy(update={"evidence_id": "ev9999"})
    assert "CLAIM_EVIDENCE_MISSING" in _codes(answer, LINE + " [t1].", BOTH, [CITE_LOR2], [ghost])
