"""Score the routing-only Live check of route contract v15 (PROTOCOL.md, as amended by AMENDMENT_1.md) from the saved
records, offline. It never calls a model, and it reports routing and request resolution only: no answer, no H1–H5
review, no rate. Three layers are reported separately (AMENDMENT_1.md):

1. **The model's extraction** (``assess_extraction``): the routing model's own decision, item by item, against the
   independently verified extraction gold (`EXTRACTION_GOLD.json`). It is read from the decision alone, never inferred
   from the resolution. It has no pass threshold.
2. **Deterministic resolution and tool eligibility:** each call's resolution class and outcome, and whether the tools
   Live would offer are the gold's.
3. **The combined acceptance criteria** (PROTOCOL.md, with D08's gold amended): the verdict below, and its known
   blockers. No acceptance is claimed unless it is PASS.

``attribution`` crosses layer 1 with layer 2 for every call:
- errors caught by code;
- correct readings rejected by code;
- correct readings mis-resolved by code (resolver defects);
- incorrect readings accepted by code;
- correct end to end;
- calls with no reading.

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
               "fixed. It claims no architectural acceptance unless the combined verdict is PASS, which cannot occur as "
               "frozen.")


def _load(name: str) -> Any:
    return json.loads((HERE / name).read_text())


_SETS = {c["config"]: c["set"] for c in _load("cases.json")["cases"]}  # PROTOCOL.md, "Scope"
SUPPLY = [c for c, s in _SETS.items() if s == "supply"]
CONTAINMENT = [c for c, s in _SETS.items() if s == "containment"]
AMBIGUITY = [c for c, s in _SETS.items() if s == "ambiguity"]


def gold_of() -> dict[str, dict[str, Any]]:
    """The amended gold (AMENDMENT_1.md: D08 re-resolved; `GOLD.json` is the original, kept unchanged)."""
    return {g["config"]: g for g in _load("GOLD_AMENDED.json")["cases"]}


def extraction_gold_of() -> dict[str, dict[str, Any]]:
    return {x["config"]: x for x in _load("EXTRACTION_GOLD.json")["cases"]}


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


# ------------------------------------------------------------------------------------------------ layer 1: extraction
def _has_words(text: str | None, q: str, keys: list[str]) -> tuple[bool, str]:
    """Words copied from the question that contain every key word (case-insensitive)."""
    if not text:
        return False, "no words given"
    if text not in q:
        return False, f"the words {text!r} are not copied from the question"
    missing = [k for k in keys if k.lower() not in text.lower()]
    return (False, f"the words {text!r} lack the key words {missing}") if missing else (True, "")


def assess_extraction(rec: dict[str, Any] | None, x: dict[str, Any]) -> dict[str, Any]:
    """The routing model's own reading against the extraction gold, item by item (AMENDMENT_1.md, "Layer 1"). Read
    from the decision alone: a resolution that matches gold says nothing here."""
    dec = (rec or {}).get("route")
    if rec is None or not dec:
        return {"reading": "none", "items": {}, "errors": ["no reading: the response was rejected or not saved"]}
    q, req = rec["question"], dec.get("requested") or {}
    fc, run, mx = req.get("forecast"), req.get("forecast_run") or {}, req.get("maximum") or {}
    items: dict[str, tuple[bool, str]] = {
        "region": (dec.get("region") == x["region"], f"region {dec.get('region')}, gold {x['region']}"),
    }
    if x["intents_agreed"]:  # assessed only where both authors' intent sets agree (AMENDMENT_1.md)
        items["intent"] = (dec.get("intent") in x["intents"], f"intent {dec.get('intent')}, gold {x['intents']}")
    if x["local_dates"]:
        items["date"] = (dec.get("event_date") in x["local_dates"], f"date {dec.get('event_date')}, gold {x['local_dates']}")
    refused = bool(dec.get("out_of_scope"))
    if fc is None:
        items["domain"] = (x["domain"] == "none" or refused, f"no forecast reading given, gold {x['domain']}")
    else:
        dom = fc.get("domain")
        items["domain"] = (dom == x["domain"] or (x["domain"] == "none" and dom in (None, "none")),
                           f"domain {dom}, gold {x['domain']}")
        if x["operation"]:
            items["operation"] = (fc.get("operation") == x["operation"],
                                  f"operation {fc.get('operation')}, gold {x['operation']}")
        if x["request_anchors"] and x["domain"] != "none" and not refused:  # a forecast's clause, not a maximum's
            items["requested clause"] = anchors_ok(fc.get("request_text"), q, x["request_anchors"], x["excluded_anchors"])
        if x["scope_kinds"]:
            ok, why = _has_words(fc.get("scope_text"), q, x["scope_key_words"])
            items["scope"] = (fc.get("scope") in x["scope_kinds"] and ok,
                              f"scope {fc.get('scope')}, gold {x['scope_kinds']}; {why}".rstrip("; "))
        words = fc.get("unsupported_text")
        if x["unsupported_anchors"]:
            on = bool(words) and words in q and any(_overlaps(o, s) for o in _spans(words, q)
                                                    for a in x["unsupported_anchors"] for s in _spans(a, q))
            items["unsupported part"] = (on, f"unsupported words {words!r}, gold {x['unsupported_anchors']}")
        else:
            items["unsupported part"] = (not words, f"unsupported words {words!r} where the question asks for none")
    if x["run_rule"] is not None:  # null: no single demand run applies, and both authors left it unassessed
        rule = run.get("selection") or "none"
        ok = rule == x["run_rule"]
        why = f"run {rule}, gold {x['run_rule']}"
        if ok and x["run_rule"] != "none":
            ok_w, why_w = _has_words(run.get("selection_text"), q, x["run_key_words"])
            ok, why = ok and ok_w, f"{why}; {why_w}" if why_w else why
            if x["half_hour_key_words"]:
                ok_h, why_h = _has_words(run.get("half_hour_text"), q, x["half_hour_key_words"])
                ok, why = ok and ok_h, f"{why}; {why_h}" if why_h else why
        items["run"] = (ok, why)
    if x["cutoff_key_words"]:
        items["cutoff"] = _has_words(dec.get("as_of_text"), q, x["cutoff_key_words"])
    else:
        items["cutoff"] = (not dec.get("as_of_text"), f"cutoff words {dec.get('as_of_text')!r} where none is stated")
    if x["maximum"]:
        g = x["maximum"]
        ok = (mx.get("kind"), mx.get("measure"), mx.get("window")) == ("maximum", g["measure"], g["window"])
        ok_m, why_m = _has_words(mx.get("measure_text"), q, g["measure_key_words"])
        ok_w, why_w = _has_words(mx.get("window_text"), q, g["window_key_words"])
        items["maximum"] = (ok and ok_m and ok_w, f"maximum {mx.get('kind')} {mx.get('measure')} {mx.get('window')}, "
                            f"gold {g['measure']} {g['window']}; {why_m} {why_w}".strip())
    else:
        items["maximum"] = (mx.get("kind") in (None, "none"), f"maximum {mx.get('kind')} where none is asked")
    errors = [f"{k}: {why}" for k, (ok, why) in items.items() if not ok]
    return {"reading": "incorrect" if errors else "correct", "items": {k: ok for k, (ok, _) in items.items()},
            "errors": errors}


RESOLUTION_OF = {"correct resolved request": "correct", "correct clarification or unsupported handling": "correct",
                 "unnecessary clarification": "sent back", "contained for another reason": "sent back",
                 "violation": "wrong", "incomplete or invalid": "no reading", "unassessable": "unassessable"}
CELLS = {("correct", "correct"): "correct end to end",
         ("correct", "sent back"): "correct reading rejected by code",
         ("correct", "wrong"): "correct reading mis-resolved by code (resolver defect)",
         ("incorrect", "correct"): "error caught by code (outcome still correct)",
         ("incorrect", "sent back"): "error caught by code (sent back)",
         ("incorrect", "wrong"): "incorrect reading accepted by code"}


def attribution(extraction: dict[str, Any], cls: str) -> str:
    """Layer 1 crossed with layer 2 (AMENDMENT_1.md, "Attribution")."""
    res = RESOLUTION_OF[cls]
    if res == "unassessable":
        return "unassessable"
    if extraction["reading"] == "none" or res == "no reading":
        return "no reading (violation surviving)" if res == "wrong" else "no reading"
    return CELLS[(extraction["reading"], res)]


def eligibility_ok(rec: dict[str, Any] | None, gold: dict[str, Any]) -> bool | None:
    """Layer 2: whether the demand-forecast tools Live would offer are the gold's (None: not restricted, or no record)."""
    if rec is None or "tools_offered" not in rec or gold["demand_forecast_tools"] == "not_restricted":
        return None
    offered = bool(set(rec["tools_offered"]) & DEMAND_TOOLS)
    return offered if gold["demand_forecast_tools"] == "eligible" and rec["resolution"]["status"] == "ok" else \
        (not offered if gold["demand_forecast_tools"] == "not_used" else None)


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
           gold: dict[str, dict[str, Any]] | None = None,
           extraction_gold: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    gold = gold or gold_of()
    xgold = extraction_gold or extraction_gold_of()
    rows = []
    for s in freeze["slots"]:
        rec = recs.get(s["slot"])
        c = classify(rec, gold[s["config"]])
        e = assess_extraction(rec, xgold[s["config"]])
        rc = (rec or {}).get("route_call") or {}
        rows.append({"slot": s["slot"], "config": s["config"], "group": gold[s["config"]]["group"],
                     "extraction": e, "attribution": attribution(e, c["class"]),
                     "eligibility_ok": eligibility_ok(rec, gold[s["config"]]),
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
    cells = Counter(r["attribution"] for r in rows)
    field_errors = Counter(k for r in rows for k, ok in r["extraction"]["items"].items() if not ok)

    def by_cell(cell: str) -> list[str]:
        return [f"slot {r['slot']} ({r['config']})" for r in rows if r["attribution"] == cell]
    return {
        "layer_1_extraction": {
            "note": "The model's own reading against the independently verified extraction gold, item by item; never "
                    "inferred from the resolution. No pass threshold.",
            "readings": dict(Counter(r["extraction"]["reading"] for r in rows)),
            "errors_by_item": dict(field_errors),
            "familiar": dict(Counter(r["extraction"]["reading"] for r in rows if r["group"] == "familiar")),
            "fresh": dict(Counter(r["extraction"]["reading"] for r in rows if r["group"] == "fresh"))},
        "layer_2_resolution": {
            "classes": dict(Counter(r["class"] for r in rows)),
            "eligibility_wrong": [f"slot {r['slot']} ({r['config']})" for r in rows if r["eligibility_ok"] is False]},
        "attribution": {
            "counts": dict(cells),
            "errors_caught_by_code": by_cell(CELLS[("incorrect", "sent back")]) +
            by_cell(CELLS[("incorrect", "correct")]),
            "correct_readings_rejected_by_code": by_cell(CELLS[("correct", "sent back")]),
            "correct_readings_mis_resolved_by_code": by_cell(CELLS[("correct", "wrong")]),
            "incorrect_readings_accepted_by_code": by_cell(CELLS[("incorrect", "wrong")]),
            "correct_end_to_end": by_cell(CELLS[("correct", "correct")]),
            "no_reading": by_cell("no reading") + by_cell("no reading (violation surviving)")},
        "layer_3_combined": {"verdict": verdict, "verdict_of": VERDICT_NAME,
                             "known_blockers": "N04 (a declined weather forecast noted as unanswered by the code) and "
                                               "N07 (the code does not read 'noon'): PASS cannot occur as frozen "
                                               "(PROTOCOL.md, 'Known before the run')",
                             "acceptance_claimed": verdict == "PASS"},
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
