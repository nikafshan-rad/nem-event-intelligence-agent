"""SYNTHETIC test builders in AEMO MMS CSV format. Output is never real market data."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path


def mms_csv(report: str, subtype: str, version: str, fields: list[str], rows: list[list[str]],
            created: str = "2099/01/01,00:00:00", declared_lines: int | None = None, trailer: bool = True) -> bytes:
    """Build a SYNTHETIC file in AEMO MMS CSV format (for parser tests only)."""
    lines = [f"C,SYNTHETIC.TEST,{report}_{subtype},AEMO,PUBLIC,{created},0000000001,,0000000001",
             ",".join(["I", report, subtype, version, *fields])]
    lines += [",".join(["D", report, subtype, version, *r]) for r in rows]
    n = len(lines) + 1
    if trailer:
        lines.append(f'C,"END OF REPORT",{declared_lines if declared_lines is not None else n}')
    return ("\n".join(lines) + "\n").encode()


def zip_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def plant_cache(home: Path, dataset: str, url: str, data: bytes) -> str:
    """Put SYNTHETIC bytes in the raw cache so rawstore returns a cache hit (no network)."""
    import hashlib

    from nem_agent import rawstore

    p = rawstore.local_path_for(dataset, url)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    (p.parent / (p.name + ".meta.json")).write_text(json.dumps({
        "url": url, "sha256": digest, "size": len(data), "http_status": 200, "content_type": "application/zip",
        "last_modified": None, "retrieved_at": "2099-01-01T00:00:00Z", "synthetic": True}))
    return digest


def mms_multi(report_name: str, tables: list[tuple[str, str, str, list[str], list[list[str]]]],
              created: str = "2099/01/01,00:00:00") -> bytes:
    """SYNTHETIC multi-table MMS file (e.g. a DispatchIS-shaped file with PRICE and REGIONSUM)."""
    lines = [f"C,SYNTHETIC.TEST,{report_name},AEMO,PUBLIC,{created},0000000001,,0000000001"]
    for report, subtype, version, fields, rows in tables:
        lines.append(",".join(["I", report, subtype, version, *fields]))
        lines += [",".join(["D", report, subtype, version, *r]) for r in rows]
    lines.append(f'C,"END OF REPORT",{len(lines) + 1}')
    return ("\n".join(lines) + "\n").encode()


def minimal_selection(sources: list[dict], window: tuple[str, str], region: str = "SA1") -> dict:
    """A schema-valid SYNTHETIC selection wrapping the given sources."""
    return {
        "schema_version": 1, "generated_at": "2099-01-01T00:00:00Z", "probe_version": "synthetic",
        "analysis_threshold": {}, "market_time": {}, "host_checks": [],
        "availability": {"margin_minutes": 166, "dispatch_margin_minutes_after_interval_start": 53},
        "primary_event_id": "SYNTHETIC", "comparisons": [{
            "comparison_id": "c", "evidence": [],
            "forecast": {"dataset": "OPDEM_FORECAST_HH", "table": "OPERATIONAL_DEMAND/FORECAST", "field": "OPERATIONAL_DEMAND_POE50",
                         "definition": "OPERATIONAL_DEMAND", "interval_minutes": 30, "unit": "MW"},
            "actual": {"dataset": "OPDEM_ACTUAL_HH", "table": "OPERATIONAL_DEMAND/ACTUAL", "field": "OPERATIONAL_DEMAND",
                       "definition": "OPERATIONAL_DEMAND", "interval_minutes": 30, "unit": "MW"}}],
        "events": [{"event_id": "SYNTHETIC", "role": "primary", "region": region, "timezone": "Australia/Adelaide",
                    "kind": "high_price", "peak_interval_end_utc": window[1], "peak_interval_end_market": "x",
                    "peak_rrp": 0.0, "window_start_utc": window[0], "window_end_utc": window[1],
                    "intervals_meeting_threshold_in_window": 0, "selection_reason": "SYNTHETIC", "checks": {}}],
        "sources": sources,
    }


def source_entry(source_id: str, dataset: str, url: str, sha: str, size: int) -> dict:
    return {"source_id": source_id, "dataset": dataset, "role": "synthetic", "url": url, "container_kind": "archive",
            "publisher": "SYNTHETIC", "http_status": 200, "size": size, "sha256": sha,
            "retrieved_at": "2099-01-01T00:00:00Z", "events": ["SYNTHETIC"]}
