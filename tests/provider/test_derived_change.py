"""Issue I-2b (docs/issue-tracker.md): a question asking by how much a demand measure changed between two times gets
that change, computed by code and traced to both source rows.

Held-out v4 W04 asked by how much NSW total demand climbed from the 06:30 AEST dispatch interval to the 07:30 AEST one.
The answer gave both values (10046.72 MW and 11432.7 MW) and no rise: the model may not do arithmetic, no tool or
controller step computed the change, and a number the model computed itself would have no evidence.

Now, for a question with change wording, one demand measure and two named times, the controller takes the two
registered values of that measure in the region at those interval ends (same interval length and unit, both public by
the as-of cutoff), registers their difference as derived evidence linked to both source rows, and opens the summary
with one sentence stating it. Otherwise nothing is added. Operational demand and dispatch total demand are never
paired. Replays use saved records through the SYNTHETIC fake transport (no network, no key).
"""

from __future__ import annotations

import copy
import dataclasses
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from nem_agent.agent.request import InvestigateRequest
from nem_agent.service import investigate
from nem_agent.timeutil import parse_iso
from nem_agent.validation import CAUSAL_RE
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

LIVE = Path(__file__).resolve().parents[2] / "artifacts" / "live"
W04 = LIVE / "L3-holdout-v4" / "W04.json"
ROW_0630 = "DISPATCHIS:PUBLIC_DISPATCHIS_202607310630_0000000530135204:L20"
ROW_0730 = "DISPATCHIS:PUBLIC_DISPATCHIS_202607310730_0000000530141929:L11"


def _replay(question: str | None = None, as_of: str | None = None):
    rec = json.loads(W04.read_text())
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"])
             for t in rec["tools"] if t["call_id"] != "controller_question_retrieval" and t["status"] != "blocked"]
    drafts: dict[str, Any] = rec["drafts"]
    draft = drafts.get("repair:draft") or drafts["synthesis:draft"]
    fake = FakeModel(rec["route"], [calls], lambda kw: copy.deepcopy(draft))
    res = investigate(InvestigateRequest(question=question or rec["question"], mode="live", as_of_utc=as_of),
                      live_client=fake, write_trace=False)
    return res, fake


def _events(res, name: str) -> list[dict[str, Any]]:
    return [e for e in res.trace.events if e["name"] == name]


def _derived(res) -> list[Any]:
    return [e for e in res.registry.items.values() if e.metric.endswith("_change")]


# ------------------------------------------------------------------------------------------------ W04
def test_w04_opens_with_the_rise_traced_to_a_derived_value_linked_to_both_source_rows():
    res, fake = _replay()
    rep = res.report
    assert rep.validation["final_passed"] and not rep.validation["fallback_applied"], rep.validation
    assert not rep.validation.get("repair_attempted")
    assert rep.summary[0] == (
        "Dispatch total demand (TOTALDEMAND) rose by 1385.98 MW, from 10046.72 MW in the 5-minute interval ending "
        "2026-07-30T20:30:00Z = 2026-07-31 06:30 AEST to 11432.7 MW in the 5-minute interval ending "
        "2026-07-30T21:30:00Z = 2026-07-31 07:30 AEST.")
    assert not CAUSAL_RE.search(rep.summary[0])
    [ch] = _derived(res)
    frm, to = res.registry.get("ev0002"), res.registry.get("ev0038")
    assert (frm.value, frm.source_row_ids, to.value, to.source_row_ids) == (10046.72, [ROW_0630], 11432.7, [ROW_0730])
    assert (ch.evidence_class, ch.metric, ch.value, ch.unit, ch.region) == \
        ("derived", "dispatch_totaldemand_change", 1385.98, "MW", "NSW1")
    assert ch.source_row_ids == [ROW_0630, ROW_0730] and ch.interval_minutes == 5
    assert ch.derivation.startswith("ev0038 minus ev0002:")
    # as-of availability: the later of the two (each row's own, now registered by get_price_timeline)
    assert (frm.available_at_utc, to.available_at_utc, ch.available_at_utc) == \
        ("2026-07-30T21:18:06Z", "2026-07-30T22:18:09Z", "2026-07-30T22:18:09Z")
    # every number in the sentence is a claim on its own evidence
    by_ev = {c.evidence_id: c.value for c in rep.numeric_claims}
    assert by_ev[ch.evidence_id] == 1385.98 and by_ev["ev0002"] == 10046.72 and by_ev["ev0038"] == 11432.7
    obs = next(o for o in rep.observations if o.evidence_id == ch.evidence_id)
    assert obs.source_row_ids == [ROW_0630, ROW_0730] and obs.evidence_class == "derived"
    # the model is told the change and its evidence ID before it writes, and is not asked to compute anything
    synthesis = [r for r in fake.requests if (r.get("text") or {}).get("format", {}).get("name") == "ModelReport"]
    told = [i["content"] for i in synthesis[0]["input"] if isinstance(i, dict) and
            str(i.get("content", "")).startswith("Change computed by the controller")]
    assert len(told) == 1 and f'"evidence_id": "{ch.evidence_id}"' in told[0] and '"value": 1385.98' in told[0]


