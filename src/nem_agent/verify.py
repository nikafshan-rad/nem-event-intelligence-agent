"""Independent verification of ``data/source_selection.json`` (Gate G0).

Checks, each producing an explicit pass/fail line:

1. the file validates against the typed schema (missing URL / bad checksum / non-allowlisted host => fail);
2. every source URL answers HTTP 200 now (HEAD, or GET for the NASA API) with a plausible content type;
3. the bytes cached by the probe (or re-downloaded) hash to the recorded SHA-256;
4. every AEMO data file parses under the MMS integrity rules and carries the contract fields;
5. every forecast/actual comparison pairs the same metric definition, interval length and unit;
6. the primary event passed its core cross-checks and the market-time evidence was confirmed.
"""

from __future__ import annotations

import concurrent.futures as cf
import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from . import rawstore
from .aemo_schema import CONTRACTS, METRIC_DEFINITIONS
from .http import fetch
from .mmscsv import MmsFormatError, iter_csv_members, parse_mms_csv, require_fields
from .selection import Selection

DATA_DATASETS = {"DISPATCHIS", "DISPATCH_SCADA", "OPDEM_FORECAST_HH", "OPDEM_ACTUAL_HH", "OPDEM_ACTUAL_DAILY",
                 "PUBLIC_PRICES", "MMSDM_DUDETAILSUMMARY"}


@dataclass
class Report:
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "n_passed": len(self.passed), "n_failed": len(self.failed),
                "failed": self.failed, "warnings": self.warnings, "passed_sample": self.passed[:25]}


def check_comparisons(sel: Selection, rep: Report) -> None:
    observed: dict[str, set[str]] = {}
    for s in sel.sources:
        for table, fields in (s.schema_fields or {}).items():
            observed.setdefault(s.dataset, set()).update(f"{table.rsplit('/v', 1)[0]}:{f}" for f in fields)
    for c in sel.comparisons:
        f, a = c.forecast, c.actual
        problems = []
        if f.definition != a.definition:
            problems.append(f"definition mismatch {f.definition!r} vs {a.definition!r}")
        if f.interval_minutes != a.interval_minutes:
            problems.append(f"interval mismatch {f.interval_minutes} vs {a.interval_minutes} min")
        if f.unit != a.unit:
            problems.append(f"unit mismatch {f.unit!r} vs {a.unit!r}")
        for side in (f, a):
            d = METRIC_DEFINITIONS.get(side.definition)
            if d is None:
                problems.append(f"unknown metric definition {side.definition!r}")
                continue
            if d["interval_minutes"] != side.interval_minutes or d["unit"] != side.unit:
                problems.append(f"{side.dataset}.{side.field}: declared {side.interval_minutes} min/{side.unit} but "
                                f"{side.definition} is {d['interval_minutes']} min/{d['unit']}")
            if f"{side.table}:{side.field}" not in observed.get(side.dataset, set()):
                problems.append(f"{side.dataset}: field {side.table}:{side.field} not observed in parsed headers")
        if problems:
            rep.failed.append(f"comparison {c.comparison_id}: " + "; ".join(problems))
        else:
            rep.passed.append(f"comparison {c.comparison_id}: same definition/interval/unit ({f.definition}, "
                              f"{f.interval_minutes} min, {f.unit})")


def _liveness(url: str, dataset: str) -> tuple[int | None, str | None, str | None]:
    """HEAD (GET for the NASA API). NEMWeb's firewall answers 403 to bursts of parallel requests, so 403/429
    are retried with backoff; a 403 that persists after the retries is a failure."""
    method = "GET" if dataset == "NASA_POWER_HOURLY" else "HEAD"
    res = fetch(url, method=method, timeout=45, retries=5, backoff_s=3.0, max_bytes=8_000_000)
    return res.status, res.content_type, res.error


def _rolled_off(s: Any, status: int | None) -> bool:
    return s.container_kind == "current" and status == 404 and "/reports/current/" in s.url.lower()


