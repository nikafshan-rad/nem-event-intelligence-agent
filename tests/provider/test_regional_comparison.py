"""Issue I-2a (docs/issue-tracker.md): an event question that is also about other regions gets their prices at the
price extreme, traced to source rows.

Live check 2026-09-29, F04 asked whether Directlink (the NSW–Queensland interconnector) being out of service drove the
NSW1 spike at 07:30 AEST on 31/07. The answer never compared regions. The model made one round of NSW1-only calls; the
price tool takes one region per call and is capped at 3 calls. In the approved dispatch file for that interval, SA1,
TAS1 and VIC1 were also above 470 $/MWh, while QLD1 was 64.95.

Now, for such a question (it names another region, uses inter-regional wording, or names something a retrieved
inter-regional-transfer notice names), the controller makes one bounded call for every region's price at the price
extreme's interval, under the request's as-of cutoff. The prices are shown as observations with their source rows, plus
one sentence without numbers saying which regions were also above or below the threshold. The model can neither see nor
call the tool, and `CLAIM_REGION_MISMATCH` is unchanged. Replays use saved records through the SYNTHETIC fake transport
(no network, no key).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from nem_agent.agent.request import InvestigateRequest
from nem_agent.service import investigate
from nem_agent.validation import CAUSAL_RE
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

LIVE = Path(__file__).resolve().parents[2] / "artifacts" / "live"
F04 = LIVE / "live-check-2026-09-29" / "F04.json"
PEAK = "2026-07-30T21:30:00Z"
ROWS = {"QLD1": ("L6", 64.95), "SA1": ("L7", 534.17438), "TAS1": ("L8", 478.08045), "VIC1": ("L9", 529.63)}


def _dispatcher(intent: str = "market_event_review"):
    from nem_agent.agent.dispatcher import Dispatcher
    from nem_agent.evidence import EvidenceRegistry
    from nem_agent.selection import load_selection
    from nem_agent.store import Store
    from nem_agent.trace import Trace

    return Dispatcher(Store(), load_selection(), Trace(), EvidenceRegistry(), intent)


# ------------------------------------------------------------------------------------------------ the tool
def test_every_region_at_one_interval_with_its_source_row():
    d = _dispatcher()
    rec = d.call("get_regional_prices", {"interval_end_utc": PEAK, "as_of_utc": None})
    got = {p["region"]: p for p in rec.view["prices"]}
    assert rec.status == "ok" and set(got) == {"NSW1", *ROWS}
    for region, (line, rrp) in ROWS.items():
        ev = d.registry.get(got[region]["rrp_evidence_id"])
        assert ev.value == rrp and ev.region == region and ev.source_row_ids[0].endswith(f"_202607310730_0000000530141929:{line}")
        assert ev.label.endswith(region) and ev.available_at_utc == "2026-07-30T22:18:09Z"


@pytest.mark.parametrize("args", [{"interval_end_utc": PEAK, "as_of_utc": "2026-07-30T22:00:00Z"},  # not yet public
                                  {"interval_end_utc": "2026-07-01T00:00:00Z", "as_of_utc": None}])  # no data held
def test_later_published_or_unheld_prices_are_not_returned(args):
    rec = _dispatcher().call("get_regional_prices", args)
    assert rec.status == "ok" and rec.view["prices"] == []


def test_only_the_controller_may_call_it_and_only_once_and_the_model_is_never_offered_it():
    from nem_agent.agent.playbook import PLAYBOOKS
    from nem_agent.tools import CONTROLLER_TOOLS, TOOLS, openai_function_tools

    d = _dispatcher()
    by_model = d.call("get_regional_prices", {"interval_end_utc": PEAK}, origin="model")
    assert by_model.status == "blocked" and "unknown tool" in (by_model.blocked_reason or "")
    assert d.call("get_regional_prices", {"interval_end_utc": PEAK}).status == "ok"
    assert "already called once" in (d.call("get_regional_prices", {"interval_end_utc": PEAK}).blocked_reason or "")
    assert "get_regional_prices" not in TOOLS and "get_regional_prices" not in json.dumps(openai_function_tools())
    assert all(set(pb.controller_only) <= set(CONTROLLER_TOOLS) for pb in PLAYBOOKS.values())
    assert _dispatcher("source_explanation").call("get_regional_prices", {"interval_end_utc": PEAK}).status == "blocked"


# ------------------------------------------------------------------------------------------------ the live controller
def _replay(path: Path, question: str | None = None, as_of: str | None = None):
    rec = json.loads(path.read_text())
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"])
             for t in rec["tools"] if t["call_id"] != "controller_question_retrieval" and t["status"] != "blocked"]
    drafts: dict[str, Any] = rec["drafts"]
    draft = drafts.get("repair:draft") or drafts["synthesis:draft"]
    fake = FakeModel(rec["route"], [calls], lambda kw: copy.deepcopy(draft))
    return investigate(InvestigateRequest(question=question or rec["question"], mode="live", as_of_utc=as_of),
                       live_client=fake, write_trace=False)


def _said(res, name: str) -> str | None:
    return next((e["text"] for e in res.trace.events if e["name"] == name), None)


def _regional_calls(res) -> list[tuple[str, str]]:
    return [(r.origin, r.status) for r in res.records if r.name == "get_regional_prices"]


def test_f04_answer_compares_the_regions_without_numbers_in_the_sentence_and_traces_each_price():
    res = _replay(F04)
    rep = res.report
    assert not rep.validation["fallback_applied"] and rep.validation["final_passed"], rep.validation
    assert _regional_calls(res) == [("controller", "ok")]
    line = _said(res, "regional_answer")
    assert line == ("At the price extreme's 5-minute interval (interval ending 2026-07-30T21:30:00Z = 2026-07-31 07:30 "
                    "AEST), SA1, TAS1 and VIC1 were also at or above the analysis threshold, and QLD1 was below it.")
    assert rep.summary[0].startswith("The records cannot settle this:") and rep.summary[1] == line  # I-1a first
    assert not CAUSAL_RE.search(line)
    shown = {o.label.rsplit(", ", 1)[-1]: o for o in rep.observations if o.label.startswith("5-minute dispatch RRP, ")}
    assert {r: (o.value, o.source_row_ids[0][-2:]) for r, o in shown.items()} == {r: (v, ln) for r, (ln, v) in ROWS.items()}


def test_w18_is_also_about_an_inter_regional_transfer_notice():
    res = _replay(LIVE / "L3-holdout-v4" / "W18.json")
    assert _regional_calls(res) == [("controller", "ok")] and _said(res, "timing_answer").startswith("Timing rules")
    assert "SA1 and TAS1 were also at or above the analysis threshold, and NSW1 and QLD1 were below it" in \
        _said(res, "regional_answer")


@pytest.mark.parametrize("path,question", [
    (LIVE / "L3-holdout-v4" / "W01.json", None),
    (LIVE / "L3-holdout-v4" / "W02.json", None),
    (LIVE / "L3-holdout-v4" / "W03.json", None),
    (LIVE / "L3-holdout-v4" / "W19.json", None),  # SA1 reserve notices only
    (F04, "What happened to NSW1 prices near 7:30 am market time on 31 July 2026?"),  # the notices are there; the
])                                                                                     # question names nothing
def test_single_region_questions_fetch_nothing(path, question):
    res = _replay(path, question)
    assert _regional_calls(res) == [] and _said(res, "regional_answer") is None


OTHER_REGIONS_Q = "Was the NSW1 price spike near 7:30 am market time on 31 July 2026 also seen in the other regions?"


def test_inter_regional_wording_makes_a_question_about_other_regions():
    res = _replay(F04, OTHER_REGIONS_Q)
    assert _regional_calls(res) == [("controller", "ok")] and "QLD1 was below it" in _said(res, "regional_answer")


def test_a_question_naming_a_second_region_is_asked_to_choose_one_first():
    res = _replay(F04, "Did Queensland prices also spike when NSW1 did near 7:30 am market time on 31 July 2026?")
    assert res.report.status == "needs_clarification" and _regional_calls(res) == []


def test_nothing_is_shown_as_of_before_the_prices_were_public():
    """The rows for the 21:30Z interval became available at 22:18:09Z."""
    res = _replay(F04, OTHER_REGIONS_Q, as_of="2026-07-30T22:00:00Z")
    rec = next(r for r in res.records if r.name == "get_regional_prices")
    assert rec.view["prices"] == [] and rec.view["n_published_after_as_of"] == 5
    assert _said(res, "regional_answer") is None
    assert not any(o.label.startswith("5-minute dispatch RRP, ") for o in res.report.observations)


def test_a_model_claim_about_another_regions_price_is_still_rejected():
    """The comparison is shown as observations; a numeric claim on another region's evidence still fails."""
    from nem_agent.report import NumericClaim
    from nem_agent.validation import validate

    res = _replay(F04)
    qld = next(o for o in res.report.observations if o.label.endswith("QLD1"))
    claim = NumericClaim(claim_id="q1", text="QLD1 price", value=qld.value, unit="$/MWh", evidence_id=qld.evidence_id)
    rep = res.report.model_copy(update={"numeric_claims": [*res.report.numeric_claims, claim]})
    assert "CLAIM_REGION_MISMATCH" in {x.code for x in validate(rep, res.registry, records=res.records).violations}
