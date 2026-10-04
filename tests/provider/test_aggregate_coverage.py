"""Issue I-20 (docs/issue-tracker.md): an aggregate carries what it was computed from, and statements of its duration,
interval count and completeness are read against that.

Live check of the v12 routing extraction (E-dev, 2026-10-03, code f2455ca): K05 said "the run's MAE for the 24-hour
target window as 10.0 MW". The MAE (ev0554) was the mean over one paired half-hour (ending 2026-08-06T08:00:00Z) of a
12-hour comparison window holding 24 target half-hours. It passed validation and was shown.

Coverage is recorded from the calculation's own inputs on real data (the pinned store), including a real gap between
held days (2026-07-29T20:00Z to 2026-07-30T04:30Z) for non-contiguous coverage. K05 is replayed from its saved draft and
its actual saved repair through the SYNTHETIC fake transport (no network, no key); the statement controls are scripted
variants, labelled as such. Scripted replays are not a measure of Live behaviour.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from nem_agent.agent.dispatcher import Dispatcher
from nem_agent.agent.request import InvestigateRequest
from nem_agent.evidence import EvidenceRegistry, aggregate_coverage
from nem_agent.report import NumericClaim
from nem_agent.service import investigate
from nem_agent.timeutil import parse_iso
from nem_agent.trace import Trace
from nem_agent.validation import validate
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

ROOT = Path(__file__).resolve().parents[2]
E2E = ROOT / "artifacts" / "live" / "LC-route-v12-e2e"
K05_WINDOW = ["2026-08-05T20:00:00Z", "2026-08-06T08:00:00Z"]  # 12 hours, 24 target half-hours
CODE = "AGGREGATE_COVERAGE_MISMATCH"


def _rec() -> dict:
    return json.loads((E2E / "K05.json").read_text())


def _replay(draft_fn=None, repair_fn=None):
    """K05's saved route, tool calls and draft; the repair is its actual saved one (a scoped patch: the claim's unit)."""
    rec = _rec()
    trace = json.loads((E2E / "traces" / f"{rec['score']['trace_id']}.json").read_text())["events"]
    patch = next(e.get("patch") for e in trace if e["name"] == "repair:scoped")
    draft = rec["drafts"]["synthesis:draft"]
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    fake = FakeModel(rec["route"], [calls], draft_fn or (lambda kw: copy.deepcopy(draft)),
                     repair_fn or (lambda kw: copy.deepcopy(patch)))
    return investigate(InvestigateRequest(question=rec["question"], mode="live"), live_client=fake, write_trace=False)


def _first(res) -> list[tuple[str, str]]:
    v = res.report.validation
    return [(x["code"], x["detail"]) for x in (v.get("pre_repair") or v["initial"])["violations"]]


def _items(found) -> list[str]:
    return sorted(d.split(":", 1)[0] for c, d in found if c == CODE)


def _only_the_d28_scope_rule(res) -> None:
    """I-20 accepts the wording; the only violations left are D28's: K05 asks about one half-hour, so no aggregate (its
    MAE, even over exactly that half-hour's one pair) is stated (``FORECAST_SCOPE_NOT_PRIMARY``)."""
    first = _first(res)
    assert _items(first) == [] and {c for c, _ in first} == {"FORECAST_SCOPE_NOT_PRIMARY"}, first
    assert all("ev0554" in d or "ev0555" in d or "ev0553" in d for _, d in first)


def _k05(summary3: str | None = None, claim_text: str | None = None, headline: str | None = None,
         uncertainties: list[str] | None = None, missing: list[str] | None = None):
    """K05's draft with its claim unit fixed (as its saved repair did) and items replaced: a scripted variant."""
    def fn(kw):
        d = copy.deepcopy(_rec()["drafts"]["synthesis:draft"])
        d["numeric_claims"][3]["unit"] = "%"
        if summary3 is not None:
            d["summary"][3] = summary3
        if claim_text is not None:
            d["numeric_claims"][4]["text"] = claim_text
        if headline is not None:
            d["headline"] = headline
        if uncertainties is not None:
            d["uncertainties"] = uncertainties
        if missing is not None:
            d["missing_evidence"] = missing
        return d
    return fn


FAITHFUL = {"summary3": "The run's MAE, over the one half-hour with a pair (ending 2026-08-06 18:00 AEST), is 10.0 MW "
                        "(evidence ev0554).",
            "claim_text": "MAE 10.0 MW over the one paired half-hour"}


