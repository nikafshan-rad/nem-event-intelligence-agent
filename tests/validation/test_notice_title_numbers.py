"""Issue I-6 (docs/issue-tracker.md): an exact title of a retrieved market notice is title text, not numbers.

Live check 2026-09-30, W19: the controller's cancellation sentence was correct, but the model's own lines named the
notices by their titles in single quotes ('STPASA - Forecast Lack Of Reserve Level 2 (LOR2) in the SA Region on
29/07/2026'). The numeric check read the "2" of "Level 2" as an untracked number, and the "1" of a LOR1 title tied its
line to an unrelated one-interval claim, so the answer fell back and nothing was shown.

Now only an exact, whole title of an eligible, unflagged market notice retrieved in this request, of at least four
words, is removed before numbers are read. A number outside the title, an altered, shortened or invented title, the
title of a notice not retrieved, ineligible or flagged, and every numeric claim are checked as before. The notice
titles are AEMO's; the extra chunks and lines are test fixtures.
"""

from __future__ import annotations

import copy

import pytest

from nem_agent.agent.request import InvestigateRequest
from nem_agent.evidence import ChunkItem
from nem_agent.report import NumericClaim
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


# ------------------------------------------------------------------------------------------------ the titles
def test_titles_are_the_notices_own_titles_of_eligible_unflagged_retrieved_notices():
    from nem_agent.evidence import EvidenceRegistry
    from nem_agent.validation import notice_titles

    reg = EvidenceRegistry()
    for c in (_chunk(1, LOR2), _chunk(2, LOR1, eligible=False), _chunk(3, LOR2_CANCEL, flagged=True),
              _chunk(4, "Demand Level 2 definition page", doc_type="definition"), _chunk(5, "Level 2 (LOR2)")):
        reg.add_chunk(c)
    assert notice_titles(reg) == {LOR2}  # prefix removed; ineligible, flagged, non-notice and short titles left out


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


def _codes(res, line: str, chunks: list[ChunkItem], claims: list[NumericClaim] = ()) -> set[str]:
    reg = copy.deepcopy(res.registry)
    for c in chunks:
        reg.add_chunk(c)
    rep = res.report.model_copy(update={"summary": [*res.report.summary, line],
                                        "numeric_claims": [*res.report.numeric_claims, *claims]})
    return {x.code for x in validate(rep, reg, records=res.records).violations if x.severity == "critical"}


LINE = f"Market notice timing: the notice titled '{LOR2}' was issued before the price extreme."


def test_a_line_naming_a_retrieved_notice_by_its_exact_title_passes(answer):
    assert "NUMERIC_UNTRACKED" not in _codes(answer, LINE, [_chunk(144624, LOR2)])


@pytest.mark.parametrize("chunks,why", [
    ([], "not retrieved in this request"),
    ([_chunk(144624, LOR2, eligible=False)], "retrieved but not eligible"),
    ([_chunk(144624, LOR2, flagged=True)], "flagged as instruction-like"),
])
def test_the_title_of_a_notice_not_usable_as_evidence_gives_no_cover(answer, chunks, why):
    assert "NUMERIC_UNTRACKED" in _codes(answer, LINE, chunks), why


def test_numbers_outside_the_title_and_altered_titles_are_still_untracked(answer):
    chunks = [_chunk(144624, LOR2)]
    assert "NUMERIC_UNTRACKED" in _codes(answer, LINE.replace("was issued", "reported 2 MW short and was issued"), chunks)
    assert "NUMERIC_UNTRACKED" in _codes(answer, LINE.replace("Level 2 (LOR2)", "Level 3 (LOR3)"), chunks)


def test_numeric_claims_are_checked_as_before(answer):
    """A claim of the title's "2" is still a claim: its value must match its evidence."""
    ev = answer.report.numeric_claims[0].evidence_id
    claim = NumericClaim(claim_id="t1", text="Level 2", value=2.0, unit="$/MWh", evidence_id=ev)
    assert "CLAIM_VALUE_MISMATCH" in _codes(answer, LINE, [_chunk(144624, LOR2)], [claim])
    ghost = claim.model_copy(update={"evidence_id": "ev9999"})
    assert "CLAIM_EVIDENCE_MISSING" in _codes(answer, LINE, [_chunk(144624, LOR2)], [ghost])
