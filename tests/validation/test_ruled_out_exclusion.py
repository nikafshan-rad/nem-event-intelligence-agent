"""Issue I-7b (docs/issue-tracker.md): a doubting hypothesis is not reliance, and an exclusion the timing backs needs
no hedge word.

Live, second development check (2026-09-30), W18:
- **The flag:** the first draft's possible_explanations[0] said the Hazelwood bus-tie notice [c1] "might refer to a
  later, separate outage and therefore might not correspond to the … price spike". I-7 flagged it, because it cites a
  notice timed after every high-price interval, although it doubts the incident's bearing.
- **The repair:** it did what I-7 asks ("say that the timing rules it out") and wrote "…so the notice's timing rules it
  out as an explanation for the price extreme".
- **The fallback:** HYPOTHESIS_UNHEDGED rejected that sentence ("a hypothesis must be hedged"), so the answer fell back.

Now I-7 flags only a hypothesis that suggests the incident had a bearing. A statement that the timing rules it out,
where every market notice it cites meets I-7's timing condition, need not be hedged, but it may assert no cause.
Replays use saved Live records through the SYNTHETIC fake transport (no network, no key). Results with a run's actual
saved repair are kept apart from scripted alternatives, and scripted replays are not a measure of Live behaviour.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from nem_agent.agent.request import InvestigateRequest
from nem_agent.report import Citation, Hypothesis
from nem_agent.service import investigate
from nem_agent.validation import validate
from tests.provider.fake_model import FakeModel
from tests.validation.test_ruled_out_explanations import _notice

pytestmark = pytest.mark.synthetic

LIVE = Path(__file__).resolve().parents[2] / "artifacts" / "live"
DEV2, C0930, C0929 = LIVE / "live-check-dev2", LIVE / "live-check-p1-dev", LIVE / "live-check-2026-09-29"
RULED_OUT, UNHEDGED = "EXPLANATION_RULED_OUT_BY_TIMING", "HYPOTHESIS_UNHEDGED"
DOUBT = ("The Hazelwood PS 4 6 bus‑tie outage notice [c1] might refer to a later, separate outage and therefore might "
         "not correspond to the 2026-08-19T23:10:00Z price spike.")  # the second check's first draft, possible_explanations[0]
RELIANCE = ("A binding network constraint or transfer limit change (the Hazelwood bus‑tie notice [c1]) might have "
            "limited local transfer capability and so could have influenced prices; however the retrieved notice "
            "records the outage at 2026-08-20 11:00 AEST (2026-08-20T01:00:00Z).")  # the first check's, I-7's case
RULES_OUT = ("Timing rules this out: the AEMO market notice that mentions Hazelwood gives 2026-08-20 11:00 AEST "
             "(2026-08-20T01:00:00Z), after the price extreme (interval ending 2026-08-19T23:10:00Z = 2026-08-20 09:10 "
             "AEST), so what it reports came later.")


def doubts_bearing(text: str) -> bool:
    from nem_agent.validation import doubts_bearing as doubts

    return doubts(text)


def _replay(path: Path, *, draft_name: str = "synthesis:draft", patch: Any = "saved", delete: str | None = None):
    """A saved Live run through the fake transport: its tool calls, a draft from its trace, and its actual saved
    repair patch ("saved"), or a scripted one."""
    rec = json.loads(path.read_text())
    trace = json.loads((path.parent / "traces" / f"{rec['score']['trace_id']}.json").read_text())
    draft = next(e for e in trace["events"] if e["name"] == draft_name)["report"]
    saved = next((e for e in trace["events"] if e["name"] == "repair:scoped"), {}).get("patch")
    if patch == "saved":
        patch = saved
    if delete:  # scripted: the saved edits, except that ``delete`` is deleted
        patch = {**saved, "edits": [e for e in saved["edits"] if not e["target"].startswith(delete)] +
                 [{"target": delete, "action": "delete", "text": None, "statement": None, "claim": None,
                   "citation": None}]}
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    fake = FakeModel(rec["route"], [calls], lambda kw: copy.deepcopy(draft),
                     (lambda kw: copy.deepcopy(patch)) if patch else None)
    return investigate(InvestigateRequest(question=rec["question"], mode="live"), live_client=fake, write_trace=False)


@pytest.fixture(scope="module")
def w18():
    """A valid W18 answer to vary: the first check's run with its reliance hypothesis deleted by a scripted repair (it
    passes before and after this fix). [c1] is the Hazelwood notice, 1100 hrs 20/08 = 01:00Z, after every interval."""
    res = _replay(C0930 / "W18.json", delete="possible_explanations[1]")
    assert res.report.validation["final_passed"] and not res.report.validation["fallback_applied"]
    return res


def _critical(res, statement: str, notices: list = (), *, drop_prices_after: str | None = None,
              replace: bool = True) -> list[tuple[str, str]]:
    """Critical violations of possible_explanations[0] once ``statement`` replaces it (or is added), with each fixture
    notice cited as [t<n>]."""
    reg = copy.deepcopy(res.registry)
    for ch in notices:
        reg.add_chunk(ch)
    if drop_prices_after:
        reg.items = {k: v for k, v in reg.items.items() if not (v.metric == "dispatch_rrp" and v.valid_at_utc
                                                                 and v.valid_at_utc > drop_prices_after)}
    cites = [Citation(citation_id=f"t{ch.doc_id.rsplit('_', 1)[1]}", chunk_id=ch.chunk_id, doc_id=ch.doc_id, title=ch.title,
                      url=ch.url, doc_type="market_notice", quote=ch.text[:60], supports="test fixture") for ch in notices]
    hyp = Hypothesis(statement=statement, supporting_evidence_ids=[], what_would_test_it="Check the constraint logs.")
    rest = res.report.possible_explanations[1:] if replace else res.report.possible_explanations
    rep = res.report.model_copy(update={"possible_explanations": [hyp, *rest], "citations": [*res.report.citations, *cites]})
    return [(v.code, v.detail) for v in validate(rep, reg, records=res.records).critical
            if v.detail.startswith("possible_explanations[0]")]


def _codes(*args: Any, **kw: Any) -> set[str]:
    return {c for c, _ in _critical(*args, **kw)}


# ------------------------------------------------------------------------------------------------ W18, as run
def test_the_actual_saved_repair_now_shows_the_answer():
    """The second check's own first draft and actual repair: in Live it fell back on HYPOTHESIS_UNHEDGED; now it
    passes."""
    run = _replay(DEV2 / "W18.json")
    v, rep = run.report.validation, run.report
    assert RULED_OUT not in set(v["pre_repair_codes"])  # the doubting first-draft hypothesis is not flagged
    assert v["repair_mode"] == "scoped" and v["final_passed"] and not v["fallback_applied"]
    assert rep.headline == RULES_OUT and rep.summary[0] == RULES_OUT
    # since I-7c the validated exclusion is shown apart from the hypotheses that remain possible
    assert "so the notice's timing rules it out as an explanation for the price extreme" in rep.ruled_out_explanations[0].statement
    assert not validate(rep, run.registry, records=run.records).critical


def test_the_live_record_itself_is_unchanged():
    """The frozen record keeps its outcome: the Live run fell back (this check does not re-score it)."""
    rec = json.loads((DEV2 / "W18.json").read_text())
    assert rec["validation"]["fallback_applied"] and rec["validation"]["final_candidate"] == [
        ["HYPOTHESIS_UNHEDGED", "possible_explanations[0]: a hypothesis must be hedged"]]
    checks = json.loads((DEV2 / "checks.json").read_text())
    assert checks["W18"]["case_verdict"] == "failed"


# ------------------------------------------------------------------------------------------------ 1. reliance, not doubt
@pytest.mark.parametrize("statement", [
    DOUBT,
    "The Hazelwood bus-tie outage [c1] is unrelated to the price spike; it may be a separate, later event.",
    "The Hazelwood notice [c1] might not be relevant to the 09:10 AEST price.",
])
def test_a_hypothesis_that_only_doubts_the_incident_is_not_flagged(w18, statement):
    assert RULED_OUT not in _codes(w18, statement)
    assert doubts_bearing(statement)


@pytest.mark.parametrize("statement", [
    RELIANCE,
    "The Hazelwood bus-tie outage [c1] might be a factor in the price.",
    "The Hazelwood outage [c1] did not affect the first interval but could have influenced the peak.",
    "The Hazelwood outage [c1] might not have been planned, and could have limited transfers into VIC1.",
])
def test_a_hypothesis_suggesting_any_bearing_is_still_flagged(w18, statement):
    assert RULED_OUT in _codes(w18, statement)


@pytest.mark.parametrize("statement", [RELIANCE, "The Hazelwood bus-tie outage [c1] might be a factor in the price.",
                                       "The Hazelwood outage [c1] did not affect the first interval but could have "
                                       "influenced the peak."])
def test_the_doubt_test_sees_any_suggested_bearing(statement):
    assert not doubts_bearing(statement)


# ------------------------------------------------------------------------------------------------ 2. the exclusion
@pytest.mark.parametrize("statement", [
    "The Hazelwood bus-tie outage [c1] is ruled out by its timing: the notice gives 2026-08-20 11:00 AEST "
    "(2026-08-20T01:00:00Z), after every interval.",
    "The Hazelwood outage [c1] could not have caused the price extreme, as it came later.",
])
def test_an_exclusion_the_timing_backs_needs_no_hedge_word(w18, statement):
    assert _codes(w18, statement) == set()


@pytest.mark.parametrize("statement,why", [
    ("Timing rules out the Hazelwood outage [c1]; wind generation caused the spike.", "an asserted cause after it"),
    ("The Hazelwood outage [c1] is ruled out by its timing, and falling wind output drove the price up.", "another"),
    ("Timing rules out the Hazelwood outage [c1] as the cause of the price extreme.",
     "causal wording in the exclusion itself: still rejected (recorded as not covered)"),
])
def test_an_exclusion_may_not_assert_a_cause(w18, statement, why):
    assert UNHEDGED in _codes(w18, statement), why


def test_an_overconfident_exclusion_is_still_rejected(w18):
    assert "HYPOTHESIS_OVERCONFIDENT" in _codes(w18, "Timing definitely rules out the Hazelwood outage [c1].")


# ------------------------------------------------------------------------------------------------ 3. controls
EXCLUDE = "The outage in the notice [t{}] is ruled out by its timing."


@pytest.mark.parametrize("n,text,why", [
    (811, "At 0700 hrs 19/08/2026 there was a planned outage of a 220 kV line in the VIC region.", "before the event"),
    (812, "At 0925 hrs 20/08/2026 there was a short notice outage of a 220 kV line in the VIC region.",
     "within the event: after the price extreme, before later high-price intervals"),
    (813, "A short notice outage of a 220 kV line in the VIC region, time to be advised.", "no stated time"),
])
def test_without_timing_evidence_an_exclusion_must_be_hedged(w18, n, text, why):
    assert UNHEDGED in _codes(w18, EXCLUDE.format(n), [_notice(n, text)]), why


def test_prices_not_registered_up_to_the_notice_give_no_exemption(w18):
    later = _notice(814, "At 1100 hrs 20/08/2026 there was a short notice outage of a 220 kV line in the VIC region.")
    assert _codes(w18, EXCLUDE.format(814), [later]) == set()  # W18's prices reach past it: backed
    assert UNHEDGED in _codes(w18, EXCLUDE.format(814), [later], drop_prices_after="2026-08-19T23:50:00Z")


def test_an_exclusion_citing_a_notice_that_does_not_back_it_must_be_hedged(w18):
    before = _notice(815, "At 0700 hrs 19/08/2026 there was a planned outage of a 220 kV line in the VIC region.")
    assert UNHEDGED in _codes(w18, "The outages in the notices [c1] [t815] are ruled out by their timing.", [before])
    assert UNHEDGED in _codes(w18, "Timing rules this out.")  # no notice cited


def test_unrelated_hypotheses_keep_every_check(w18):
    assert UNHEDGED in _codes(w18, "Rebidding by marginal units raised the price.")
    assert _codes(w18, "Rebidding by marginal units may have raised the price.") == set()
    assert {UNHEDGED, RULED_OUT} <= _codes(w18, "The Hazelwood outage [c1] caused the spike.")


# ------------------------------------------------------------------------------------------------ 4. replays
def test_w18_scripted_alternative_deleting_the_hypothesis_also_passes():
    """Scripted, not a Live result: the run's saved edits, with possible_explanations[0] deleted instead."""
    res = _replay(DEV2 / "W18.json", delete="possible_explanations[0]")
    assert res.report.validation["final_passed"] and not res.report.validation["fallback_applied"]
    assert res.report.headline == RULES_OUT