def check_liveness(sel: Selection, rep: Report, allow_cached: bool, workers: int = 4,
                   allow_rolled_off: bool = False) -> None:
    with cf.ThreadPoolExecutor(workers) as ex:
        results = list(ex.map(lambda s: (s, _liveness(s.url, s.dataset)), sel.sources))
    for s, (status, ctype, err) in results:
        ctype = (ctype or "").lower()
        good_type = (
            ("pdf" in ctype) if s.dataset == "AEMO_PDF"
            else ("json" in ctype) if s.dataset == "NASA_POWER_HOURLY"
            else ("html" in ctype) if s.dataset == "MMS_DATA_MODEL_HTML"
            else True
        )
        if status == 200 and good_type:
            rep.passed.append(f"live {s.source_id}: HTTP 200 {ctype}")
        elif allow_rolled_off and _rolled_off(s, status):
            rep.warnings.append(f"{s.source_id}: rolled off NEMWeb Current (HTTP 404); expected after rolling retention "
                                "(docs/data-retention.md)")
        elif allow_cached and Path(rawstore.local_path_for(s.dataset, s.url)).exists():
            rep.warnings.append(f"{s.source_id}: URL now answers {status} ({err}); relying on verified cached copy "
                                f"retrieved {s.retrieved_at}")
        else:
            rep.failed.append(f"live {s.source_id}: {s.url} -> HTTP {status} {ctype} {err or ''}".strip())


def check_bytes_and_schema(sel: Selection, rep: Report, datasets: set[str] | None = None,
                           offline: bool = False, allow_rolled_off: bool = False) -> None:
    """``offline=True`` hashes the local cached copy only (no download), so a mismatch is reported as such."""
    for s in sel.sources:
        if datasets and s.dataset not in datasets:
            continue
        if offline:
            local = rawstore.local_path_for(s.dataset, s.url)
            if not local.exists():
                rep.failed.append(f"sha256 {s.source_id}: no local copy (offline check)")
                continue
            actual = rawstore.sha256_file(local)
            if actual != s.sha256:
                rep.failed.append(f"sha256 {s.source_id}: local bytes hash {actual[:16]} != recorded {s.sha256[:16]}")
                continue
            local_path = str(local)
        else:
            rf = rawstore.get(s.dataset, s.url, expected_sha256=s.sha256, expected_content_sha256=s.content_sha256)
            if rf.rolled_off:
                from .recover import recover_from_archive

                rf = recover_from_archive(s.dataset, s.url, s.sha256, log=lambda *_: None) or rf
            if not rf.available and allow_rolled_off and rf.rolled_off:
                rep.warnings.append(f"sha256 {s.source_id}: rolled off NEMWeb Current and not (yet) in an Archive bundle")
                continue
            if not rf.available:
                rep.failed.append(f"sha256 {s.source_id}: cannot obtain bytes matching {s.sha256[:16]} ({rf.error})")
                continue
            local_path = rf.local_path
        rep.passed.append(f"sha256 {s.source_id}: {s.sha256[:16]}")
        data = Path(local_path).read_bytes()
        if s.dataset == "AEMO_PDF" and data[:5] != b"%PDF-":
            rep.failed.append(f"format {s.source_id}: not a PDF")
        if s.dataset not in DATA_DATASETS:
            continue
        try:
            n = 0
            for mp, csvb in iter_csv_members(data, Path(local_path).name):
                mf, _ = parse_mms_csv(csvb, mp, line_prefixes=())  # integrity + headers; skip bodies
                for c in CONTRACTS[s.dataset]:
                    require_fields(mf, c.report, c.subtype, c.required)
                n += 1
            if n == 0:
                raise MmsFormatError("container has no CSV members")
            rep.passed.append(f"schema {s.source_id}: {n} member file(s) pass integrity + contract fields")
        except MmsFormatError as exc:
            rep.failed.append(f"schema {s.source_id}: {exc}")


def check_events(sel: Selection, rep: Report) -> None:
    if not sel.market_time.get("confirmed_by_probe"):
        rep.failed.append("market_time: probe did not confirm the fixed UTC+10 clock")
    else:
        rep.passed.append("market_time: fixed UTC+10 confirmed by Last-Modified and DST-boundary evidence")
    ids = {s.source_id for s in sel.sources}
    for ev in sel.events:
        linked = [s for s in sel.sources if ev.event_id in s.events]
        needed = {"DISPATCHIS", "OPDEM_FORECAST_HH", "OPDEM_ACTUAL_HH"}
        have = {s.dataset for s in linked}
        if not needed <= have:
            rep.failed.append(f"event {ev.event_id}: missing core datasets {sorted(needed - have)}")
            continue
        ck = ev.checks
        if not ck.get("all_core_checks_pass"):
            (rep.failed if ev.role == "primary" else rep.warnings).append(f"event {ev.event_id}: core checks failed {ck}")
            continue
        rep.passed.append(
            f"event {ev.event_id}: price cross-check {ck['price_cross_check']['dispatchis_rrp']} $/MWh, "
            f"{ck['forecast']['runs_created_before_peak']} forecast runs before peak, actual {ck['actual'].get('initial')} MW"
        )
    if sel.primary_event_id not in {e.event_id for e in sel.events}:
        rep.failed.append("primary_event_id does not match any event")
    if not ids:
        rep.failed.append("no sources")


