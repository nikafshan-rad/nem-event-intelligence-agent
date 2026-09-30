"""Issue I-3d (docs/issue-tracker.md): one row-backed data point is shown once.

Live check 2026-09-30: W04 listed each TOTALDEMAND endpoint twice, and W18 and W19 their price peaks twice. The
registry holds one evidence item per tool call, so the same source row can come back under several evidence IDs, and
the answer listed each ID.

Now, after the complete answer is validated, observations whose evidence agrees on class (not derived), metric,
region, value, unit, time, interval, the full source-row list and the publication and availability times are shown
once. The other IDs and labels are kept in `validation.observations_merged`. Derived values, and anything that differs,
are left as they are. Replays use saved Live records through the SYNTHETIC fake transport (no network, no key); the
added evidence items are test fixtures.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from nem_agent.agent.request import InvestigateRequest
from nem_agent.report import Observation
from nem_agent.service import investigate
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

LIVE = Path(__file__).resolve().parents[2] / "artifacts" / "live"
V4, C0930 = LIVE / "L3-holdout-v4", LIVE / "live-check-p1-dev"


def _replay(path: Path, *, first_draft: bool = False, delete: str | None = None, draft_update: dict | None = None):
    rec = json.loads(path.read_text())
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    patch: dict[str, Any] | None = None
    if first_draft:
        trace = json.loads((path.parent / "traces" / f"{rec['score']['trace_id']}.json").read_text())
        patch = next(e for e in trace["events"] if e["name"] == "repair:scoped")["patch"]
        if delete:
            patch = {**patch, "edits": [e for e in patch["edits"] if not e["target"].startswith(delete)] +
                     [{"target": delete, "action": "delete", "text": None, "statement": None, "claim": None,
                       "citation": None}]}
    draft = rec["drafts"]["synthesis:draft"] if first_draft else (rec["drafts"].get("repair:draft")
                                                                  or rec["drafts"]["synthesis:draft"])
    draft = {**draft, **(draft_update or {})}
    fake = FakeModel(rec["route"], [calls], lambda kw: copy.deepcopy(draft),
                     (lambda kw: copy.deepcopy(patch)) if patch else None)
    return investigate(InvestigateRequest(question=rec["question"], mode="live"), live_client=fake, write_trace=False)


def merge_repeated_observations(report, registry):
    from nem_agent.validation import merge_repeated_observations as merge

    return merge(report, registry)


def _points(rep) -> list[tuple]:
    return [(o.metric, o.value, o.valid_at_utc, tuple(o.source_row_ids)) for o in rep.observations]


# ------------------------------------------------------------------------------------------------ the examples
def test_w04_shows_each_endpoint_once_and_keeps_its_change():
    res = _replay(C0930 / "W04.json", first_draft=True)
    rep = res.report
    assert rep.validation["final_passed"] and not rep.validation["fallback_applied"]
    points = _points(rep)
    assert len(points) == len(set(points))  # each data point once
    td = [o for o in rep.observations if o.metric == "dispatch_totaldemand"]
    assert sorted((o.value, o.valid_at_utc) for o in td) == [(10046.72, "2026-07-30T20:30:00Z"), (11432.7, "2026-07-30T21:30:00Z")]
    assert any(o.metric == "dispatch_totaldemand_change" and o.value == 1385.98 for o in rep.observations)
    merged = {a["evidence_id"] for e in rep.validation["observations_merged"] for a in e["also"]}
    assert merged == {"ev0395", "ev0431"}  # the repeats' IDs stay reachable
    assert rep.summary[0].startswith("Dispatch total demand (TOTALDEMAND) rose by 1385.98 MW")  # both endpoints stated


@pytest.mark.parametrize("path,kw,metric,value", [
    (C0930 / "W18.json", {"first_draft": True, "delete": "possible_explanations[1]"}, "dispatch_rrp", 406.00544),
    (C0930 / "W19.json", {"first_draft": True}, "dispatch_rrp", 845.0),
    (V4 / "W01.json", {}, "dispatch_rrp", 450.08),
])
def test_a_repeated_price_peak_is_shown_once(path, kw, metric, value):
    rep = _replay(path, **kw).report
    assert sum(o.metric == metric and o.value == value for o in rep.observations) == 1
    assert rep.validation["observations_merged"]


def test_derived_values_that_agree_are_both_kept():
    """v4 W01: two counts of 1 interval, from different computations (their derivations differ)."""
    rep = _replay(V4 / "W01.json").report
    counts = [o for o in rep.observations if o.metric == "intervals_meeting_threshold" and o.value == 1.0]
    assert len(counts) >= 2


# ------------------------------------------------------------------------------------------------ controls
@pytest.fixture(scope="module")
def w18():
    return _replay(C0930 / "W18.json", first_draft=True, delete="possible_explanations[1]")


def _obs(ev) -> Observation:
    return Observation(metric=ev.metric, value=float(ev.value), unit=ev.unit, valid_at_utc=ev.valid_at_utc,
                       valid_at_local=None, interval_minutes=ev.interval_minutes, evidence_id=ev.evidence_id,
                       source_row_ids=ev.source_row_ids[:12], evidence_class=ev.evidence_class, label=ev.label or ev.metric)


def _with(res, evs):
    return res.report.model_copy(update={"observations": [_obs(ev) for ev in evs]})


def test_equal_values_at_different_times_are_all_kept(w18):
    """W18's window holds four 5-minute intervals at 301.55 $/MWh (23:20Z, 23:25Z, 23:35Z, 23:45Z)."""
    evs = [ev for ev in w18.registry.items.values() if ev.metric == "dispatch_rrp" and ev.value == 301.55
           and ev.region == "VIC1"]
    evs = list({ev.valid_at_utc: ev for ev in evs}.values())
    assert len(evs) == 4
    rep, merged = merge_repeated_observations(_with(w18, evs), w18.registry)
    assert len(rep.observations) == 4 and merged == []


