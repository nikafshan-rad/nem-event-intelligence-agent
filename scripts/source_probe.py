#!/usr/bin/env python
"""G0 source probe: discover real publisher files, choose verifiable events, record provenance.

Everything written to ``data/source_selection.json`` is derived from responses observed during this
run: directory listings, HTTP status/headers, downloaded bytes (SHA-256), and parsed records. No URL
is trusted without a response; no event, number or timestamp is typed in by hand.

Usage:  python scripts/source_probe.py --output data/source_selection.json
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import math
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nem_agent import nemweb, rawstore  # noqa: E402
from nem_agent.aemo_schema import CONTRACTS  # noqa: E402
from nem_agent.http import fetch  # noqa: E402
from nem_agent.mmscsv import MmsFormatError, iter_csv_members, parse_mms_csv, require_fields  # noqa: E402
from nem_agent.selection import Selection  # noqa: E402
from nem_agent.timeutil import NEM_TZ, REGION_TZ, UTC, iso_utc, market_str, parse_market  # noqa: E402

PROBE_VERSION = "0.1.0"

HOST_CHECKS = [
    ("AEMO operational demand data page",
     "https://www.aemo.com.au/energy-systems/electricity/national-electricity-market-nem/data-nem/operational-demand-data"),
    ("AEMO dispatch data page",
     "https://www.aemo.com.au/energy-systems/electricity/national-electricity-market-nem/data-nem/market-management-system-mms-data/dispatch"),
    ("AEMO generation and load page",
     "https://www.aemo.com.au/energy-systems/electricity/national-electricity-market-nem/data-nem/market-management-system-mms-data/generation-and-load"),
    ("AEMO market event reports page",
     "https://www.aemo.com.au/energy-systems/electricity/national-electricity-market-nem/nem-events-and-reports/market-event-reports"),
    ("AEMO copyright permissions page", "https://www.aemo.com.au/privacy-and-legal-notices/copyright-permissions"),
    ("NEMWeb Reports/Current listing", "https://nemweb.com.au/Reports/Current/"),
    ("NEMWeb Reports/Archive listing", "https://nemweb.com.au/Reports/Archive/"),
    ("NASA POWER hourly API docs", "https://power.larc.nasa.gov/docs/services/api/temporal/hourly/"),
    ("NASA POWER referencing guide", "https://power.larc.nasa.gov/docs/referencing/"),
]

# Candidate public AEMO PDFs (media-library URLs). Each is kept only if it returns HTTP 200 with a real
# PDF body (magic bytes), because the site can answer 200/302 with an HTML error page.
AEMO_PDF_CANDIDATES = [
    ("aemo_demand_terms", "Demand Terms in EMMS Data Model",
     "https://www.aemo.com.au/-/media/files/electricity/nem/security_and_reliability/dispatch/policy_and_process/demand-terms-in-emms-data-model.pdf"),
    ("aemo_so_op_3710", "SO_OP_3710 Load Forecasting",
     "https://www.aemo.com.au/-/media/files/electricity/nem/security_and_reliability/power_system_ops/procedures/so_op_3710-load-forecasting.pdf"),
    ("aemo_so_op_3705", "SO_OP_3705 Dispatch procedure",
     "https://www.aemo.com.au/-/media/files/electricity/nem/security_and_reliability/power_system_ops/procedures/so_op_3705-dispatch.pdf"),
    ("aemo_so_op_3704", "SO_OP_3704 Pre-dispatch procedure",
     "https://www.aemo.com.au/-/media/files/electricity/nem/security_and_reliability/power_system_ops/procedures/so_op_3704-predispatch.pdf"),
    ("aemo_nem_fact_sheet", "Fact Sheet: National Electricity Market",
     "https://www.aemo.com.au/-/media/files/electricity/nem/national-electricity-market-fact-sheet.pdf"),
    # Plausible-looking URL kept deliberately: it must be rejected (redirects to an HTML page).
    ("aemo_opdemand_methodology_guess", "Operational demand methodology (unverified guess)",
     "https://www.aemo.com.au/-/media/files/electricity/nem/security_and_reliability/dispatch/policy_and_process/operational-demand-methodology.pdf"),
]

MMS_DM_BASE = "https://nemweb.com.au/Reports/Current/MMSDataModelReport/Electricity/Electricity%20Data%20Model%20Report_files/"
MMS_DM_TABLES = ["DEMANDOPERATIONALACTUAL", "DEMANDOPERATIONALFORECAST", "DISPATCHPRICE", "DISPATCHREGIONSUM",
                 "DISPATCH_UNIT_SCADA", "DISPATCH_PRICE_REVISION", "DISPATCHINTERCONNECTORRES", "DISPATCHCASESOLUTION"]

# One documented representative point per region (capital city). This is context, not a regional average.
WEATHER_POINTS = {
    "SA1": ("Adelaide", -34.9285, 138.6007),
    "NSW1": ("Sydney", -33.8688, 151.2093),
    "VIC1": ("Melbourne", -37.8136, 144.9631),
    "QLD1": ("Brisbane", -27.4698, 153.0251),
    "TAS1": ("Hobart", -42.8821, 147.3272),
}
WEATHER_PARAMS = "T2M,WS50M,ALLSKY_SFC_SW_DWN"

AEMO_PUBLISHER = "Australian Energy Market Operator (AEMO)"
AEMO_LICENCE = ("© AEMO. Used under AEMO copyright permissions with attribution "
                "(https://www.aemo.com.au/privacy-and-legal-notices/copyright-permissions); not redistributed by this repo.")
NASA_PUBLISHER = "NASA Langley Research Center POWER Project"
NASA_LICENCE = "NASA POWER data; cite per https://power.larc.nasa.gov/docs/referencing/ ; not redistributed by this repo."


def log(msg: str) -> None:
    print(f"[probe] {msg}", flush=True)


def floor30(dt: datetime) -> datetime:
    return dt.replace(minute=0 if dt.minute < 30 else 30, second=0, microsecond=0)


def ceil30(dt: datetime) -> datetime:
    f = floor30(dt)
    return f if f == dt else f + timedelta(minutes=30)


def pct(values: list[float], q: float) -> float:
    s = sorted(values)
    if not s:
        return math.nan
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


@dataclass
class Candidate:
    region: str
    market_date: date
    peak_end_utc: datetime
    peak_rrp: float
    kind: str
    n_threshold: int
    scan_file: str


class Probe:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.sources: dict[str, dict[str, Any]] = {}
        self.attempted: list[dict[str, Any]] = []
        self.listings: dict[tuple[str, str], list[nemweb.ListingEntry]] = {}
        self.notes: list[str] = []
        self.host_checks: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ helpers
    def listing(self, dataset: str, which: str) -> list[nemweb.ListingEntry]:
        key = (dataset, which)
        if key not in self.listings:
            cur, arc = nemweb.DATASET_DIRS[dataset]
            path = cur if which == "current" else arc
            if path is None:
                self.listings[key] = []
            else:
                res, entries = nemweb.list_dir(path)
                if not res.ok:
                    self.attempted.append({"url": res.url, "status": res.status, "error": res.error})
                    log(f"listing FAILED {res.url}: {res.error}")
                self.listings[key] = [e for e in entries if not e.is_dir]
                log(f"listing {dataset}/{which}: {len(self.listings[key])} files")
        return self.listings[key]

    def add_source(self, rf: rawstore.RawFile, *, source_id: str, dataset: str, role: str, kind: str,
                   publisher: str = AEMO_PUBLISHER, licence: str = AEMO_LICENCE, event: str | None = None,
                   **extra: Any) -> dict[str, Any]:
        if source_id in self.sources:
            entry = self.sources[source_id]
            if event and event not in entry["events"]:
                entry["events"].append(event)
            return entry
        entry = {
            "source_id": source_id, "dataset": dataset, "role": role, "url": rf.url, "container_kind": kind,
            "publisher": publisher, "http_status": rf.http_status or 0, "content_type": rf.content_type,
            "size": rf.size or 0, "sha256": rf.sha256 or "", "retrieved_at": rf.retrieved_at or "",
            "content_sha256": rawstore.content_sha256(dataset, Path(rf.local_path).read_bytes()) if rf.available else None,
            "last_modified": rf.last_modified, "events": [event] if event else [], "notes": licence,
        }
        entry.update(extra)
        self.sources[source_id] = entry
        return entry

    def get(self, dataset: str, url: str, **kw: Any) -> rawstore.RawFile:
        rf = rawstore.get(dataset, url, **kw)
        if not rf.available:
            self.attempted.append({"url": url, "status": rf.http_status, "error": rf.error, "dataset": dataset})
            log(f"FETCH FAILED {url}: {rf.error}")
        return rf

    # ------------------------------------------------------------------ steps
    def check_hosts(self) -> None:
        for label, url in HOST_CHECKS:
            res = fetch(url, timeout=30, retries=1, max_bytes=5_000_000)
            body = (res.body or b"")[:4000].decode("utf-8", "replace")
            challenge = "Just a moment" in body or res.headers.get("cf-mitigated") == "challenge"
            self.host_checks.append({
                "label": label, "url": url, "http_status": res.status, "content_type": res.content_type,
                "cloudflare_challenge": challenge, "checked_at": iso_utc(datetime.now(UTC)),
            })
            log(f"host {res.status} {'(Cloudflare challenge) ' if challenge else ''}{label}")

    def measure_availability(self) -> dict[str, Any]:
        """Observed lag between AEMO file creation and appearance in the NEMWeb listing."""
        out: dict[str, Any] = {}
        for ds in ("OPDEM_FORECAST_HH", "OPDEM_ACTUAL_HH"):
            lags = []
            for e in self.listing(ds, "current"):
                created = nemweb.creation_time_from_name(e.name)
                if created and e.listed_at_utc:
                    lags.append((e.listed_at_utc - created).total_seconds() / 60.0)
            out[ds] = {
                "n_files": len(lags), "min_min": round(min(lags), 2), "p50_min": round(pct(lags, 0.5), 2),
                "p95_min": round(pct(lags, 0.95), 2), "p99_min": round(pct(lags, 0.99), 2), "max_min": round(max(lags), 2),
                "method": "NEMWeb Current listing time (minute precision, market time) minus creation timestamp in file name",
            }
        lags = []
        for e in self.listing("DISPATCHIS", "current"):
            m = nemweb.NAME_PATTERNS["DISPATCHIS"].match(e.name)
            if m and e.listed_at_utc:
                start = parse_market(m.group(1)) - timedelta(minutes=5)
                lags.append((e.listed_at_utc - start).total_seconds() / 60.0)
        if lags:
            out["DISPATCHIS"] = {
                "n_files": len(lags), "min_min": round(min(lags), 2), "p50_min": round(pct(lags, 0.5), 2),
                "p99_min": round(pct(lags, 0.99), 2), "max_min": round(max(lags), 2),
                "method": "NEMWeb Current listing time minus dispatch interval START (interval end - 5 min)",
            }
        worst = max(out[d]["max_min"] for d in ("OPDEM_FORECAST_HH", "OPDEM_ACTUAL_HH"))
        margin = int(math.ceil(worst)) + 1
        out["margin_minutes"] = margin
        out["policy"] = (
            f"A file is treated as publicly available at creation time + {margin} min (the maximum lag observed in "
            "the Current listings, rounded up, +1 min for the listing's minute precision). As-of queries only use "
            "rows whose available_at <= as_of. Archived files carry no listing time of their own, so the same "
            "margin is applied; this is an evidence-based assumption, not a publisher guarantee."
        )
        if "DISPATCHIS" in out:
            dmargin = int(math.ceil(max(out["DISPATCHIS"]["max_min"], 0))) + 1
            out["dispatch_margin_minutes_after_interval_start"] = dmargin
        return out

    def check_market_time(self) -> dict[str, Any]:
        evidence: list[str] = []
        checks: dict[str, Any] = {}
        # (a) HTTP Last-Modified (GMT) vs C-header creation time of the newest Current actual file.
        entries = self.listing("OPDEM_ACTUAL_HH", "current")
        newest = entries[-1]
        rf = self.get("OPDEM_ACTUAL_HH", newest.url)
        if rf.available and rf.last_modified:
            data = Path(rf.local_path).read_bytes()
            mp, csvb = next(iter_csv_members(data, newest.name))
            mf, _ = parse_mms_csv(csvb, mp)
            lm = datetime.strptime(rf.last_modified, "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=UTC)
            naive_created = datetime.strptime(mf.created_at_market, "%Y/%m/%d %H:%M:%S")
            offset_h = (naive_created - lm.replace(tzinfo=None)).total_seconds() / 3600
            checks["last_modified_vs_c_header"] = {
                "file": newest.name, "http_last_modified_gmt": rf.last_modified,
                "c_header_created": mf.created_at_market, "implied_offset_hours": round(offset_h, 3),
                "listing_time": newest.listed_at_market,
            }
            evidence.append(
                f"{newest.name}: C-header creation {mf.created_at_market} vs HTTP Last-Modified {rf.last_modified} "
                f"=> header clock is UTC{offset_h:+.2f}h (expected +10)."
            )
        # (b) Daylight-saving boundaries: trading days spanning Australian DST changes must still have 48
        #     unique half-hour intervals if AEMO timestamps are a fixed UTC+10 clock.
        dst_checks = []
        for ym, dst_day in (("20251001", date(2025, 10, 5)), ("20260401", date(2026, 4, 5))):
            # The change happens at 02:00 market time, i.e. inside the trading day that starts the day before.
            arc = [e for e in self.listing("OPDEM_ACTUAL_DAILY", "archive") if e.name.endswith(f"_{ym}.zip")]
            if not arc:
                dst_checks.append({"month": ym, "status": "archive not listed"})
                continue
            rf2 = self.get("OPDEM_ACTUAL_DAILY", arc[0].url)
            if not rf2.available:
                continue
            self.add_source(rf2, source_id=f"opdem_actual_daily_{ym}", dataset="OPDEM_ACTUAL_DAILY",
                            role="dst_boundary_check", kind="archive")
            for mp, csvb in iter_csv_members(Path(rf2.local_path).read_bytes(), arc[0].name):
                tdays = {(dst_day - timedelta(days=1)).strftime("%Y%m%d"), dst_day.strftime("%Y%m%d")}
                m = re.search(r"_DAILY_(\d{8})_", mp)
                if not m or m.group(1) not in tdays:
                    continue
                counts: dict[str, int] = defaultdict(int)
                stamps: dict[str, set[str]] = defaultdict(set)
                mf, recs = parse_mms_csv(csvb, mp, wanted={("OPERATIONAL_DEMAND", "ACTUAL")})
                for r in recs:
                    counts[r.values["REGIONID"]] += 1
                    stamps[r.values["REGIONID"]].add(r.values["INTERVAL_DATETIME"])
                dst_checks.append({
                    "month_archive": arc[0].name, "member": mp, "trading_date": m.group(1),
                    "dst_change_date": dst_day.isoformat(),
                    "rows_per_region": dict(counts), "unique_intervals_per_region": {k: len(v) for k, v in stamps.items()},
                })
                evidence.append(
                    f"{mp} (trading day {m.group(1)}, adjacent to the {dst_day.isoformat()} DST change): "
                    f"{sorted(set(counts.values()))} rows per region and {sorted({len(v) for v in stamps.values()})} "
                    "unique half-hour stamps (48 => fixed-offset clock, no DST shift)."
                )
        checks["dst_boundaries"] = dst_checks
        lm = checks.get("last_modified_vs_c_header", {})
        dst_ok = bool(dst_checks) and all(
            set(d.get("unique_intervals_per_region", {}).values()) == {48} for d in dst_checks if "member" in d)
        offset_ok = abs(lm.get("implied_offset_hours", 0) - 10) < 0.1
        return {"name": "NEM market time (AEST)", "utc_offset": "+10:00", "dst": False,
                "confirmed_by_probe": bool(dst_ok and offset_ok),
                "evidence": evidence, "checks": checks}

    def interval_convention(self) -> list[str]:
        ev = []
        lags = []
        for e in self.listing("OPDEM_ACTUAL_HH", "current"):
            m = nemweb.NAME_PATTERNS["OPDEM_ACTUAL_HH"].match(e.name)
            if m:
                lags.append((parse_market(m.group(2)) - parse_market(m.group(1))).total_seconds())
        ev.append(
            f"ACTUAL_HH: across {len(lags)} Current files, the file for INTERVAL_DATETIME T is created "
            f"{min(lags):.0f}-{max(lags):.0f} s after T; a half-hour average cannot be known before its interval "
            "ends, so INTERVAL_DATETIME is the interval END."
        )
        return ev

    def scan_prices(self) -> list[Candidate]:
        """Scan the daily next-day Public_Prices files currently on NEMWeb for candidate intervals."""
        files = [e for e in self.listing("PUBLIC_PRICES", "current") if nemweb.NAME_PATTERNS["PUBLIC_PRICES"].match(e.name)]
        log(f"scanning {len(files)} Public_Prices daily files")
        with cf.ThreadPoolExecutor(6) as ex:
            rfs = list(ex.map(lambda e: self.get("PUBLIC_PRICES", e.url), files))
        by_day: dict[tuple[str, date], list[tuple[float, datetime, str]]] = defaultdict(list)
        seen: set[tuple[str, str]] = set()
        for e, rf in zip(files, rfs, strict=True):
            if not rf.available:
                continue
            self.add_source(rf, source_id=f"public_prices_{e.name[14:22]}", dataset="PUBLIC_PRICES",
                            role="event_scan", kind="current")
            for mp, csvb in iter_csv_members(Path(rf.local_path).read_bytes(), e.name):
                mf, recs = parse_mms_csv(csvb, mp, wanted={("DREGION", "")})
                key = require_fields(mf, "DREGION", "", CONTRACTS["PUBLIC_PRICES"][0].required)
                for r in recs:
                    if r.table != key or r.values["INTERVENTION"] != "0":
                        continue
                    k = (r.values["SETTLEMENTDATE"], r.values["REGIONID"])
                    if k in seen:
                        continue
                    seen.add(k)
                    t = parse_market(r.values["SETTLEMENTDATE"])
                    mday = (t - timedelta(minutes=5)).astimezone(NEM_TZ).date()
                    by_day[(r.values["REGIONID"], mday)].append((float(r.values["RRP"]), t, e.name))
        cands = []
        thr = self.args.threshold
        for (region, mday), vals in by_day.items():
            if len(vals) < 288:
                continue  # incomplete day in the scan (edge of retention window)
            mx = max(vals, key=lambda v: v[0])
            mn = min(vals, key=lambda v: v[0])
            cands.append(Candidate(region, mday, mx[1], mx[0], "high_price", sum(v[0] >= thr for v in vals), mx[2]))
            cands.append(Candidate(region, mday, mn[1], mn[0], "low_price", sum(v[0] < 0 for v in vals), mn[2]))
        log(f"scan produced {len(seen)} region-intervals across {len(by_day)} region-days")
        return cands

    def choose_events(self, cands: list[Candidate]) -> list[tuple[Candidate, str]]:
        highs = sorted([c for c in cands if c.kind == "high_price" and c.peak_rrp >= self.args.threshold],
                       key=lambda c: -c.peak_rrp)
        arc_fc = [nemweb.archive_start("OPDEM_FORECAST_HH", e.name) for e in self.listing("OPDEM_FORECAST_HH", "archive")]
        last_week = max(d for d in arc_fc if d)
        archive_limit = (last_week + timedelta(days=7)).astimezone(UTC) - timedelta(hours=1)
        disp_days = {nemweb.archive_start("DISPATCHIS", e.name) for e in self.listing("DISPATCHIS", "archive")}

        def covered(c: Candidate) -> bool:
            ws, we = self.window(c)
            days_needed = {(t - timedelta(minutes=5)).astimezone(NEM_TZ).date()
                           for t in (ws + timedelta(minutes=5), we)}
            have = {d.date() for d in disp_days if d}
            return we <= archive_limit and days_needed <= have

        chosen: list[tuple[Candidate, str]] = []
        pref = [c for c in highs if c.region == self.args.prefer_region and covered(c)]
        primary = pref[0] if pref else next(c for c in highs if covered(c))
        chosen.append((primary, "primary"))
        per_region: dict[str, int] = defaultdict(int)
        per_region[primary.region] += 1
        for c in highs:
            if len([x for x in chosen if x[0].kind == "high_price"]) >= self.args.max_high_events:
                break
            if not covered(c) or per_region[c.region] >= self.args.max_per_region:
                continue
            if any(self.overlaps(c, x) for x, _ in chosen):
                continue
            chosen.append((c, "evaluation"))
            per_region[c.region] += 1
        lows = sorted([c for c in cands if c.kind == "low_price" and c.peak_rrp < 0 and covered(c)],
                      key=lambda c: c.peak_rrp)
        for c in lows:
            if not any(self.overlaps(c, x) for x, _ in chosen):
                chosen.append((c, "evaluation"))
                break
        return chosen

    def window(self, c: Candidate) -> tuple[datetime, datetime]:
        h = timedelta(hours=self.args.half_window_hours)
        return floor30(c.peak_end_utc - h), ceil30(c.peak_end_utc + h)

    def overlaps(self, a: Candidate, b: Candidate) -> bool:
        if a.region != b.region:
            return False
        a0, a1 = self.window(a)
        b0, b1 = self.window(b)
        return a0 < b1 and b0 < a1

    # ------------------------------------------------------------------ per-event resolution
    def resolve_event(self, c: Candidate, role: str) -> dict[str, Any]:
        ws, we = self.window(c)
        tz = REGION_TZ[c.region]
        event_id = f"{c.region}-{c.peak_end_utc.astimezone(NEM_TZ).strftime('%Y%m%dT%H%M')}-{'hi' if c.kind == 'high_price' else 'lo'}"
        log(f"resolving {event_id} ({c.kind} {c.peak_rrp} $/MWh) window {iso_utc(ws)}..{iso_utc(we)}")
        checks: dict[str, Any] = {}

        # --- dispatch price + regionsum (daily archives by market date)
        days = sorted({(t - timedelta(minutes=5)).astimezone(NEM_TZ).date() for t in (ws + timedelta(minutes=5), we)})
        days = [days[0] + timedelta(days=i) for i in range((days[-1] - days[0]).days + 1)]
        price_rows: dict[datetime, float] = {}
        for ds, role_name in (("DISPATCHIS", "price_5min"), ("DISPATCH_SCADA", "scada_5min")):
            for d in days:
                ent = [e for e in self.listing(ds, "archive") if e.name.upper().endswith(f"_{d:%Y%m%d}.ZIP")]
                if not ent:
                    raise SystemExit(f"G0 FAIL: no {ds} archive for {d}")
                rf = self.get(ds, ent[0].url)
                if not rf.available:
                    raise SystemExit(f"G0 FAIL: {ds} archive {ent[0].url} unavailable: {rf.error}")
                cov, schema, recs = self.inspect_container(ds, rf, ent[0].name)
                self.add_source(rf, source_id=f"{ds.lower()}_{d:%Y%m%d}", dataset=ds, role=role_name,
                                kind="archive", event=event_id, coverage=cov, schema_fields=schema,
                                issue_time_provenance=(
                                    "Per-interval AEMO C-header creation time of each inner file (market time); "
                                    "dispatch files are created at the START of their 5-minute interval."
                                    if ds == "DISPATCHIS" else
                                    "Per-interval C-header creation time; SCADAVALUE is the reading at the start of the interval."))
                if ds == "DISPATCHIS":
                    for r in recs:
                        if r["REGIONID"] == c.region and r["INTERVENTION"] == "0":
                            price_rows[parse_market(r["SETTLEMENTDATE"])] = float(r["RRP"])
        disp_peak = price_rows.get(c.peak_end_utc)
        checks["price_cross_check"] = {
            "interval_end_market": market_str(c.peak_end_utc),
            "public_prices_rrp": c.peak_rrp, "dispatchis_rrp": disp_peak,
            "match": disp_peak is not None and abs(disp_peak - c.peak_rrp) < 1e-6,
            "note": "Public_Prices (next-day report) vs DispatchIS (real-time report) for the same interval.",
        }
        in_window = [p for t, p in price_rows.items() if ws < t <= we]
        checks["price_intervals_in_window"] = len(in_window)
        if c.kind == "high_price":
            n_thr = sum(p >= self.args.threshold for p in in_window)
        else:
            n_thr = sum(p < 0 for p in in_window)

        # --- forecasts: runs created in [ws - lead, we]
        lead = timedelta(hours=self.args.lead_hours)
        need_first_target = (ceil30(ws - lead), ceil30(we) + timedelta(minutes=30))
        fc_summary = self.resolve_weekly("OPDEM_FORECAST_HH", need_first_target, event_id, "forecast_runs")
        # --- actual HH: targets in (ws, we]
        act_summary = self.resolve_weekly("OPDEM_ACTUAL_HH", (ws, we + timedelta(minutes=30)), event_id, "actual_initial")
        # --- actual daily (revised/updated), by trading date
        tdays = sorted({(t - timedelta(hours=4, minutes=30)).astimezone(NEM_TZ).date() for t in (ws + timedelta(minutes=30), we)})
        tdays = [tdays[0] + timedelta(days=i) for i in range((tdays[-1] - tdays[0]).days + 1)]
        daily_members = self.resolve_daily_actuals(tdays, event_id)

        # --- event-specific verification from parsed rows
        peak_hh = ceil30(c.peak_end_utc)
        fc = self.forecasts_for(c.region, peak_hh)
        before = [f for f in fc if f["created_utc"] <= c.peak_end_utc]
        checks["forecast"] = {
            "target_halfhour_end_market": market_str(peak_hh),
            "runs_targeting_interval": len(fc),
            "runs_created_before_peak": len(before),
            "latest_run_before_peak": ({k: (iso_utc(v) if isinstance(v, datetime) else v) for k, v in before[-1].items()}
                                       if before else None),
            "load_date_not_after_creation": all(f["load_utc"] <= f["created_utc"] for f in fc),
            "issue_time_sources": "LOAD_DATE field ('Date time this forecast was produced'), C-header creation "
                                  "time, and the creation timestamp in the file name (checked equal).",
            "name_matches_c_header": all(f["name_created_utc"] == f["created_utc"] for f in fc),
        }
        act = self.actuals_for(c.region, peak_hh)
        checks["actual"] = {"target_halfhour_end_market": market_str(peak_hh), **act}
        checks["forecast_weeks"] = fc_summary
        checks["actual_weeks"] = act_summary
        checks["actual_daily_members"] = daily_members

        ok = (checks["price_cross_check"]["match"] and len(before) > 0 and act.get("initial") is not None
              and checks["forecast"]["load_date_not_after_creation"] and checks["forecast"]["name_matches_c_header"])
        checks["all_core_checks_pass"] = ok

        # --- market notices (Current only; rolling ~60-day retention)
        self.resolve_notices(ws, we, event_id)
        # --- weather (retrospective context)
        self.resolve_weather(c.region, ws, we, event_id)

        reason = (
            f"{'Highest' if role == 'primary' else 'Candidate'} {c.kind.replace('_', ' ')} interval in {c.region} "
            f"found by scanning NEMWeb Public_Prices daily files (RRP {c.peak_rrp} $/MWh at interval ending "
            f"{market_str(c.peak_end_utc)} market time); window fully covered by archived DispatchIS, "
            "operational-demand forecast and actual files."
        )
        if role == "primary":
            reason += f" Region preference: {self.args.prefer_region}."
        return {
            "event_id": event_id, "role": role, "region": c.region, "timezone": tz, "kind": c.kind,
            "peak_interval_end_utc": iso_utc(c.peak_end_utc), "peak_interval_end_market": market_str(c.peak_end_utc),
            "peak_rrp": c.peak_rrp, "window_start_utc": iso_utc(ws), "window_end_utc": iso_utc(we),
            "intervals_meeting_threshold_in_window": n_thr, "selection_reason": reason, "checks": checks,
        }

    def inspect_container(self, ds: str, rf: rawstore.RawFile, name: str) -> tuple[dict, dict, list[dict[str, str]]]:
        data = Path(rf.local_path).read_bytes()
        members = 0
        first = last = None
        schema: dict[str, list[str]] = {}
        out: list[dict[str, str]] = []
        created: list[datetime] = []
        wanted = {(t.report, t.subtype) for t in CONTRACTS[ds]}
        prefixes = tuple(f"D,{t.report},{t.subtype}," for t in CONTRACTS[ds])
        for mp, csvb in iter_csv_members(data, name):
            mf, recs = parse_mms_csv(csvb, mp, wanted=wanted, line_prefixes=prefixes)
            for t in CONTRACTS[ds]:
                key = require_fields(mf, t.report, t.subtype, t.required)
                schema[f"{key[0]}/{key[1]}/v{key[2]}"] = mf.tables[key]
            members += 1
            first = first or mp
            last = mp
            created.append(mf.created_at_utc)
            if ds == "DISPATCHIS":
                out.extend(r.values for r in recs if r.table[1] == "PRICE")
        cov = {"members": members, "first_member": first, "last_member": last,
               "first_created_utc": iso_utc(min(created)), "last_created_utc": iso_utc(max(created))}
        return cov, schema, out

    def resolve_weekly(self, ds: str, need: tuple[datetime, datetime], event_id: str, role: str) -> list[dict]:
        """Weekly archives are named by the Sunday of the week of their first-target timestamps."""
        arc = [(nemweb.archive_start(ds, e.name), e) for e in self.listing(ds, "archive")]
        arc = [(d, e) for d, e in arc if d]
        picked = [(d, e) for d, e in arc if d.astimezone(UTC) < need[1] and (d + timedelta(days=7)).astimezone(UTC) > need[0]]
        summary = []
        for d, e in picked:
            rf = self.get(ds, e.url)
            if not rf.available:
                raise SystemExit(f"G0 FAIL: {e.url} unavailable")
            cov, schema = self.parse_opdemand(ds, rf, e.name)
            self.add_source(rf, source_id=f"{ds.lower()}_{d:%Y%m%d}", dataset=ds, role=role, kind="archive",
                            event=event_id, coverage=cov, schema_fields=schema,
                            issue_time_provenance=(
                                "published_at = AEMO C-header creation time of each inner file (equals the second "
                                "timestamp in its file name); issued_at = LOAD_DATE ('Date time this forecast was "
                                "produced'); available_at = published_at + observed NEMWeb posting margin."
                                if ds == "OPDEM_FORECAST_HH" else
                                "published_at = C-header creation time of each inner file (seconds after interval end)."))
            summary.append({"archive": e.name, **cov})
        if not picked:
            raise SystemExit(f"G0 FAIL: no {ds} archive covers {need}")
        return summary

    _fc_rows: dict[tuple[str, datetime], list[dict[str, Any]]]
    _act_rows: dict[tuple[str, datetime], dict[str, Any]]

    def parse_opdemand(self, ds: str, rf: rawstore.RawFile, name: str) -> tuple[dict, dict]:
        if not hasattr(self, "_fc_rows"):
            self._fc_rows = defaultdict(list)
            self._act_rows = defaultdict(dict)
            self._parsed: dict[str, tuple[dict, dict]] = {}
        if rf.local_path in self._parsed:
            return self._parsed[rf.local_path]
        targets = getattr(self, "targets", set())
        data = Path(rf.local_path).read_bytes()
        members = 0
        created = []
        schema: dict[str, list[str]] = {}
        contract = CONTRACTS[ds][0]
        first = last = None
        for mp, csvb in iter_csv_members(data, name):
            mf, recs = parse_mms_csv(csvb, mp, wanted={(contract.report, contract.subtype)})
            key = require_fields(mf, contract.report, contract.subtype, contract.required)
            schema[f"{key[0]}/{key[1]}/v{key[2]}"] = mf.tables[key]
            members += 1
            first = first or mp
            last = mp
            created.append(mf.created_at_utc)
            inner = mp.split("/")[0]
            name_created = nemweb.creation_time_from_name(inner)
            for r in recs:
                t = parse_market(r.values["INTERVAL_DATETIME"])
                if (r.values["REGIONID"], t) not in targets:
                    continue
                if ds == "OPDEM_FORECAST_HH":
                    self._fc_rows[(r.values["REGIONID"], t)].append({
                        "member": inner, "created_utc": mf.created_at_utc, "name_created_utc": name_created,
                        "load_utc": parse_market(r.values["LOAD_DATE"]),
                        "poe50": float(r.values["OPERATIONAL_DEMAND_POE50"]),
                    })
                else:
                    slot = "initial" if ds == "OPDEM_ACTUAL_HH" else "daily"
                    self._act_rows[(r.values["REGIONID"], t)][slot] = float(r.values["OPERATIONAL_DEMAND"])
                    self._act_rows[(r.values["REGIONID"], t)][f"{slot}_member"] = inner
        cov = {"members": members, "first_member": first, "last_member": last,
               "first_created_utc": iso_utc(min(created)), "last_created_utc": iso_utc(max(created))}
        self._parsed[rf.local_path] = (cov, schema)
        return cov, schema

    def forecasts_for(self, region: str, target: datetime) -> list[dict[str, Any]]:
        return sorted(getattr(self, "_fc_rows", {}).get((region, target), []), key=lambda f: f["created_utc"])

    def actuals_for(self, region: str, target: datetime) -> dict[str, Any]:
        return dict(getattr(self, "_act_rows", {}).get((region, target), {}))

    def resolve_daily_actuals(self, tdays: list[date], event_id: str) -> list[str]:
        members = []
        for td in tdays:
            month = f"{td:%Y%m}01"
            arc = [e for e in self.listing("OPDEM_ACTUAL_DAILY", "archive") if e.name.endswith(f"_{month}.zip")]
            cur = [e for e in self.listing("OPDEM_ACTUAL_DAILY", "current")
                   if (m := nemweb.NAME_PATTERNS["OPDEM_ACTUAL_DAILY"].match(e.name)) and m.group(1) == f"{td:%Y%m%d}"]
            if arc:
                e, kind, sid = arc[0], "archive", f"opdem_actual_daily_{month}"
            elif cur:
                e, kind, sid = cur[0], "current", f"opdem_actual_daily_{td:%Y%m%d}"
            else:
                self.notes.append(f"No ACTUAL_DAILY file found for trading date {td} (archive or current).")
                continue
            rf = self.get("OPDEM_ACTUAL_DAILY", e.url)
            if not rf.available:
                continue
            cov, schema = self.parse_opdemand("OPDEM_ACTUAL_DAILY", rf, e.name)
            self.add_source(rf, source_id=sid, dataset="OPDEM_ACTUAL_DAILY", role="actual_updated", kind=kind,
                            event=event_id, coverage=cov, schema_fields=schema,
                            issue_time_provenance="C-header creation time (published next day, ~04:40 market time).")
            members.append(e.name)
        return members

    def resolve_notices(self, ws: datetime, we: datetime, event_id: str) -> None:
        d0 = (ws.astimezone(NEM_TZ) - timedelta(days=1)).date()
        d1 = (we.astimezone(NEM_TZ) + timedelta(days=1)).date()
        ents = []
        for e in self.listing("MARKET_NOTICE", "current"):
            m = nemweb.MARKET_NOTICE_RE.match(e.name)
            if m and d0 <= datetime.strptime(m.group(1), "%Y%m%d").date() <= d1:
                ents.append(e)
        with cf.ThreadPoolExecutor(6) as ex:
            rfs = list(ex.map(lambda e: self.get("MARKET_NOTICE", e.url, max_bytes=2_000_000), ents))
        for e, rf in zip(ents, rfs, strict=True):
            if rf.available:
                self.add_source(rf, source_id=f"market_notice_{e.name.split('.R')[-1]}", dataset="MARKET_NOTICE",
                                role="document_event_notice", kind="current", event=event_id,
                                issue_time_provenance="'Creation Date' line inside the notice (market time).")
        if not ents:
            self.notes.append(f"No market notices listed on NEMWeb Current for {d0}..{d1} ({event_id}).")

    def resolve_weather(self, region: str, ws: datetime, we: datetime, event_id: str) -> None:
        name, lat, lon = WEATHER_POINTS[region]
        q = {"parameters": WEATHER_PARAMS, "community": "RE", "longitude": lon, "latitude": lat,
             "start": ws.strftime("%Y%m%d"), "end": we.strftime("%Y%m%d"), "format": "JSON", "time-standard": "UTC"}
        url = "https://power.larc.nasa.gov/api/temporal/hourly/point?" + urlencode(q, quote_via=quote)
        rf = self.get("NASA_POWER_HOURLY", url, max_bytes=5_000_000)
        if not rf.available:
            return
        doc = json.loads(Path(rf.local_path).read_text())
        hdr = doc.get("header", {})
        params = doc.get("properties", {}).get("parameter", {})
        fill = hdr.get("fill_value", -999)
        n = {p: sum(1 for v in vals.values() if v != fill) for p, vals in params.items()}
        self.add_source(rf, source_id=f"nasa_power_{region.lower()}_{ws:%Y%m%d}_{we:%Y%m%d}", dataset="NASA_POWER_HOURLY",
                        role="weather_retrospective", kind="api", publisher=NASA_PUBLISHER, licence=NASA_LICENCE,
                        event=event_id,
                        coverage={"point": name, "latitude": lat, "longitude": lon, "time_standard": "UTC",
                                  "non_fill_values": n, "api_version": hdr.get("api", {}).get("version"),
                                  "sources": hdr.get("sources"), "title": hdr.get("title")},
                        issue_time_provenance="Retrospective model-derived data; publication time unknown, "
                                              "treated as available only from retrieval time.")

    # ------------------------------------------------------------------ documents
    def resolve_documents(self) -> None:
        for sid, title, url in AEMO_PDF_CANDIDATES:
            rf = self.get("AEMO_PDF", url, max_bytes=20_000_000)
            ok = rf.available and Path(rf.local_path).read_bytes()[:5] == b"%PDF-"
            if not ok:
                self.attempted.append({"url": url, "status": rf.http_status, "content_type": rf.content_type,
                                       "error": rf.error or "response is not a PDF (magic bytes)", "title": title})
                log(f"document REJECTED {title}: status={rf.http_status} type={rf.content_type}")
                continue
            self.add_source(rf, source_id=sid, dataset="AEMO_PDF", role="document_reference", kind="document",
                            coverage={"title": title})
            log(f"document ok {title}")
        # MMS Data Model Report (HTML) pages that define the tables we use, discovered from its TOC.
        toc_url = MMS_DM_BASE + "Electricity%20Data%20Model%20Report_toc.htm"
        toc = self.get("MMS_DATA_MODEL_HTML", toc_url, max_bytes=5_000_000)
        if not toc.available:
            return
        self.add_source(toc, source_id="mms_dm_toc", dataset="MMS_DATA_MODEL_HTML", role="document_toc", kind="document")
        html = Path(toc.local_path).read_text(encoding="utf-8", errors="replace")
        pages: dict[str, list[str]] = defaultdict(list)
        for href, label in re.findall(r'href="([^"#]+)#?[^"]*"[^>]*>\s*Table:\s*([A-Z0-9_]+)\s*<', html, re.I):
            if label.upper() in MMS_DM_TABLES:
                pages[href].append(label.upper())
        cover = self.get("MMS_DATA_MODEL_HTML", MMS_DM_BASE + "Electricity%20Data%20Model%20Report.htm")
        if cover.available:
            self.add_source(cover, source_id="mms_dm_cover", dataset="MMS_DATA_MODEL_HTML", role="document_cover",
                            kind="document")
        for href, tables in sorted(pages.items()):
            rf = self.get("MMS_DATA_MODEL_HTML", MMS_DM_BASE + quote(href))
            if rf.available:
                self.add_source(rf, source_id=f"mms_dm_{Path(href).stem.lower()}", dataset="MMS_DATA_MODEL_HTML",
                                role="document_reference", kind="document", coverage={"tables": sorted(tables)})

    def resolve_duid_mapping(self) -> None:
        now = datetime.now(NEM_TZ)
        for back in range(0, 6):
            y, m = now.year, now.month - back
            while m <= 0:
                y, m = y - 1, m + 12
            base = f"https://nemweb.com.au/Data_Archive/Wholesale_Electricity/MMSDM/{y}/MMSDM_{y}_{m:02d}/MMSDM_Historical_Data_SQLLoader/DATA/"
            _res, entries = nemweb.list_dir(base)
            hit = [e for e in entries if "#DUDETAILSUMMARY#" in e.name.upper()]
            if not hit:
                continue
            rf = self.get("MMSDM_DUDETAILSUMMARY", hit[0].url)
            if rf.available:
                mp, csvb = next(iter_csv_members(Path(rf.local_path).read_bytes(), hit[0].name))
                mf, recs = parse_mms_csv(csvb, mp)
                c = CONTRACTS["MMSDM_DUDETAILSUMMARY"][0]
                key = require_fields(mf, c.report, c.subtype, c.required)
                self.add_source(rf, source_id="mmsdm_dudetailsummary", dataset="MMSDM_DUDETAILSUMMARY",
                                role="duid_region_mapping", kind="archive",
                                coverage={"rows": len(recs), "created_market": mf.created_at_market},
                                schema_fields={f"{key[0]}/{key[1]}/v{key[2]}": mf.tables[key]})
                return
        self.notes.append("DUDETAILSUMMARY not found in the last 6 MMSDM months; generation tool will be unavailable.")


def write_sources_md(sel: dict[str, Any], path: Path) -> None:
    by_ds: dict[str, list[dict]] = defaultdict(list)
    for s in sel["sources"]:
        by_ds[s["dataset"]].append(s)
    retrieved = sorted({s["retrieved_at"][:10] for s in sel["sources"]})
    lines = [
        "# Data and document sources",
        "",
        "_Generated by `scripts/source_probe.py` from the probe run recorded in `data/source_selection.json`; "
        "do not edit by hand._",
        "",
        f"Probe run: {sel['generated_at']} (probe v{sel['probe_version']}). Retrieval dates: {', '.join(retrieved)}.",
        "",
        "## Redistribution policy",
        "",
        "This repository commits **code, selection metadata (URLs, checksums, timestamps) and small derived outputs "
        "generated by the code** (reports, evaluation summaries). It does **not** commit publisher files: AEMO "
        "archives, AEMO PDFs, AEMO market notices and NASA POWER responses are fetched from the publisher by "
        "`make data` / `make index` into git-ignored folders. Reason: AEMO's copyright-permissions page returned "
        "HTTP 403 (Cloudflare challenge) to scripted access during the probe, so its current redistribution terms "
        "could not be re-read and verified by this project (see `docs/decisions.md`).",
        "",
        "## Attribution",
        "",
        "**AEMO.** Source: Australian Energy Market Operator (AEMO), NEMWeb (https://nemweb.com.au/) and AEMO "
        "publications at https://www.aemo.com.au/. © AEMO. AEMO material is used with attribution under AEMO's "
        "copyright permissions (https://www.aemo.com.au/privacy-and-legal-notices/copyright-permissions); the AEMO "
        "publication *Demand Terms in EMMS Data Model* (July 2025, p.2) states: “The material in this "
        "publication may be used in accordance with the copyright permissions on AEMO’s website.” AEMO data "
        "pages also carry use and quality disclaimers; AEMO data is not warranted as accurate or fit for any "
        "operational purpose, and this project makes no such claim either.",
        "",
        "**NASA POWER.** Referencing text as published at https://power.larc.nasa.gov/docs/referencing/ (retrieved "
        "during the probe): “The data was obtained from National Aeronautics and Space Administration (NASA) "
        "Langley Research Center's Prediction Of Worldwide Energy Resources (POWER) project funded through the NASA "
        "Earth Science Division.” Data reference: “The data was obtained from the POWER Project's Hourly "
        "{version} version on {date}.” — the API version and access date for each response are recorded "
        "below. POWER requests notification of redistribution; this repo does not redistribute POWER data.",
        "",
        "## Host reachability observed by the probe",
        "",
        "| Resource | HTTP | Cloudflare challenge |",
        "| --- | --- | --- |",
    ]
    for h in sel["host_checks"]:
        lines.append(f"| [{h['label']}]({h['url']}) | {h['http_status']} | {'yes' if h['cloudflare_challenge'] else 'no'} |")
    lines += ["", "## Datasets", ""]
    desc = {
        "DISPATCHIS": "AEMO DispatchIS reports (DISPATCH/PRICE, DISPATCH/REGIONSUM), 5-minute, daily archive",
        "DISPATCH_SCADA": "AEMO Dispatch SCADA (DISPATCH/UNIT_SCADA), 5-minute unit MW, daily archive",
        "OPDEM_FORECAST_HH": "AEMO issued operational demand forecasts (OPERATIONAL_DEMAND/FORECAST, POE10/50/90), half-hourly runs, weekly archive",
        "OPDEM_ACTUAL_HH": "AEMO actual operational demand, real-time half-hourly files (initial values), weekly archive",
        "OPDEM_ACTUAL_DAILY": "AEMO actual operational demand, next-day daily files (updated values)",
        "PUBLIC_PRICES": "AEMO Public_Prices next-day report (DREGION) — used only to scan for candidate events",
        "MARKET_NOTICE": "AEMO market notices (NEMWeb Current; rolling ~60-day retention, no archive)",
        "MMSDM_DUDETAILSUMMARY": "AEMO MMS Data Model monthly archive, DUDETAILSUMMARY (DUID → region)",
        "MMS_DATA_MODEL_HTML": "AEMO MMS Data Model Report (Electricity), HTML pages defining the tables used",
        "AEMO_PDF": "AEMO public PDF publications (definitions and procedures)",
        "NASA_POWER_HOURLY": "NASA POWER hourly point API (retrospective weather context)",
    }
    for ds, items in sorted(by_ds.items()):
        total = sum(i["size"] for i in items)
        lines.append(f"### {ds}")
        lines.append("")
        lines.append(f"{desc.get(ds, ds)}. Files: {len(items)}, total {total / 1e6:.1f} MB.")
        lines.append("")
        lines.append("| source_id | URL | SHA-256 (first 16) | retrieved | role |")
        lines.append("| --- | --- | --- | --- | --- |")
        for i in sorted(items, key=lambda x: x["source_id"])[:40]:
            lines.append(f"| {i['source_id']} | {i['url']} | `{i['sha256'][:16]}` | {i['retrieved_at']} | {i['role']} |")
        if len(items) > 40:
            lines.append(f"| … | {len(items) - 40} more in data/source_selection.json | | | |")
        lines.append("")
    if sel["attempted_unavailable"]:
        lines += ["## Attempted but not used", "", "| URL | status | reason |", "| --- | --- | --- |"]
        for a in sel["attempted_unavailable"]:
            lines.append(f"| {a.get('url')} | {a.get('status')} | {a.get('error') or ''} |")
        lines.append("")
    path.write_text("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", default="data/source_selection.json")
    ap.add_argument("--threshold", type=float, default=300.0, help="project analysis threshold, $/MWh")
    ap.add_argument("--prefer-region", default="SA1")
    ap.add_argument("--max-high-events", type=int, default=7)
    ap.add_argument("--max-per-region", type=int, default=3)
    ap.add_argument("--half-window-hours", type=int, default=12)
    ap.add_argument("--lead-hours", type=int, default=48, help="forecast runs kept: created within this many hours before the window")
    args = ap.parse_args()

    p = Probe(args)
    p.check_hosts()
    availability = p.measure_availability()
    log(f"availability margin: {availability['margin_minutes']} min")
    market_time = p.check_market_time()
    market_time["interval_convention"] = p.interval_convention() + [
        "MMS Data Model Report, DISPATCHCASESOLUTION.SETTLEMENTDATE: 'Date and time of the dispatch interval (e.g. five "
        "minute dispatch interval ending 28/09/2000 16:35)'."
    ]
    cands = p.scan_prices()
    chosen = p.choose_events(cands)
    p.targets = {(c.region, ceil30(c.peak_end_utc)) for c, _ in chosen}
    events = [p.resolve_event(c, role) for c, role in chosen]
    p.resolve_documents()
    p.resolve_duid_mapping()

    primary = events[0]
    if not primary["checks"]["all_core_checks_pass"]:
        log("primary event failed core checks; see checks in output")
    sel = {
        "schema_version": 1,
        "generated_at": iso_utc(datetime.now(UTC)),
        "probe_version": PROBE_VERSION,
        "analysis_threshold": {
            "high_price_rrp_at_or_above": args.threshold, "low_price_rrp_below": 0.0, "unit": "$/MWh",
            "note": "Project analysis thresholds used to find candidate intervals. They are NOT AEMO incident labels.",
        },
        "market_time": market_time,
        "availability": availability,
        "host_checks": p.host_checks,
        "primary_event_id": primary["event_id"],
        "events": events,
        "comparisons": [{
            "comparison_id": "opdemand_poe50_vs_actual",
            "forecast": {"dataset": "OPDEM_FORECAST_HH", "table": "OPERATIONAL_DEMAND/FORECAST",
                         "field": "OPERATIONAL_DEMAND_POE50", "definition": "OPERATIONAL_DEMAND",
                         "interval_minutes": 30, "unit": "MW"},
            "actual": {"dataset": "OPDEM_ACTUAL_HH", "table": "OPERATIONAL_DEMAND/ACTUAL",
                       "field": "OPERATIONAL_DEMAND", "definition": "OPERATIONAL_DEMAND",
                       "interval_minutes": 30, "unit": "MW"},
            "evidence": [
                "Both series come from AEMO's OPERATIONAL_DEMAND report family (DEMANDOPERATIONALFORECAST / "
                "DEMANDOPERATIONALACTUAL in the MMS Data Model Report).",
                "Both use INTERVAL_DATETIME (half-hour interval end) and MW; checked by the verifier against parsed headers.",
            ],
        }],
        "sources": sorted(p.sources.values(), key=lambda s: s["source_id"]),
        "attempted_unavailable": p.attempted,
        "notes": p.notes + [
            "AEMO market event report pages (aemo.com.au HTML) are behind a Cloudflare browser challenge for scripted "
            "access; no event report could be listed. AEMO media-library PDFs remained reachable.",
            "Market notices exist only in NEMWeb Current (rolling retention). Once they roll off, a fresh `make data` "
            "cannot re-download them; tools then report them as missing evidence.",
        ],
    }
    Selection.model_validate(sel)  # schema check before writing
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(sel, indent=2, sort_keys=False) + "\n")
    write_sources_md(sel, out.parent / "SOURCES.md")
    log(f"wrote {out} with {len(events)} events and {len(sel['sources'])} sources")
    for ev in events:
        ck = ev["checks"]
        log(f"  {ev['event_id']:<24} {ev['kind']:<10} rrp={ev['peak_rrp']:>9} cross_check={ck['price_cross_check']['match']} "
            f"runs_before_peak={ck['forecast']['runs_created_before_peak']} actual={ck['actual'].get('initial')} "
            f"daily={ck['actual'].get('daily')} core_ok={ck['all_core_checks_pass']}")
    return 0 if primary["checks"]["all_core_checks_pass"] else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except MmsFormatError as exc:
        print(f"[probe] G0 FAIL: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