# ------------------------------------------------------------------------------------------------ K05
def test_3_k05s_mae_records_what_it_was_computed_from():
    res = _replay()
    ev = res.registry.get("ev0554")
    assert (ev.metric, ev.value) == ("mae_mw", 10.0)
    c = ev.coverage
    assert c["window_utc"] == K05_WINDOW and c["interval_minutes"] == 30
    assert (c["intervals_included"], c["intervals_expected"]) == (1, 24)
    assert c["included_ends_utc"] == ["2026-08-06T08:00:00Z"] and not c["complete"] and c["contiguous"]
    assert c["gaps_utc"] == [["2026-08-05T20:00:00Z", "2026-08-06T07:30:00Z"]]
    cmp_ = next(r for r in res.records if r.call_id and r.view.get("mae_mw", {}).get("evidence_id") == "ev0554")
    for key in ("mean_error_mw", "n_pairs_evidence_id"):  # the other two aggregates of the call share it
        eid = cmp_.view[key]["evidence_id"] if key == "mean_error_mw" else cmp_.view[key]
        assert res.registry.get(eid).coverage == c


def test_1_k05s_24_hour_claim_is_rejected_and_not_shown():
    res = _replay()
    first = _first(res)
    assert _items(first) == ["c5", "summary[3]"]
    detail = next(d for c, d in first if c == CODE and d.startswith("summary[3]"))
    assert "“24‑hour” for the MAE (ev0554)" in detail
    assert "1 of the 24 30-minute intervals of 2026-08-05T20:00:00Z to 2026-08-06T08:00:00Z" in detail
    v = res.report.validation  # the actual saved repair fixed only the claim's unit: it falls back
    assert v["fallback_applied"] and not any("24" in s and "hour" in s for s in res.report.summary)


def test_2_a_faithful_description_of_its_one_paired_half_hour_passes():
    """I-20 accepts it. Since D28 the MAE is not stated at all for a one-half-hour request (it was shown before)."""
    res = _replay(_k05(**FAITHFUL))
    _only_the_d28_scope_rule(res)
    assert not any("MAE" in s for s in res.report.summary)


def test_2_a_faithful_repair_of_k05_passes_i20_but_d28_withholds_the_mae():
    """It was shown before D28. I-20 still names exactly the two items the repair fixes; since D28 the MAE is not stated
    at all for this one-half-hour request, so the answer falls back without it."""
    def repair(kw):  # a scoped patch replacing both rejected items and the claim's unit
        return {"edits": [{"target": "summary[3]", "action": "replace", "text": FAITHFUL["summary3"]},
                          {"target": "numeric_claims[c5]", "action": "replace",
                           "claim": {**_rec()["drafts"]["synthesis:draft"]["numeric_claims"][4],
                                     "text": FAITHFUL["claim_text"]}},
                          {"target": "numeric_claims[c4]", "action": "replace",
                           "claim": {**_rec()["drafts"]["synthesis:draft"]["numeric_claims"][3], "unit": "%"}}],
                "new_numeric_claims": [], "new_citations": []}
    res = _replay(repair_fn=repair)
    assert _items(_first(res)) == ["c5", "summary[3]"]
    v = res.report.validation
    assert v["fallback_applied"] and v["final_passed"] and not any("MAE" in x for x in res.report.summary)


@pytest.mark.parametrize("summary3", [
    "The run's MAE over the 12-hour comparison window, in which one half-hour had a pair, is 10.0 MW.",
    "The run's MAE, from one of the twenty-four half-hours of the window, is 10.0 MW.",
    "The run's MAE for the half-hour ending 2026-08-06 18:00 AEST is 10.0 MW.",
    "The run's MAE is 10.0 MW.",  # no coverage stated
    "The run's MAE is 10.0 MW; it does not cover the whole 12-hour window.",  # a negated claim
    "The run's MAE of its 30-minute pairs is 10.0 MW.",  # an interval length, not coverage
])
def test_2_partial_coverage_described_by_what_it_includes_passes(summary3):
    """I-20 accepts each wording (D28 rejects the aggregate itself for this one-half-hour request)."""
    _only_the_d28_scope_rule(_replay(_k05(summary3=summary3, claim_text="MAE 10.0 MW")))