def test_different_regions_and_disagreeing_values_are_kept(w18):
    reg = copy.deepcopy(w18.registry)
    base = next(ev for ev in reg.items.values() if ev.metric == "dispatch_rrp" and ev.value == 406.00544)

    def like(**change: Any):
        return reg.add(**{k: v for k, v in {**base.as_dict(), **change}.items() if k != "evidence_id"})
    other_region, conflict, same = like(region="SA1"), like(value=400.0), like()
    rep, merged = merge_repeated_observations(_with(w18, [base, other_region, conflict, same]), reg)
    assert [o.evidence_id for o in rep.observations] == [base.evidence_id, other_region.evidence_id, conflict.evidence_id]
    assert merged == [{"shown": base.evidence_id, "metric": "dispatch_rrp", "valid_at_utc": base.valid_at_utc,
                       "also": [{"evidence_id": same.evidence_id, "label": same.label or same.metric}]}]


def test_a_wrong_claim_on_a_repeated_data_point_is_still_rejected():
    """Validation runs on the complete answer before anything is merged: a claim giving the wrong value for the
    repeat's evidence (W04's ev0395, the 06:30 endpoint again) makes the answer fall back."""
    rec = json.loads((C0930 / "W04.json").read_text())
    wrong = {"claim_id": "w1", "text": "TOTALDEMAND at 06:30", "value": 9999.0, "unit": "MW", "evidence_id": "ev0395",
             "rounding": 0.01}
    res = _replay(C0930 / "W04.json", draft_update={"numeric_claims": [*rec["drafts"]["synthesis:draft"]["numeric_claims"],
                                                                      wrong]})
    assert "CLAIM_VALUE_MISMATCH" in set(res.report.validation.get("pre_repair_codes") or [])
    assert res.report.validation["fallback_applied"]


def test_claims_on_a_repeat_point_to_the_shown_observation_of_the_same_row():
    """W04: the controller's endpoint claims cite ev0395 and ev0431, the repeats no longer shown; the record maps each
    to the shown observation of the same source row."""
    rep = _replay(C0930 / "W04.json", first_draft=True).report
    by_id = {c.evidence_id: c for c in rep.numeric_claims}
    assert {"ev0395", "ev0431"} <= set(by_id)
    shown = {o.evidence_id: o for o in rep.observations}
    for entry in rep.validation["observations_merged"]:
        for also in entry["also"]:
            kept = shown[entry["shown"]]
            assert also["evidence_id"] in by_id and by_id[also["evidence_id"]].value == kept.value
