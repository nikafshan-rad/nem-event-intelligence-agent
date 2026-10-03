"""Compare the v12 and v13 resolutions of the saved routing decisions, and of the I-18 paraphrase matrix, and check
every changed binding against the independently checked gold (D26, acceptance criterion 2). Offline.

Inputs, made beforehand:
- the outputs of `resolve_saved_routes.py` and of `eval/structured_requests/run_matrix.py`, each run once on the v12
  code (`main` before this change) and once on this code;
- every resolution the scratch ledger allows: no model call is made.

Usage:
    python eval/route_v13/compare.py ROUTES_V12.json ROUTES_V13.json MATRIX_V12.json MATRIX_V13.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
MEASURE = {"dispatch_total_demand": "total demand", "operational_demand": "operational demand",
           "total demand": "total demand", "operational demand": "operational demand"}
KIND = {"whole_local_day": "day", "day": "day", "event": "event", "explicit": "explicit"}


def _gold() -> dict[str, dict[str, Any]]:
    """Case key -> the gold maximum (measure, window kind, window) where an independently checked one exists."""
    out: dict[str, dict[str, Any]] = {}
    for c in json.loads((REPO / "eval/livecheck_maxima/GOLD.json").read_text())["cases"]:
        r = c["reading"]
        if r.get("window_utc"):
            out[f"LC-maxima-run/{c['case_id']}"] = {"source": "eval/livecheck_maxima/GOLD.json", "measure": r["measure"],
                                                    "window_kind": KIND[r["window_kind"]], "window_utc": r["window_utc"]}
    for c in json.loads((REPO / "eval/livecheck_i15_17/cases.json").read_text())["cases"]:
        e = c["expected"]
        if e.get("window_utc") and e.get("gold_numbers"):
            m = "total demand" if e["gold_numbers"][0]["metric"] == "dispatch_totaldemand" else "operational demand"
            for label in ("LC-i15-17-fresh", "LC-route-v12-e2e", "MC-dev-e2e-mini", "MC-dev-e2e-sol"):
                out[f"{label}/{c['case_id']}"] = {"source": "eval/livecheck_i15_17/cases.json", "measure": m,
                                                  "window_kind": None, "window_utc": e["window_utc"]}
    for c in json.loads((REPO / "eval/livecheck_routing_v12/cases.json").read_text())["cases"]:
        mx = c["expected"].get("maximum") or {}
        if mx.get("window_utc"):
            out[f"LC-route-v12-fresh/{c['case_id']}"] = {
                "source": "eval/livecheck_routing_v12/cases.json", "measure": MEASURE[mx["measure"]],
                "window_kind": KIND[mx["window_kind"]], "window_utc": mx["window_utc"],
                "expected_outcome": c["expected"].get("outcome")}
        elif c["expected"].get("outcome"):
            out.setdefault(f"LC-route-v12-fresh/{c['case_id']}", {"source": "eval/livecheck_routing_v12/cases.json",
                                                                  "expected_outcome": c["expected"]["outcome"],
                                                                  "as_of_utc": c["expected"].get("as_of_utc")})
    return out


def _key(v: dict[str, Any]) -> tuple[Any, ...]:
    fr, mx = v["forecast_run"], v["maximum"]
    return (v["status"], v["as_of"], v["window"], fr["status"], fr["selection"], fr["half_hour_utc"], fr["issued_at_utc"],
            mx["status"], tuple(mx["measures"] or []), mx["window_kind"], tuple(mx["window_utc"] or []))


def routes(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    gold = _gold()
    changed = []
    for k in sorted(a):
        if _key(a[k]) == _key(b[k]):
            continue
        g = gold.get(k)
        mx = b[k]["maximum"]
        check = None
        if g and g.get("window_utc") and mx["status"] == "bound":
            check = ("matches gold" if mx["measures"] == [g["measure"]] and mx["window_utc"] == g["window_utc"]
                     and (g["window_kind"] is None or mx["window_kind"] == g["window_kind"]) else "DIFFERS FROM GOLD")
        changed.append({"key": k, "v12": {f: a[k][f] for f in ("status", "as_of", "maximum", "forecast_run", "reasons")},
                        "v13": {f: b[k][f] for f in ("status", "as_of", "maximum", "forecast_run", "cutoff", "reasons")},
                        "gold": g, "gold_check": check})
    return {"routes": len(a), "unchanged": len(a) - len(changed), "changed": changed}


def matrix(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    ra = {(r["id"], r["mode"]): r for r in a["rows"]}
    rb = {(r["id"], r["mode"]): r for r in b["rows"]}
    return {"summary_v12": a["summary"], "summary_v13": b["summary"], "rows": len(ra),
            "changed": [{"id": k[0], "mode": k[1], "v12": ra[k]["verdict"], "v13": rb[k]["verdict"],
                         "v13_detail": rb[k]["detail"]} for k in sorted(ra) if ra[k]["verdict"] != rb[k]["verdict"]]}


def main() -> int:
    ra, rb, ma, mb = (json.loads(Path(p).read_text()) for p in sys.argv[1:5])
    r, m = routes(ra, rb), matrix(ma, mb)
    (HERE / "HISTORICAL_BINDINGS.json").write_text(json.dumps(r, indent=1) + "\n")
    (HERE / "MATRIX_COMPARISON.json").write_text(json.dumps(m, indent=1) + "\n")
    print(f"saved routes: {r['routes']}, changed {len(r['changed'])}:",
          [(c["key"], c["gold_check"]) for c in r["changed"]])
    print(f"matrix rows: {m['rows']}, changed {len(m['changed'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
