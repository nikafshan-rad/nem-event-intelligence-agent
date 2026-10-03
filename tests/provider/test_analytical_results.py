"""D24 (docs/decisions.md): typed analytical results for demand maxima: the contract, identity, admission by the
runtime verifier, serialisation, and re-verification against the pinned store.

Saved Live records are replayed through the SYNTHETIC fake transport (no network, no key); Replay answers run the
scripted controller over the pinned store. Synthetic series and tampered results are labelled as such. Nothing here
measures Live quality: this is a foundation, and every displayed answer is unchanged.
"""

from __future__ import annotations

import copy
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from nem_agent.agent import demand_max as DM
from nem_agent.agent.demand_max import MEASURES, binding_from_result, requested_window, result_from_output
from nem_agent.agent.live import ModelReport, RepairPatch, apply_patch
from nem_agent.agent.request import InvestigateRequest
from nem_agent.evidence import EvidenceRegistry
from nem_agent.report import InvestigationReport
from nem_agent.results import (
    AnalyticalResult,
    ReportedResult,
    ResultIdentity,
    ResultRegistry,
    Transient,
    VerifiedResult,
    _content,
    _sha,
    make_result,
    verify_in_run,
    verify_loaded,
)
from nem_agent.selection import load_selection
from nem_agent.service import investigate
from nem_agent.store import Store
from nem_agent.timeutil import iso_utc, parse_iso
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

LIVE = Path(__file__).resolve().parents[2] / "artifacts" / "live"
SAVED = [("L3-holdout-v6", "Z04"), ("LC-i15-17-dev", "Z04"), ("LC-i15-17-fresh", "K11"), ("LC-route-v12-e2e", "K09"),
         ("MC-dev-e2e-mini", "K09"), ("MC-dev-e2e-mini", "K11"), ("MC-dev-e2e-sol", "K09"), ("MC-dev-e2e-sol", "K11")]
STORE = Store()
SELECTION = load_selection()


def _rec(label: str, cid: str) -> dict:
    return json.loads((LIVE / label / f"{cid}.json").read_text())


def _replay(label: str, cid: str, draft_edit=None):
    """A saved Live record's route, tool calls, draft and actual saved repair, through the fake transport."""
    rec = _rec(label, cid)
    trace = json.loads((LIVE / label / "traces" / f"{rec['score']['trace_id']}.json").read_text())["events"]
    draft = rec["drafts"]["synthesis:draft"]
    patch = next((e.get("patch") for e in trace if e["name"] == "repair:scoped"), None)
    repaired = rec["drafts"].get("repair:draft")

    def saved(kw):
        return copy.deepcopy(patch if kw["text"]["format"]["name"] == "RepairPatch" else repaired)

    def first(kw):
        d = copy.deepcopy(draft)
        return draft_edit(d) if draft_edit else d
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    fake = FakeModel(rec["route"], [calls], first, saved if (patch or repaired) else None)
    return investigate(InvestigateRequest(question=rec["question"], mode="live", **(rec.get("request") or {})),
                       live_client=fake, write_trace=False)


def _z04_replay(as_of: str | None = None):
    q = _rec("L3-holdout-v6", "Z04")["question"]
    return investigate(InvestigateRequest(question=q, mode="replay", as_of_utc=as_of), write_trace=False)


