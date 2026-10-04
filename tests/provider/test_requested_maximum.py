"""Issue I-17 (docs/issue-tracker.md): a demand measure's requested maximum is computed by code over the requested
window, stated by the controller, and the answer is held to it.

Held-out v6 Z04 (Live, 2026-10-02) asked "when did TAS1 total demand peak and at what level?" for 29 July 2026 (Hobart
time). The answer gave dispatch TOTALDEMAND at the price peak (1,321.81 MW, 20:05) and the maximum of operational
demand (1,452 MW, half-hour ending 08:00), a different measure. TOTALDEMAND's maximum, 1,367.32 MW in the interval
ending 07:55, was in the retrieved series but never given.

Replays use saved Live records through the SYNTHETIC fake transport (no network, no key); the controls use SYNTHETIC
registries and a SYNTHETIC dispatcher where stated.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from nem_agent.agent import demand_max
from nem_agent.agent.request import (
    MAXIMUM_CLARIFICATION,
    MAXIMUM_EVENT_CLARIFICATION,
    MAXIMUM_WINDOW_CLARIFICATION,
    InvestigateRequest,
    Resolution,
    maximum_window_kind,
    requested_maxima,
)
from nem_agent.evidence import EvidenceRegistry
from nem_agent.report import NumericClaim, Observation
from nem_agent.results import ResultRegistry
from nem_agent.selection import load_selection
from nem_agent.service import investigate
from nem_agent.validation import validate
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

ROOT = Path(__file__).resolve().parents[2]
V6 = ROOT / "artifacts" / "live" / "L3-holdout-v6"
MAX_ROW = "DISPATCHIS:PUBLIC_DISPATCHIS_202607290755_0000000529809198:L91"  # TOTALDEMAND 1367.32 MW, ending 21:55Z
MAX_END = "2026-07-28T21:55:00Z"
DAY = ["2026-07-28T14:00:00Z", "2026-07-29T14:00:00Z"]  # 29 July 2026 in Hobart (AEST)


def _z04() -> dict:
    return json.loads((V6 / "Z04.json").read_text())


def _codes(v: dict) -> set[str]:
    return {x["code"] for x in (v.get("pre_repair") or v["initial"])["violations"]} | \
        {x["code"] for x in v["initial"]["violations"]}


# ------------------------------------------------------------------------------------------------ reading the request
def test_z04_asks_for_total_demands_maximum():
    assert requested_maxima(_z04()["question"]) == ["total demand"]


@pytest.mark.parametrize("question,measures", [
    ("When did TAS1 total demand peak on 29 July 2026?", ["total demand"]),
    ("What was the peak total demand in SA1 on 29 July 2026?", ["total demand"]),
    ("Give the highest 5-minute total demand for VIC1 on 20 August 2026.", ["total demand"]),
    ("When did TAS1 operational demand reach its maximum on 29 July 2026?", ["operational demand"]),
    ("What was the maximum operational demand in NSW1 on 30 July 2026?", ["operational demand"]),
    ("When did demand peak in SA1 on 29 July 2026?", ["demand"]),  # no measure named
    ("What was the peak demand in TAS1 on 29 July 2026?", ["demand"]),
])
def test_a_measures_maximum_is_read(question, measures):
    assert requested_maxima(question) == measures


@pytest.mark.parametrize("question", [
    "What was TAS1 total demand at the peak?",  # the value at the price peak, asked for as such
    "Give the top price, SA total demand for that same interval, and a count of intervals at or above $300/MWh.",
    "What were the SA1 forecast and the actual demand for the peak half-hour on 2026-07-31?",
    "What was the peak dispatch price and the total demand in that interval?",
])
def test_a_value_at_the_price_peak_is_not_a_maximum_request(question):
    assert requested_maxima(question) == []


def test_no_other_question_in_the_repository_asks_for_a_maximum():
    found = []
    for f in sorted(ROOT.glob("eval/**/*.json")) + sorted(ROOT.glob("artifacts/live/**/*.json")):
        # the Live check of this fix asks for maxima by design: its case file and its run and review records; so do
        # the I-18 paraphrase matrix and its records, the Live check of the v12 routing extraction, and the development
        # model comparison's run and review records (it reran that check's cases), and the Live acceptance check of
        # computed maxima (D24, D25) and its records, the routing-only Live check of route contract v13 (D26), the
        # end-to-end Live acceptance check of v13 request resolution and its records, the routing-only Live check
        # of route contract v15 (its demand-maximum regression control, F07), and the comparative routing-only
        # evaluation of route contracts v15 and v16 (its held-out and development maxima) and its records
        if "traces" in f.parts or any(part.startswith(("livecheck_i15_17", "LC-i15-17", "structured_requests",
                                                       "livecheck_routing_v12", "LC-route-v12", "MC-dev",
                                                       "livecheck_maxima", "LC-maxima", "livecheck_route_v13",
                                                       "LC-route-v13", "livecheck_e2e_v13", "LC-e2e-v13",
                                                       "livecheck_route_v15", "LC-route-v15",
                                                       "compare_route_v15_v16", "CMP-route-v15-v16"))
                                      for part in f.parts):
            continue
        try:
            d = json.loads(f.read_text())
        except (ValueError, UnicodeDecodeError):
            continue
        items = d if isinstance(d, list) else d.get("cases") or ([d] if isinstance(d, dict) and "question" in d else [])
        found += [c["question"] for c in items if isinstance(c, dict) and isinstance(c.get("question"), str)
                  and requested_maxima(c["question"])]
    assert set(found) == {_z04()["question"]}


# ------------------------------------------------------------------------------------------------ Z04 replayed
def _replay(draft_fn=None, *, question: str | None = None, as_of: str | None = None):
    rec = _z04()
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    draft = rec["drafts"]["synthesis:draft"]
    fake = FakeModel(rec["route"], [calls], draft_fn or (lambda kw: copy.deepcopy(draft)))
    res = investigate(InvestigateRequest(question=question or rec["question"], mode="live", as_of_utc=as_of),
                      live_client=fake, write_trace=False)
    return res, fake


def test_3_the_live_controller_supplies_z04s_maximum():
    """With Z04's saved tool calls and draft, the controller computes and states TOTALDEMAND's maximum."""
    res, fake = _replay()
    b = res.resolution.demand_max[0]
    assert (b["measure"], b["value"], b["interval_ends_utc"], b["complete"]) == ("total demand", 1367.32, [MAX_END], True)
    assert b["window_kind"] == "day" and b["window_utc"] == DAY and b["intervals_held"] == b["intervals_in_window"] == 288
    (a,) = res.report.answer  # the computed answer (D25), rendered from the admitted result, apart from the summary
    assert (a.status, a.verification) == ("established", "verified")
    line = a.statement
    assert "dispatch total demand (TOTALDEMAND) was highest at 1367.32 MW" in line
    assert "ending 2026-07-28T21:55:00Z = 2026-07-29 07:55 AEST" in line
    o = next(o for o in res.report.observations if o.evidence_id == b["evidence_ids"][0])
    assert (o.metric, o.value, o.valid_at_utc, o.source_row_ids) == ("dispatch_totaldemand", 1367.32, MAX_END, [MAX_ROW])
    v = res.report.validation
    assert v["final_passed"] and not v["fallback_applied"], v["initial"]["violations"]
    assert "requested_maximum" in v["initial"]["checks_run"]
    sent = json.dumps(fake.requests[-1]["input"])
    assert "Requested demand maximum, computed by the controller" in sent  # the model is given it too


def test_3_replay_mode_supplies_z04s_maximum():
    res = investigate(InvestigateRequest(question=_z04()["question"], mode="replay"), write_trace=False)
    b = res.resolution.demand_max[0]
    assert (b["value"], b["interval_ends_utc"], b["complete"]) == (1367.32, [MAX_END], True)
    assert any("was highest at 1367.32 MW" in a.statement and "2026-07-29 07:55 AEST" in a.statement
               for a in res.report.answer)
    assert res.report.validation["final_passed"] and not res.report.validation["fallback_applied"]


def test_1_z04s_saved_answer_without_the_maximum_is_rejected():
    """The saved draft gave TOTALDEMAND at the price peak and operational demand's maximum, not the maximum asked for:
    without the controller's computed answer it does not answer, so it is not shown as an answer."""
    res, _ = _replay()
    b = res.resolution.demand_max
    ids = set(b[0]["evidence_ids"])
    saved = res.report.model_copy(update={
        "answer": [], "numeric_claims": [c for c in res.report.numeric_claims if c.evidence_id not in ids],
        "observations": [o for o in res.report.observations if o.evidence_id not in ids], "validation": {}})
    out = validate(saved, res.registry, records=res.records, demand_max=b)
    assert [v.code for v in out.critical] == ["REQUESTED_MAXIMUM_MISSING"]
    assert "1367.32" in out.critical[0].detail and MAX_END in out.critical[0].detail