@pytest.mark.parametrize("summary3,phrase", [
    ("The run's MAE over the 12-hour comparison window is 10.0 MW.", "12-hour"),
    ("The run's MAE across all half-hours of the window is 10.0 MW.", "across all half-hours"),
    ("The run's MAE over twenty-four half-hours is 10.0 MW.", "twenty-four half-hours"),
    ("The run's MAE, from one of the twelve half-hours of the window, is 10.0 MW.", "one of the twelve half-hours"),
    ("The run's MAE between 2026-08-05T20:00:00Z and 2026-08-06T08:00:00Z is 10.0 MW.", "2026-08-05T20:00:00Z"),
    ("The run's MAE over the day is 10.0 MW.", "the day"),
])
def test_1_partial_coverage_described_as_more_is_rejected(summary3, phrase):
    res = _replay(_k05(summary3=summary3, claim_text="MAE 10.0 MW"))
    first = _first(res)
    assert _items(first) == ["summary[3]"], first
    assert f"“{phrase}" in next(d for c, d in first if c == CODE)


def test_1_the_headline_caveats_and_the_models_own_headline_are_read():
    res = _replay(_k05(**FAITHFUL, headline="MAE 10.0 MW over the 24-hour target window for the requested run.",
                       uncertainties=["The MAE of 10.0 MW covers the whole target window."],
                       missing=["Nothing further: the MAE already covers the full 12-hour window."]))
    assert _items(_first(res)) == ["headline", "missing_evidence[0]", "uncertainties[0]"]
    rep = res.report  # no repair is scripted: it falls back without the rejected caveats
    assert res.report.validation["fallback_applied"]
    assert not any("whole target window" in x or "full 12-hour" in x for x in rep.uncertainties + rep.missing_evidence)
    ok = _replay(_k05(**FAITHFUL))  # since D28 a fallback without the MAE: the claim is put back to read I-20 alone
    claim = NumericClaim(**{**_rec()["drafts"]["synthesis:draft"]["numeric_claims"][4], "text": FAITHFUL["claim_text"]})
    rep = ok.report.model_copy(update={"numeric_claims": [*ok.report.numeric_claims, claim]})
    rep._model_headline = "MAE 10.0 MW over the 24-hour target window."
    out = validate(rep, ok.registry, records=ok.records)
    assert [v.detail.split(":", 1)[0] for v in out.critical if v.code == CODE] == ["headline (the model's own, not shown)"]


def test_2_caveats_without_a_coverage_claim_or_with_a_limited_one_pass():
    """I-20 accepts the caveats (D28 rejects the aggregate itself for this one-half-hour request)."""
    _only_the_d28_scope_rule(_replay(_k05(**FAITHFUL, uncertainties=["The MAE covers only one half-hour, so it says "
                                                                     "little about the run."],
                                         missing=["Forecast-actual pairs for the rest of the comparison window."])))


# ------------------------------------------------------------------------------------------------ coverage, real data
@pytest.fixture
def call():
    from nem_agent.service import _shared
    store, selection = _shared()[0], _shared()[1]

    def _call(tool: str, args: dict, as_of: str | None = None):
        d = Dispatcher(store, selection, Trace(), EvidenceRegistry(),
                       "forecast_review" if tool == "compare_forecast_actual" else "market_event_review",
                       parse_iso(as_of) if as_of else None)
        rec = d.call(tool, {**args, **({"as_of_utc": as_of} if as_of else {})})
        assert rec.status == "ok", rec.view
        metric = "mae_mw" if tool == "compare_forecast_actual" else "mean_dispatch_rrp"
        ev = next(e for e in d.registry.items.values() if e.metric == metric)
        return d.registry, ev
    return _call


def _cmp(start: str, end: str, selector: str = "latest_before_target") -> dict:
    return {"region": "QLD1", "target_start_utc": start, "target_end_utc": end, "run_selector": selector}


def test_3_full_coverage(call):
    _, ev = call("compare_forecast_actual", _cmp(*K05_WINDOW))
    c = ev.coverage
    assert (c["intervals_included"], c["intervals_expected"], c["complete"], c["contiguous"]) == (24, 24, True, True)
    assert c["runs_utc"] == [K05_WINDOW] and c["gaps_utc"] == [] and c["excluded_by_as_of"] is None


def test_3_as_of_limited_coverage(call):
    _, ev = call("compare_forecast_actual", _cmp(*K05_WINDOW), as_of="2026-08-06T05:00:00Z")
    c = ev.coverage
    assert (c["intervals_included"], c["intervals_expected"], c["complete"], c["excluded_by_as_of"]) == (12, 24, False, 12)
    assert c["runs_utc"] == [["2026-08-05T20:00:00Z", "2026-08-06T02:00:00Z"]]
    assert all(parse_iso(t) <= parse_iso("2026-08-06T05:00:00Z") for t in c["included_ends_utc"])