def test_w18_first_check_with_its_actual_repair_still_falls_back():
    """2026-09-30 first check: its repair kept the notice as a possible influence, so I-7 still rejects it."""
    res = _replay(C0930 / "W18.json")
    v = res.report.validation
    assert v["fallback_applied"] and RULED_OUT in {x["code"] for x in v["initial"]["violations"]}


@pytest.mark.parametrize("path", [C0930 / "W19.json", DEV2 / "W19.json", C0930 / "F04.json", DEV2 / "F04.json"])
def test_w19_and_f04_with_their_actual_repairs_still_pass(path):
    res = _replay(path)
    v = res.report.validation
    assert v["final_passed"] and not v["fallback_applied"], (path, v.get("pre_repair_codes"))
    assert RULED_OUT not in set(v.get("pre_repair_codes") or [])


def test_w18_first_check_scripted_deletion_is_flagged_then_passes():
    """Scripted, not a Live result: the first check's reliance hypothesis is flagged, and deleting it passes."""
    res = _replay(C0930 / "W18.json", delete="possible_explanations[1]")
    v = res.report.validation
    assert RULED_OUT in set(v["pre_repair_codes"]) and v["final_passed"] and not v["fallback_applied"]


def test_f04s_2026_09_29_answer_is_unchanged():
    """An incident before the event (Directlink, 0700 hrs 27/07): the answer as the 2026-09-29 run repaired it."""
    rec = json.loads((C0929 / "F04.json").read_text())
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    draft = rec["drafts"].get("repair:draft") or rec["drafts"]["synthesis:draft"]
    res = investigate(InvestigateRequest(question=rec["question"], mode="live"),
                      live_client=FakeModel(rec["route"], [calls], lambda kw: copy.deepcopy(draft)), write_trace=False)
    assert res.report.validation["final_passed"] and not res.report.validation["fallback_applied"]
