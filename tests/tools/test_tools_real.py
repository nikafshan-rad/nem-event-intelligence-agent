"""G2: deterministic tools on the real snapshot, checked against independently recomputed store/source values."""

from __future__ import annotations

from datetime import timedelta

import pytest

from nem_agent.agent.dispatcher import Dispatcher
from nem_agent.evidence import EvidenceRegistry
from nem_agent.store import trace_row
from nem_agent.timeutil import half_hour_end_for, iso_utc, parse_iso
from nem_agent.trace import Trace


@pytest.fixture
def mk(real_store, selection):
    def _mk(intent: str = "market_event_review", as_of=None) -> Dispatcher:
        return Dispatcher(real_store, selection, Trace(), EvidenceRegistry(), intent, as_of)
    return _mk


@pytest.fixture
def ev(selection):
    return selection.primary


def win(ev):
    return {"region": ev.region, "start_utc": ev.window_start_utc, "end_utc": ev.window_end_utc}


def test_price_timeline_peak_matches_source_bytes(mk, ev, real_store):
    d = mk()
    rec = d.call("get_price_timeline", win(ev))
    assert rec.status == "ok"
    pk = rec.view["peak"]
    assert pk["interval_end_utc"] == ev.peak_interval_end_utc and pk["value"] == pytest.approx(ev.peak_rrp)
    item = d.registry.get(pk["evidence_id"])
    assert item.unit == "$/MWh" and item.interval_minutes == 5 and len(item.source_row_ids) == 1
    raw = trace_row(real_store, item.source_row_ids[0])["raw_line"].split(",")
    assert float(raw[raw.index(ev.region) + 3]) == pytest.approx(ev.peak_rrp)  # SA1,<DISPATCHINTERVAL>,<INTERVENTION>,<RRP>
    # the window has 5-minute resolution only
    series = rec.data["series"]
    assert all(parse_iso(b["interval_end_utc"]) - parse_iso(a["interval_end_utc"]) == timedelta(minutes=5)
               for a, b in zip(series, series[1:], strict=False))


def test_compare_forecast_actual_matches_independent_arithmetic(mk, ev, real_store):
    peak = parse_iso(ev.peak_interval_end_utc)
    hh = half_hour_end_for(peak)
    args = {"region": ev.region, "target_start_utc": iso_utc(hh - timedelta(hours=3)), "target_end_utc": iso_utc(hh + timedelta(hours=3)),
            "run_selector": "latest_before_target"}
    d = mk("forecast_review")
    rec = d.call("compare_forecast_actual", args)
    assert rec.status == "ok" and rec.view["n_pairs"] == 12
    for p in rec.data["pairs"]:
        t = parse_iso(p["target_end_utc"])
        f = real_store.query(
            "SELECT poe50_mw, run_id FROM opdemand_forecast WHERE region=? AND target_end_utc=? AND available_at_utc <= ? "
            "ORDER BY published_at_utc DESC LIMIT 1", [ev.region, t, t - timedelta(minutes=30)])[0]
        a = real_store.query("SELECT operational_demand_mw FROM opdemand_actual WHERE region=? AND interval_end_utc=? "
                             "AND revision='updated'", [ev.region, t])[0]
        assert p["run_id"] == f["run_id"]
        assert p["error_mw"] == pytest.approx(f["poe50_mw"] - a["operational_demand_mw"])
        assert p["error_pct"] == pytest.approx(100 * (f["poe50_mw"] - a["operational_demand_mw"]) / a["operational_demand_mw"], abs=0.01)
    errs = [p["error_mw"] for p in rec.data["pairs"]]
    assert rec.view["mae_mw"]["value"] == pytest.approx(sum(abs(e) for e in errs) / len(errs), abs=0.01)


def test_as_of_forecast_runs_never_include_unproven_publications(mk, ev, selection):
    as_of = parse_iso(ev.peak_interval_end_utc) - timedelta(hours=2)
    hh = half_hour_end_for(parse_iso(ev.peak_interval_end_utc))
    d = mk("forecast_review", as_of)
    rec = d.call("get_forecast_runs", {"region": ev.region, "target_start_utc": iso_utc(hh - timedelta(hours=2)),
                                       "target_end_utc": iso_utc(hh + timedelta(hours=2))})
    assert rec.status == "ok"
    assert any("injected" in n for n in rec.policy_notes)
    margin = timedelta(minutes=selection.availability["margin_minutes"])
    for run in rec.view["runs"]:
        assert parse_iso(run["available_at_utc"]) <= as_of
        assert parse_iso(run["published_at_utc"]) + margin == parse_iso(run["available_at_utc"])
    assert rec.view["runs_excluded_created_after_as_of"] > 0
    assert rec.view["runs_excluded_created_but_not_proven_public_by_as_of"] > 0


