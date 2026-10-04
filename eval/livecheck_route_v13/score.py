"""Score the routing-only Live check of route contract v13 (PROTOCOL.md) from the saved records, offline. It never
calls a model.

**Each call gets exactly one class** (``classify``):
- supplied;
- contained;
- unnecessary clarification;
- wrong binding;
- missed request;
- incomplete.

**The verdict** (``decide``), in the protocol's order:
1. FAIL on any demonstrated violation;
2. INCOMPLETE if a call is missing;
3. INCONCLUSIVE if containment evidence or supply is missing;
4. PASS.

It names only what it accepts: v13 request extraction and resolution on this development sample. C01 and C02
(truncation) are reported in their own section and never suggest that truncation is fixed.

Usage: python eval/livecheck_route_v13/score.py [--live DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "src"))

from nem_agent.agent.structured import CUTOFF_CLARIFICATION  # noqa: E402

LIVE = REPO / "artifacts" / "live"
SUPPLY_EACH = {"C03": 2, "C04": 2, "C05": 2}  # of 3 calls each
SUPPLY_TOGETHER = (("C03", "C04", "C05"), 7)  # of their 9 calls
RUN_SUPPLY = (("C10", "C11"), 3)  # of their 4 calls
TRUNCATION = ("C01", "C02")
CONTAINMENT = ("C06", "C07", "C08", "C09")
VERDICT_NAME = "v13 request extraction and resolution, on this development sample"


def _load(name: str) -> Any:
    return json.loads((HERE / name).read_text())


def gold_of() -> dict[str, dict[str, Any]]:
    return {g["config"]: g for g in _load("GOLD.json")["cases"]}


def _bound(rq: dict[str, Any], part: str) -> dict[str, Any] | None:
    x = (rq or {}).get(part) or {}
    return x if x.get("status") == "bound" else None


def _max_matches(mx: dict[str, Any], g: dict[str, Any] | None) -> bool:
    return g is not None and mx.get("measures") == [g["measure"]] and mx.get("window_kind") == g["window_kind"] \
        and mx.get("window_utc") == g["window_utc"]


def _run_matches(fr: dict[str, Any], g: dict[str, Any] | None) -> bool:
    return g is not None and fr.get("selection") == g["selection"] and fr.get("half_hour_utc") == g["half_hour_utc"] \
        and fr.get("issued_at_utc") == g["issued_at_utc"]


def classify(rec: dict[str, Any] | None, gold: dict[str, Any]) -> dict[str, Any]:
    """One call's class and what decided it. Hard violations are listed in ``violations``."""
    if rec is None:
        return {"class": "missing", "violations": [], "detail": "not saved"}
    res = rec["resolution"]
    rq = res.get("requests") or {}
    status = res["status"]
    violations: list[str] = []
    if rec["route_invalid"]:  # rejected before parsing: fail-closed, never an interpretation
        if status == "ok":
            violations.append("an incomplete or invalid routing response was not sent back")
        diag = rec.get("incomplete_diagnostics") or {}
        return {"class": "incomplete", "violations": violations,
                "detail": f"{rec['route_call'].get('status')} {rec['route_call'].get('incomplete')}; cause: "
                          f"{diag.get('cause')}; open field: {(diag.get('open_json_field') or {}).get('path')}"}
    mx, fr = _bound(rq, "maximum"), _bound(rq, "forecast_run")
    co = rq.get("cutoff") or {}
    wrong = []
    if res.get("region") is not None and res["region"] != gold["region"]:
        wrong.append(f"region {res['region']}, gold {gold['region']}")
    if mx is not None and not _max_matches(mx, gold["maximum"]):
        wrong.append(f"maximum {mx.get('measures')} {mx.get('window_kind')} {mx.get('window_utc')}, gold {gold['maximum']}")
    if fr is not None and not _run_matches(fr, gold["forecast_run"]):
        wrong.append(f"forecast run {fr.get('selection')} {fr.get('half_hour_utc')} {fr.get('issued_at_utc')}, "
                     f"gold {gold['forecast_run']}")
    if res.get("as_of_utc") is not None and res["as_of_utc"] != gold["as_of_utc"]:
        wrong.append(f"cutoff {res['as_of_utc']}, gold {gold['as_of_utc']}")
    if wrong:
        violations += [f"wrong binding: {w}" for w in wrong]
    if co.get("detected_by") and status == "ok" and res.get("as_of_utc") is None:
        violations.append(f"a detected cutoff was dropped ({co.get('detected_by')})")
    cfg = gold["config"]
    if cfg == "C06" and status == "ok":
        violations.append("C06 proceeded although its cutoff cannot be read")
    if cfg == "C07" and mx is not None:
        violations.append("C07 bound a maximum although no measure is named")
    if cfg == "C08" and fr is not None:
        violations.append("C08 bound a run although its half-hour has no date")
    if cfg == "C09" and mx is not None:
        violations.append("C09 bound a maximum although none is asked for")
    asked = {"maximum": gold["maximum"] is not None or cfg == "C07", "forecast_run": gold["forecast_run"] is not None
             or cfg == "C08"}
    for part, wanted in asked.items():
        if wanted and status == "ok" and ((rq.get(part) or {}).get("status") in (None, "absent")):
            violations.append(f"missed request: the {part.replace('_', ' ')} was never detected, and it proceeded")
    if violations:
        return {"class": "wrong binding" if wrong else "violation", "violations": violations, "detail": "; ".join(violations)}
    reasons = res.get("reasons") or []
    if gold["outcome"] == "bound":
        if status == "ok" and (gold["maximum"] is None or mx is not None) and (gold["forecast_run"] is None or fr is not None) \
                and res.get("as_of_utc") == gold["as_of_utc"] and (mx is None or gold["maximum"] is not None) \
                and (fr is None or gold["forecast_run"] is not None):
            return {"class": "supplied", "violations": [], "detail": ""}
        return {"class": "unnecessary clarification", "violations": [], "detail": " | ".join(reasons)[:300]}
    if gold["outcome"] == "no_request":  # C09
        if status == "ok" and mx is None and fr is None and res.get("as_of_utc") is None:
            return {"class": "contained", "violations": [], "detail": "no request bound"}
        return {"class": "unnecessary clarification", "violations": [], "detail": " | ".join(reasons)[:300]}
    # must be sent back (C06, C07, C08)
    shown = status == "needs_clarification" and (
        (cfg == "C06" and co.get("status") == "unresolved" and CUTOFF_CLARIFICATION in reasons)
        or (cfg == "C07" and mx is None) or (cfg == "C08" and fr is None))
    return {"class": "contained" if shown else "violation" if status == "ok" else "contained (other reason)",
            "violations": [], "detail": " | ".join(reasons)[:300]}


