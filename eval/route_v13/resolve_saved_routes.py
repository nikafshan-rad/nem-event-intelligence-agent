"""Resolve every saved Live routing decision with the code on ``sys.path`` (offline: no model call, no key, no ledger).

For each saved Live record whose trace holds a routing decision (``model_decision``), the decision is resolved as the
Live path resolves it (``live.checked_route``, ``service.resolve_routed``), with the record's question and request
fields, and the resolution is written as JSON: status, intent, region, cutoff, window, and the forecast-run, maximum
and cutoff requests. Run it once on the v12 code and once on this code, and compare (D26, acceptance criterion 2).

Usage: PYTHONPATH=<src> python eval/route_v13/resolve_saved_routes.py OUT.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
LIVE = REPO / "artifacts" / "live"


def _routes() -> list[dict[str, Any]]:
    out = []
    for rec_p in sorted(LIVE.glob("*/*.json")):
        try:
            rec = json.loads(rec_p.read_text())
        except ValueError:
            continue
        if not isinstance(rec, dict) or "question" not in rec:
            continue
        tid = rec.get("trace_id") or (rec.get("score") or {}).get("trace_id")
        tp = rec_p.parent / "traces" / f"{tid}.json"
        if not tid or not tp.exists():
            continue
        ev = json.loads(tp.read_text())["events"]
        dec = next((e.get("decision") for e in ev if e.get("name") == "model_decision"), None)
        if dec is None:
            continue
        out.append({"key": f"{rec_p.parent.name}/{rec_p.stem}", "question": rec["question"],
                    "request": rec.get("request") or {}, "decision": dec})
    return out


def main() -> int:
    from nem_agent.agent.live import RouteDecision, checked_route
    from nem_agent.agent.request import InvestigateRequest
    from nem_agent.selection import load_selection
    from nem_agent.service import resolve_routed

    sel = load_selection()
    rows = {}
    for r in _routes():
        req = InvestigateRequest(question=r["question"], mode="live", **r["request"])
        res = resolve_routed(req, checked_route(RouteDecision.model_validate(r["decision"])), sel)
        rq = (res.routing or {}).get("requests") or {}
        rows[r["key"]] = {
            "status": res.status, "intent": res.intent, "region": res.region,
            "as_of": res.as_of.isoformat() if res.as_of else None,
            "window": [w.isoformat() for w in res.window] if res.window else None,
            "forecast_run": {k: (rq.get("forecast_run") or {}).get(k)
                             for k in ("status", "selection", "half_hour_utc", "issued_at_utc", "missing", "conflicts")},
            "maximum": {k: (rq.get("maximum") or {}).get(k)
                        for k in ("status", "measures", "window_kind", "window_utc", "missing", "conflicts")},
            "cutoff": {k: (rq.get("cutoff") or {}).get(k) for k in ("status", "as_of_utc", "missing", "conflicts")}
            if rq.get("cutoff") else None,
            "reasons": res.reasons}
    Path(sys.argv[1]).write_text(json.dumps(rows, indent=1, sort_keys=True) + "\n")
    print(f"{len(rows)} saved routing decisions resolved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