def _stating(value: float, evidence_id: str, end: str, name: str = "TAS1 total demand"):
    """Z04's saved draft plus a sentence stating ``value`` as the measure's peak, claimed with ``evidence_id``."""
    def draft_fn(kw):
        d = copy.deepcopy(_z04()["drafts"]["synthesis:draft"])
        d["summary"] = [f"{name} peaked at {value} MW in the interval ending {end}."] + d["summary"]
        d["numeric_claims"].append({"claim_id": "nx", "text": f"{value} MW", "value": value, "unit": "MW",
                                    "evidence_id": evidence_id, "rounding": 0.005})
        return d
    return draft_fn


@pytest.mark.parametrize("value,evidence_id,end", [
    (1321.81, "ev0722", "2026-07-29T10:05:00Z"),  # TOTALDEMAND at the price peak
    (1452.0, "ev0885", "2026-07-28T22:00:00Z"),  # operational demand's maximum
])
def test_1_a_substitute_stated_as_the_peak_is_rejected_and_not_shown(value, evidence_id, end):
    res, _ = _replay(_stating(value, evidence_id, end))
    v = res.report.validation
    mism = [x["detail"] for x in (v.get("pre_repair") or v["initial"])["violations"]
            if x["code"] == "REQUESTED_MAXIMUM_MISMATCH"]
    assert mism and f"{value:g} is stated as the maximum of total demand" in mism[0]
    assert v["fallback_applied"] and not any(f"{value:g}" in s for s in res.report.summary)
    # the fallback still shows the maximum, as a validated observation
    assert any(o.value == 1367.32 and o.valid_at_utc == MAX_END for o in res.report.observations)