def test_3_non_contiguous_coverage_is_never_one_span(call):
    """The pinned store holds no rows from 2026-07-29T20:00Z to 2026-07-30T04:30Z (between held days)."""
    _, ev = call("compare_forecast_actual", _cmp("2026-07-29T14:00:00Z", "2026-07-30T14:00:00Z"))
    c = ev.coverage
    assert (c["intervals_included"], c["intervals_expected"], c["complete"], c["contiguous"]) == (31, 48, False, False)
    assert c["runs_utc"] == [["2026-07-29T14:00:00Z", "2026-07-29T20:00:00Z"],
                             ["2026-07-30T04:30:00Z", "2026-07-30T14:00:00Z"]]
    assert c["gaps_utc"] == [["2026-07-29T20:00:00Z", "2026-07-30T04:30:00Z"]]


def test_3_the_price_timelines_mean_full_gapped_and_as_of_limited(call):
    day = {"region": "QLD1", "start_utc": "2026-07-28T14:00:00Z", "end_utc": "2026-07-29T14:00:00Z"}
    _, full = call("get_price_timeline", day)
    assert (full.coverage["intervals_included"], full.coverage["intervals_expected"], full.coverage["complete"]) == \
        (288, 288, True)
    assert full.coverage["interval_minutes"] == 5 and len(full.source_row_ids) == 288
    _, cut = call("get_price_timeline", day, as_of="2026-07-29T05:00:00Z")
    assert not cut.coverage["complete"] and cut.coverage["excluded_by_as_of"] > 0
    assert cut.coverage["intervals_included"] + cut.coverage["excluded_by_as_of"] == 288
    _, gapped = call("get_price_timeline", {"region": "QLD1", "start_utc": "2026-07-29T14:00:00Z",
                                            "end_utc": "2026-07-30T14:00:00Z"})
    assert (gapped.coverage["intervals_included"], gapped.coverage["contiguous"]) == (186, False)


def test_3_coverage_comes_from_the_included_intervals_not_their_first_and_last():
    t = [parse_iso(x) for x in ("2026-08-05T20:30:00Z", "2026-08-06T08:00:00Z")]
    c = aggregate_coverage((parse_iso(K05_WINDOW[0]), parse_iso(K05_WINDOW[1])), 30, t)
    assert (c["intervals_included"], c["contiguous"], len(c["runs_utc"])) == (2, False, 2)


def test_3_items_without_coverage_serialise_as_before():
    reg = EvidenceRegistry()
    ev = reg.add(evidence_class="observed", metric="dispatch_rrp", value=1.0, unit="$/MWh", region="SA1",
                 valid_at_utc="2026-07-29T08:00:00Z", interval_minutes=5, source_row_ids=["r"], source_urls=[],
                 tool_call_id="t")
    assert "coverage" not in ev.as_dict()


# ------------------------------------------------------------------------------------------------ statements, real data
def _codes(reg: EvidenceRegistry, ev, text: str) -> list[str]:
    """The coverage findings for one summary sentence stating ``ev``'s value, in a report built from K05's replay."""
    base = _replay(_k05(**FAITHFUL)).report
    rep = base.model_copy(update={
        "region": ev.region, "summary": [text], "headline": "SYNTHETIC answer.", "uncertainties": [],
        "missing_evidence": [], "possible_explanations": [], "published_findings": [], "citations": [],
        "observations": [], "forecast_comparison": None, "validation": {},
        "numeric_claims": [NumericClaim(claim_id="n1", text="the aggregate", value=ev.value, unit=ev.unit,
                                        evidence_id=ev.evidence_id, rounding=0.005)]})
    return [v.detail for v in validate(rep, reg).critical if v.code == CODE]


@pytest.mark.parametrize("text,ok", [
    ("Over the whole 12-hour window the MAE was {v} MW.", True),
    ("Across all twenty-four half-hours the MAE was {v} MW.", True),
    ("The MAE over 12 hours of continuous pairs was {v} MW.", True),
])
def test_statements_with_full_coverage(call, text, ok):
    reg, ev = call("compare_forecast_actual", _cmp(*K05_WINDOW))
    assert (_codes(reg, ev, text.format(v=ev.value)) == []) is ok


@pytest.mark.parametrize("text,ok", [
    ("Over the whole window the MAE was {v} MW.", False),
    ("Over the 12-hour window the MAE was {v} MW.", False),
    ("Over the twelve half-hours public by the cutoff the MAE was {v} MW.", True),
    ("Over 6 hours of pairs the MAE was {v} MW.", True),  # one contiguous run of 12 half-hours
])
def test_statements_with_as_of_limited_coverage(call, text, ok):
    reg, ev = call("compare_forecast_actual", _cmp(*K05_WINDOW), as_of="2026-08-06T05:00:00Z")
    assert (_codes(reg, ev, text.format(v=ev.value)) == []) is ok


