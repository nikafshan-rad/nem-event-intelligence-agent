"""Gold for the Live acceptance check of computed demand maxima (PROTOCOL.md, "Gold"). Offline.

It reads the pinned store's parquet files directly with duckdb, and never imports the application. For each answerable
maximum case of `cases.json` it computes, from the case's intended reading:
- **the window:** interval ends in (start, end]. A whole local day is DST-aware, from the region's IANA zone;
- **eligibility under a cutoff:** both `published_at_utc` and `available_at_utc` at or before it;
- **one value per interval:** for operational demand, the latest **eligible** revision: the greatest
  `available_at_utc`, preferring `updated` on a tie;
- **coverage, status, value, ties, source rows and runner-up,** with the excluded-row and missing-interval counts.

It also records:
- for D01–D03, agreement with the reused cases' frozen gold;
- for D03 and D04, the price facts their question also asks for (reference for the review, not a criterion).

Usage:
    python eval/livecheck_maxima/gold.py                         # write GOLD.json
    python eval/livecheck_maxima/gold.py --compare GOLD_CHECK.json  # compare with the independent check, exactly
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
STORE = REPO / "data" / "store"
UTC = ZoneInfo("UTC")
TZ = {"NSW1": "Australia/Sydney", "QLD1": "Australia/Brisbane", "SA1": "Australia/Adelaide",
      "TAS1": "Australia/Hobart", "VIC1": "Australia/Melbourne"}
MEASURES = {"total demand": ("regionsum_5min", "totaldemand_mw", 5),
            "operational demand": ("opdemand_actual", "operational_demand_mw", 30)}
READING = ("measure", "region", "window_kind", "window_utc", "event_id", "as_of_utc", "expected_outcome")
RESULT = ("status", "value", "unit", "interval_ends_utc", "source_row_ids", "intervals_in_window", "intervals_held",
          "complete", "excluded_rows_by_as_of", "intervals_without_eligible_row", "runner_up")
# the frozen gold of the reused cases (D01-D03), and which of its numbers is the maximum asked for
FROZEN = {"D01": ("eval/livecheck_i15_17/cases.json", "K09", "dispatch_totaldemand"),
          "D02": ("eval/livecheck_i15_17/cases.json", "K11", "opdemand_actual"),
          "D03": ("eval/holdout_v6/cases.json", "Z04", "dispatch_totaldemand")}


def iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def local_day(d: date, region: str) -> tuple[datetime, datetime]:
    z = ZoneInfo(TZ[region])
    return (datetime.combine(d, datetime.min.time(), z).astimezone(UTC),
            datetime.combine(d + timedelta(days=1), datetime.min.time(), z).astimezone(UTC))


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    for t in ("regionsum_5min", "opdemand_actual", "price_5min"):
        con.execute(f"CREATE VIEW {t} AS SELECT * FROM read_parquet('{(STORE / f'{t}.parquet').as_posix()}')")
    return con


def eligible(row: dict[str, Any], cutoff: datetime | None) -> bool:
    return cutoff is None or (row["published_at_utc"] <= cutoff and row["available_at_utc"] <= cutoff)


def compute(con: duckdb.DuckDBPyConnection, measure: str, region: str, window: tuple[str, str],
            cutoff_s: str | None) -> dict[str, Any]:
    """The result of one maximum over (start, end], by the rules above."""
    table, col, minutes = MEASURES[measure]
    w0, w1 = ts(window[0]), ts(window[1])
    cutoff = ts(cutoff_s) if cutoff_s else None
    step = timedelta(minutes=minutes)
    n_window = (w1 - w0) / step
    if n_window != int(n_window):
        raise SystemExit(f"{measure} window {window} is not a whole number of intervals")
    rev = "revision" if table == "opdemand_actual" else "NULL AS revision"
    cur = con.execute(f"SELECT row_id, interval_end_utc, {col} AS value, {rev}, published_at_utc, available_at_utc "
                      f"FROM {table} WHERE region=? AND interval_end_utc > ? AND interval_end_utc <= ? AND {col} IS "
                      "NOT NULL", [region, w0, w1])
    names = [d[0] for d in cur.description]
    rows = [dict(zip(names, r, strict=True)) for r in cur.fetchall()]
    by_end: defaultdict[datetime, list[dict[str, Any]]] = defaultdict(list)
    excluded = 0
    for r in rows:
        if eligible(r, cutoff):
            by_end[r["interval_end_utc"]].append(r)
        else:
            excluded += 1
    chosen = {t: max(rs, key=lambda r: (r["available_at_utc"], r["revision"] == "updated")) for t, rs in by_end.items()}
    held, n = len(chosen), int(n_window)
    out: dict[str, Any] = {"unit": "MW", "intervals_in_window": n, "intervals_held": held, "complete": held == n,
                           "excluded_rows_by_as_of": excluded, "intervals_without_eligible_row": n - held}
    if not chosen:
        return {"status": "unavailable", "value": None, "interval_ends_utc": [], "source_row_ids": [],
                "runner_up": None, **out}
    top = max(r["value"] for r in chosen.values())
    tied = sorted((t, r) for t, r in chosen.items() if r["value"] == top)
    below = [r["value"] for r in chosen.values() if r["value"] < top]
    second = max(below) if below else None
    return {"status": "established" if held == n else "not_established", "value": top,
            "interval_ends_utc": [iso(t) for t, _ in tied], "source_row_ids": [r["row_id"] for _, r in tied],
            "runner_up": None if second is None else {
                "value": second, "interval_ends_utc": sorted(iso(t) for t, r in chosen.items() if r["value"] == second)},
            **out, "revisions_used": {k: sum(1 for r in chosen.values() if r["revision"] == k)
                                      for k in ("initial", "updated")} if table == "opdemand_actual" else None}


def price_reference(con: duckdb.DuckDBPyConnection, region: str, window: tuple[str, str],
                    cutoff_s: str | None) -> dict[str, Any]:
    """The highest dispatch price over the window (held by the cutoff, if any): reference for the review only."""
    cutoff = ts(cutoff_s) if cutoff_s else None
    cur = con.execute("SELECT row_id, interval_end_utc, rrp, published_at_utc, available_at_utc FROM price_5min "
                      "WHERE region=? AND interval_end_utc > ? AND interval_end_utc <= ?", [region, ts(window[0]),
                                                                                            ts(window[1])])
    names = [d[0] for d in cur.description]
    rows = [dict(zip(names, r, strict=True)) for r in cur.fetchall()]
    ok = [r for r in rows if eligible(r, cutoff)]
    top = max(ok, key=lambda r: (r["rrp"], -r["interval_end_utc"].timestamp())) if ok else None
    return {"metric": "dispatch_rrp", "unit": "$/MWh", "held": len(ok), "in_window": len(rows),
            "highest": None if top is None else {"value": top["rrp"], "interval_end_utc": iso(top["interval_end_utc"]),
                                                 "source_row_id": top["row_id"]},
            "note": "reference for the review, not a criterion" + (
                "; with the cutoff, the day's highest price is not established either" if cutoff else "")}


def frozen_agreement(case_id: str, result: dict[str, Any]) -> dict[str, Any] | None:
    if case_id not in FROZEN:
        return None
    rel, cid, metric = FROZEN[case_id]
    exp = next(c for c in json.loads((REPO / rel).read_text())["cases"] if c["case_id"] == cid)["expected"]
    g = next(x for x in exp["gold_numbers"] if x["metric"] == metric)
    ok = (result["status"] == "established" and abs(result["value"] - g["value"]) <= 1e-9
          and result["interval_ends_utc"] == [g["valid_at_utc"]] and result["source_row_ids"] == [g["source_row_id"]])
    return {"frozen": f"{rel} {cid}", "value": g["value"], "valid_at_utc": g["valid_at_utc"],
            "source_row_id": g["source_row_id"], "agrees": ok}


def reading_of(case: dict[str, Any]) -> dict[str, Any]:
    it = case["intended"]
    return {k: (list(it[k]) if k == "window_utc" and it.get(k) else it.get(k)) for k in READING}


def build(cases: list[dict[str, Any]]) -> dict[str, Any]:
    con = connect()
    out = []
    for c in cases:
        it = c.get("intended") or {}
        if c["check_group"] not in ("development", "fresh"):
            continue
        reading = reading_of(c)
        row: dict[str, Any] = {"case_id": c["case_id"], "reading": reading, "result": None}
        if it.get("expected_outcome") in ("established", "not_established"):
            if it["window_kind"] == "day":  # recomputed from the local day, as a check on the stated bounds
                d = (ts(it["window_utc"][0]) + timedelta(hours=12)).astimezone(ZoneInfo(TZ[it["region"]])).date()
                a, b = local_day(d, it["region"])
                if [iso(a), iso(b)] != list(it["window_utc"]):
                    raise SystemExit(f"{c['case_id']}: window_utc is not the local day {d} in {it['region']}")
            res = compute(con, it["measure"], it["region"], tuple(it["window_utc"]), it.get("as_of_utc"))
            if res["status"] != it["expected_outcome"]:
                raise SystemExit(f"{c['case_id']}: computed {res['status']}, intended {it['expected_outcome']}")
            row["result"] = res
            row["frozen_gold"] = frozen_agreement(c["case_id"], res)
            if c["case_id"] in ("D03", "D04"):
                row["price_reference"] = price_reference(con, it["region"], tuple(it["window_utc"]), it.get("as_of_utc"))
        out.append(row)
    store = {t: hashlib.sha256((STORE / f"{t}.parquet").read_bytes()).hexdigest()
             for t in ("regionsum_5min", "opdemand_actual", "price_5min")}
    return {"generated_by": "eval/livecheck_maxima/gold.py", "store_sha256": store,
            "cases_json_sha256": hashlib.sha256((HERE / "cases.json").read_bytes()).hexdigest(), "cases": out}


def compare(gold: dict[str, Any], check: dict[str, Any]) -> list[str]:
    """Every difference between GOLD.json and the independent check: readings and results, exactly."""
    g = {c["case_id"]: c for c in gold["cases"]}
    k = {c["case_id"]: c for c in check["cases"]}
    diffs = [f"{cid}: only in {'GOLD' if cid in g else 'the check'}" for cid in sorted(set(g) ^ set(k))]
    for cid in sorted(set(g) & set(k)):
        for f in READING:
            a, b = g[cid]["reading"].get(f), k[cid]["reading"].get(f)
            if (list(a) if isinstance(a, tuple) else a) != (list(b) if isinstance(b, tuple) else b):
                diffs.append(f"{cid}: reading {f}: gold {a!r}, check {b!r}")
        ra, rb = g[cid]["result"], k[cid]["result"]
        if (ra is None) != (rb is None):
            diffs.append(f"{cid}: result {'absent' if ra is None else 'present'} in gold, "
                         f"{'absent' if rb is None else 'present'} in the check")
            continue
        for f in RESULT if ra is not None else ():
            if ra.get(f) != rb.get(f):
                diffs.append(f"{cid}: result {f}: gold {ra.get(f)!r}, check {rb.get(f)!r}")
    return diffs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--compare", default=None, help="the independent check's output to compare exactly")
    args = ap.parse_args()
    if args.compare:
        diffs = compare(json.loads((HERE / "GOLD.json").read_text()), json.loads(Path(args.compare).read_text()))
        print("\n".join(diffs) if diffs else "GOLD.json and the independent check agree exactly")
        return 1 if diffs else 0
    gold = build(json.loads((HERE / "cases.json").read_text())["cases"])
    (HERE / "GOLD.json").write_text(json.dumps(gold, indent=1) + "\n")
    for c in gold["cases"]:
        r = c["result"]
        print(c["case_id"], "clarification" if r is None else
              f"{r['status']} {r['value']} at {r['interval_ends_utc']} ({r['intervals_held']}/{r['intervals_in_window']}"
              f", excluded rows {r['excluded_rows_by_as_of']})", "" if not c.get("frozen_gold") else
              f"frozen gold agrees: {c['frozen_gold']['agrees']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