def test_request_cutoff_cannot_be_widened_by_tool_args(mk, ev):
    as_of = parse_iso(ev.peak_interval_end_utc) - timedelta(hours=2)
    d = mk("forecast_review", as_of)
    rec = d.call("get_forecast_runs", {"region": ev.region, "target_start_utc": ev.window_start_utc,
                                       "target_end_utc": iso_utc(parse_iso(ev.window_start_utc) + timedelta(hours=12)),
                                       "as_of_utc": iso_utc(as_of + timedelta(hours=5))})
    assert rec.status == "blocked" and "later than the request cutoff" in rec.blocked_reason


def test_as_of_actuals_and_prices_exclude_later_publications(mk, ev):
    as_of = parse_iso(ev.peak_interval_end_utc) - timedelta(hours=1)
    d = mk("market_event_review", as_of)
    p = d.call("get_price_timeline", win(ev))
    a = d.call("get_actual_demand", win(ev))
    assert p.status == "ok" and p.view["excluded_not_yet_available_at_as_of"] > 0
    assert all(parse_iso(d.registry.get(s["rrp_evidence_id"]).available_at_utc) <= as_of for s in p.data["series"])
    assert a.status == "ok" and all(parse_iso(d.registry.get(s["evidence_id"]).available_at_utc) <= as_of
                                    for s in a.data["series"])


def test_actual_revision_policies_are_distinct(mk, ev):
    d = mk()
    ini = d.call("get_actual_demand", {**win(ev), "revision_policy": "initial"})
    upd = d.call("get_actual_demand", {**win(ev), "revision_policy": "updated"})
    assert {s["revision"] for s in ini.data["series"]} == {"initial"}
    assert {s["revision"] for s in upd.data["series"]} == {"updated"}
    assert {s["row_id"] for s in ini.data["series"]}.isdisjoint({s["row_id"] for s in upd.data["series"]})
    bad = d.call("get_actual_demand", {**win(ev), "revision_policy": "final_final"})
    assert bad.status == "blocked" and "revision_policy" in bad.blocked_reason


@pytest.mark.parametrize(("args", "fragment"), [
    ({"region": "WA1"}, "region"),
    ({"end_utc": "2026-08-10T00:00:00Z"}, "exceeds"),
    ({"start_utc": "2026-07-31T05:00:00"}, "offset"),
    ({"start_utc": "2026-07-31T05:00:00Z", "end_utc": "2026-07-31T04:00:00Z"}, "end must be after start"),
    ({"sql": "DROP TABLE price_5min"}, "Extra inputs"),
])
def test_invalid_arguments_are_blocked_before_execution(mk, ev, args, fragment):
    d = mk()
    rec = d.call("get_price_timeline", {**win(ev), **args})
    assert rec.status == "blocked" and fragment in rec.blocked_reason
    assert not d.registry.items, "nothing may execute or register evidence for a blocked call"


def test_nonexistent_data_is_unavailable_not_invented(mk, ev):
    d = mk()
    rec = d.call("get_price_timeline", {"region": ev.region, "start_utc": "2026-01-10T00:00:00Z", "end_utc": "2026-01-10T06:00:00Z"})
    assert rec.status == "unavailable" and rec.missing and not d.registry.items


def test_incompatible_definition_is_refused(mk, ev):
    d = mk("forecast_review")
    rec = d.call("compare_forecast_actual", {"region": ev.region, "target_start_utc": ev.window_start_utc,
                                             "target_end_utc": iso_utc(parse_iso(ev.window_start_utc) + timedelta(hours=6)),
                                             "actual_metric": "DISPATCH_TOTALDEMAND"})
    assert rec.status == "refused" and "not comparable" in rec.view["reason"] and not d.registry.items


def test_weather_is_unavailable_in_as_of_view_and_labelled_otherwise(mk, ev):
    as_of = parse_iso(ev.peak_interval_end_utc)
    d = mk("forecast_review", as_of)
    rec = d.call("get_weather_context", win(ev))
    assert rec.status == "unavailable" and "retrospective" in rec.view["reason"]
    d2 = mk("forecast_review")
    rec2 = d2.call("get_weather_context", win(ev))
    assert rec2.status == "ok"
    assert all(i.evidence_class == "retrospective_context" for i in d2.registry.items.values())


def test_generation_change_is_descriptive(mk, ev):
    peak = parse_iso(ev.peak_interval_end_utc)
    d = mk()
    rec = d.call("get_generation_change", {"region": ev.region, "start_utc": iso_utc(peak - timedelta(hours=1)),
                                           "end_utc": iso_utc(peak), "top_n": 3})
    assert rec.status == "ok" and len(rec.view["largest_changes"]) == 3
    assert "does not by itself show an outage" in rec.view["caveat"]
    u = rec.view["largest_changes"][0]
    assert u["change_mw"]["value"] == pytest.approx(u["end"]["mw"] - u["start"]["mw"], abs=0.005)  # rounded to 2 dp