def test_2_a_faithful_answer_stating_the_maximum_passes():
    """The model's own evidence for the same row (ev0284, from its get_price_timeline call) is the maximum too."""
    res, _ = _replay(_stating(1367.32, "ev0284", MAX_END, "TAS1 dispatch total demand"))
    v = res.report.validation
    assert v["final_passed"] and not v["fallback_applied"], v["initial"]["violations"]
    assert any(s.startswith("TAS1 dispatch total demand peaked at 1367.32 MW") for s in res.report.summary)


# ------------------------------------------------------------------------------------------------ controls (SYNTHETIC)
def _series(values: dict[str, float]) -> tuple[EvidenceRegistry, list[dict], dict[str, str]]:
    """A SYNTHETIC day of TAS1 TOTALDEMAND (1000 MW, except ``values`` by interval end) and its registry."""
    reg = EvidenceRegistry()
    series, ids = [], {}
    t, end = datetime(2026, 7, 28, 14, 5, tzinfo=UTC), datetime(2026, 7, 29, 14, 0, tzinfo=UTC)
    while t <= end:
        at = t.strftime("%Y-%m-%dT%H:%M:%SZ")
        ev = reg.add(evidence_class="observed", metric="dispatch_totaldemand", value=values.get(at, 1000.0), unit="MW",
                     region="TAS1", valid_at_utc=at, interval_minutes=5, source_row_ids=[f"SYNTH:TD:{at}"],
                     source_urls=[], tool_call_id="t")
        series.append({"interval_end_utc": at, "totaldemand_mw": ev.value, "totaldemand_evidence_id": ev.evidence_id})
        ids[at] = ev.evidence_id
        t += timedelta(minutes=5)
    return reg, series, ids


def _resolution(as_of: str | None = None) -> Resolution:
    return Resolution(InvestigateRequest(question="SYNTHETIC: when did TAS1 total demand peak on 29 July 2026?"),
                      "market_event_review", "TAS1", None, None, None, routing={"dates_found": ["2026-07-29"]})