def test_a_fall_is_stated_as_a_fall_with_the_signed_change_as_evidence():
    res, _ = _replay("NSW, 31 July 2026: by how much did regional total demand change from the 07:30 AEST dispatch "
                     "interval to the 07:35 AEST one?")
    rep = res.report
    assert rep.validation["final_passed"] and not rep.validation["fallback_applied"], rep.validation
    assert rep.summary[0].startswith("Dispatch total demand (TOTALDEMAND) fell by 75.03 MW, from 11432.7 MW in the "
                                     "5-minute interval ending 2026-07-30T21:30:00Z")
    [ch] = _derived(res)
    assert ch.value == -75.03  # the later value minus the earlier one
    later = next(c for c in rep.numeric_claims if c.claim_id == "controller_to")  # the model never claimed 21:35
    assert later.value == 11357.67 and res.registry.get(later.evidence_id).valid_at_utc == "2026-07-30T21:35:00Z"


def test_operational_demand_is_changed_only_against_operational_demand():
    res, _ = _replay("NSW, 31 July 2026: by how much did regional operational demand climb from the 06:30 AEST "
                     "half-hour to the 07:30 AEST one?")
    rep = res.report
    assert rep.validation["final_passed"] and not rep.validation["fallback_applied"], rep.validation
    [ch] = _derived(res)
    assert (ch.metric, ch.value, ch.interval_minutes) == ("opdemand_actual_change", 1426.0, 30)
    assert all(r.startswith("OPDEM_ACTUAL") for r in ch.source_row_ids) and len(ch.source_row_ids) == 2
    assert rep.summary[0].startswith("Actual operational demand rose by 1426 MW, from 9752 MW in the half-hour ending")


# ------------------------------------------------------------------------------------------------ controls
@pytest.mark.parametrize("question,reason", [
    # a named time with no registered value: 08:00 AEST is outside the price timeline the model fetched; operational
    # demand does have a value then, and is not used in its place
    ("NSW, 31 July 2026: by how much did regional total demand climb from the 06:30 AEST dispatch interval to the "
     "08:00 AEST one?", "0 dispatch_totaldemand values for the interval ending 2026-07-30T22:00:00Z"),
    # not an interval end of that measure
    ("NSW, 31 July 2026: by how much did regional total demand climb from 06:32 AEST to 07:30 AEST?",
     "0 dispatch_totaldemand values for the interval ending 2026-07-30T20:32:00Z"),
    ("NSW, 31 July 2026: by how much did regional operational demand climb from 06:30 AEST to 06:45 AEST?",
     "0 opdemand_actual values for the interval ending 2026-07-30T20:45:00Z"),
    # both measures, or none, named: no pair is chosen
    ("NSW, 31 July 2026: by how much did total demand and operational demand climb from 06:30 AEST to 07:30 AEST?",
     "the question names 2 demand measures, not one"),
    ("NSW, 31 July 2026: by how much did regional demand climb from 06:30 AEST to 07:30 AEST?",
     "the question names 0 demand measures, not one"),
    # one time only
    ("NSW, 31 July 2026: by how much did regional total demand climb by 07:30 AEST?",
     "the question names 1 times, not two"),
    # a forecast's change is not the change in the actual values
    ("NSW, 31 July 2026: by how much did the operational demand forecast rise from 06:30 AEST to 07:30 AEST?",
     "the question is about forecasts; only observed values are paired"),
])
def test_no_change_without_one_measure_and_a_value_at_each_named_interval_end(question, reason):
    res, _ = _replay(question)
    assert [e["skipped"] for e in _events(res, "demand_change")] == [reason]
    assert _derived(res) == [] and _events(res, "change_answer") == []
    assert not any(c.claim_id.startswith("controller_") for c in res.report.numeric_claims)