def test_notice_clock_times_are_nem_time_converted_to_utc_and_local():
    from nem_agent.tools.impl import notice_clock_times

    dated, bare = notice_clock_times("At 1630 hrs 30/07/2026 there was a short notice outage.", "2026-07-30", "SA1"), \
        notice_clock_times("At 1140 hrs, the City West transformer tripped.", "2026-07-30", "SA1")
    assert dated == [{"text": "1630 hrs 30/07/2026", "nem_time": "2026-07-30 16:30 NEM (UTC+10)",
                      "utc": "2026-07-30T06:30:00Z", "local": "2026-07-30 16:00 ACST (UTC+0930)"}]
    assert bare[0]["utc"] == "2026-07-30T01:40:00Z" and "notice date" in bare[0]["date"]
    assert notice_clock_times("At 1140 hrs.", None, "SA1") == []  # no date anywhere: nothing is guessed


def test_retrieved_notices_carry_clock_times(mk, ev):
    rec = mk().call("retrieve_public_evidence", {"query": "network outage", "region": ev.region,
                                                 "event_start_utc": ev.window_start_utc, "event_end_utc": ev.window_end_utc,
                                                 "top_k": 8, "doc_types": ["market_notice"]})
    notices = [r for r in rec.view.get("results", []) if r["doc_type"] == "market_notice"]
    if not notices:
        pytest.skip("not in corpus: NEMWeb Current notices have rolling retention")
    assert "NEM market time (UTC+10" in rec.view["clock_time_basis"]
    assert all("clock_times" in r for r in notices)
    assert any(t["utc"].endswith("Z") for r in notices for t in r["clock_times"])


def test_price_timeline_states_netinterchange_sign(mk, ev):
    rec = mk().call("get_price_timeline", {**win(ev), "as_of_utc": None})
    ni = rec.view["netinterchange_at_peak"]
    assert rec.view["definitions"]["DISPATCH_NETINTERCHANGE"].startswith("Net interconnector flow from the regional")
    expected = "into" if ni["value"] < 0 else "out of" if ni["value"] > 0 else "no net"
    assert expected in ni["direction"]


def test_find_market_events_contains_primary_peak(mk, ev):
    d = mk()
    rec = d.call("find_market_events", {**win(ev), "kind": ev.kind})
    assert rec.status == "ok"
    top = rec.view["episodes"][0]["peak_rrp"]
    assert top["interval_end_utc"] == ev.peak_interval_end_utc and top["value"] == pytest.approx(ev.peak_rrp)
    assert rec.view["threshold_note"].startswith("project analysis threshold")
    # the threshold is its own evidence item, so a stated threshold never borrows a count's evidence id
    thr = d.registry.get(rec.view["threshold"]["evidence_id"])
    assert thr is not None and thr.metric == "project_analysis_threshold" and thr.unit == "$/MWh"
    assert thr.value == pytest.approx(rec.view["threshold"]["value"])
    n = d.registry.get(rec.view["episodes"][0]["n_intervals"]["evidence_id"])
    assert n is not None and n.unit == "intervals" and rec.view["episodes"][0]["n_intervals"]["unit"] == "intervals"


def test_market_events_respect_the_request_cutoff(mk, ev):
    """L3 live run (AMB06): find_market_events had no as-of field, so an as-of request saw the later price spike."""
    as_of = parse_iso(ev.peak_interval_end_utc) - timedelta(hours=1)
    d = mk("market_event_review", as_of)
    rec = d.call("find_market_events", {**win(ev), "kind": "high_price"})
    assert any("as_of_utc injected" in n for n in rec.policy_notes)
    assert rec.status == "ok" and rec.view["excluded_not_yet_available_at_as_of"] > 0
    peaks = [d.registry.get(e["peak_rrp"]["evidence_id"]) for e in rec.view["episodes"]]
    assert peaks and all(parse_iso(p.available_at_utc) <= as_of for p in peaks)
    assert all(p.value < ev.peak_rrp for p in peaks)  # the event's own peak was not yet public
    # without a cutoff the peak is found, as before
    full = mk("market_event_review").call("find_market_events", {**win(ev), "kind": "high_price"})
    assert max(e["peak_rrp"]["value"] for e in full.view["episodes"]) == ev.peak_rrp


def test_notice_clock_times_read_the_colon_form():
    """L3 live, EV09: a notice's "from 11:00 hrs" had no UTC equivalent (only "1100 hrs" was parsed)."""
    from nem_agent.tools.impl import notice_clock_times

    got = notice_clock_times("AEMO has invoked automated constraint set X from 11:00 hrs until further notice.",
                             "2026-07-28", "VIC1")
    assert [(g["utc"], g["nem_time"]) for g in got] == [("2026-07-28T01:00:00Z", "2026-07-28 11:00 NEM (UTC+10)")]
    assert notice_clock_times("At 1630 hrs 30/07/2026 there was an outage.", None, "SA1")[0]["utc"] == \
        "2026-07-30T06:30:00Z"