def _dispatcher(series: list[dict] | None, status: str = "ok", reason: str | None = None,
                reg: EvidenceRegistry | None = None):
    """A stand-in dispatcher returning SYNTHETIC series. Since D24 the computation submits its typed result to the
    investigation's result registry, which re-derives it from the store, and since D25 only an admitted result gives
    the binding a value. Its store is SYNTHETIC: the same series (``synthetic_store`` re-derives from it), so these
    controls test the validator against admitted results, as before."""
    def call(name, args, *, call_id=None, origin="controller"):
        return SimpleNamespace(status=status, call_id=call_id, blocked_reason=reason,
                               data={"series": series or []}, view={"excluded_not_yet_available_at_as_of": 0})
    reg = reg if reg is not None else EvidenceRegistry()
    store = SimpleNamespace(data_version="SYNTHETIC", synthetic={"series": series or [], "status": status,
                                                                 "reason": reason, "registry": reg})
    return SimpleNamespace(call=call, store=store, selection=load_selection(), registry=reg, results=ResultRegistry(),
                           trace=None)


@pytest.fixture
def synthetic_store(monkeypatch):
    """SYNTHETIC: a stand-in dispatcher's series is the store its results are re-derived from (D24)."""
    real = demand_max.rederive

    def rederive(identity, store, selection):
        s = getattr(store, "synthetic", None)
        if s is None:
            return real(identity, store, selection)
        return demand_max.result_from_output(identity, s["status"], {"series": s["series"]},
                                             {"excluded_not_yet_available_at_as_of": 0}, s["registry"], "rederive",
                                             s["reason"])
    monkeypatch.setattr(demand_max, "rederive", rederive)


def _report(summary: list[str], claims: list[tuple[str, float]], reg: EvidenceRegistry):
    base = investigate(InvestigateRequest(question=_z04()["question"], mode="replay"), write_trace=False).report
    obs = [Observation(metric=ev.metric, value=float(ev.value), unit=ev.unit, valid_at_utc=ev.valid_at_utc,
                       interval_minutes=ev.interval_minutes, evidence_id=e, source_row_ids=ev.source_row_ids,
                       evidence_class=ev.evidence_class, label=ev.metric) for e, _ in claims if (ev := reg.get(e))]
    return base.model_copy(update={
        "headline": "SYNTHETIC answer.", "summary": summary, "answer": [], "results": [],  # not the base's (D25)
        "possible_explanations": [], "published_findings": [],
        "citations": [], "uncertainties": [], "missing_evidence": [], "forecast_comparison": None, "validation": {},
        "observations": obs, "numeric_claims": [NumericClaim(claim_id=f"n{i}", text=f"{v}", value=v, unit="MW",
                                                             evidence_id=e, rounding=0.005)
                                                for i, (e, v) in enumerate(claims)]})


def _max_codes(report, reg, binding) -> list[str]:
    return [v.code for v in validate(report, reg, demand_max=binding).critical if "MAXIMUM" in v.code]


def test_an_equal_number_from_another_measure_does_not_satisfy_a_total_demand_request(synthetic_store):
    reg, series, ids = _series({"2026-07-28T21:55:00Z": 1452.0})
    op = reg.add(evidence_class="observed", metric="opdemand_actual", value=1452.0, unit="MW", region="TAS1",
                 valid_at_utc="2026-07-28T22:00:00Z", interval_minutes=30, source_row_ids=["SYNTH:OP"], source_urls=[],
                 tool_call_id="t")
    binding = [demand_max.compute(_dispatcher(series, reg=reg), _resolution(), "total demand")]
    assert binding[0]["evidence_ids"] == [ids["2026-07-28T21:55:00Z"]]
    as_peak = _report(["TAS1 total demand peaked at 1452 MW in the half-hour ending 2026-07-28T22:00:00Z."],
                      [(op.evidence_id, 1452.0)], reg)
    assert _max_codes(as_peak, reg, binding) == ["REQUESTED_MAXIMUM_MISSING", "REQUESTED_MAXIMUM_MISMATCH"]
    labelled = _report(["TAS1 operational demand was 1452 MW in the half-hour ending 2026-07-28T22:00:00Z."],
                       [(op.evidence_id, 1452.0)], reg)
    assert _max_codes(labelled, reg, binding) == ["REQUESTED_MAXIMUM_MISSING"]


