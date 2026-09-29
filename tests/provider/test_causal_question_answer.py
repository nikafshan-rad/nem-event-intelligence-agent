"""Issue I-1a (docs/issue-tracker.md): a question asking whether a notice-reported incident explains a price event
gets a direct answer from the evidence.

Live check 2026-09-29, F04: "Was Directlink being out of service what drove the NSW1 price spike …?" The answer
listed correct observations and hedged possibilities but never answered. Two causes:
1. the question was not recognised as asking whether a notice-reported incident explains the event, because "being out
   of service" matched no incident word;
2. even where it is recognised (H13, W18), the notice timing is stated and never turned into what it supports.

The controller now opens the summary with one sentence built from the notice that names what the question names. If
that notice's earliest stated time is after the price extreme, timing rules the incident out. Otherwise the records
cannot settle it. The replays use saved tool calls and model drafts through the SYNTHETIC fake transport (no network,
no key); controls get no sentence.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from nem_agent.agent.request import InvestigateRequest, asks_if_notice_event_caused
from nem_agent.service import investigate
from nem_agent.validation import CAUSAL_RE, HYPOTHETICAL_RE
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

LIVE = Path(__file__).resolve().parents[2] / "artifacts" / "live"
F04 = LIVE / "live-check-2026-09-29" / "F04.json"
OPENERS = ("Timing rules this out:", "The records cannot settle this:")


def _replay(path: Path, question: str | None = None):
    """A saved Live record's tool calls and its final model draft (repaired where the run repaired)."""
    rec = json.loads(path.read_text())
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"])
             for t in rec["tools"] if t["call_id"] != "controller_question_retrieval" and t["status"] != "blocked"]
    drafts: dict[str, Any] = rec["drafts"]
    draft = drafts.get("repair:draft") or drafts["synthesis:draft"]
    fake = FakeModel(rec["route"], [calls], lambda kw: copy.deepcopy(draft))
    return investigate(InvestigateRequest(question=question or rec["question"], mode="live"), live_client=fake,
                       write_trace=False)


def _critical(res) -> set[str]:
    v = res.report.validation
    if v.get("repair_attempted"):
        return set(v.get("pre_repair_codes") or [])
    return {x["code"] for x in v["initial"]["violations"] if x["severity"] == "critical"}


def _answer(res) -> str | None:
    return next((e["text"] for e in res.trace.events if e["name"] == "timing_answer"), None)


# ------------------------------------------------------------------------------------------------ recognition
def test_out_of_service_is_an_incident_but_offline_for_commercial_reasons_is_not():
    q = json.loads(F04.read_text())["question"]
    assert asks_if_notice_event_caused(q)
    assert asks_if_notice_event_caused("Was Basslink being back in service behind the fall in Tasmanian prices?")
    assert not asks_if_notice_event_caused("Origin kept an Eraring unit offline for commercial reasons. Did that "
                                           "decision lift NSW1 evening prices?")  # a blind negative, unchanged


# ------------------------------------------------------------------------------------------------ the answers
def test_f04_gets_a_direct_answer_the_evidence_supports():
    """The Directlink outage began at 0700 hrs 27/07 and ran past the 07:30 AEST price extreme on 31/07: timing does
    not rule it out, and nothing retrieved shows whether it was behind the price (insufficient evidence)."""
    res = _replay(F04)
    rep = res.report
    assert _critical(res) == set() and not rep.validation["fallback_applied"], rep.validation
    first = rep.summary[0]
    assert first == _answer(res) and first.startswith("The records cannot settle this:")
    assert "mentions Directlink" in first and "2026-07-27 07:00 AEST (2026-07-26T21:00:00Z)" in first
    assert "before the price extreme (interval ending 2026-07-30T21:30:00Z = 2026-07-31 07:30 AEST)" in first
    assert "does not rule it out" in first and "Avon" not in first
    assert rep.status == "answered_with_caveats"


def test_a_timing_contradiction_reads_differently():
    """W18: the Hazelwood bus-tie outage is timed 11:00 AEST, after the 09:10 AEST price extreme."""
    res = _replay(LIVE / "L3-holdout-v4" / "W18.json")
    rep = res.report
    assert _critical(res) == set() and not rep.validation["fallback_applied"], rep.validation
    assert rep.summary[0].startswith("Timing rules this out:") and "mentions Hazelwood" in rep.summary[0]
    assert "after the price extreme (interval ending 2026-08-19T23:10:00Z = 2026-08-20 09:10 AEST)" in rep.summary[0]


def test_the_sentence_meets_the_notice_timing_requirement():
    """H13's old draft (held-out v2) never set the notice's time against the event; the opening sentence now does.
    Its other findings are the draft's own and unchanged."""
    res = _replay(LIVE / "L3-holdout-v2" / "H13.json")
    assert _answer(res).startswith("Timing rules this out:") and "NOTICE_TIMING_OMITTED" not in _critical(res)


@pytest.mark.parametrize("path,question", [
    (LIVE / "L3-holdout-v4" / "W01.json", None),   # not causal
    (LIVE / "L3-holdout-v4" / "W02.json", None),
    (LIVE / "L3-holdout-v4" / "W03.json", None),
    (LIVE / "L3-holdout-v4" / "W19.json", None),   # causal, but names nothing: its "reserve" notices include a cancellation
    (F04, "Was the cold morning weather what drove the NSW1 price spike near 7:30 am market time on 31 July 2026?"),
    (F04, "Was Basslink being out of service what drove the NSW1 price spike near 7:30 am market time on 31 July "
          "2026?"),                                  # causal, but no retrieved notice names Basslink
])
def test_no_sentence_where_the_evidence_gives_none(path, question):
    res = _replay(path, question)
    assert _answer(res) is None and not any(s.startswith(OPENERS) for s in res.report.summary)


def test_the_sentences_use_no_causal_or_hypothetical_wording_in_their_timing_statement():
    """The validator rejects causal wording outside hypotheses and skips any timing sentence with 'whether' or 'if'."""
    for path in (F04, LIVE / "L3-holdout-v4" / "W18.json"):
        text = _answer(_replay(path))
        assert not CAUSAL_RE.search(text), text
        assert not HYPOTHETICAL_RE.search(text.split(". ")[0]), text


def test_a_violation_on_the_controller_sentence_asks_for_a_full_repair():
    from types import SimpleNamespace

    from nem_agent.agent.live import ModelReport, repair_targets

    m = ModelReport.model_validate({"status": "answered", "headline": "h", "summary": ["model line"], "document_statements": [],
                                    "observation_evidence_ids": [], "numeric_claims": [], "possible_explanations": [],
                                    "published_findings": [], "citations": [], "uncertainties": [],
                                    "missing_evidence": [], "forecast_mae_evidence_id": None})
    result = SimpleNamespace(critical=[SimpleNamespace(code="X", detail="summary[0]: something")])
    targets, unmapped = repair_targets(result, m, [("controller", 0), ("summary", 0)])
    assert targets == set() and unmapped == ["X"]