def _legacy_binding(res, measure: str, rec) -> dict[str, Any]:
    """REFERENCE: `demand_max.compute` as it was on main 77d2095, verbatim except that the tool call is given."""
    tool, field, eid_field, metric, minutes, _ = MEASURES[measure]
    kind, window = requested_window(res)
    out: dict[str, Any] = {"measure": measure, "metric": metric, "interval_minutes": minutes, "window_kind": kind,
                           "window_utc": [iso_utc(window[0]), iso_utc(window[1])] if window else None}
    if window is None or res.region is None:
        return out | {"unavailable": "the window is not pinned down"}
    w0, w1 = window
    out["call_id"] = rec.call_id
    if rec.status != "ok":
        return out | {"unavailable": f"the controller's {tool} call returned {rec.status}"
                                     + (f" ({rec.blocked_reason})" if rec.blocked_reason else "")}
    series = [x for x in (rec.data or {}).get("series", []) if x.get(field) is not None and x.get(eid_field)
              and w0 < parse_iso(x["interval_end_utc"]) <= w1]
    if not series:
        return out | {"unavailable": "no value of the measure is held for the window"}
    top = max(float(x[field]) for x in series)
    tied = [x for x in series if float(x[field]) == top]
    expected = round((w1 - w0) / timedelta(minutes=minutes))
    return out | {"value": top, "evidence_ids": [x[eid_field] for x in tied],
                  "interval_ends_utc": [x["interval_end_utc"] for x in tied], "intervals_held": len(series),
                  "intervals_in_window": expected, "complete": len(series) >= expected,
                  "excluded_by_as_of": int((rec.view or {}).get("excluded_not_yet_available_at_as_of") or 0)}


def _controller_call(result, metric: str):
    return next(r for r in result.records if r.call_id == f"controller_requested_max_{metric}")


def _resealed(r: AnalyticalResult, **changes: Any) -> AnalyticalResult:
    """SCRIPTED tampering with every identifier and the digest recomputed, so only re-derivation can tell."""
    d = r.model_dump(mode="json")
    for k, v in changes.items():
        if k.startswith("identity."):
            d["identity"][k.split(".", 1)[1]] = v
        elif k.startswith("coverage."):
            d["coverage"][k.split(".", 1)[1]] = v
        else:
            d[k] = v
    ident = ResultIdentity.model_validate(d["identity"])
    content = {k: v for k, v in d.items() if k not in ("result_id", "computation_id", "identity", "digest")}
    return make_result(ident, **AnalyticalResult.model_validate(
        {**d, "result_id": "x", "computation_id": "x", "digest": "x"}).model_dump(include=set(content)))


# ------------------------------------------------------------------------------------------------ compatibility
@pytest.mark.parametrize("label,cid", SAVED)
def test_every_saved_maximum_yields_a_verified_result_and_exactly_todays_binding(label, cid):
    res = _replay(label, cid)
    bindings, reported = res.resolution.demand_max, res.report.results
    assert bindings and len(reported) == len(bindings)
    for b, rr in zip(bindings, reported, strict=True):
        assert rr.server_verification.outcome == "verified" and rr.server_verification.basis == "in_run"
        assert binding_from_result(rr.result) == b  # the adapter gives the binding everything reads
        assert b == _legacy_binding(res.resolution, b["measure"], _controller_call(res, b["metric"]))


def test_the_k09_result_contract():
    r = _replay("MC-dev-e2e-sol", "K09").report.results[0].result
    assert (r.schema_version, r.identity.kind, r.status) == ("analytical_result/1", "demand_maximum", "established")
    assert (r.maximum, r.unit, r.interval_ends_utc) == (10954.2, "MW", ("2026-07-29T09:05:00Z",))
    assert r.highest_held is None and r.reason is None
    assert r.coverage is not None and (r.coverage.intervals_in_window, r.coverage.intervals_held,
                                       r.coverage.complete) == (288, 288, True)
    assert r.source_row_ids and all(x.startswith("DISPATCHIS:") for x in r.source_row_ids)
    assert [x.code for x in r.limitations] == ["PINNED_DATA", "MEASURE_DEFINITION"]
    i = r.identity
    assert (i.measure, i.region, i.window_utc, i.cutoff_utc) == (
        "total demand", "NSW1", ("2026-07-28T14:00:00Z", "2026-07-29T14:00:00Z"), None)
    assert (i.calculation_version, i.data_version) == ("demand_max/1", STORE.data_version)
    assert r.transient.tool_call_id == "controller_requested_max_dispatch_totaldemand" and r.transient.evidence_ids