def test_a_value_at_the_price_peak_satisfies_the_request_only_when_it_is_the_maximum(synthetic_store):
    reg, series, ids = _series({"2026-07-29T10:05:00Z": 1400.0, "2026-07-28T21:55:00Z": 1367.32})
    binding = [demand_max.compute(_dispatcher(series, reg=reg), _resolution(), "total demand")]
    at_peak = _report(["At the price peak, TAS1 total demand peaked at 1400 MW in the interval ending "
                       "2026-07-29T10:05:00Z."], [(ids["2026-07-29T10:05:00Z"], 1400.0)], reg)
    assert _max_codes(at_peak, reg, binding) == []  # here the price peak's interval is the maximum
    reg2, series2, ids2 = _series({"2026-07-29T10:05:00Z": 1321.81, "2026-07-28T21:55:00Z": 1367.32})
    binding2 = [demand_max.compute(_dispatcher(series2, reg=reg2), _resolution(), "total demand")]
    not_max = _report(["TAS1 total demand peaked at 1321.81 MW in the interval ending 2026-07-29T10:05:00Z."],
                      [(ids2["2026-07-29T10:05:00Z"], 1321.81)], reg2)
    assert _max_codes(not_max, reg2, binding2) == ["REQUESTED_MAXIMUM_MISSING", "REQUESTED_MAXIMUM_MISMATCH"]


def test_tied_maxima_are_all_stated_and_either_satisfies_the_request(synthetic_store):
    ends = ["2026-07-28T21:55:00Z", "2026-07-29T09:00:00Z"]
    reg, series, ids = _series({e: 1367.32 for e in ends})
    binding = [demand_max.compute(_dispatcher(series, reg=reg), _resolution(), "total demand")]
    assert binding[0]["interval_ends_utc"] == ends and len(binding[0]["evidence_ids"]) == 2
    claimed: list[str] = []
    line = demand_max.sentence(binding[0], "TAS1", lambda e: claimed.append(e) or "1367.32 MW", None)
    assert "in more than one 5-minute interval" in line and all(e in line for e in ends)
    assert claimed == binding[0]["evidence_ids"]  # each tied interval is claimed
    for e in ends:
        one = _report([f"TAS1 total demand peaked at 1367.32 MW in the interval ending {e}."], [(ids[e], 1367.32)], reg)
        assert _max_codes(one, reg, binding) == []
    full = _report([line], [(i, 1367.32) for i in binding[0]["evidence_ids"]], reg)
    assert not validate(full, reg, demand_max=binding).critical  # the sentence also passes I-15's time binding


@pytest.mark.parametrize("dispatcher,why", [
    (_dispatcher([]), "no value of the measure is held for the window"),
    # a run-time policy block cannot be re-derived from the store, so its result is unverifiable and, since D25, not
    # admitted: the binding gives the verifier's reason instead of the block (which the trace and the result keep)
    (_dispatcher(None, "blocked", "'get_price_timeline' already called 3 times"),
     "could not be verified against the pinned data (unverifiable)"),
])
def test_missing_data_or_a_blocked_call_says_the_maximum_cannot_be_given(dispatcher, why, synthetic_store):
    reg, _, ids = _series({})
    binding = [demand_max.compute(dispatcher, _resolution(), "total demand")]
    assert why in binding[0]["unavailable"] and "evidence_ids" not in binding[0]
    line = demand_max.sentence(binding[0], "TAS1", lambda e: "", None)
    assert line.startswith("The maximum of TAS1 dispatch total demand (TOTALDEMAND) over all of 2026-07-29 (AEST) "
                           "cannot be given")
    stated = _report(["TAS1 total demand peaked at 1000 MW in the interval ending 2026-07-28T21:55:00Z."],
                     [(ids["2026-07-28T21:55:00Z"], 1000.0)], reg)
    assert _max_codes(stated, reg, binding) == ["REQUESTED_MAXIMUM_MISMATCH"]
    assert _max_codes(_report([line], [], reg), reg, binding) == []


