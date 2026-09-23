"""Gate G1: normalise selected publisher files into Parquet tables with full provenance.

Every row carries the design's event-store fields: ``source_id``/``source_url`` (publisher URL of the
container), ``container_sha256`` and ``member_sha256`` (bytes as downloaded), ``member`` + ``line_no`` (the
exact CSV line), ``published_at_utc`` (AEMO creation time), ``available_at_utc`` (published + measured posting
margin), ``issued_at_utc`` for forecasts (LOAD_DATE), the valid interval in UTC, ``revision`` where relevant,
``retrieved_at`` and ``parser_version``. ``row_id`` is stable: ``<DATASET>:<member file stem>:L<line>``.

Rules: rows are never invented; a file that breaks the MMS contract is recorded as a failed source and
contributes no rows; identical duplicates are dropped and counted; *conflicting* duplicates abort the table.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from . import paths, rawstore
from .aemo_schema import CONTRACTS
from .mmscsv import MmsFormatError, iter_csv_members, parse_mms_csv, require_fields
from .selection import Selection, SourceEntry, load_selection
from .timeutil import iso_utc, parse_iso, parse_market

PARSER_VERSION = "nem_agent.ingest/1"
TABLES = ("price_5min", "regionsum_5min", "opdemand_forecast", "opdemand_actual", "scada_5min", "duid_region",
          "weather_hourly")


class DuplicateConflictError(ValueError):
    """Two rows share a primary key but disagree on values."""


@dataclass
class BuildResult:
    tables: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: defaultdict(list))
    source_status: dict[str, dict[str, Any]] = field(default_factory=dict)
    duplicates_dropped: dict[str, int] = field(default_factory=lambda: defaultdict(int))


def _stem(member_path: str) -> str:
    return Path(member_path.split("/")[-1]).stem


def _prov(src: SourceEntry, rf: rawstore.RawFile, member: str, member_sha: str, line_no: int,
          published: datetime, margin: timedelta) -> dict[str, Any]:
    return {
        "row_id": f"{src.dataset}:{_stem(member)}:L{line_no}",
        "source_id": src.source_id,
        "source_url": src.url,
        "container_sha256": rf.sha256,
        "member": member,
        "member_sha256": member_sha,
        "line_no": line_no,
        "published_at_utc": published,
        "available_at_utc": published + margin,
        "retrieved_at": rf.retrieved_at,
        "parser_version": PARSER_VERSION,
    }


def _f(v: str) -> float | None:
    v = v.strip()
    return float(v) if v else None


class Windows:
    """Union of event windows (UTC) used to bound what is ingested."""

    def __init__(self, sel: Selection, lead_hours: int = 48) -> None:
        self.windows = [(parse_iso(e.window_start_utc), parse_iso(e.window_end_utc)) for e in sel.events]
        self.lead = timedelta(hours=lead_hours)
        # DST-boundary trading days kept for the round-trip test (probe records them in market_time checks)
        self.extra_actual_days: set[str] = set()
        for chk in sel.market_time.get("checks", {}).get("dst_boundaries", []):
            if "trading_date" in chk:
                self.extra_actual_days.add(chk["trading_date"])

    def target_in(self, t: datetime) -> bool:
        return any(a < t <= b for a, b in self.windows)

    def run_relevant(self, created: datetime, target: datetime) -> bool:
        return any(a < target <= b and a - self.lead <= created <= b for a, b in self.windows)


def _members(src: SourceEntry, rf: rawstore.RawFile) -> Iterable[tuple[str, bytes]]:
    return iter_csv_members(Path(rf.local_path).read_bytes(), Path(rf.local_path).name)


def ingest_dispatchis(src: SourceEntry, rf: rawstore.RawFile, win: Windows, margin: timedelta, out: BuildResult) -> int:
    n = 0
    wanted = {("DISPATCH", "PRICE"), ("DISPATCH", "REGIONSUM")}
    prefixes = ("D,DISPATCH,PRICE,", "D,DISPATCH,REGIONSUM,")
    for member, csvb in _members(src, rf):
        mf, recs = parse_mms_csv(csvb, member, wanted=wanted, line_prefixes=prefixes)
        pkey = require_fields(mf, "DISPATCH", "PRICE", CONTRACTS["DISPATCHIS"][0].required)
        rkey = require_fields(mf, "DISPATCH", "REGIONSUM", CONTRACTS["DISPATCHIS"][1].required)
        interventions: dict[tuple[str, str], bool] = defaultdict(bool)
        for r in recs:
            if r.values["INTERVENTION"] != "0":
                interventions[(r.values["REGIONID"], r.values["SETTLEMENTDATE"])] = True
        for r in recs:
            v = r.values
            if v["INTERVENTION"] != "0":
                continue
            end = parse_market(v["SETTLEMENTDATE"])
            if not win.target_in(end):
                continue
            base = _prov(src, rf, member, mf.sha256, r.line_no, mf.created_at_utc, margin)
            base.update(region=v["REGIONID"], interval_end_utc=end, interval_start_utc=end - timedelta(minutes=5),
                        intervention_record_published=interventions[(v["REGIONID"], v["SETTLEMENTDATE"])],
                        runno=int(v["RUNNO"]))
            if r.table == pkey:
                out.tables["price_5min"].append({**base, "rrp": float(v["RRP"]), "rop": _f(v["ROP"]),
                                                 "price_status": v["PRICE_STATUS"], "unit": "$/MWh"})
            elif r.table == rkey:
                out.tables["regionsum_5min"].append({
                    **base, "totaldemand_mw": _f(v["TOTALDEMAND"]), "availablegeneration_mw": _f(v["AVAILABLEGENERATION"]),
                    "demandforecast_mw": _f(v["DEMANDFORECAST"]), "dispatchablegeneration_mw": _f(v["DISPATCHABLEGENERATION"]),
                    "netinterchange_mw": _f(v["NETINTERCHANGE"]),
                })
            n += 1
    return n


def ingest_forecast(src: SourceEntry, rf: rawstore.RawFile, win: Windows, margin: timedelta, out: BuildResult) -> int:
    n = 0
    c = CONTRACTS["OPDEM_FORECAST_HH"][0]
    for member, csvb in _members(src, rf):
        mf, recs = parse_mms_csv(csvb, member, wanted={(c.report, c.subtype)})
        require_fields(mf, c.report, c.subtype, c.required)
        for r in recs:
            v = r.values
            target = parse_market(v["INTERVAL_DATETIME"])
            if not win.run_relevant(mf.created_at_utc, target):
                continue
            row = _prov(src, rf, member, mf.sha256, r.line_no, mf.created_at_utc, margin)
            row.update(
                region=v["REGIONID"], target_end_utc=target, target_start_utc=target - timedelta(minutes=30),
                issued_at_utc=parse_market(v["LOAD_DATE"]), run_id=_stem(member),
                poe10_mw=_f(v["OPERATIONAL_DEMAND_POE10"]), poe50_mw=_f(v["OPERATIONAL_DEMAND_POE50"]),
                poe90_mw=_f(v["OPERATIONAL_DEMAND_POE90"]), unit="MW", definition="OPERATIONAL_DEMAND",
            )
            out.tables["opdemand_forecast"].append(row)
            n += 1
    return n


def ingest_actual(src: SourceEntry, rf: rawstore.RawFile, win: Windows, margin: timedelta, out: BuildResult) -> int:
    n = 0
    c = CONTRACTS[src.dataset][0]
    revision = "initial" if src.dataset == "OPDEM_ACTUAL_HH" else "updated"
    for member, csvb in _members(src, rf):
        keep_whole_day = revision == "updated" and any(f"_DAILY_{d}_" in member for d in win.extra_actual_days)
        mf, recs = parse_mms_csv(csvb, member, wanted={(c.report, c.subtype)})
        key = require_fields(mf, c.report, c.subtype, c.required)
        fields = mf.tables[key]
        for r in recs:
            v = r.values
            end = parse_market(v["INTERVAL_DATETIME"])
            if not (keep_whole_day or win.target_in(end)):
                continue
            row = _prov(src, rf, member, mf.sha256, r.line_no, mf.created_at_utc, margin)
            row.update(
                region=v["REGIONID"], interval_end_utc=end, interval_start_utc=end - timedelta(minutes=30),
                operational_demand_mw=float(v["OPERATIONAL_DEMAND"]),
                adjustment_mw=_f(v["OPERATIONAL_DEMAND_ADJUSTMENT"]) if "OPERATIONAL_DEMAND_ADJUSTMENT" in fields else None,
                wdr_estimate_mw=_f(v["WDR_ESTIMATE"]) if "WDR_ESTIMATE" in fields else None,
                revision=revision, unit="MW", definition="OPERATIONAL_DEMAND",
            )
            out.tables["opdemand_actual"].append(row)
            n += 1
    return n


def ingest_scada(src: SourceEntry, rf: rawstore.RawFile, win: Windows, margin: timedelta, out: BuildResult) -> int:
    n = 0
    c = CONTRACTS["DISPATCH_SCADA"][0]
    for member, csvb in _members(src, rf):
        mf, recs = parse_mms_csv(csvb, member, wanted={(c.report, c.subtype)})
        require_fields(mf, c.report, c.subtype, c.required)
        for r in recs:
            v = r.values
            end = parse_market(v["SETTLEMENTDATE"])
            if not win.target_in(end):
                continue
            row = _prov(src, rf, member, mf.sha256, r.line_no, mf.created_at_utc, margin)
            row.update(duid=v["DUID"], interval_end_utc=end, scada_mw=float(v["SCADAVALUE"]), unit="MW",
                       reading_time_note="SCADAVALUE: instantaneous reading at the START of the dispatch interval")
            out.tables["scada_5min"].append(row)
            n += 1
    return n


def ingest_duid(src: SourceEntry, rf: rawstore.RawFile, out: BuildResult) -> int:
    c = CONTRACTS["MMSDM_DUDETAILSUMMARY"][0]
    n = 0
    for member, csvb in _members(src, rf):
        mf, recs = parse_mms_csv(csvb, member, wanted={(c.report, c.subtype)})
        require_fields(mf, c.report, c.subtype, c.required)
        for r in recs:
            v = r.values
            out.tables["duid_region"].append({
                "row_id": f"{src.dataset}:{_stem(member)}:L{r.line_no}", "source_id": src.source_id,
                "source_url": src.url, "container_sha256": rf.sha256, "member": member, "line_no": r.line_no,
                "duid": v["DUID"], "region": v["REGIONID"], "valid_from_utc": parse_market(v["START_DATE"]),
                "valid_to_utc": parse_market(v["END_DATE"]), "dispatchtype": v["DISPATCHTYPE"],
                "schedule_type": v["SCHEDULE_TYPE"], "stationid": v["STATIONID"], "parser_version": PARSER_VERSION,
            })
            n += 1
    return n


WEATHER_UNITS = {"T2M": "°C", "WS50M": "m/s", "ALLSKY_SFC_SW_DWN": "W/m^2"}


def ingest_weather(src: SourceEntry, rf: rawstore.RawFile, win: Windows, out: BuildResult) -> int:
    doc = json.loads(Path(rf.local_path).read_text())
    hdr = doc.get("header", {})
    fill = hdr.get("fill_value", -999.0)
    cov = src.coverage or {}
    region = src.source_id.split("_")[2].upper()
    params = doc.get("properties", {}).get("parameter", {})
    units = {k: v.get("units") for k, v in doc.get("parameters", {}).items()} if isinstance(doc.get("parameters"), dict) else {}
    retrieved = parse_iso(rf.retrieved_at) if rf.retrieved_at else datetime.now(UTC)
    content_id = rawstore.content_sha256(src.dataset, Path(rf.local_path).read_bytes())
    n = 0
    for p, series in params.items():
        for stamp, value in series.items():
            hour = datetime.strptime(stamp, "%Y%m%d%H").replace(tzinfo=UTC)
            if not any(a - timedelta(hours=1) < hour <= b for a, b in win.windows):
                continue
            if value == fill:
                continue
            out.tables["weather_hourly"].append({
                "row_id": f"NASA_POWER:{src.source_id}:{p}:{stamp}", "source_id": src.source_id, "source_url": src.url,
                "container_sha256": rf.sha256, "content_sha256": content_id, "region": region, "point": cov.get("point"),
                "latitude": cov.get("latitude"), "longitude": cov.get("longitude"), "parameter": p,
                "hour_utc": hour, "value": float(value), "unit": units.get(p) or WEATHER_UNITS.get(p, ""),
                "api_version": cov.get("api_version"), "published_at_utc": None, "available_at_utc": retrieved,
                "retrieved_at": rf.retrieved_at, "parser_version": PARSER_VERSION,
                "evidence_class": "retrospective_model_derived",
            })
            n += 1
    return n


PRIMARY_KEYS: dict[str, tuple[str, ...]] = {
    "price_5min": ("region", "interval_end_utc"),
    "regionsum_5min": ("region", "interval_end_utc"),
    "opdemand_forecast": ("region", "target_end_utc", "run_id"),
    "opdemand_actual": ("region", "interval_end_utc", "revision"),
    "scada_5min": ("duid", "interval_end_utc"),
    "duid_region": ("row_id",),
    "weather_hourly": ("region", "parameter", "hour_utc"),
}
VALUE_FIELDS: dict[str, tuple[str, ...]] = {
    "price_5min": ("rrp", "price_status"),
    "regionsum_5min": ("totaldemand_mw", "availablegeneration_mw", "netinterchange_mw"),
    "opdemand_forecast": ("poe10_mw", "poe50_mw", "poe90_mw", "issued_at_utc"),
    "opdemand_actual": ("operational_demand_mw",),
    "scada_5min": ("scada_mw",),
    "duid_region": ("region",),
    "weather_hourly": ("value",),
}


def dedupe(table: str, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Drop exact duplicates (same key, same values); raise on conflicting duplicates."""
    seen: dict[tuple, dict[str, Any]] = {}
    dropped = 0
    for row in rows:
        key = tuple(row[k] for k in PRIMARY_KEYS[table])
        prev = seen.get(key)
        if prev is None:
            seen[key] = row
            continue
        a = tuple(prev[f] for f in VALUE_FIELDS[table])
        b = tuple(row[f] for f in VALUE_FIELDS[table])
        if a != b:
            raise DuplicateConflictError(
                f"{table}: conflicting duplicate for key {key}: {prev['row_id']} {a} vs {row['row_id']} {b}")
        dropped += 1
    return list(seen.values()), dropped