def test_a_question_asking_for_the_values_but_no_change_gets_no_sentence():
    res, _ = _replay("NSW, 31 July 2026: what was regional total demand in the 06:30 AEST dispatch interval and in the "
                     "07:30 AEST one, and what was the RRP at 07:30?")
    assert _events(res, "demand_change") == [] and _derived(res) == [] and _events(res, "change_answer") == []


def test_as_of_before_the_later_value_was_public_gives_no_change():
    """The 07:30 AEST row became available at 22:18:09Z. As of 22:00Z the price tool does not return it."""
    res, _ = _replay(as_of="2026-07-30T22:00:00Z")
    assert [e["skipped"] for e in _events(res, "demand_change")] == \
        ["0 dispatch_totaldemand values for the interval ending 2026-07-30T21:30:00Z"]
    assert _derived(res) == [] and _events(res, "change_answer") == []


def test_the_controller_itself_refuses_a_value_published_after_the_cutoff():
    """Defence in depth: even with both values registered, one not public by the cutoff is not used."""
    from nem_agent.agent.dispatcher import Dispatcher
    from nem_agent.agent.live import LiveController
    from nem_agent.selection import load_selection
    from nem_agent.store import Store
    from nem_agent.trace import Trace

    done, _ = _replay()
    res = dataclasses.replace(done.resolution, as_of=parse_iso("2026-07-30T22:00:00Z"))
    reg = copy.deepcopy(done.registry)
    reg.items = {k: v for k, v in reg.items.items() if not v.metric.endswith("_change")}
    trace = Trace()
    ctl = LiveController(Dispatcher(Store(), load_selection(), trace, reg, "market_event_review"), reg,
                         done.report.versions, client=FakeModel({}, [], None))
    assert ctl._demand_change(res, trace) is None and ctl._change_answer(res) is None
    assert [e["skipped"] for e in trace.events if e["name"] == "demand_change"] == \
        ["ev0038 was not public by the as-of cutoff"]
    assert not any(v.metric.endswith("_change") for v in reg.items.values())


# ------------------------------------------------------------------------------------------------ the question
@pytest.mark.parametrize("question,times", [
    ("by how much did total demand rise from 6:30 am to 7:30 am market time", ["20:30", "21:30"]),
    ("by how much did total demand rise from 20:30 UTC to 21:30 UTC", ["20:30", "21:30"]),  # the date, in UTC
    ("how much did total demand fall between 2026-07-30T21:30:00Z and 2026-07-30T21:35:00Z", ["21:30", "21:35"]),
    ("as of 07:00 AEST, by how much did total demand change from 06:30 to 06:45?", ["20:30", "20:45"]),
])
def test_the_times_a_question_names(question, times):
    from nem_agent.agent.request import asks_for_change, named_instants

    assert asks_for_change(question)
    got = named_instants(question, "NSW1", date(2026, 7, 30 if "UTC" in question else 31))
    assert [f"{t:%H:%M}" for t in got] == times