def test_an_as_of_cutoff_that_hides_part_of_the_window_is_said():
    """Under a 2026-07-29T05:00Z cutoff, the later intervals of 29 July are not yet public (real data)."""
    res = investigate(InvestigateRequest(question=_z04()["question"], mode="replay", as_of_utc="2026-07-29T05:00:00Z"),
                      write_trace=False)
    b = res.resolution.demand_max[0]
    assert not b["complete"] and b["excluded_by_as_of"] > 0 and b["intervals_held"] < b["intervals_in_window"]
    line = next(a.statement for a in res.report.answer if a.statement.startswith("Not every 5-minute interval"))
    assert "held and public by the as-of cutoff" in line and "cannot be established" in line
    assert res.report.validation["final_passed"]


def test_an_operational_demand_maximum_is_answered_with_operational_demand():
    q = ("Looking at Tasmania across 29 July 2026 in Hobart local time, what was the day's highest 5-minute dispatch "
         "price and when did it happen, and when did TAS1 operational demand peak and at what level?")
    res = investigate(InvestigateRequest(question=q, mode="replay"), write_trace=False)
    b = res.resolution.demand_max[0]
    assert (b["metric"], b["value"], b["interval_ends_utc"], b["complete"]) == (
        "opdemand_actual", 1452.0, ["2026-07-28T22:00:00Z"], True)
    assert any("TAS1 operational demand was highest at 1452 MW in the half-hour ending 2026-07-28T22:00:00Z" in s
               for s in [a.statement for a in res.report.answer])
    assert res.report.validation["final_passed"] and not res.report.validation["fallback_applied"]
    # TOTALDEMAND's maximum (the same day, its own evidence) stated as operational demand's peak is another measure
    tot = next(e for e, ev in res.registry.items.items() if ev.metric == "dispatch_totaldemand"
               and ev.valid_at_utc == MAX_END and ev.value == 1367.32)
    wrong = res.report.model_copy(update={
        "summary": ["TAS1 operational demand peaked at 1367.32 MW in the interval ending 2026-07-28T21:55:00Z."]
        + res.report.summary,
        "numeric_claims": [*res.report.numeric_claims, NumericClaim(claim_id="nx", text="1367.32 MW", value=1367.32,
                                                                    unit="MW", evidence_id=tot, rounding=0.005)],
        "validation": {}})
    codes = [v.code for v in validate(wrong, res.registry, demand_max=res.resolution.demand_max).critical]
    assert codes == ["REQUESTED_MAXIMUM_MISMATCH"]


@pytest.mark.parametrize("mode", ["live", "replay"])
def test_a_demand_peak_without_its_measure_is_sent_back(mode):
    q = ("Looking at Tasmania across 29 July 2026 in Hobart local time, what was the day's highest 5-minute dispatch "
         "price, and when did demand peak and at what level?")
    if mode == "live":
        res, fake = _replay(question=q)
        assert len(fake.requests) == 1 and not res.records  # the routing call only: no tool, nothing computed
    else:
        res = investigate(InvestigateRequest(question=q, mode="replay"), write_trace=False)
    assert res.report.status == "needs_clarification" and MAXIMUM_CLARIFICATION in res.report.headline


def test_values_at_the_price_peak_asked_for_as_such_are_not_bound():
    q = ("Overnight into 31 July 2026, SA1 prices hit extreme levels. I need the highest dispatch price with its "
         "interval, SA1's TOTALDEMAND for that very interval, and a tally of event-window intervals priced at "
         "$300/MWh or above.")
    res = investigate(InvestigateRequest(question=q, mode="replay"), write_trace=False)
    assert res.resolution.demand_max is None
    assert "requested_maximum" not in res.report.validation["initial"]["checks_run"]


# ------------------------------------------------------------------------------------------------ the requested window
# (I-17 review) A whole day only when the question clearly asks for one; an explicit request window exactly; an event's
# window from the event the resolution holds; anything else sent back. Never the day's maximum in place of another
# window's. VIC1's low-price event (2026-07-27T23:00Z to 2026-07-28T23:30Z) runs into 29 July (AEST); both are fully
# held, and their TOTALDEMAND maxima differ: 7,867.57 MW at 22:10Z (event) and 8,700.91 MW at 08:30Z on the 29th (day).
VIC_EVENT_Q = ("Walk me through the low-price event that ran into 29 July 2026 in Victoria (AEST): what was the lowest "
               "dispatch price, and when during the event did VIC1 total demand peak and at what level?")