_VOLATILE = {"retrieved_at"}  # retrieval time is provenance, not content


def content_hash(rows: list[dict[str, Any]]) -> str:
    h = hashlib.sha256()
    for row in sorted(rows, key=lambda r: r["row_id"]):
        api_row = row.get("evidence_class") == "retrospective_model_derived"
        # API responses: raw bytes (and retrieval-time availability) vary per download; their identity is the
        # canonical content hash recorded in the row, so the byte hash is left out of the content hash.
        stable = {k: v for k, v in row.items() if k not in _VOLATILE
                  and not (api_row and k in ("available_at_utc", "container_sha256"))}
        h.update(json.dumps(stable, sort_keys=True, default=str).encode())
    return h.hexdigest()


def _write_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    rows = sorted(rows, key=lambda r: r["row_id"])
    tbl = pa.Table.from_pylist(rows) if rows else pa.table({"row_id": pa.array([], pa.string())})
    pq.write_table(tbl, path, compression="zstd")


def build(sel: Selection | None = None, *, refresh: bool = False, store: Path | None = None,
          log: Any = print) -> dict[str, Any]:
    sel = sel or load_selection()
    store = store or paths.store_dir()
    store.mkdir(parents=True, exist_ok=True)
    win = Windows(sel)
    av = sel.availability
    opdem_margin = timedelta(minutes=int(av["margin_minutes"]))
    disp_margin = timedelta(minutes=int(av.get("dispatch_margin_minutes_after_interval_start", av["margin_minutes"])))
    out = BuildResult()
    handlers = {
        "DISPATCHIS": lambda s, rf: ingest_dispatchis(s, rf, win, disp_margin, out),
        "DISPATCH_SCADA": lambda s, rf: ingest_scada(s, rf, win, disp_margin, out),
        "OPDEM_FORECAST_HH": lambda s, rf: ingest_forecast(s, rf, win, opdem_margin, out),
        "OPDEM_ACTUAL_HH": lambda s, rf: ingest_actual(s, rf, win, opdem_margin, out),
        "OPDEM_ACTUAL_DAILY": lambda s, rf: ingest_actual(s, rf, win, opdem_margin, out),
        "MMSDM_DUDETAILSUMMARY": lambda s, rf: ingest_duid(s, rf, out),
        "NASA_POWER_HOURLY": lambda s, rf: ingest_weather(s, rf, win, out),
    }
    for src in sel.sources:
        handler = handlers.get(src.dataset)
        if handler is None:
            continue  # documents are handled by `build-index`; PUBLIC_PRICES was only used for the scan
        rf = rawstore.get(src.dataset, src.url, expected_sha256=src.sha256,
                          expected_content_sha256=src.content_sha256, refresh=refresh)
        if rf.rolled_off:
            from .recover import recover_from_archive

            rf = recover_from_archive(src.dataset, src.url, src.sha256, log=log) or rf
        status: dict[str, Any] = {"dataset": src.dataset, "fetch_status": rf.status, "retrieved_at": rf.retrieved_at}
        if not rf.available:
            status.update(ingested=False, error=rf.error, rolled_off=rf.rolled_off)
            log(f"[data] {'ROLLED OFF' if rf.rolled_off else 'MISSING'} {src.source_id}: {rf.error}")
        else:
            try:
                status.update(ingested=True, rows=handler(src, rf))
            except MmsFormatError as exc:
                status.update(ingested=False, error=f"{type(exc).__name__}: {exc}")
                log(f"[data] REJECTED {src.source_id}: {exc}")
        out.source_status[src.source_id] = status

    counts: dict[str, int] = {}
    hashes: dict[str, str] = {}
    examples: dict[str, list[str]] = {}
    final: dict[str, list[dict[str, Any]]] = {}
    for table in TABLES:  # dedupe everything first: a conflict aborts before any file is written
        rows, dropped = dedupe(table, out.tables.get(table, []))
        out.duplicates_dropped[table] = dropped
        final[table] = rows
    for table, rows in final.items():
        _write_parquet(store / f"{table}.parquet", rows)
        counts[table] = len(rows)
        hashes[table] = content_hash(rows)
        examples[table] = sorted(r["row_id"] for r in rows)[:2]
        log(f"[data] {table:<18} rows={len(rows):>8} duplicates_dropped={out.duplicates_dropped[table]}")

    data_version = hashlib.sha256(
        json.dumps({"parser": PARSER_VERSION, "sources": sorted((s.source_id, s.sha256) for s in sel.sources),
                    "tables": hashes}, sort_keys=True).encode()).hexdigest()[:16]
    snapshot = {
        "data_version": data_version,
        "parser_version": PARSER_VERSION,
        "selection_generated_at": sel.generated_at,
        "built_at": iso_utc(datetime.now(UTC)),
        "row_counts": counts,
        "content_sha256": hashes,
        "example_row_ids": examples,
        "duplicates_dropped": dict(out.duplicates_dropped),
        "availability_margins_min": {"operational_demand": opdem_margin.total_seconds() / 60,
                                     "dispatch_after_creation": disp_margin.total_seconds() / 60},
        "sources": out.source_status,
        "failed_sources": {k: v for k, v in out.source_status.items() if not v.get("ingested") and not v.get("rolled_off")},
        "rolled_off_sources": {k: v for k, v in out.source_status.items() if v.get("rolled_off")},
    }
    (store / "snapshot.json").write_text(json.dumps(snapshot, indent=2, sort_keys=True, default=str))
    log(f"[data] data_version={data_version} failed_sources={len(snapshot['failed_sources'])} "
        f"rolled_off_sources={len(snapshot['rolled_off_sources'])}")
    return snapshot
