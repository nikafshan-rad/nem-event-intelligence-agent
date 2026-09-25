"""G1 ingestion: failure safety (SYNTHETIC fixtures through the real build path) and real-store properties."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from nem_agent import ingest
from nem_agent.selection import Selection
from nem_agent.store import trace_row
from nem_agent.timeutil import parse_iso
from tests.helpers import minimal_selection, mms_csv, mms_multi, plant_cache, source_entry, zip_bytes

FC_FIELDS = ["REGIONID", "INTERVAL_DATETIME", "LOAD_DATE", "OPERATIONAL_DEMAND_POE10", "OPERATIONAL_DEMAND_POE50",
             "OPERATIONAL_DEMAND_POE90", "LASTCHANGED"]
PRICE_FIELDS = ["SETTLEMENTDATE", "RUNNO", "REGIONID", "DISPATCHINTERVAL", "INTERVENTION", "RRP", "EEP", "ROP",
                "APCFLAG", "MARKETSUSPENDEDFLAG", "LASTCHANGED", "PRICE_STATUS"]
RS_FIELDS = ["SETTLEMENTDATE", "RUNNO", "REGIONID", "DISPATCHINTERVAL", "INTERVENTION", "TOTALDEMAND",
             "AVAILABLEGENERATION", "AVAILABLELOAD", "DEMANDFORECAST", "DISPATCHABLEGENERATION", "DISPATCHABLELOAD",
             "NETINTERCHANGE"]
WINDOW = ("2098-12-31T13:00:00Z", "2098-12-31T16:00:00Z")  # 23:00-02:00 NEM time, synthetic year 2099


def _dispatch_file(rrp: str, created: str = "2099/01/01,00:00:10") -> bytes:
    t = '"2099/01/01 00:05:00"'
    return mms_multi("DISPATCHIS", [
        ("DISPATCH", "PRICE", "5", PRICE_FIELDS, [[t, "1", "SA1", "1", "0", rrp, "0", rrp, "0", "0", t, "FIRM"]]),
        ("DISPATCH", "REGIONSUM", "9", RS_FIELDS, [[t, "1", "SA1", "1", "0", "1500", "2000", "0", "0", "1400", "0", "-100"]]),
    ], created=created)


@pytest.mark.synthetic
def test_malformed_schema_fails_safely_through_build(synthetic_home):
    drifted = [f for f in FC_FIELDS if f != "OPERATIONAL_DEMAND_POE50"]
    row = ["SA1", '"2099/01/01 00:30:00"', '"2098/12/31 23:00:00"', "10", "8", '"2098/12/31 23:00:00"']
    data = zip_bytes({"SYNTHETIC_FC.zip": zip_bytes({"SYNTHETIC_FC.CSV": mms_csv(
        "OPERATIONAL_DEMAND", "FORECAST", "1", drifted, [row], created="2098/12/31,23:05:00")})})
    url = "https://nemweb.com.au/Reports/ARCHIVE/SYNTHETIC_TEST/broken_forecast.zip"
    sha = plant_cache(synthetic_home, "OPDEM_FORECAST_HH", url, data)
    sel = Selection.model_validate(minimal_selection(
        [source_entry("synthetic_fc", "OPDEM_FORECAST_HH", url, sha, len(data))], WINDOW))
    snap = ingest.build(sel, store=synthetic_home / "store", log=lambda *_: None)
    assert "synthetic_fc" in snap["failed_sources"]
    assert "SchemaDriftError" in snap["failed_sources"]["synthetic_fc"]["error"]
    assert snap["row_counts"]["opdemand_forecast"] == 0


@pytest.mark.synthetic
def test_conflicting_duplicates_abort_before_writing(synthetic_home):
    srcs = []
    for i, rrp in enumerate(["100", "999"]):  # same interval, different price => conflict
        data = zip_bytes({f"SYN_{i}.zip": zip_bytes({f"SYN_{i}.CSV": _dispatch_file(rrp)})})
        url = f"https://nemweb.com.au/Reports/ARCHIVE/SYNTHETIC_TEST/dispatch_{i}.zip"
        sha = plant_cache(synthetic_home, "DISPATCHIS", url, data)
        srcs.append(source_entry(f"syn_disp_{i}", "DISPATCHIS", url, sha, len(data)))
    sel = Selection.model_validate(minimal_selection(srcs, WINDOW))
    store = synthetic_home / "store"
    with pytest.raises(ingest.DuplicateConflictError, match="conflicting duplicate"):
        ingest.build(sel, store=store, log=lambda *_: None)
    assert not list(store.glob("*.parquet")), "no table may be written when a conflict is detected"


@pytest.mark.synthetic
def test_identical_duplicates_are_dropped_and_counted(synthetic_home):
    srcs = []
    for i in range(2):  # the same interval and value delivered twice (e.g. overlapping containers)
        data = zip_bytes({f"SYN_{i}.zip": zip_bytes({f"SYN_{i}.CSV": _dispatch_file("123.45")})})
        url = f"https://nemweb.com.au/Reports/ARCHIVE/SYNTHETIC_TEST/dup_{i}.zip"
        sha = plant_cache(synthetic_home, "DISPATCHIS", url, data)
        srcs.append(source_entry(f"syn_dup_{i}", "DISPATCHIS", url, sha, len(data)))
    snap = ingest.build(Selection.model_validate(minimal_selection(srcs, WINDOW)), store=synthetic_home / "store",
                        log=lambda *_: None)
    assert snap["row_counts"]["price_5min"] == 1
    assert snap["duplicates_dropped"]["price_5min"] == 1


@pytest.mark.synthetic
def test_truncated_container_is_rejected_not_partially_ingested(synthetic_home):
    good = _dispatch_file("50")
    truncated = good[: len(good) - 40]  # cut through the trailer
    data = zip_bytes({"SYN_T.zip": zip_bytes({"SYN_T.CSV": truncated})})
    url = "https://nemweb.com.au/Reports/ARCHIVE/SYNTHETIC_TEST/truncated.zip"
    sha = plant_cache(synthetic_home, "DISPATCHIS", url, data)
    snap = ingest.build(Selection.model_validate(minimal_selection(
        [source_entry("syn_trunc", "DISPATCHIS", url, sha, len(data))], WINDOW)), store=synthetic_home / "store",
        log=lambda *_: None)
    assert "syn_trunc" in snap["failed_sources"]
    assert snap["row_counts"]["price_5min"] == 0


# ------------------------------------------------------------------------------------------ real data
def test_real_store_nonempty_and_no_failed_sources(real_store):
    counts = real_store.snapshot["row_counts"]
    for t in ("price_5min", "regionsum_5min", "opdemand_forecast", "opdemand_actual"):
        assert counts[t] > 0, t
    assert real_store.snapshot["failed_sources"] == {}


def test_primary_peak_traces_to_source_bytes(real_store, selection):
    ev = selection.primary
    rows = real_store.query("SELECT row_id, rrp FROM price_5min WHERE region=? AND interval_end_utc=?",
                            [ev.region, parse_iso(ev.peak_interval_end_utc)])
    assert len(rows) == 1 and rows[0]["rrp"] == pytest.approx(ev.peak_rrp)
    tr = trace_row(real_store, rows[0]["row_id"])
    assert tr["container_sha256_recorded"] == tr["container_sha256_recomputed"]
    assert tr["member_sha256_recorded"] == tr["member_sha256_recomputed"]
    fields = tr["raw_line"].split(",")
    assert fields[:3] == ["D", "DISPATCH", "PRICE"] and ev.region in fields
    assert tr["source_url"].startswith("https://nemweb.com.au/")


def test_every_row_has_provenance(real_store):
    for t in ("price_5min", "opdemand_forecast", "opdemand_actual"):
        bad = real_store.query(
            f"SELECT count(*) AS n FROM {t} WHERE row_id IS NULL OR source_url IS NULL OR container_sha256 IS NULL "
            "OR member_sha256 IS NULL OR published_at_utc IS NULL OR available_at_utc < published_at_utc")
        assert bad[0]["n"] == 0, t


def test_forecast_runs_and_revisions_remain_distinct(real_store, selection):
    ev = selection.primary
    peak = parse_iso(ev.peak_interval_end_utc)
    hh = peak + timedelta(minutes=(30 - peak.minute % 30) % 30)
    runs = real_store.query("SELECT run_id, published_at_utc FROM opdemand_forecast WHERE region=? AND target_end_utc=?",
                            [ev.region, hh])
    assert len(runs) > 1 and len({r["run_id"] for r in runs}) == len(runs)
    both = real_store.query(
        "SELECT count(*) AS n FROM opdemand_actual a JOIN opdemand_actual b ON a.region=b.region AND "
        "a.interval_end_utc=b.interval_end_utc WHERE a.revision='initial' AND b.revision='updated' "
        "AND b.published_at_utc > a.published_at_utc")
    assert both[0]["n"] > 0


def test_rebuild_from_cache_is_idempotent(real_store, selection, tmp_path):
    """A second build from the verified raw cache reproduces identical table contents."""
    snap2 = ingest.build(selection, store=tmp_path / "store2", log=lambda *_: None)
    snap1 = real_store.snapshot
    assert snap2["data_version"] == snap1["data_version"]
    assert snap2["content_sha256"] == snap1["content_sha256"]
    assert json.dumps(snap2["row_counts"], sort_keys=True) == json.dumps(snap1["row_counts"], sort_keys=True)
