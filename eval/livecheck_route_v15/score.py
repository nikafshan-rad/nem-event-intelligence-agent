"""Score the routing-only Live check of route contract v15 (PROTOCOL.md) from the saved records, offline. It never
calls a model, and it reports routing and request resolution only: no answer, no H1–H5 review, no rate.

- **The outcome** of each call is read from its resolution (``outcome_of``; PROTOCOL.md, "Outcomes").
- **The class** (``classify``) is exactly one per call, in the protocol's order:
  1. violation;
  2. unassessable (missing);
  3. incomplete or invalid;
  4. correct resolved request;
  5. correct clarification or unsupported handling;
  6. unnecessary clarification;
  7. contained for another reason.
- **The verdict** (``decide``): FAIL, INCOMPLETE, INCONCLUSIVE, then PASS.
- **The model's reading** is reported against gold for every call. It is never gated by itself.

Usage: python eval/livecheck_route_v15/score.py [--live DIR]
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
LIVE = REPO / "artifacts" / "live"
LOG_NAME = "LC-route-v15"
DEMAND_TOOLS = {"get_forecast_runs", "compare_forecast_actual"}
SUPPLY_EACH, SUPPLY_TOTAL = 1, 17  # of 2 calls each; of the 20 supply calls together
VERDICT_NAME = "v15 request extraction and resolution, on this sample (10 familiar and 7 fresh questions)"
NOT_ANSWERED = "Not answered:"
UNCLEAR_NOTE = "The question also mentions a forecast without showing which"
MEASURE = {"operational_demand": "operational demand", "dispatch_total_demand": "total demand"}
WINDOW = {"whole_local_day": "day", "event": "event", "explicit": "explicit"}
NOT_CLAIMED = ("This report covers routing and request resolution only. It makes no claim about answers, tools or "
               "synthesis, no H1–H5 answer review, no rate, and no generalisation; it does not say that truncation is "
               "fixed.")


def _load(name: str) -> Any:
    return json.loads((HERE / name).read_text())


_SETS = {c["config"]: c["set"] for c in _load("cases.json")["cases"]}  # PROTOCOL.md, "Scope"
SUPPLY = [c for c, s in _SETS.items() if s == "supply"]
CONTAINMENT = [c for c, s in _SETS.items() if s == "containment"]
AMBIGUITY = [c for c, s in _SETS.items() if s == "ambiguity"]


def gold_of() -> dict[str, dict[str, Any]]:
    return {g["config"]: g for g in _load("GOLD.json")["cases"]}


# ------------------------------------------------------------------------------------------------ reading a record
REQUIRED = ("route_invalid", "route", "resolution", "tools_offered")
REQUIRED_RES = ("status", "reasons", "intent", "region", "as_of_utc", "window_utc", "target_utc", "requests")
REQUIRED_RQ = ("forecast", "forecast_run", "maximum", "cutoff", "notes", "ineligible_tools")
REQUIRED_FA = ("status", "domain", "unsupported", "operation", "scope", "target_utc", "window_utc", "half_hours",
               "provenance", "missing", "conflicts")


def unassessable(rec: dict[str, Any]) -> str | None:
    """Why a saved record lacks a field a gated assessment needs (PROTOCOL.md: INCOMPLETE), or None."""
    missing = [k for k in REQUIRED if k not in rec]
    res = rec.get("resolution") or {}
    missing += [f"resolution.{k}" for k in REQUIRED_RES if k not in res]
    rq = res.get("requests")
    if rq is not None:
        missing += [f"requests.{k}" for k in REQUIRED_RQ if k not in rq]
        fa = rq.get("forecast") or {}
        missing += [f"requests.forecast.{k}" for k in REQUIRED_FA if k not in fa]
    elif res.get("status") == "ok":
        missing.append("requests (the resolution proceeds)")
    return f"missing {', '.join(missing)}" if missing else None


def notes_of(rq: dict[str, Any] | None) -> list[str]:
    return list((rq or {}).get("notes") or [])


def outcome_of(res: dict[str, Any]) -> str:
    """The outcome a resolution shows (PROTOCOL.md, "Outcomes")."""
    rq = res.get("requests") or {}
    fa = rq.get("forecast") or {}
    status = res["status"]
    if status == "refused":
        return "refusal"
    if status != "ok":
        missing, conflicts = fa.get("missing") or [], fa.get("conflicts") or []
        if missing == ["domain_unsupported"]:
            return "clarify_unsupported"
        if missing == ["domain"] or any(str(c).startswith("domain") for c in conflicts):
            return "clarify_which_forecast"
        if missing == ["domain_mixed"]:
            return "clarify_mixed"
        return "other send-back"
    if res.get("intent") == "market_event_review" and set(rq.get("ineligible_tools") or {}) >= DEMAND_TOOLS:
        notes = notes_of(rq)
        if any(n.startswith(NOT_ANSWERED) for n in notes):
            return "event_review_unsupported"
        if any(n.startswith(UNCLEAR_NOTE) for n in notes):
            return "event_review_unclear"
        return "other event review"
    return "resolved"


def _spans(text: str, q: str) -> list[tuple[int, int]]:
    out, i = [], q.find(text) if text else -1
    while i >= 0:
        out.append((i, i + len(text)))
        i = q.find(text, i + 1)
    return out


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def anchors_ok(text: str | None, q: str, include: list[str], exclude: list[str]) -> tuple[bool, str]:
    """Whether grounded words read as the request overlap at least one request anchor and no excluded anchor. Any
    such span is accepted: there is no single required extraction string (PROTOCOL.md, "Gold")."""
    occ = _spans(text or "", q)
    if not occ:
        return False, f"the words {text!r} are not located in the question"
    inc = [s for a in include for s in _spans(a, q)]
    exc = [s for a in exclude for s in _spans(a, q)]
    if not any(_overlaps(o, s) for o in occ for s in inc):
        return False, f"the words {text!r} overlap none of the request anchors {include}"
    if any(_overlaps(o, s) for o in occ for s in exc):
        return False, f"the words {text!r} overlap an excluded anchor {exclude}"
    return True, ""


def _resolved_reading(gold: dict[str, Any]) -> bool:
    return gold["resolved_reading"] is not None


def _demand_reading(gold: dict[str, Any]) -> bool:
    """The gold accepts a resolved operational demand forecast request (`gold.py`, ``resolved_reading``)."""
    return gold["resolved_reading"] == "operational_demand_forecast"


def forecast_mismatches(rec: dict[str, Any], gold: dict[str, Any]) -> list[str]:
    """Every gated item of a bound forecast request that differs from the gold's resolved reading."""
    res, q = rec["resolution"], rec["question"]
    rq = res["requests"]
    fa, fr = rq["forecast"], rq["forecast_run"]
    out = []
    if not _demand_reading(gold):
        return [f"a forecast request is bound ({fa.get('domain')}, {fa.get('operation')}) where the gold has none"]
    if res.get("intent") not in gold["intents"]:
        out.append(f"intent {res.get('intent')}, gold {gold['intents']}")
    if fa.get("domain") != "operational_demand":
        out.append(f"domain {fa.get('domain')}, gold operational_demand")
    clause = (fa.get("provenance") or {}).get("domain") or {}
    ok, why = anchors_ok(clause.get("text"), q, gold["request_anchors"], gold["excluded_anchors"])
    if not ok:
        out.append(f"requested clause: {why}")
    if fa.get("operation") != gold["operation"]:
        out.append(f"operation {fa.get('operation')}, gold {gold['operation']}")
    sc = gold["scope"]
    bounds = fa.get("target_utc") or fa.get("window_utc")
    if fa.get("scope") not in sc["kinds"] or bounds != [sc["start_utc"], sc["end_utc"]] or \
            fa.get("half_hours") != sc["half_hours"]:
        out.append(f"scope {fa.get('scope')} {bounds} ({fa.get('half_hours')} half-hours), gold {sc['kinds']} "
                   f"{[sc['start_utc'], sc['end_utc']]} ({sc['half_hours']})")
    run = gold["run"]
    want = {"none": ("absent", None, None, None),
            "as_of_availability": ("as_of_availability", None, None, None)}.get(
        run["rule"], ("bound", run["rule"], run["half_hour_end_utc"], run["issued_at_utc"]))
    got = (fr.get("status"), fr.get("selection") if fr.get("status") == "bound" else None,
           (fr.get("half_hour_utc") or [None, None])[1] if fr.get("status") == "bound" else None,
           fr.get("issued_at_utc") if fr.get("status") == "bound" else None)
    if got != want:
        out.append(f"run {got}, gold {want}")
    if res.get("as_of_utc") != gold["cutoff_utc"]:
        out.append(f"cutoff {res.get('as_of_utc')}, gold {gold['cutoff_utc']}")
    if (rq.get("maximum") or {}).get("status") == "bound":
        out.append("a maximum is bound where the gold has none")
    return out