VIC_DAY_Q = ("Looking at Victoria across 29 July 2026 in Melbourne local time, what was the day's lowest 5-minute "
             "dispatch price, and when did VIC1 total demand peak and at what level?")
VIC_EVENT = ["2026-07-27T23:00:00Z", "2026-07-28T23:30:00Z"]


@pytest.mark.parametrize("question,request_window,kind", [
    (None, False, "day"),  # Z04: "across 29 July 2026 …", "the day's"
    ("When did TAS1 total demand peak on 29 July 2026?", False, "day"),
    (None, True, "explicit"),  # the request's own window fields
    (VIC_EVENT_Q, False, "event"),
    ("On 29 July 2026, when did TAS1 total demand peak during the morning?", False, "unresolved"),
    ("When did TAS1 total demand peak between 06:00 and 09:00 AEST on 29 July 2026?", False, "unresolved"),
    ("When did TAS1 total demand peak around the price spike on 29 July 2026?", False, "unresolved"),
    ("What was the day's peak total demand in TAS1 from 06:00 to 09:00 AEST on 29 July 2026?", False, "unresolved"),
    ("When did TAS1 total demand peak?", False, "unresolved"),  # nothing says which window
])
def test_the_window_of_a_maximum_is_read(question, request_window, kind):
    q = question or _z04()["question"]
    w = {"window_start_utc": "2026-07-29T00:00:00Z", "window_end_utc": "2026-07-29T06:00:00Z"} if request_window else {}
    assert maximum_window_kind(q, InvestigateRequest(question=q, **w)) == kind


def test_an_event_maximum_uses_the_event_window_and_a_whole_day_maximum_the_day():
    ev = investigate(InvestigateRequest(question=VIC_EVENT_Q, mode="replay"), write_trace=False)
    b = ev.resolution.demand_max[0]
    assert (b["window_kind"], b["window_utc"], b["complete"]) == ("event", VIC_EVENT, True)
    assert (b["value"], b["interval_ends_utc"]) == (7867.57, ["2026-07-28T22:10:00Z"])
    assert any("was highest at 7867.57 MW" in s and "over the event window, 2026-07-27T23:00:00Z to "
               "2026-07-28T23:30:00Z" in s for s in [a.statement for a in ev.report.answer])
    assert ev.report.validation["final_passed"] and not ev.report.validation["fallback_applied"]
    day = investigate(InvestigateRequest(question=VIC_DAY_Q, mode="replay"), write_trace=False)
    d = day.resolution.demand_max[0]
    assert (d["window_kind"], d["window_utc"], d["complete"]) == ("day", ["2026-07-28T14:00:00Z", "2026-07-29T14:00:00Z"],
                                                                  True)
    assert (d["value"], d["interval_ends_utc"]) == (8700.91, ["2026-07-29T08:30:00Z"])  # not the event's maximum
    assert any("was highest at 8700.91 MW" in s and "over all of 2026-07-29 (AEST)" in s
               for s in [a.statement for a in day.report.answer])
    assert day.report.validation["final_passed"] and not day.report.validation["fallback_applied"]


def _vic_live(draft_fn):
    """VIC_EVENT_Q in Live mode; the model fetched the whole local day, so the day's maximum is in its evidence."""
    route = {"intent": "market_event_review", "region": "VIC1", "event_date": "2026-07-29", "as_of_utc": None,
             "needs_clarification": False, "clarification_reason": None, "clarification": None, "out_of_scope": False}
    calls = [("get_price_timeline", {"region": "VIC1", "start_utc": "2026-07-28T14:00:00Z", "end_utc": "2026-07-29T14:00:00Z"})]
    fake = FakeModel(route, [calls], draft_fn)
    return investigate(InvestigateRequest(question=VIC_EVENT_Q, mode="live"), live_client=fake, write_trace=False)


def _draft(text: str, claims: list[tuple[str, float]]) -> dict:
    return {"status": "answered", "headline": "SYNTHETIC answer.", "summary": [text], "document_statements": [],
            "observation_evidence_ids": [e for e, _ in claims], "possible_explanations": [], "published_findings": [],
            "citations": [], "uncertainties": [], "missing_evidence": [], "forecast_mae_evidence_id": None,
            "numeric_claims": [{"claim_id": f"n{i}", "text": f"{v} MW", "value": v, "unit": "MW", "evidence_id": e,
                                "rounding": 0.005} for i, (e, v) in enumerate(claims)]}