def records(freeze: dict[str, Any], live: Path = LIVE) -> dict[int, dict[str, Any] | None]:
    """Each slot's saved record (None if the log does not record it as saved)."""
    p = live / "LC-route-v13" / "run_log.jsonl"
    log = [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()] if p.exists() else []
    saved = {e["slot"] for e in log if e.get("event") == "slot_end" and e.get("outcome") == "saved"}
    out: dict[int, dict[str, Any] | None] = {}
    for s in freeze["slots"]:
        rp = live / freeze["label"] / f"{s['case']}.json"
        out[s["slot"]] = json.loads(rp.read_text()) if s["slot"] in saved and rp.exists() else None
    return out


def decide(freeze: dict[str, Any], recs: dict[int, dict[str, Any] | None]) -> dict[str, Any]:
    gold = gold_of()
    rows = []
    for s in freeze["slots"]:
        c = classify(recs.get(s["slot"]), gold[s["config"]])
        rec = recs.get(s["slot"]) or {}
        rc = rec.get("route_call") or {}
        rows.append({"slot": s["slot"], "config": s["config"], "class": c["class"], "violations": c["violations"],
                     "detail": c["detail"], "resolution_status": (rec.get("resolution") or {}).get("status"),
                     "route_status": rc.get("status"), "input_tokens": rc.get("input_tokens"),
                     "output_tokens": rc.get("output_tokens"), "reasoning_tokens": rc.get("reasoning_tokens"),
                     "cached_tokens": rc.get("cached_tokens"), "duration_ms": rc.get("duration_ms"),
                     "ledger_cost_usd": (rec.get("score") or {}).get("ledger_cost_usd")})
    by = {cfg: [r for r in rows if r["config"] == cfg] for cfg in gold}
    violations = [f"slot {r['slot']} ({r['config']}): {v}" for r in rows for v in r["violations"]]
    violations += [f"slot {r['slot']} ({r['config']}): {r['detail']}" for r in rows if r["class"] == "violation"
                   and not r["violations"]]
    missing = [r["slot"] for r in rows if r["class"] == "missing"]
    supplied = {cfg: sum(r["class"] == "supplied" for r in rs) for cfg, rs in by.items()}
    containment = {cfg: sum(r["class"] == "contained" for r in by[cfg]) for cfg in CONTAINMENT}
    undemonstrated = [cfg for cfg, n in containment.items() if n == 0]
    supply_ok = (all(supplied[c] >= n for c, n in SUPPLY_EACH.items())
                 and sum(supplied[c] for c in SUPPLY_TOGETHER[0]) >= SUPPLY_TOGETHER[1]
                 and sum(supplied[c] for c in RUN_SUPPLY[0]) >= RUN_SUPPLY[1])
    if violations:
        verdict = "FAIL"
    elif missing:
        verdict = "INCOMPLETE"
    elif undemonstrated or not supply_ok:
        verdict = "INCONCLUSIVE"
    else:
        verdict = "PASS"
    trunc = {cfg: {"calls": len(by[cfg]), "completed": sum(r["class"] not in ("incomplete", "missing") for r in by[cfg]),
                   "incomplete": sum(r["class"] == "incomplete" for r in by[cfg]),
                   "classes": dict(Counter(r["class"] for r in by[cfg])),
                   "diagnostics": [r["detail"] for r in by[cfg] if r["class"] == "incomplete"]} for cfg in TRUNCATION}
    costs = [r["ledger_cost_usd"] for r in rows if r["ledger_cost_usd"] is not None]
    return {
        "verdict": verdict, "verdict_of": VERDICT_NAME,
        "verdict_note": "Truncation is reported separately (C01, C02): no verdict here says that whitespace "
                        "degeneration or routing truncation is fixed.",
        "coverage": {"saved": len(rows) - len(missing), "of": len(rows), "missing_slots": missing},
        "violations": violations,
        "containment_evidence": {cfg: {"contained_completed": n, "of": len(by[cfg])} for cfg, n in containment.items()},
        "containment_undemonstrated": undemonstrated,
        "supply": {cfg: {"supplied": supplied[cfg], "of": len(by[cfg])} for cfg in gold
                   if gold[cfg]["outcome"] == "bound"},
        "supply_bars": {"each": SUPPLY_EACH, "together": [list(SUPPLY_TOGETHER[0]), SUPPLY_TOGETHER[1]],
                        "runs": [list(RUN_SUPPLY[0]), RUN_SUPPLY[1]], "met": supply_ok},
        "unnecessary_clarifications": [r for r in rows if r["class"] == "unnecessary clarification"],
        "truncation_section": trunc,
        "usage": {"calls_with_usage": sum(r["input_tokens"] is not None for r in rows),
                  "input_tokens": sum(r["input_tokens"] or 0 for r in rows),
                  "output_tokens": sum(r["output_tokens"] or 0 for r in rows),
                  "reasoning_tokens": sum(r["reasoning_tokens"] or 0 for r in rows),
                  "ledger_cost_usd": round(sum(costs), 6) if costs else 0.0,
                  "billed": "not observed (the API response does not carry it)"},
        "calls": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", default=str(LIVE))
    args = ap.parse_args()
    freeze = _load("FREEZE.json")
    print(json.dumps(decide(freeze, records(freeze, Path(args.live))), indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
