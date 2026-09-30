"""Issue I-7 (docs/issue-tracker.md): a hypothesis may not rest on a cited notice that its own timing rules out.

Live check 2026-09-30, W18: the answer opened with "Timing rules this out": the Hazelwood bus-tie notice gives 1100 hrs
20/08 (01:00Z), after all six of VIC1's high-price intervals (23:05Z–23:45Z on 19/08). Yet a hypothesis resting on that
notice [c1] still said the outage "might … could have influenced prices".

Now a possible explanation citing a same-region market notice whose earliest stated time is after every interval of
the event is rejected, when the prices are registered up to that time, unless it says the timing rules it out. Base:
W18's Live run replayed through the SYNTHETIC fake transport (its calls, first draft and repair patch, the patch
deleting the ruled-out hypothesis). The extra notices are test fixtures.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from nem_agent.agent.request import InvestigateRequest
from nem_agent.evidence import ChunkItem
from nem_agent.report import Citation, Hypothesis
from nem_agent.service import investigate
from nem_agent.validation import validate
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

RUN = Path(__file__).resolve().parents[2] / "artifacts" / "live" / "live-check-p1-dev"
CODE = "EXPLANATION_RULED_OUT_BY_TIMING"
LIVE_HYPOTHESIS = ("A binding network constraint or transfer limit change (the Hazelwood bus‑tie notice [c1]) might have "
                   "limited local transfer capability and so could have influenced prices; however the retrieved notice "
                   "records the outage at 2026-08-20 11:00 AEST (2026-08-20T01:00:00Z).")


@pytest.fixture(scope="module")
def w18():
    rec = json.loads((RUN / "W18.json").read_text())
    trace = json.loads((RUN / "traces" / f"{rec['score']['trace_id']}.json").read_text())
    patch = next(e for e in trace["events"] if e["name"] == "repair:scoped")["patch"]
    patch = {**patch, "edits": [e for e in patch["edits"] if not e["target"].startswith("possible_explanations[1]")] +
             [{"target": "possible_explanations[1]", "action": "delete", "text": None, "statement": None, "claim": None,
               "citation": None}]}
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    fake = FakeModel(rec["route"], [calls], lambda kw: copy.deepcopy(rec["drafts"]["synthesis:draft"]),
                     lambda kw: copy.deepcopy(patch))
    res = investigate(InvestigateRequest(question=rec["question"], mode="live"), live_client=fake, write_trace=False)
    assert not res.report.validation["fallback_applied"] and res.report.validation["final_passed"]
    return res


def _notice(n: int, text: str, region: str = "VIC1") -> ChunkItem:
    return ChunkItem(chunk_id=f"market_notice_{n}#0", doc_id=f"market_notice_{n}",
                     title=f"AEMO market notice {n} (POWER SYSTEM EVENTS): test fixture", url=f"https://example.invalid/{n}",
                     text=text, section="POWER SYSTEM EVENTS", page=None, publication_date="2026-08-19T00:00:00Z",
                     doc_type="market_notice", event_region=region, event_date="2026-08-20", eligible=True,
                     eligibility_reason="test fixture", tool_call_id="call-t")


def _codes(res, statement: str, notices: list[ChunkItem] = (), *, drop_prices_after: str | None = None) -> list[str]:
    """W18's answer plus one hypothesis; each fixture notice is cited as [t<n>]."""
    reg = copy.deepcopy(res.registry)
    for ch in notices:
        reg.add_chunk(ch)
    if drop_prices_after:  # prices registered only up to this time
        reg.items = {k: v for k, v in reg.items.items() if not (v.metric == "dispatch_rrp" and v.valid_at_utc
                                                                 and v.valid_at_utc > drop_prices_after)}
    cites = [Citation(citation_id=f"t{ch.doc_id.rsplit('_', 1)[1]}", chunk_id=ch.chunk_id, doc_id=ch.doc_id, title=ch.title,
                      url=ch.url, doc_type="market_notice", quote=ch.text[:60], supports="test fixture") for ch in notices]
    hyp = Hypothesis(statement=statement, supporting_evidence_ids=[], what_would_test_it="Check the constraint logs.")
    rep = res.report.model_copy(update={"possible_explanations": [*res.report.possible_explanations, hyp],
                                        "citations": [*res.report.citations, *cites]})
    return [v.detail for v in validate(rep, reg, records=res.records).violations if v.code == CODE]


# ------------------------------------------------------------------------------------------------ W18 itself
def test_the_live_hypothesis_resting_on_the_hazelwood_notice_is_rejected(w18):
    found = _codes(w18, LIVE_HYPOTHESIS)
    assert len(found) == 1 and "market_notice_144893#0 [c1]" in found[0] and "2026-08-20T01:00:00Z" in found[0]
    assert found[0].startswith(f"possible_explanations[{len(w18.report.possible_explanations)}]:")  # a scoped target


@pytest.mark.parametrize("statement", [
    "The Hazelwood bus-tie outage [c1] is ruled out by its timing: the notice gives 1100 hrs, after every interval.",
    "Timing rules this out: the Hazelwood notice [c1] reports an outage that came after the high prices.",
    "The Hazelwood outage [c1] could not have caused the price, as it came later.",
])
def test_saying_the_timing_rules_it_out_is_allowed(w18, statement):
    assert _codes(w18, statement) == []


def test_unrelated_hypotheses_are_untouched(w18):
    assert _codes(w18, "Rebidding by marginal units [ev0437] may have raised the price.") == []
    assert _codes(w18, w18.report.possible_explanations[0].statement) == []  # W18's own, kept by the repair


# ------------------------------------------------------------------------------------------------ controls
HYP = "The outage in the notice [t{}] might have tightened supply and could have influenced prices."


@pytest.mark.parametrize("n,text,why", [
    (801, "At 0700 hrs 19/08/2026 there was a planned outage of a 220 kV line in the VIC region.",
     "an incident before the event"),
    (802, "At 0925 hrs 20/08/2026 there was a short notice outage of a 220 kV line in the VIC region.",
     "after the price extreme, but before later high-price intervals (23:35Z, 23:45Z)"),
    (803, "A short notice outage of a 220 kV line in the VIC region, time to be advised.", "no stated time"),
])
def test_timing_that_does_not_rule_it_out_is_left_alone(w18, n, text, why):
    assert _codes(w18, HYP.format(n), [_notice(n, text)]) == [], why


def test_a_later_notice_is_left_alone_when_prices_are_not_registered_up_to_it(w18):
    later = _notice(804, "At 1100 hrs 20/08/2026 there was a short notice outage of a 220 kV line in the VIC region.")
    assert _codes(w18, HYP.format(804), [later]) != []  # with W18's prices: after every interval
    assert _codes(w18, HYP.format(804), [later], drop_prices_after="2026-08-19T23:50:00Z") == []  # not known up to it


def test_another_regions_notice_is_left_alone(w18):
    nsw = _notice(805, "At 1100 hrs 20/08/2026 there was a short notice outage of a 330 kV line in the NSW region.",
                  region="NSW1")
    assert _codes(w18, HYP.format(805), [nsw]) == []