# ------------------------------------------------------------------------------------------------ identity
def test_the_same_inputs_give_the_same_identity_across_runs():
    a = _replay("MC-dev-e2e-sol", "K09").report.results[0].result
    b = _replay("MC-dev-e2e-sol", "K09").report.results[0].result
    assert (a.result_id, a.computation_id, a.digest) == (b.result_id, b.computation_id, b.digest)


def test_the_request_is_in_the_result_id_but_not_in_the_computation_id():
    """Slots 53 and 54 asked the same question: same result. K09 of the v12 check asked it in other words."""
    mini = _replay("MC-dev-e2e-mini", "K09").report.results[0].result
    sol = _replay("MC-dev-e2e-sol", "K09").report.results[0].result
    other = mini.model_copy(update={"identity": mini.identity.model_copy(update={"request_digest": "0" * 64})})
    redone = make_result(other.identity, **{k: getattr(mini, k) for k in _content(mini)
                                           if k not in ("result_id", "computation_id", "identity", "schema_version")})
    assert sol.result_id == mini.result_id
    assert redone.result_id != mini.result_id and redone.computation_id == mini.computation_id


@pytest.mark.parametrize("field,value", [("measure", "operational demand"), ("region", "VIC1"),
                                         ("window_utc", ("2026-07-27T14:00:00Z", "2026-07-28T14:00:00Z")),
                                         ("cutoff_utc", "2026-07-29T05:00:00Z"), ("calculation_version", "demand_max/2"),
                                         ("data_version", "other"), ("window_kind", "explicit")])
def test_every_identity_field_changes_both_ids(field, value):
    r = _replay("MC-dev-e2e-sol", "K09").report.results[0].result
    other = _resealed(r, **{f"identity.{field}": value})
    assert other.result_id != r.result_id and other.computation_id != r.computation_id


def test_transient_references_are_outside_the_identity():
    r = _replay("MC-dev-e2e-sol", "K09").report.results[0].result
    moved = _resealed(r, transient={"evidence_ids": ["ev9999"], "tool_call_id": "call_other"})
    assert (moved.result_id, moved.computation_id) == (r.result_id, r.computation_id) and moved.digest != r.digest


# ------------------------------------------------------------------------------------------------ JSON and re-verification
def _loaded():
    res = _replay("MC-dev-e2e-sol", "K09")
    back = InvestigationReport.model_validate_json(res.report.model_dump_json())
    return res, back


def test_a_json_round_trip_loses_nothing_and_re_verifies_against_the_pinned_store():
    res, back = _loaded()
    assert back.results == res.report.results
    v = verify_loaded(back.results[0], store=STORE, selection=SELECTION)
    assert (v.outcome, v.basis, v.data_version, v.reasons) == ("verified", "on_load", STORE.data_version, ())


def test_the_servers_statement_is_not_trusted_when_read_back():
    _, back = _loaded()
    d = back.results[0].model_dump(mode="json")
    d["server_verification"]["outcome"] = "failed"
    assert verify_loaded(d, store=STORE, selection=SELECTION).outcome == "verified"  # ignored either way
    d["result"]["maximum"] = 99999.0
    d["server_verification"]["outcome"] = "verified"
    assert verify_loaded(d, store=STORE, selection=SELECTION).outcome == "failed"


TAMPER = [("maximum", 10954.3), ("interval_ends_utc", ["2026-07-29T09:35:00Z"]), ("coverage.intervals_held", 287),
          ("coverage.complete", False), ("status", "not_established"), ("identity.region", "VIC1"),
          ("identity.measure", "operational demand"), ("identity.window_utc", ["2026-07-28T14:00:00Z",
                                                                               "2026-07-29T13:00:00Z"]),
          ("identity.cutoff_utc", "2026-07-29T05:00:00Z"), ("source_row_ids", ["DISPATCHIS:other"]),
          ("limitations", []), ("unit", "GW"), ("result_id", "0" * 64), ("computation_id", "0" * 64),
          ("digest", "0" * 64)]