def unsupported_findings(rec: dict[str, Any], gold: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(omitted parts, wrongly claimed parts) of a resolution that proceeds with a resolved request."""
    rq = rec["resolution"]["requests"]
    fa = rq["forecast"]
    named = bool(fa.get("unsupported")) or any(n.startswith(NOT_ANSWERED) for n in notes_of(rq))
    parts = gold["unsupported_parts"]
    omitted, wrong = [], []
    if parts and not named:
        omitted.append(f"the unsupported part {[p['anchor'] for p in parts]} is not named")
    if not parts and named:
        wrong.append(f"an unsupported part is named ({fa.get('unsupported')}) where the question asks for none")
    words = (((rec.get("route") or {}).get("requested") or {}).get("forecast") or {}).get("unsupported_text")
    on_a_part = any(_overlaps(o, s) for o in _spans(words or "", rec["question"]) for p in parts
                    for s in _spans(p["anchor"], rec["question"]))
    if parts and named and words and not on_a_part:
        wrong.append(f"the unsupported words {words!r} are not the part the question asks for "
                     f"{[p['anchor'] for p in parts]}")
    return omitted, wrong


def maximum_mismatch(mx: dict[str, Any], g: dict[str, Any] | None) -> str | None:
    if g is None:
        return f"a maximum is bound ({mx.get('measures')} {mx.get('window_kind')}) where the gold has none"
    want = ([MEASURE[g["measure"]]], WINDOW[g["window_kind"]], [g["start_utc"], g["end_utc"]])
    got = (mx.get("measures"), mx.get("window_kind"), mx.get("window_utc"))
    return None if got == want else f"maximum {got}, gold {want}"


def classify(rec: dict[str, Any] | None, gold: dict[str, Any]) -> dict[str, Any]:
    """One call's class, outcome and what decided it (PROTOCOL.md, "Classes and their precedence")."""
    if rec is None:
        return {"class": "unassessable", "outcome": None, "violations": [], "detail": "not saved"}
    why = unassessable(rec)
    if why:
        return {"class": "unassessable", "outcome": None, "violations": [], "detail": why}
    res = rec["resolution"]
    rq = res.get("requests") or {}
    status = res["status"]
    tools = rec["tools_offered"]
    outcome = outcome_of(res)
    v: list[str] = []
    # -- every call, whatever its outcome: bound requests, region and cutoff
    if res.get("region") is not None and res["region"] != gold["region"]:
        v.append(f"wrong binding: region {res['region']}, gold {gold['region']}")
    if res.get("as_of_utc") is not None and res["as_of_utc"] != gold["cutoff_utc"]:
        v.append(f"wrong binding: cutoff {res['as_of_utc']}, gold {gold['cutoff_utc']}")
    fa, fr, mx, co = (rq.get(k) or {} for k in ("forecast", "forecast_run", "maximum", "cutoff"))
    if fa.get("status") == "bound":
        v += [f"wrong binding: {m}" for m in forecast_mismatches(rec, gold)]
    elif fr.get("status") == "bound":
        run = gold["run"] if _resolved_reading(gold) and gold.get("run") else {"rule": "none"}
        if run["rule"] not in ("last_issued_before", "issued_at") or (
                fr.get("selection"), (fr.get("half_hour_utc") or [None, None])[1], fr.get("issued_at_utc")) != (
                run["rule"], run["half_hour_end_utc"], run["issued_at_utc"] if run["rule"] == "issued_at" else None):
            v.append(f"wrong binding: run {fr.get('selection')} {fr.get('half_hour_utc')} {fr.get('issued_at_utc')}, "
                     f"gold {run}")
    if mx.get("status") == "bound" and (m := maximum_mismatch(mx, gold.get("maximum"))):
        v.append(f"wrong binding: {m}")
    if status == "ok":
        if co.get("detected_by") and res.get("as_of_utc") is None:
            v.append(f"dropped cutoff: detected ({co.get('detected_by')}), and the resolution proceeds without it")
        if gold["demand_forecast_tools"] == "not_used" and set(tools) & DEMAND_TOOLS:
            v.append(f"incorrect tool eligibility: {sorted(set(tools) & DEMAND_TOOLS)} offered where the gold says "
                     "not used")
        if gold["demand_forecast_tools"] == "eligible" and outcome == "resolved" and not set(tools) & DEMAND_TOOLS:
            v.append("incorrect tool eligibility: no demand-forecast tool offered for a resolved demand request")
        if outcome == "resolved" and _resolved_reading(gold):
            if gold["cutoff_utc"] is not None and res.get("as_of_utc") is None:
                v.append(f"wrong binding: no cutoff applied, gold {gold['cutoff_utc']}")
            if _demand_reading(gold) and fa.get("status") != "bound":
                v.append("missed request: the resolution proceeds without the operational demand forecast request")
            if gold.get("maximum") and mx.get("status") != "bound":
                v.append("missed request: the resolution proceeds without the demand maximum")
            if gold.get("maximum") and res.get("intent") not in gold["intents"]:
                v.append(f"wrong binding: intent {res.get('intent')}, gold {gold['intents']}")
            omitted, wrong = unsupported_findings(rec, gold)
            v += [f"omitted unsupported part: {x}" for x in omitted] + [f"unsupported part wrongly claimed: {x}"
                                                                       for x in wrong]
    if v:
        return {"class": "violation", "outcome": outcome, "violations": v, "detail": "; ".join(v)}
    if rec["route_invalid"]:  # rejected before it could be read: an extraction miss, never containment or supply
        diag = rec.get("incomplete_diagnostics") or {}
        return {"class": "incomplete or invalid", "outcome": outcome, "violations": [],
                "detail": f"{rec['route_call'].get('status')} {rec['route_call'].get('incomplete')}; cause: "
                          f"{diag.get('cause')}; open field: {(diag.get('open_json_field') or {}).get('path')}"}
    reasons = " | ".join(res.get("reasons") or [])[:300]
    if outcome in gold["acceptable_outcomes"]:
        return {"class": "correct resolved request" if outcome == "resolved" else
                "correct clarification or unsupported handling", "outcome": outcome, "violations": [],
                "detail": reasons}
    if gold["config"] in SUPPLY:
        return {"class": "unnecessary clarification", "outcome": outcome, "violations": [], "detail": reasons}
    return {"class": "contained for another reason", "outcome": outcome, "violations": [], "detail": reasons}


# ------------------------------------------------------------------------------------------------ the model's reading
def model_reading(rec: dict[str, Any] | None, gold: dict[str, Any]) -> dict[str, Any] | None:
    """What the routing model read, against gold: reported, never gated by itself."""
    dec = (rec or {}).get("route")
    if rec is None or not dec:
        return None
    req = dec.get("requested") or {}
    fc = req.get("forecast") or {}
    q = rec["question"]
    clause_ok = anchors_ok(fc.get("request_text"), q, gold["request_anchors"], gold["excluded_anchors"])[0] \
        if gold["request_anchors"] and fc.get("request_text") else None
    return {"intent": dec.get("intent"), "needs_clarification": dec.get("needs_clarification"),
            "out_of_scope": dec.get("out_of_scope"), "domain": fc.get("domain"),
            "domain_matches_gold": fc.get("domain") == gold["domain"] if fc else None,
            "operation": fc.get("operation"),
            "operation_matches_gold": fc.get("operation") == gold["operation"] if gold["operation"] else None,
            "request_text": fc.get("request_text"), "request_text_on_the_request": clause_ok,
            "scope": fc.get("scope"), "scope_text": fc.get("scope_text"),
            "unsupported_text": fc.get("unsupported_text"), "run": req.get("forecast_run"),
            "as_of_text": dec.get("as_of_text"), "maximum": req.get("maximum")}


# ------------------------------------------------------------------------------------------------ the verdict
def records(freeze: dict[str, Any], live: Path = LIVE) -> dict[int, dict[str, Any] | None]:
    """Each slot's saved record (None if the log does not record it as saved)."""
    p = live / LOG_NAME / "run_log.jsonl"
    log = [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()] if p.exists() else []
    saved = {e["slot"] for e in log if e.get("event") == "slot_end" and e.get("outcome") == "saved"}
    out: dict[int, dict[str, Any] | None] = {}
    for s in freeze["slots"]:
        rp = live / freeze["label"] / f"{s['case']}.json"
        out[s["slot"]] = json.loads(rp.read_text()) if s["slot"] in saved and rp.exists() else None
    return out


def decide(freeze: dict[str, Any], recs: dict[int, dict[str, Any] | None],
           gold: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    gold = gold or gold_of()
    rows = []
    for s in freeze["slots"]:
        rec = recs.get(s["slot"])
        c = classify(rec, gold[s["config"]])
        rc = (rec or {}).get("route_call") or {}
        rows.append({"slot": s["slot"], "config": s["config"], "group": gold[s["config"]]["group"],
                     "class": c["class"], "outcome": c["outcome"], "violations": c["violations"], "detail": c["detail"],
                     "resolution_status": ((rec or {}).get("resolution") or {}).get("status"),
                     "tools_offered": (rec or {}).get("tools_offered"),
                     "model_reading": model_reading(rec, gold[s["config"]]),
                     "route_status": rc.get("status"), "input_tokens": rc.get("input_tokens"),
                     "output_tokens": rc.get("output_tokens"), "reasoning_tokens": rc.get("reasoning_tokens"),
                     "cached_tokens": rc.get("cached_tokens"), "duration_ms": rc.get("duration_ms"),
                     "ledger_cost_usd": ((rec or {}).get("score") or {}).get("ledger_cost_usd")})
    by = {cfg: [r for r in rows if r["config"] == cfg] for cfg in gold}
    violations = [f"slot {r['slot']} ({r['config']}): {x}" for r in rows for x in r["violations"]]
    unassessable_ = [r["slot"] for r in rows if r["class"] == "unassessable"]
    supplied = {cfg: sum(r["class"] == "correct resolved request" for r in by[cfg]) for cfg in SUPPLY}
    supply_ok = all(n >= SUPPLY_EACH for n in supplied.values()) and sum(supplied.values()) >= SUPPLY_TOTAL
    contained = {cfg: sum(r["class"] == "correct clarification or unsupported handling" for r in by[cfg])
                 for cfg in CONTAINMENT}
    undemonstrated = [cfg for cfg, n in contained.items() if n == 0]
    if violations:
        verdict = "FAIL"
    elif unassessable_:
        verdict = "INCOMPLETE"
    elif undemonstrated or not supply_ok:
        verdict = "INCONCLUSIVE"
    else:
        verdict = "PASS"
    costs = [r["ledger_cost_usd"] for r in rows if r["ledger_cost_usd"] is not None]

    def table(group: str) -> dict[str, Any]:
        return {cfg: {"set": "supply" if cfg in SUPPLY else "containment" if cfg in CONTAINMENT else "ambiguity",
                      "classes": dict(Counter(r["class"] for r in by[cfg])),
                      "outcomes": dict(Counter(str(r["outcome"]) for r in by[cfg]))}
                for cfg in gold if gold[cfg]["group"] == group}
    return {
        "verdict": verdict, "verdict_of": VERDICT_NAME, "not_claimed": NOT_CLAIMED,
        "coverage": {"assessable": len(rows) - len(unassessable_), "of": len(rows), "unassessable_slots": unassessable_},
        "violations": violations,
        "supply": {"each_config": supplied, "total": sum(supplied.values()), "of": 2 * len(SUPPLY),
                   "bars": {"each": SUPPLY_EACH, "total": SUPPLY_TOTAL}, "met": supply_ok},
        "containment": {"each_config": contained, "undemonstrated": undemonstrated},
        "ambiguity": {cfg: [{"slot": r["slot"], "class": r["class"], "outcome": r["outcome"]} for r in by[cfg]]
                      for cfg in AMBIGUITY},
        "familiar": table("familiar"), "fresh": table("fresh"),
        "extraction_misses": [r for r in rows if r["class"] == "incomplete or invalid"],
        "unnecessary_clarifications": [r for r in rows if r["class"] == "unnecessary clarification"],
        "contained_for_another_reason": [r for r in rows if r["class"] == "contained for another reason"],
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