def verify(sel_json: dict[str, Any], *, live: bool = True, allow_cached: bool = False,
           deep: bool = True, allow_rolled_off: bool = False) -> Report:
    rep = Report()
    try:
        sel = Selection.model_validate(sel_json)
        rep.passed.append(f"schema: selection validates ({len(sel.sources)} sources, {len(sel.events)} events)")
    except ValidationError as exc:
        rep.failed.append(f"schema: {exc.error_count()} validation error(s): " +
                          "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:5]))
        return rep
    check_comparisons(sel, rep)
    check_events(sel, rep)
    if live:
        check_liveness(sel, rep, allow_cached, allow_rolled_off=allow_rolled_off)
    if deep:
        check_bytes_and_schema(sel, rep, allow_rolled_off=allow_rolled_off)
    return rep


def self_test(sel_json: dict[str, Any]) -> list[tuple[str, bool, str]]:
    """Mutate the selection and confirm the verifier rejects each mutation (returns name, rejected, reason)."""
    out: list[tuple[str, bool, str]] = []
    base_src = next(s for s in sel_json["sources"] if s["dataset"] == "OPDEM_FORECAST_HH")

    m1 = copy.deepcopy(sel_json)
    bad = copy.deepcopy(base_src)
    bad["source_id"] = "invented_archive"
    bad["url"] = base_src["url"].rsplit("/", 1)[0] + "/PUBLIC_FORECAST_OPERATIONAL_DEMAND_HH_20190101.zip"
    m1["sources"] = [bad]
    r1 = Report()
    check_liveness(Selection.model_validate(m1), r1, allow_cached=False)
    out.append(("invented URL", not r1.ok, "; ".join(r1.failed)[:300]))

    m2 = copy.deepcopy(sel_json)
    m2["sources"][0]["url"] = ""
    r2 = verify(m2, live=False, deep=False)
    out.append(("missing URL", not r2.ok, "; ".join(r2.failed)[:300]))

    m3 = copy.deepcopy(sel_json)
    m3["sources"][0]["url"] = "https://example.com/fake.zip"
    r3 = verify(m3, live=False, deep=False)
    out.append(("non-publisher URL", not r3.ok, "; ".join(r3.failed)[:300]))

    m4 = copy.deepcopy(sel_json)
    m4["comparisons"][0]["actual"] = {"dataset": "DISPATCHIS", "table": "DISPATCH/REGIONSUM", "field": "TOTALDEMAND",
                                      "definition": "DISPATCH_TOTALDEMAND", "interval_minutes": 5, "unit": "MW"}
    r4 = verify(m4, live=False, deep=False)
    out.append(("incompatible definition/interval (TOTALDEMAND 5-min vs operational demand 30-min)", not r4.ok,
                "; ".join(r4.failed)[:300]))

    m5 = copy.deepcopy(sel_json)
    m5["comparisons"][0]["actual"]["interval_minutes"] = 5
    r5 = verify(m5, live=False, deep=False)
    out.append(("interval relabelled to 5 min", not r5.ok, "; ".join(r5.failed)[:300]))

    m6 = copy.deepcopy(sel_json)
    m6["sources"][0]["sha256"] = ""
    r6 = verify(m6, live=False, deep=False)
    out.append(("empty checksum", not r6.ok, "; ".join(r6.failed)[:300]))

    m7 = copy.deepcopy(sel_json)
    tgt = next(s for s in m7["sources"] if s["dataset"] == "OPDEM_ACTUAL_HH")
    tgt["sha256"] = "0" * 64
    m7["sources"] = [tgt]
    r7 = Report()
    check_bytes_and_schema(Selection.model_validate({**m7, "sources": [tgt]}), r7, offline=True)
    out.append(("checksum mismatch", not r7.ok, "; ".join(r7.failed)[:300]))
    return out


def load(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())