@pytest.mark.parametrize("field,value", TAMPER)
def test_each_field_tampered_alone_fails(field, value):
    _, back = _loaded()
    d = back.results[0].result.model_dump(mode="json")
    head, _, tail = field.partition(".")
    if tail:
        d[head][tail] = value
    else:
        d[head] = value
    v = verify_loaded(d, store=STORE, selection=SELECTION)
    assert v.outcome == "failed" and v.reasons


@pytest.mark.parametrize("field,value", [
    ("maximum", 10954.3), ("interval_ends_utc", ["2026-07-29T09:35:00Z"]), ("source_row_ids", ["DISPATCHIS:other"]),
    ("limitations", []), ("coverage.excluded_by_as_of", 3), ("identity.region", "VIC1"),
    ("identity.window_utc", ["2026-07-28T14:00:00Z", "2026-07-29T13:00:00Z"]),
    ("identity.cutoff_utc", "2026-07-30T00:00:00Z")])
def test_tampering_with_the_digest_and_ids_recomputed_still_fails_on_re_derivation(field, value):
    _, back = _loaded()
    forged = _resealed(back.results[0].result, **{field: value})
    v = verify_loaded(forged, store=STORE, selection=SELECTION)
    assert v.outcome == "failed" and "re-derived from the pinned store" in v.reasons[0]


def test_what_cannot_be_checked_is_unverifiable_and_never_admitted():
    _, back = _loaded()
    r = back.results[0].result
    reg = ResultRegistry()
    cases = {"no store": (r, None), "another data version": (_resealed(r, **{"identity.data_version": "other"}), STORE),
             "an unknown calculation": (_resealed(r, **{"identity.calculation_version": "demand_max/9"}), STORE)}
    for why, (x, store) in cases.items():
        v = reg.submit_loaded(x, store=store, selection=SELECTION)
        assert v.outcome == "unverifiable" and v.reasons, why
        assert reg.verified(x.result_id) is None
    assert reg.submit_loaded(r, store=STORE, selection=SELECTION).outcome == "verified" and reg.verified(r.result_id)


def test_not_an_analytical_result_fails():
    v = verify_loaded({"schema_version": "analytical_result/1", "maximum": 1.0}, store=STORE)
    assert v.outcome == "failed" and "schema error" in v.reasons[0]


# ------------------------------------------------------------------------------------------------ admission
def test_only_the_registry_creates_a_verified_result():
    r = _replay("MC-dev-e2e-sol", "K09").report.results[0]
    with pytest.raises(PermissionError):
        VerifiedResult(r.result, r.server_verification)


def test_a_tampered_in_run_result_is_failed_reported_and_not_admitted():
    res = _z04_replay()
    r = res.report.results[0].result
    reg = ResultRegistry()
    forged = _resealed(r, maximum=r.maximum + 1 if r.maximum is not None else 1.0)
    v = reg.submit_in_run(forged, store=STORE, selection=SELECTION, evidence=res.registry)
    assert v.outcome == "failed" and reg.verified(forged.result_id) is None
    assert reg.reported()[0].server_verification.outcome == "failed"
    # its own in-run evidence must be the run's: another evidence ID is refused
    other = _resealed(r, transient={"evidence_ids": [next(iter(res.registry.items))],
                                    "tool_call_id": r.transient.tool_call_id})
    v2 = verify_in_run(other, store=STORE, selection=SELECTION, evidence=res.registry)
    assert v2.outcome == "failed" and any("in-run evidence" in x for x in v2.reasons)
    assert verify_in_run(r, store=STORE, selection=SELECTION, evidence=res.registry).outcome == "verified"


