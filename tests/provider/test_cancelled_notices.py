"""Issue I-1b (docs/issue-tracker.md): an answer states that a cited notice was cancelled, and never relies on a cancelled
forecast as active.

Held-out v4 W19 asked whether SA's reserve position explained the $845/MWh price at 17:25 ACST on 29/07/2026. AEMO had
forecast lack of reserve for that day three times (notices 144624, 144627 and 144652). Each forecast was cancelled on
27 or 28/07, as the pinned notices 144626, 144628 and 144655 show. The answer listed the cancellation notices only as
timing items, never said a forecast was cancelled, and two of its hypotheses relied on the cancelled forecasts. The query
had also missed 144626.

Now the retrieve tool marks each returned notice that a later eligible notice cancels, and adds that notice. The
controller states the cancellations of cited notices. The validator rejects a hypothesis that rests on a cancelled notice
without saying so. Replays use saved records through the SYNTHETIC fake transport (no network, no key); SYNTHETIC notices
are labelled.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from nem_agent.agent.request import InvestigateRequest
from nem_agent.retrieval.corpus import cancelled_notices
from nem_agent.service import investigate
from nem_agent.validation import CAUSAL_RE, validate
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

LIVE = Path(__file__).resolve().parents[2] / "artifacts" / "live"
W19 = json.loads((LIVE / "L3-holdout-v4" / "W19.json").read_text())
W19_RETRIEVE = next(t["args"] for t in W19["tools"] if t["name"] == "retrieve_public_evidence")


# ------------------------------------------------------------------------------------------------ the notices say so
@pytest.mark.parametrize("title,text,cancels", [
    ("STPASA - Cancellation of the Forecast Lack Of Reserve Level 2 (LOR2) in the SA Region on 29/07/2026",
     "The Forecast LOR2 condition in the SA region advised in AEMO Electricity Market Notice No. 144624 is cancelled at "
     "0920 hrs 27/07/2026.", ["144624"]),
    ("Cancellation: Direction issued to: AGL SA Generation Pty Limited - TORRB2 TORRENS ISLAN",
     "Refer to Market Notice 144636 Direction is cancelled from: 1730 hrs 27/07/2026", ["144636"]),
    ("NEGRES CONSTRAINT NRM_TAS1_VIC1 ceased", "CANCELLATION - ACTUAL NEGATIVE SETTLEMENT RESIDUES - TAS to VIC. Refer to "
     "market notice: 144637 AEMO has ceased taking action", ["144637"]),
    ("STPASA - Forecast Lack Of Reserve Level 2 (LOR2) in the SA Region on 29/07/2026",
     "AEMO declares a Forecast LOR2 condition … From 1030 hrs 29/07/2026 to 1200 hrs 29/07/2026.", []),
    ("Direction - in SA region to AGL SA Generation Pty Limited", "Refer to Market Notice 144629 In accordance with "
     "section 116 of the National Electricity Law, AEMO is issuing a direction", []),           # refers, cancels nothing
    ("Prices for interval 27-Jul-2026 18:35 are now confirmed", "In accordance with Market Notice 144638 AEMO has "
     "reviewed this trading interval … Prices remain unchanged.", []),
])
def test_a_notice_cancels_only_what_it_says_it_cancels(title, text, cancels):
    assert cancelled_notices(title, text) == cancels


# ------------------------------------------------------------------------------------------------ retrieval
def _retrieve(args: dict[str, Any]):
    from nem_agent.agent.dispatcher import Dispatcher
    from nem_agent.evidence import EvidenceRegistry
    from nem_agent.selection import load_selection
    from nem_agent.store import Store
    from nem_agent.trace import Trace

    d = Dispatcher(Store(), load_selection(), Trace(), EvidenceRegistry(), "market_event_review")
    return {h["chunk_id"]: h for h in d.call("retrieve_public_evidence", args).view["results"]}


def test_w19_retrieval_marks_each_cancelled_forecast_and_adds_the_missed_cancellation():
    got = _retrieve(W19_RETRIEVE)
    assert {c: (got[c].get("cancelled_by") or {}).get("chunk_id") for c in
            ("market_notice_144624#0", "market_notice_144627#0", "market_notice_144652#0")} == {
        "market_notice_144624#0": "market_notice_144626#0", "market_notice_144627#0": "market_notice_144628#0",
        "market_notice_144652#0": "market_notice_144655#0"}
    assert "market_notice_144626#0" in got  # the model's query had missed it
    assert got["market_notice_144649#0"].get("cancelled_by") is None  # the MT PASA notice was never cancelled


def test_a_forecast_still_active_as_of_a_time_shows_no_later_cancellation():
    """As of 23:00Z on 26/07, forecast 144624 (issued 21:51Z) was public and its cancellation (23:27Z) was not."""
    got = _retrieve(W19_RETRIEVE | {"as_of_utc": "2026-07-26T23:00:00Z"})
    assert got["market_notice_144624#0"].get("cancelled_by") is None and "market_notice_144626#0" not in got


# ------------------------------------------------------------------------------------------------ the validator
@pytest.fixture(scope="module")
def event_answer(selection):
    from nem_agent.evaluation.adversarial import _base

    return _base(selection)  # the replay SA1 event answer the safety suite corrupts (price extreme 2026-07-30T16:35Z)


def _notice(n: int, text: str, published: str):
    from nem_agent.evidence import ChunkItem

    return ChunkItem(chunk_id=f"market_notice_{n}#0", doc_id=f"market_notice_{n}", title=f"SYNTHETIC notice {n}",
                     url="https://nemweb.com.au/SYNTHETIC", text=text, section="RESERVE NOTICE", page=None,
                     publication_date=published, doc_type="market_notice", event_region="SA1", event_date="2026-07-30",
                     eligible=True, eligibility_reason="synthetic", tool_call_id="call-t")


FORECAST = "SYNTHETIC. AEMO declares a Forecast LOR2 condition for the SA region from 1600 hrs to 1630 hrs 30/07/2026."
CANCEL = "SYNTHETIC. The Forecast LOR2 condition advised in AEMO Electricity Market Notice No. 990001 is cancelled."


def _codes(res, statement: str, cancel_published: str | None) -> set[str]:
    from nem_agent.report import Citation, Hypothesis

    reg = copy.deepcopy(res.registry)
    reg.add_chunk(_notice(990001, FORECAST, "2026-07-29T02:00:00Z"))
    if cancel_published:
        reg.add_chunk(_notice(990002, CANCEL, cancel_published))
    cit = Citation(citation_id="f1", chunk_id="market_notice_990001#0", doc_id="market_notice_990001",
                   title="SYNTHETIC notice 990001", url="https://nemweb.com.au/SYNTHETIC", doc_type="market_notice",
                   quote="AEMO declares a Forecast LOR2 condition for the SA region", supports="t")
    h = Hypothesis(statement=statement, supporting_evidence_ids=[], what_would_test_it="compare offers")
    rep = res.report.model_copy(update={"citations": [*res.report.citations, cit],
                                        "possible_explanations": [*res.report.possible_explanations, h]})
    return {x.code for x in validate(rep, reg, records=res.records).violations if x.severity == "critical"}


RELIES = "Tight reserves, as the forecast in [f1] indicated, may have left only higher-priced offers."


def test_a_hypothesis_resting_on_a_forecast_cancelled_before_the_extreme_fails(event_answer):
    assert "CANCELLED_NOTICE_AS_ACTIVE" in _codes(event_answer, RELIES, "2026-07-29T05:00:00Z")


@pytest.mark.parametrize("statement,cancel_published", [
    (RELIES, None),                                    # an active forecast: never cancelled
    (RELIES, "2026-07-31T01:00:00Z"),                  # cancelled only after the price extreme
    ("The forecast in [f1], later cancelled, may still have shaped offers made before it was cancelled.",
     "2026-07-29T05:00:00Z"),                          # says it was cancelled
])
def test_active_or_acknowledged_forecasts_pass(event_answer, statement, cancel_published):
    assert "CANCELLED_NOTICE_AS_ACTIVE" not in _codes(event_answer, statement, cancel_published)


# ------------------------------------------------------------------------------------------------ the live controller
def _replay(path: Path, question: str | None = None, repair: dict[str, Any] | None = None, final: bool = False):
    rec = json.loads(path.read_text())
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"])
             for t in rec["tools"] if t["call_id"] != "controller_question_retrieval" and t["status"] != "blocked"]
    drafts = rec["drafts"]
    draft = (drafts.get("repair:draft") if final else None) or drafts["synthesis:draft"]
    fake = FakeModel(rec["route"], [calls], lambda kw: copy.deepcopy(draft),
                     (lambda kw: copy.deepcopy(repair)) if repair else None)
    return investigate(InvestigateRequest(question=question or rec["question"], mode="live"), live_client=fake,
                       write_trace=False)


def _said(res, name: str) -> str | None:
    return next((e["text"] for e in res.trace.events if e["name"] == name), None)


DROP_TWO = {"edits": [{"target": f"possible_explanations[{i}]", "action": "delete", "text": None, "statement": None,
                       "claim": None, "citation": None} for i in (0, 1)], "new_numeric_claims": [], "new_citations": []}


def test_w19_hypotheses_resting_on_cancelled_forecasts_fail_closed():
    res = _replay(LIVE / "L3-holdout-v4" / "W19.json")
    v = res.report.validation
    bad = {x["detail"].split(":")[0] for x in v["pre_repair"]["violations"] if x["code"] == "CANCELLED_NOTICE_AS_ACTIVE"}
    assert bad == {"possible_explanations[0]", "possible_explanations[1]"}  # the third cites no notice
    assert v["fallback_applied"] and v["final_passed"]


def test_w19_answer_states_each_cancellation_with_issue_and_cancellation_times():
    res = _replay(LIVE / "L3-holdout-v4" / "W19.json", repair=DROP_TWO)
    rep = res.report
    assert not rep.validation["fallback_applied"] and rep.validation["final_passed"], rep.validation
    first = rep.summary[0]
    assert first == _said(res, "cancellation_answer") and first.startswith("AEMO later cancelled")
    assert "before the price extreme (interval ending 2026-07-29T07:55:00Z = 2026-07-29 17:25 ACST)" in first
    for issued, cancelled in (("2026-07-27 07:21 ACST", "2026-07-27 08:57 ACST"),
                              ("2026-07-27 10:02 ACST", "2026-07-27 11:58 ACST"),
                              ("2026-07-28 12:45 ACST", "2026-07-28 13:14 ACST")):
        assert f"issued {issued}" in first and f"cancelled by one issued {cancelled}" in first
    assert not CAUSAL_RE.search(first)
    assert [h.statement for h in rep.possible_explanations] == [W19["drafts"]["synthesis:draft"][
        "possible_explanations"][2]["statement"]]


def test_the_timing_answer_never_treats_a_cancelled_forecast_as_the_incident():
    """A question naming the cancelled LOR2 forecast gets no 'cannot settle' timing sentence (I-1a), only the status."""
    res = _replay(LIVE / "L3-holdout-v4" / "W19.json", repair=DROP_TWO,
                  question="Was the forecast LOR2 condition behind SA's $845/MWh price on the evening of 29 July 2026?")
    assert _said(res, "timing_answer") is None and _said(res, "cancellation_answer")


@pytest.mark.parametrize("name", ["W01", "W02", "W03", "W18"])
def test_answers_citing_no_cancelled_notice_are_unchanged(name):
    res = _replay(LIVE / "L3-holdout-v4" / f"{name}.json", final=True)
    assert _said(res, "cancellation_answer") is None
    assert not any(s.startswith("AEMO later cancelled") for s in res.report.summary)
    assert "CANCELLED_NOTICE_AS_ACTIVE" not in {x["code"] for x in res.report.validation["initial"]["violations"]}