def test_the_days_maximum_stated_as_the_events_peak_is_rejected():
    probe = _vic_live(lambda kw: _draft("SYNTHETIC.", []))
    b = probe.resolution.demand_max[0]
    assert (b["window_kind"], b["value"]) == ("event", 7867.57)
    day_max = next(e for e, ev in probe.registry.items.items() if ev.metric == "dispatch_totaldemand"
                   and ev.valid_at_utc == "2026-07-29T08:30:00Z" and ev.value == 8700.91)
    res = _vic_live(lambda kw: _draft("VIC1 total demand peaked at 8700.91 MW in the interval ending "
                                      "2026-07-29T08:30:00Z.", [(day_max, 8700.91)]))
    v = res.report.validation
    mism = [x["detail"] for x in (v.get("pre_repair") or v["initial"])["violations"]
            if x["code"] == "REQUESTED_MAXIMUM_MISMATCH"]
    assert mism and "the maximum is 7867.57" in mism[0]
    assert v["fallback_applied"] and not any("8700.91" in s for s in res.report.summary)
    assert any(o.value == 7867.57 and o.valid_at_utc == "2026-07-28T22:10:00Z" for o in res.report.observations)


def test_an_explicit_request_window_is_used_exactly_and_the_days_maximum_does_not_stand_in():
    w = {"window_start_utc": "2026-07-29T00:00:00Z", "window_end_utc": "2026-07-29T06:00:00Z"}
    rep = investigate(InvestigateRequest(question=_z04()["question"], mode="replay", **w), write_trace=False)
    b = rep.resolution.demand_max[0]
    assert (b["window_kind"], b["window_utc"], b["complete"]) == ("explicit", [w["window_start_utc"], w["window_end_utc"]],
                                                                  True)
    assert (b["value"], b["interval_ends_utc"]) == (1164.48, ["2026-07-29T00:10:00Z"])  # not the day's 1367.32
    assert any("over the requested window, 2026-07-29T00:00:00Z to 2026-07-29T06:00:00Z" in s
               for s in [a.statement for a in rep.report.answer])
    # Z04's saved tool calls cover the whole day: its maximum (ev0284) stated as the window's peak is rejected
    rec = _z04()
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    live = investigate(InvestigateRequest(question=rec["question"], mode="live", **w), write_trace=False,
                       live_client=FakeModel(rec["route"], [calls], _stating(1367.32, "ev0284", MAX_END)))
    assert "REQUESTED_MAXIMUM_MISMATCH" in _codes(live.report.validation)


@pytest.mark.parametrize("question,clarification", [
    ("Looking at Tasmania on 29 July 2026, what was the highest dispatch price, and when did TAS1 total demand peak "
     "during the morning?", MAXIMUM_WINDOW_CLARIFICATION),
    ("Looking at Tasmania on 29 July 2026, what was the highest dispatch price, and when did TAS1 total demand peak "
     "between 06:00 and 09:00 AEST?", MAXIMUM_WINDOW_CLARIFICATION),
    ("Looking at Tasmania on 29 July 2026, what was the highest dispatch price, and when did TAS1 total demand peak "
     "around the price spike?", MAXIMUM_WINDOW_CLARIFICATION),
    # event-relative, but no event is held for TAS1 on 29 July: its window cannot be established
    ("Looking at Tasmania on 29 July 2026, what was the highest dispatch price, and when during the price event did "
     "TAS1 total demand peak?", MAXIMUM_EVENT_CLARIFICATION),
])
@pytest.mark.parametrize("mode", ["live", "replay"])
def test_a_window_that_is_not_given_is_sent_back_without_a_maximum(question, clarification, mode):
    if mode == "live":
        res, fake = _replay(question=question)
        assert len(fake.requests) == 1 and not res.records  # the routing call only: nothing fetched or computed
    else:
        res = investigate(InvestigateRequest(question=question, mode="replay"), write_trace=False)
    assert res.report.status == "needs_clarification" and clarification in res.report.headline
    assert res.resolution.demand_max is None and not res.report.observations