# ------------------------------------------------------------------------------------------------ as-of, coverage, ties
def test_a_cutoff_inside_the_window_gives_no_maximum_and_re_verifies_only_under_that_cutoff():
    res = _z04_replay("2026-07-29T05:00:00Z")
    rr = res.report.results[0]
    r, b = rr.result, res.resolution.demand_max[0]
    assert rr.server_verification.outcome == "verified" and r.status == "not_established"
    assert r.maximum is None and r.interval_ends_utc == () and r.highest_held is not None
    assert r.coverage is not None and not r.coverage.complete and r.coverage.excluded_by_as_of > 0
    assert {x.code for x in r.limitations} >= {"AS_OF_CUTOFF", "INCOMPLETE_WINDOW"}
    assert r.identity.cutoff_utc == "2026-07-29T05:00:00Z"
    assert b == binding_from_result(r) == _legacy_binding(res.resolution, b["measure"], _controller_call(res, b["metric"]))
    assert b["value"] == r.highest_held and b["complete"] is False  # today's binding, unchanged
    back = InvestigationReport.model_validate_json(res.report.model_dump_json()).results[0]
    assert verify_loaded(back, store=STORE, selection=SELECTION).outcome == "verified"
    assert verify_loaded(_resealed(r, **{"identity.cutoff_utc": None}), store=STORE,
                         selection=SELECTION).outcome == "failed"


def _synthetic(values: list[float], window_minutes: int, *, status: str = "ok"):
    """SYNTHETIC: a total-demand series of 5-minute values ending at 01:05, 01:10, … in a window from 01:00."""
    reg = EvidenceRegistry()
    w0 = parse_iso("2026-07-29T01:00:00Z")
    series = []
    for k, v in enumerate(values):
        end = iso_utc(w0 + timedelta(minutes=5 * (k + 1)))
        ev = reg.add(evidence_class="observed_value", metric="dispatch_totaldemand", value=v, unit="MW", region="NSW1",
                     valid_at_utc=end, interval_minutes=5, source_row_ids=[f"SYN:{k}"], source_urls=[],
                     tool_call_id="c1")
        series.append({"interval_end_utc": end, "totaldemand_mw": v, "totaldemand_evidence_id": ev.evidence_id})
    window = (iso_utc(w0), iso_utc(w0 + timedelta(minutes=window_minutes)))
    ident = ResultIdentity(request_digest="0" * 64, kind="demand_maximum", measure="total demand", region="NSW1",
                           window_utc=window, window_kind="explicit", cutoff_utc=None,
                           calculation_version="demand_max/1", data_version=STORE.data_version)
    rec = SimpleNamespace(status=status, data={"series": series}, view={}, call_id="c1", blocked_reason=None)
    return ident, rec, reg, None, (parse_iso(window[0]), parse_iso(window[1]))


def _legacy_synthetic(rec, window) -> dict[str, Any]:
    """REFERENCE: the same pre-D24 calculation, for a synthetic call over an explicit window."""
    tool, field, eid_field, metric, minutes, _ = MEASURES["total demand"]
    w0, w1 = window
    out: dict[str, Any] = {"measure": "total demand", "metric": metric, "interval_minutes": minutes,
                           "window_kind": "explicit", "window_utc": [iso_utc(w0), iso_utc(w1)], "call_id": rec.call_id}
    if rec.status != "ok":
        return out | {"unavailable": f"the controller's {tool} call returned {rec.status}"
                                     + (f" ({rec.blocked_reason})" if rec.blocked_reason else "")}
    series = [x for x in (rec.data or {}).get("series", []) if x.get(field) is not None and x.get(eid_field)
              and w0 < parse_iso(x["interval_end_utc"]) <= w1]
    if not series:
        return out | {"unavailable": "no value of the measure is held for the window"}
    top = max(float(x[field]) for x in series)
    tied = [x for x in series if float(x[field]) == top]
    expected = round((w1 - w0) / timedelta(minutes=minutes))
    return out | {"value": top, "evidence_ids": [x[eid_field] for x in tied],
                  "interval_ends_utc": [x["interval_end_utc"] for x in tied], "intervals_held": len(series),
                  "intervals_in_window": expected, "complete": len(series) >= expected,
                  "excluded_by_as_of": int((rec.view or {}).get("excluded_not_yet_available_at_as_of") or 0)}


