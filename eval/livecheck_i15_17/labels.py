"""Gold evidence and overlap labels for the targeted Live check (PASS_RULE.md), from the frozen cases and the pinned
store. Offline; it never calls a model.

- **GOLD.json:** for every gold row of D1 (`DEVCHECK.json`, with the frozen v6 gold) and D2 (`cases.json`), the stored
  source row: table, region, interval, value, revision, run and issue time, publication and availability. Also the
  forecast runs a case names (`gold_run`, `must_not_substitute`), and for each case its expected outcome and check.
  The writer and the verifier derived the gold; this re-reads every row from the store, so the published gold is
  traceable to source rows.
- **LABELS.json:** each case's run, area, expected outcome, and its overlap with development material (PASS_RULE.md,
  "Overlap with development material"): "development case" for D1, else the development items its gold rows fall in,
  or "none".

Usage: python eval/livecheck_i15_17/labels.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(HERE))

from build_kit import DEVELOPMENT  # noqa: E402

from nem_agent.store import Store  # noqa: E402
from nem_agent.timeutil import iso_utc, parse_iso  # noqa: E402

TABLES = {"price_5min": ("interval_end_utc", "rrp"), "regionsum_5min": ("interval_end_utc", "totaldemand_mw"),
          "opdemand_actual": ("interval_end_utc", "operational_demand_mw"),
          "opdemand_forecast": ("target_end_utc", "poe50_mw")}


def _iso(v: Any) -> Any:
    return iso_utc(v) if isinstance(v, datetime) else v


def store_rows(store: Store, row_id: str) -> list[dict[str, Any]]:
    """Every stored row with this row_id (a dispatch file line holds both a price and a region-summary row)."""
    out = []
    for table, (at, _val) in TABLES.items():
        extra = {"opdemand_forecast": ", run_id, issued_at_utc, poe10_mw, poe50_mw, poe90_mw",
                 "opdemand_actual": ", operational_demand_mw, revision", "price_5min": ", rrp",
                 "regionsum_5min": ", totaldemand_mw, netinterchange_mw"}[table]
        for r in store.query(f"SELECT region, {at} AS interval_end_utc, published_at_utc, available_at_utc{extra} "
                             f"FROM {table} WHERE row_id = ?", [row_id]):
            out.append({"table": table, **{k: _iso(v) for k, v in dict(r).items()}})
    return out


def run_rows(store: Store, run: dict[str, Any] | None) -> dict[str, Any] | None:
    if not run or not run.get("run_id"):
        return None
    r = store.query("SELECT MIN(issued_at_utc) i, MIN(published_at_utc) p, MAX(available_at_utc) a, COUNT(*) n "
                    "FROM opdemand_forecast WHERE run_id = ?", [run["run_id"]])[0]
    return {"run_id": run["run_id"], "issued_at_utc": _iso(r["i"]), "published_at_utc": _iso(r["p"]),
            "available_at_utc": _iso(r["a"]), "rows": r["n"]}


def overlaps(region: str | None, at: str | None) -> list[str]:
    """The development items a (region, interval end) falls in."""
    if not region or not at:
        return []
    t = parse_iso(at)
    hits = []
    for it in DEVELOPMENT["items"]:
        if it["region"] != region:
            continue
        if "half_hour_end_utc" in it and t == parse_iso(it["half_hour_end_utc"]):
            hits.append(f"{region} half-hour ending {it['half_hour_end_utc']}")
        for key in ("utc", "event_window_utc"):
            if key in it and parse_iso(it[key][0]) < t <= parse_iso(it[key][1]):
                what = f"local day {it['local_day']}" if "local_day" in it else "event window"
                hits.append(f"{region} {what} {it[key][0]}..{it[key][1]}")
    return hits


def main() -> int:
    store = Store()
    dev = json.loads((HERE / "DEVCHECK.json").read_text())
    v6 = {c["case_id"]: c for c in json.loads((REPO / dev["cases_file"]).read_text())["cases"]}
    fresh = json.loads((HERE / "cases.json").read_text())["cases"]
    gold: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []
    for run, cases in (("D1", [v6[c["case_id"]] for c in dev["cases"]]), ("D2", fresh)):
        for c in cases:
            exp = c["expected"]
            items = []
            hits: list[str] = []
            for g in exp.get("gold_numbers") or []:
                rows = store_rows(store, g["source_row_id"]) if g.get("source_row_id") else []
                items.append({**g, "store_rows": rows})
                for r in rows:
                    hits += overlaps(r.get("region"), r.get("interval_end_utc"))
            runs = {k: run_rows(store, exp.get("gold_run") if k == "gold_run" else (exp.get("gold_run") or {}).get(k))
                    for k in ("gold_run", "must_not_substitute")}
            for k in ("gold_run", "must_not_substitute"):
                src = exp.get("gold_run") if k == "gold_run" else (exp.get("gold_run") or {}).get(k)
                region = next((r["region"] for i in items for r in i["store_rows"]), None)
                if src and src.get("target_end_utc"):
                    hits += overlaps(region, src["target_end_utc"])
            area = exp.get("area") or {"Z03": "value_time", "Z05": "forecast_run", "Z04": "demand_max"}[c["case_id"]]
            outcome = exp.get("expected_outcome", "supplied")
            gold.append({"case_id": c["case_id"], "run": run, "area": area, "expected_outcome": outcome,
                         "request": c.get("request", {}), "gold_numbers": items,
                         "runs": {k: v for k, v in runs.items() if v},
                         **{k: exp[k] for k in ("gold_run", "as_of_utc", "window_utc", "ties", "next_highest",
                                                "day_max_for_comparison", "gold_citation", "check") if exp.get(k)}})
            labels.append({"case_id": c["case_id"], "run": run, "area": area, "expected_outcome": outcome,
                           "overlap": "development case" if run == "D1" else
                           ("; ".join(sorted(set(hits))) if hits else "none")})
    (HERE / "GOLD.json").write_text(json.dumps({"note": "Gold evidence, re-read from the pinned store at the freeze "
                                                        "(labels.py).", "cases": gold}, indent=1) + "\n")
    (HERE / "LABELS.json").write_text(json.dumps({"note": "Run, area, expected outcome and overlap with development "
                                                          "material (PASS_RULE.md), at the freeze (labels.py).",
                                                  "cases": labels}, indent=1) + "\n")
    print("\n".join(f"{x['case_id']} {x['run']} {x['area']:<13} {x['expected_outcome']:<13} overlap: {x['overlap']}"
                    for x in labels))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