@pytest.mark.parametrize("text,ok", [
    ("Between 2026-07-29T14:00:00Z and 2026-07-30T14:00:00Z the MAE was {v} MW.", False),  # the window
    ("Between 2026-07-29T14:30:00Z and 2026-07-30T14:00:00Z the MAE was {v} MW.", False),  # first to last included
    ("The MAE over continuous pairs was {v} MW.", False),
    ("The MAE over 15.5 hours was {v} MW.", False),  # the included count as a duration, gapped
    ("The MAE over 31 paired half-hours (15.5 hours, in two separate runs) was {v} MW.", True),
])
def test_statements_with_non_contiguous_coverage(call, text, ok):
    reg, ev = call("compare_forecast_actual", _cmp("2026-07-29T14:00:00Z", "2026-07-30T14:00:00Z"))
    assert (_codes(reg, ev, text.format(v=ev.value)) == []) is ok


@pytest.mark.parametrize("as_of,ok", [(None, True), ("2026-07-29T05:00:00Z", False)])
def test_statements_about_the_mean_price_over_the_day(call, as_of, ok):
    reg, ev = call("get_price_timeline", {"region": "QLD1", "start_utc": "2026-07-28T14:00:00Z",
                                          "end_utc": "2026-07-29T14:00:00Z"}, as_of=as_of)
    assert (_codes(reg, ev, f"The mean dispatch price over the whole day was {ev.value} $/MWh.") == []) is ok


# ------------------------------------------------------------------------------------------------ unaffected
@pytest.mark.parametrize("text", [
    "Using only runs issued at least a day ahead (the day-ahead view), the mean absolute error was {v} MW.",
    "The MAE was {v} MW; the run was issued 24 hours before the window's last half-hour.",
    "The MAE was {v} MW.",
    "The run issued at 2026-08-05 14:00 UTC covered the 24-hour horizon, and the half-hour's POE50 was 7598.0 MW.",
])
def test_unrelated_durations_and_aggregates_without_a_coverage_claim_are_unaffected(call, text):
    reg, ev = call("compare_forecast_actual", _cmp(*K05_WINDOW, selector="run_id") | {
        "run_id": "PUBLIC_FORECAST_OPERATIONAL_DEMAND_HH_202608061800_20260806173222"})
    assert ev.coverage["intervals_included"] == 1
    assert _codes(reg, ev, text.format(v=ev.value)) == []


# ------------------------------------------------------------------------------------------------ qualifiers (PR #60 review)
# A qualifier qualifies the statement it stands before, not every statement in the aggregate's clauses. At the PR's
# first head (2b10008) "only", a negation or "incomplete" anywhere there switched every duration and completeness check
# off: the four "reject" statements below passed, and the negated count was rejected.
QUALIFIERS = [  # (aggregate: K05's 1 of 24, or the gapped 31 of 48), statement, passes
    ("k05", "This MAE covers only a 24-hour window.", False),
    ("gap", "The coverage is not continuous, but the MAE covers all forty-eight half-hours.", False),
    ("k05", "The MAE uses only one of the twenty-four half-hours.", True),
    ("k05", "This MAE does not cover the full window.", True),
    ("gap", "The coverage is not continuous, but the MAE covers the whole window.", False),
    ("k05", "Only this MAE is reported, and it covers the whole 12-hour window.", False),
    ("k05", "The MAE covers an incomplete 24-hour window.", False),
    ("k05", "The MAE covers an incomplete 12-hour window.", True),
    ("k05", "The MAE covers only 30 minutes of the 12-hour window.", True),
    ("k05", "The MAE does not use all twenty-four half-hours.", True),
    ("k05", "The MAE is not for the 24-hour window.", True),
    ("gap", "The MAE does not cover a continuous period.", True),
]


@pytest.mark.parametrize("which,text,ok", QUALIFIERS)
@pytest.mark.parametrize("valued", [False, True])
def test_a_qualifier_affects_only_the_statement_it_qualifies(call, which, text, ok, valued):
    if which == "k05":
        res = _replay(_k05(**FAITHFUL))
        reg, ev = res.registry, res.registry.get("ev0554")
    else:
        reg, ev = call("compare_forecast_actual", _cmp("2026-07-29T14:00:00Z", "2026-07-30T14:00:00Z"))
    if valued:  # the MAE given by its value, as well as named
        text = text.replace("MAE", f"MAE of {ev.value} MW", 1)
    assert (_codes(reg, ev, text) == []) is ok