def test_ties_keep_every_interval_and_its_rows(monkeypatch):
    ident, rec, reg, _, window = _synthetic([100.0, 120.0, 120.0], 15)
    r = result_from_output(ident, rec.status, rec.data, rec.view, reg, rec.call_id)
    assert r.status == "established" and r.maximum == 120.0
    assert r.interval_ends_utc == ("2026-07-29T01:10:00Z", "2026-07-29T01:15:00Z")
    assert r.source_row_ids == ("SYN:1", "SYN:2") and len(r.transient.evidence_ids) == 2
    assert binding_from_result(r) == _legacy_synthetic(rec, window)
    # dropping a tie, even with the digest and ids recomputed, fails re-derivation (SCRIPTED: re-derivation returns
    # the synthetic series' own result)
    monkeypatch.setattr(DM, "rederive", lambda i, s, sel: result_from_output(ident, "ok", rec.data, {}, reg, "c1"))
    assert verify_loaded(r, store=STORE, selection=SELECTION).outcome == "verified"
    one = _resealed(r, interval_ends_utc=["2026-07-29T01:10:00Z"], source_row_ids=["SYN:1"])
    assert verify_loaded(one, store=STORE, selection=SELECTION).outcome == "failed"


def test_an_incomplete_window_carries_no_maximum_only_the_highest_value_held():
    ident, rec, reg, _, window = _synthetic([100.0, 130.0, 110.0], 20)  # 4 intervals expected, 3 held
    r = result_from_output(ident, rec.status, rec.data, rec.view, reg, rec.call_id)
    assert r.status == "not_established" and r.maximum is None and r.interval_ends_utc == ()
    assert (r.highest_held, r.highest_held_interval_ends_utc) == (130.0, ("2026-07-29T01:10:00Z",))
    assert r.coverage is not None and (r.coverage.intervals_in_window, r.coverage.intervals_held) == (4, 3)
    assert "INCOMPLETE_WINDOW" in {x.code for x in r.limitations}
    assert binding_from_result(r) == _legacy_synthetic(rec, window)
    # an incomplete result claiming complete coverage is inconsistent in itself
    assert verify_loaded(_resealed(r, **{"coverage.complete": True}), store=STORE).outcome == "failed"


@pytest.mark.parametrize("status,values,reason", [
    ("unavailable", [100.0], "the controller's get_price_timeline call returned unavailable"),
    ("refused", [100.0], "the controller's get_price_timeline call returned refused"),
    ("ok", [], "no value of the measure is held for the window")])
def test_unavailable_data_gives_no_value_and_its_reason(status, values, reason):
    ident, rec, reg, _, window = _synthetic(values, 15, status=status)
    r = result_from_output(ident, rec.status, rec.data, rec.view, reg, rec.call_id)
    assert (r.status, r.reason, r.maximum, r.highest_held, r.coverage) == ("unavailable", reason, None, None, None)
    assert binding_from_result(r) == _legacy_synthetic(rec, window)


def test_an_unpinned_window_is_unavailable_and_re_verifies_as_such():
    ident = ResultIdentity(request_digest="0" * 64, kind="demand_maximum", measure="total demand", region="NSW1",
                           window_utc=None, window_kind="day", cutoff_utc=None, calculation_version="demand_max/1",
                           data_version=STORE.data_version)
    r = DM._unavailable(ident, "the window is not pinned down", None)
    assert binding_from_result(r) == {"measure": "total demand", "metric": "dispatch_totaldemand",
                                      "interval_minutes": 5, "window_kind": "day", "window_utc": None,
                                      "unavailable": "the window is not pinned down"}
    assert verify_loaded(r, store=STORE, selection=SELECTION).outcome == "verified"


def test_a_run_time_block_cannot_be_re_derived_so_it_is_unverifiable():
    ident, rec, reg, _, _ = _synthetic([100.0], 15, status="blocked")
    rec.blocked_reason = "per-tool call budget exhausted"
    r = result_from_output(ident, rec.status, rec.data, rec.view, reg, rec.call_id, rec.blocked_reason)
    assert r.status == "unavailable" and r.reason.endswith("returned blocked (per-tool call budget exhausted)")
    assert verify_loaded(r, store=STORE, selection=SELECTION).outcome == "unverifiable"


# ------------------------------------------------------------------------------------------------ the model
def test_model_output_cannot_carry_results():
    draft = _rec("MC-dev-e2e-sol", "K09")["drafts"]["synthesis:draft"]
    assert "results" not in json.dumps(ModelReport.model_json_schema())
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        ModelReport.model_validate({**draft, "results": [{"result_id": "x"}]})


def test_a_repair_patch_cannot_target_results():
    m = ModelReport.model_validate(_rec("MC-dev-e2e-sol", "K09")["drafts"]["synthesis:draft"])
    patch = RepairPatch.model_validate({"edits": [{"target": "results[0]", "action": "replace", "text": "1",
                                                   "statement": None, "claim": None, "citation": None}],
                                        "new_numeric_claims": [], "new_citations": []})
    out, notes = apply_patch(m, patch, {"headline"})
    assert out == m and notes == ["ignored an edit to results[0]: only the failing items may change"]


def test_a_draft_carrying_results_changes_nothing_the_controller_reports():
    """SCRIPTED: the draft adds a 'results' key with a forged maximum; a strict structured-output transport drops it,
    and the report's results are the controller's own, verified."""
    def forge(d):
        d["results"] = [{"result_id": "forged", "maximum": 99999.0}]
        return d
    rep = _replay("MC-dev-e2e-sol", "K09", draft_edit=forge).report
    assert [rr.result.maximum for rr in rep.results] == [10954.2]
    assert rep.results[0].server_verification.outcome == "verified"


def test_the_api_schema_carries_results_with_the_servers_statement():
    schema = json.dumps(InvestigationReport.model_json_schema())
    assert "ReportedResult" in schema and "server_verification" in schema and "analytical_result/1" in schema


def test_a_reported_result_is_frozen():
    rr = _replay("MC-dev-e2e-sol", "K09").report.results[0]
    with pytest.raises(ValueError):
        rr.result.maximum = 1.0  # type: ignore[misc]
    assert isinstance(rr, ReportedResult) and isinstance(rr.result.transient, Transient)
    assert _sha(_content(rr.result)) == rr.result.digest


def test_a_result_not_admitted_gives_the_unavailable_binding():
    """SCRIPTED: a stand-in dispatcher returning a synthetic series that is not the pinned data. The result is
    reported as failed and not admitted, and since D25 the binding the validator and the model's context read is the
    unavailable form, with the verifier's reason: the legacy binding does not stand in for a result not admitted."""
    _, rec, reg, _, window = _synthetic([100.0, 120.0, 110.0], 15)
    d = SimpleNamespace(call=lambda *a, **k: rec, store=STORE, selection=SELECTION, registry=reg,
                        results=ResultRegistry(), trace=None)
    res = SimpleNamespace(request=InvestigateRequest(question="SYNTHETIC maximum question", mode="replay"),
                          region="NSW1", as_of=None, requests=None)
    original = DM.requested_window
    DM.requested_window = lambda _r: ("explicit", window)  # type: ignore[assignment]
    try:
        binding = DM.compute(d, res, "total demand")  # type: ignore[arg-type]
    finally:
        DM.requested_window = original  # type: ignore[assignment]
    reported = d.results.reported()
    assert reported[0].server_verification.outcome == "failed" and d.results.verified(reported[0].result.result_id) is None
    legacy = _legacy_synthetic(rec, window)
    assert binding == {k: legacy[k] for k in ("measure", "metric", "interval_minutes", "window_kind", "window_utc",
                                              "call_id")} | {"unavailable": "the computed result could not be "
                                                                            "verified against the pinned data (failed)"}


def test_an_error_during_re_derivation_is_unverifiable_not_verified(monkeypatch):
    r = _replay("MC-dev-e2e-sol", "K09").report.results[0].result

    def broken(*a, **k):
        raise RuntimeError("SYNTHETIC store failure")
    monkeypatch.setattr(DM, "rederive", broken)
    v = verify_loaded(r, store=STORE, selection=SELECTION)
    assert v.outcome == "unverifiable" and "could not run" in v.reasons[0]
