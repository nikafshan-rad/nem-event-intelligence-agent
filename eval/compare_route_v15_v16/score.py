"""Score the comparison (PROTOCOL.md, "Scoring" and "Acceptance criteria") from the saved records and the run log,
offline. It never calls a model. One arm-neutral definition scores both arms against the same frozen gold.

- **Layer 1, the model's extraction** (``assess_extraction``), from the decision alone, never from the resolution:
  ``reading`` adapts a v15 decision and a v16 plan to one common form, and only items both contracts can represent are
  scored for both arms. Words are judged by their key words, never by whether code can convert them. Plan-only items
  (B) are reported apart (``plan_items``).
- **Layer 2, resolution and tool eligibility** (``assess_resolution``): the outcome, exact resolution, critical
  violations C1–C6, silent omission, partial handling, the unsupported parts, and eligibility. The definitions the
  pre-registered protocol left open are fixed by AMENDMENT_1.md (before any run), the same for both arms:
  - **a prohibited binding retained in a sent-back record:** C4 when its words are declined or background words
    (labelled "retained", counted as critical); otherwise a reported, non-critical retained mis-binding. Both are scored
    apart from tool eligibility (C1, on the tools offered) and execution (C6, on tools executed and case-note writes);
  - **partial handling** is reported apart, never acceptable and never exact; its one binding is not also C3 for
    binding where the gold resolves none;
  - **silent omission** is defined against the gold: a gold-asked supported request in a resolution that proceeds is
    accounted for only when bound, served by an investigation the gold accepts with the demand-forecast tools it makes
    eligible, or (a demand forecast) named by the note that no operational demand forecast is given for it;
  - **the not-answered kinds** are structured: the kinds each not-answered note is built from, captured from the
    application's own note function in an offline re-resolution that reproduces the record exactly (``noted``). Every
    gold-asked unsupported part must be among them; declined and background parts are never required.
- **Attribution** crosses the two layers per slot.
- **The verdict** (``decide``), in the protocol's order: B FAILS, INCOMPLETE, INCONCLUSIVE, then MET or NOT MET with
  each unmet criterion named. Raw counts per call and per question are reported beside every rate and the interval.
- **V0** (``recompile_v0``): B's recorded plans compiled offline under V0; descriptive only.
- **Accounting** from the run log: reserved, settled, observed usage, unresolved and conservative, kept apart.

Usage: .venv/bin/python eval/compare_route_v15_v16/score.py [--live DIR] [--out SCORE.json]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import random
import re
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "src"))
LIVE = REPO / "artifacts" / "live"
LOG_NAME = "CMP-route-v15-v16"
DEMAND_TOOLS = {"get_forecast_runs", "compare_forecast_actual"}
NOT_ANSWERED = "Not answered:"
UNCLEAR_NOTE = "The question also mentions a forecast without showing which"
MEASURE = {"operational_demand": "operational demand", "dispatch_total_demand": "total demand"}
WINDOW = {"whole_local_day": "day", "event": "event", "explicit": "explicit"}
EVIDENCE_ROLES = ("operation", "subject", "request", "measure", "peak", "run_selection")
DEMAND_SUBJECTS = ("operational_demand", "demand_unspecified")
OTHER_SUBJECTS = ("weather", "price", "other", "unclear")
OP_CLASS = {"forecast_value": "value", "single_interval_comparison": "comparison", "window_comparison": "comparison",
            "forecast_comparison": "comparison", "demand_maximum": "maximum", "unclear": "unclear",
            "not_stated": "unclear"}
RESAMPLES, SEED, LOW, HIGH = 10_000, 20261005, 0.05, 0.95  # PROTOCOL.md, "The interval"
BOOTSTRAP = {"resamples": RESAMPLES, "seed": SEED, "low": LOW, "high": HIGH,
             "percentile": "inverted empirical CDF: the ceil(p·N)-th smallest of the N sorted differences"}
CRITERIA = {"gain_points": 0.15, "availability_floor": 0.80, "incomplete_margin_points": 0.05, "cost_ratio": 1.5}
NOT_CLAIMED = ("Routing-only evidence. It does not establish whether answers are correct or available in the data, how "
               "validators, repairs and fallbacks behave, the quality of interpretation, truncation during synthesis, "
               "whether the echo and clarification texts work for a reader, tool-call behaviour, or the cost and latency "
               "of a full investigation, and it does not generalise beyond the questions written. Zero observed "
               "violations does not establish a zero failure rate. Passing supports an end-to-end held-out check only; "
               "it does not authorize default enablement.")


def _sibling(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"compare_route_v15_v16_{name}", HERE / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------------------------------------ words
def _spans(text: str | None, q: str) -> list[tuple[int, int]]:
    out, i = [], q.find(text) if text else -1
    while text and i >= 0:
        out.append((i, i + len(text)))
        i = q.find(text, i + 1)
    return out


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def on_anchor(words: list[str | None], q: str, anchors: list[str]) -> bool:
    """Whether any of the words, located in the question, overlaps any anchor."""
    return any(_overlaps(o, s) for w in words for o in _spans(w, q) for a in anchors for s in _spans(a, q))


def has_words(text: str | None, q: str, keys: list[str]) -> bool:
    """Words copied from the question that contain every key word (case-insensitive)."""
    return text is not None and bool(text) and text in q and all(k.lower() in text.lower() for k in keys)


# ------------------------------------------------------------------------------------------------ gold
def is_supported(m: dict[str, Any]) -> bool:
    if m["kind"] == "demand_maximum":
        return m["subject"] in ("operational_demand", "dispatch_total_demand", "demand_unspecified")
    return m["kind"] != "unclear" and m["subject"] in DEMAND_SUBJECTS


def asked_supported(g: dict[str, Any]) -> list[dict[str, Any]]:
    return [m for m in g["mentions"] if m["stance"] == "asked" and is_supported(m)]


def target_mention(g: dict[str, Any]) -> dict[str, Any] | None:
    """The gold's one asked supported request: the primary, else the only one."""
    prim = [m for m in g["mentions"] if m.get("primary")]
    if prim:
        return prim[0]
    sup = asked_supported(g)
    return sup[0] if len(sup) == 1 else None


def inactive_anchors(g: dict[str, Any]) -> list[str]:
    return [a for m in g["mentions"] if m["stance"] in ("declined", "background") for a in m["anchors"]]


# ------------------------------------------------------------------------------------------------ layer 1: reading
def _req(family: str, subject: str | None, op: str | None, words: list[str | None], scope: tuple[Any, Any] | None,
         run: tuple[str, Any], cutoff: str | None, alt_scope: str | None = None) -> dict[str, Any]:
    return {"family": family, "subject": subject, "op_class": op, "words": [w for w in words if w],
            "scope": scope, "alt_scope_text": alt_scope, "run": run, "cutoff": cutoff}


def reading(rec: dict[str, Any] | None) -> dict[str, Any] | None:
    """The model's reading in one form for both contracts, or None (no reading)."""
    if rec is None or rec.get("api_error") or rec.get("route_invalid") or not rec.get("decision"):
        return None
    dec = rec["decision"]
    base = {"intent": dec.get("intent"), "region": dec.get("region"), "date": dec.get("event_date"),
            "out_of_scope": dec.get("out_of_scope")}
    if "plan" in dec:
        return {**base, "contract": "v16", **_plan_reading(dec["plan"])}
    return {**base, "contract": "v15", **_v15_reading(dec)}


def _v15_reading(dec: dict[str, Any]) -> dict[str, Any]:
    rq = dec.get("requested") or {}
    fc, run, mx = rq.get("forecast") or {}, rq.get("forecast_run") or {}, rq.get("maximum") or {}
    sel = run.get("selection") or "none"
    run_t = (sel, run.get("selection_text"))
    reqs, others = [], []
    dom, op = fc.get("domain"), fc.get("operation")
    if dom not in (None, "none") or op not in (None, "none"):
        subj = {"operational_demand": "operational_demand"}.get(str(dom), dom if dom not in ("none",) else None)
        reqs.append(_req("forecast", subj, OP_CLASS.get(str(op)), [fc.get("request_text"), fc.get("operation_text")],
                         (fc.get("scope"), fc.get("scope_text")), run_t, dec.get("as_of_text"),
                         run.get("half_hour_text")))
        if dom in OTHER_SUBJECTS:
            others.append((dom, [fc.get("request_text"), fc.get("operation_text")]))
    if fc.get("unsupported_text"):
        others.append((None, [fc.get("unsupported_text")]))
    if mx.get("kind") in ("maximum", "unclear"):
        subj = {"unspecified": "demand_unspecified", None: "unclear"}.get(mx.get("measure"), mx.get("measure"))
        reqs.append(_req("maximum", subj, "maximum", [mx.get("measure_text"), mx.get("peak_text")],
                         (mx.get("window"), mx.get("window_text")), run_t, dec.get("as_of_text")))
    return {"requests": reqs, "others": others,
            "request_words": [w for r in reqs for w in r["words"]], "plan": None}


def _plan_reading(plan: dict[str, Any]) -> dict[str, Any]:
    scopes = {s["id"]: s for s in plan.get("scopes") or []}
    runs = {r["id"]: r for r in plan.get("runs") or []}
    cutoffs = {c["id"]: c for c in plan.get("cutoffs") or []}
    reqs, others = [], []
    for o in plan.get("operations") or []:
        if o.get("stance") != "asked":
            continue
        fam = {"forecast_value": "forecast", "forecast_comparison": "forecast",
               "demand_maximum": "maximum"}.get(o.get("kind"), "unknown")
        subj = "unclear" if o.get("subject") == "not_stated" else o.get("subject")
        sc = scopes.get(o.get("scope_ref") or "")
        rn = runs.get(o.get("run_ref") or "")
        co = cutoffs.get(o.get("cutoff_ref") or plan.get("cutoff_ref") or "")
        words = [o.get("operation_text"), o.get("subject_text")]
        reqs.append(_req(fam, subj, OP_CLASS.get(str(o.get("kind"))), words,
                         (sc["kind"], sc["text"]) if sc else None,
                         (rn["selection"], rn["text"]) if rn else ("none", None), co["text"] if co else None))
        if subj in OTHER_SUBJECTS:
            others.append((subj, words))
    return {"requests": reqs, "others": others, "request_words": [w for r in reqs for w in r["words"]],
            "plan": plan}


def _subject_ok(m: dict[str, Any], subject: str | None) -> bool:
    if m["kind"] != "demand_maximum" and m["subject"] in DEMAND_SUBJECTS:
        return subject in DEMAND_SUBJECTS
    return subject == m["subject"]


def _family(m: dict[str, Any]) -> str:
    return "maximum" if m["kind"] == "demand_maximum" else "forecast"


def _corresponds(r: dict[str, Any], m: dict[str, Any], q: str) -> bool:
    return r["family"] == _family(m) and _subject_ok(m, r["subject"]) and r["op_class"] == OP_CLASS[m["kind"]] and \
        (not r["words"] or on_anchor(r["words"], q, m["anchors"]))


def match_request(rd: dict[str, Any], m: dict[str, Any], q: str) -> dict[str, Any] | None:
    cands = [r for r in rd["requests"] if r["family"] == _family(m)]
    on = [r for r in cands if on_anchor(r["words"], q, m["anchors"])]
    return (on or cands or [None])[0]


def _named_other(rd: dict[str, Any], m: dict[str, Any], q: str) -> bool:
    return any((s == m["subject"] or (s is None and m["subject"] in ("weather", "price", "other"))) and
               (not [w for w in ws if w] or on_anchor(ws, q, m["anchors"])) for s, ws in rd["others"])


def assess_extraction(rec: dict[str, Any] | None, g: dict[str, Any]) -> dict[str, Any]:
    """The common items (PROTOCOL.md, "Layer 1"), for both arms; plan-only items apart."""
    rd = reading(rec)
    if rd is None:
        return {"reading": "none", "items": {}, "errors": ["no reading"], "plan_items": None}
    assert rec is not None
    q = rec["question"]
    items: dict[str, tuple[bool, str]] = {}
    if g["intents"]:
        items["intent"] = (rd["intent"] in g["intents"], f"intent {rd['intent']}, gold {g['intents']}")
    if not (rec.get("request") or {}).get("region"):
        items["region"] = (rd["region"] == g["region"], f"region {rd['region']}, gold {g['region']}")
    if g["local_dates"]:
        items["date"] = (rd["date"] in g["local_dates"], f"date {rd['date']}, gold {g['local_dates']}")
    sup = asked_supported(g)
    m = target_mention(g)
    rdr = g.get("reader")
    if len(sup) >= 2:
        supported_read = [r for r in rd["requests"] if r["family"] != "unknown" and
                          (r["subject"] in DEMAND_SUBJECTS or r["family"] == "maximum")]
        ok = bool(supported_read) and all(any(_corresponds(r, x, q) for x in sup) for r in supported_read)
        items["asked_request"] = (ok, "the request read is not one of the gold's asked requests")
    elif m is not None and rdr is not None:
        r = match_request(rd, m, q)
        if r is None:
            items["request"] = (False, f"no {_family(m)} request read")
        else:
            items["subject"] = (_subject_ok(m, r["subject"]), f"subject {r['subject']}, gold {m['subject']}")
            items["operation"] = (r["op_class"] == OP_CLASS[m["kind"]],
                                  f"operation {r['op_class']}, gold {OP_CLASS[m['kind']]}")
            kind, text = r["scope"] or (None, None)
            if m["kind"] == "demand_maximum" and rdr.get("maximum"):
                gm = rdr["maximum"]
                items["scope"] = (kind == gm["window"] and has_words(text, q, gm["window_key_words"]),
                                  f"window {kind} {text!r}, gold {gm['window']} {gm['window_key_words']}")
            elif rdr["scope_kinds"]:
                words_ok = has_words(text, q, rdr["scope_key_words"]) or \
                    has_words(r["alt_scope_text"], q, rdr["scope_key_words"])
                items["scope"] = (kind in rdr["scope_kinds"] and words_ok,
                                  f"scope {kind} {text!r}, gold {rdr['scope_kinds']} {rdr['scope_key_words']}")
            rule, rtext = r["run"]
            items["run"] = (rule == rdr["run_rule"] and (rule == "none" or has_words(rtext, q, rdr["run_key_words"])),
                            f"run {rule} {rtext!r}, gold {rdr['run_rule']} {rdr['run_key_words']}")
            keys = rdr["cutoff_key_words"]
            items["cutoff"] = (has_words(r["cutoff"], q, keys) if keys else r["cutoff"] is None,
                               f"cutoff words {r['cutoff']!r}, gold {keys}")
    other = [x for x in g["mentions"] if x["stance"] == "asked" and x["subject"] in OTHER_SUBJECTS]
    if other:
        items["other_kind"] = (any(_named_other(rd, x, q) for x in other),
                               f"no other kind named on {[x['anchors'] for x in other]}")
    inact = inactive_anchors(g)
    if inact:
        items["declined_or_background"] = (not on_anchor(rd["request_words"], q, inact),
                                           "request words overlap a declined or background mention")
    errors = [f"{k}: {why}" for k, (ok, why) in items.items() if not ok]
    return {"reading": "incorrect" if errors else "correct", "items": {k: ok for k, (ok, _) in items.items()},
            "errors": errors, "plan_items": plan_items(rd, g, q) if rd["plan"] is not None else None}


def plan_items(rd: dict[str, Any], g: dict[str, Any], q: str) -> dict[str, Any]:
    """Plan-only items (B), reported separately: stances, references, the plan-level cutoff, located words."""
    plan = rd["plan"]
    ops = plan.get("operations") or []
    stances = []
    for m in g["mentions"]:
        hit = [o for o in ops if on_anchor([o.get("operation_text"), o.get("subject_text")], q, m["anchors"])]
        stances.append(bool(hit) and any(o.get("stance") == m["stance"] for o in hit))
    out: dict[str, Any] = {"stances_correct": sum(stances), "mentions": len(stances)}
    m, rdr = target_mention(g), g.get("reader")
    if m is not None and rdr is not None:
        op = next((o for o in ops if o.get("stance") == "asked" and
                   on_anchor([o.get("operation_text"), o.get("subject_text")], q, m["anchors"])), None)
        if op is not None:
            want_scope = bool(rdr["scope_kinds"] or rdr.get("maximum"))
            out["scope_ref"] = (op.get("scope_ref") is not None) == want_scope
            out["run_ref"] = (op.get("run_ref") is not None) == (rdr["run_rule"] != "none")
            out["cutoff_ref"] = (op.get("cutoff_ref") is not None or plan.get("cutoff_ref") is not None) == \
                bool(rdr["cutoff_key_words"])
        else:
            out["primary_operation_found"] = False
    out["plan_cutoff_ref"] = plan.get("cutoff_ref")
    texts = [t for o in ops for t in (o.get("operation_text"), o.get("subject_text")) if t] + \
        [x["text"] for k in ("scopes", "runs", "cutoffs") for x in plan.get(k) or []]
    out["located_words"] = sum(1 for t in texts if len(_spans(t, q)) == 1)
    out["words"] = len(texts)
    return out


# ------------------------------------------------------------------------------------------------ layer 2
UNSUPPORTED_KINDS = ("weather", "price", "other")
_RR: Any = None


def _run_route() -> Any:
    global _RR
    if _RR is None:
        _RR = _sibling("run_route")
    return _RR


def note_text_kinds(notes: list[str]) -> list[str]:
    """Kinds read from not-answered note text: the fallback only. The text names `other` only when it is the sole kind
    ("another kind of"): beside weather or price it drops it (AMENDMENT_1.md, "Not-answered kinds")."""
    kinds: set[str] = set()
    for n in notes:
        if n.startswith(NOT_ANSWERED):
            mt = re.search(r"asks about a (.+?) forecast", n)
            what = mt.group(1) if mt else ""
            if what == "another kind of":
                kinds.add("other")
            kinds.update(k for k in ("weather", "price") if re.search(rf"\b{k}\b", what))
    return sorted(kinds)


def resolve_capturing(rec: dict[str, Any], policy: str | None) -> tuple[Any, list[list[str]]]:
    """The recorded decision resolved offline exactly as ``run_route.route_call`` resolves it, capturing the kinds each
    not-answered note is built from: the application's own ``not_answered_note`` is wrapped, its text and behaviour
    unchanged. ``policy``: the stated-basis policy for a v16 plan (B: V1; the descriptive recompilation: V0)."""
    from unittest import mock

    from nem_agent.agent import plan as plan_module
    from nem_agent.agent import structured
    from nem_agent.agent.live import RouteDecision
    from nem_agent.agent.plan import PlanRouteDecision
    from nem_agent.agent.request import InvestigateRequest
    from nem_agent.service import _shared, resolve_routed

    calls: list[list[str]] = []
    original = structured.not_answered_note

    def spy(kinds: list[str]) -> str:
        calls.append(sorted(str(k) for k in kinds))
        return original(kinds)

    env = {"NEM_AGENT_PLAN_POLICY": policy} if policy else {}
    with mock.patch.object(structured, "not_answered_note", spy), \
            mock.patch.object(plan_module, "not_answered_note", spy), mock.patch.dict(os.environ, env):
        d = rec["decision"]
        dec = (PlanRouteDecision if "plan" in d else RouteDecision).model_validate(d)
        req = InvestigateRequest(question=rec["question"], mode="live", **(rec.get("request") or {}))
        res = resolve_routed(req, dec, _shared()[1], None)
    return res, calls


def _canonical(x: Any) -> str:
    return json.dumps(x, sort_keys=True, default=str)


def note_calls(rec: dict[str, Any]) -> tuple[list[list[str]] | None, str]:
    """The kinds of each not-answered note in a record, and where they come from: an offline re-resolution of its
    decision that reproduces its resolution and tools exactly (both arms alike), or None (the record's fields only)."""
    if "_note_calls" in rec:
        return rec["_note_calls"], "recompiled"
    if not rec.get("decision") or rec.get("resolution") is None:
        return None, "record (no decision)"
    rr = _run_route()
    try:
        res, calls = resolve_capturing(rec, rr.ARM_ENV["B"]["NEM_AGENT_PLAN_POLICY"] if "plan" in rec["decision"]
                                       else None)
    except Exception as exc:  # a decision that cannot be resolved again: the record's own fields are used, flagged
        return None, f"record (re-resolution failed: {type(exc).__name__})"
    same = _canonical(rr.resolution_record(res)) == _canonical(rec["resolution"]) and \
        rr.tools_offered(res) == (rec.get("tools_offered") or [])
    return (calls, "re-resolution") if same else (None, "record (re-resolution did not reproduce it)")


def noted(rec: dict[str, Any]) -> dict[str, Any]:
    """What the resolution's notes name as not answered: the kinds (weather, price, other), and whether a note says a
    forecast is mentioned without showing which. Structured where available (AMENDMENT_1.md, "Not-answered kinds"):
    the captured note kinds; otherwise the bound forecast's ``unsupported`` kinds with the note text, flagged."""
    rq = rec["resolution"].get("requests") or {}
    calls, source = note_calls(rec)
    if calls is not None:
        return {"kinds": sorted({k for c in calls for k in c}), "unclear": any(not c for c in calls),
                "source": source}
    notes = rq.get("notes") or []
    kinds = set((rq.get("forecast") or {}).get("unsupported") or []) | set(note_text_kinds(notes))
    return {"kinds": sorted(kinds), "unclear": any(n.startswith(UNCLEAR_NOTE) for n in notes), "source": source}


def unsupported_parts(g: dict[str, Any], nk: dict[str, Any]) -> dict[str, Any]:
    """Every gold-asked unsupported part (a weather, price or other forecast the gold marks asked) must be named as not
    answered, and a gold-asked forecast of an unshown kind must be covered by a note; declined and background parts are
    never required, and naming one is an error unless an asked forecast of an unshown kind could be the one named."""
    asked = sorted({m["subject"] for m in g["mentions"] if m["stance"] == "asked" and m["subject"] in UNSUPPORTED_KINDS})
    inactive = {m["subject"] for m in g["mentions"] if m["stance"] != "asked" and m["subject"] in UNSUPPORTED_KINDS}
    asked_unclear = any(m["stance"] == "asked" and m["subject"] == "unclear" for m in g["mentions"])
    missing = [k for k in asked if k not in nk["kinds"]]
    unclear_missing = asked_unclear and not (nk["unclear"] or nk["kinds"])
    extra = [] if asked_unclear else [k for k in nk["kinds"] if k not in asked]
    return {"required": asked, "named": nk["kinds"], "unclear_named": nk["unclear"], "missing": missing,
            "unclear_missing": unclear_missing, "extra": extra,
            "declined_or_background_named": [k for k in extra if k in inactive],
            "accounted": not missing and not unclear_missing and not extra, "source": nk["source"]}


def _named(rq: dict[str, Any]) -> bool:
    return any(n.startswith(NOT_ANSWERED) or n.startswith(UNCLEAR_NOTE) for n in rq.get("notes") or [])


def _bound(rq: dict[str, Any], k: str) -> dict[str, Any] | None:
    x = rq.get(k) or {}
    return x if x.get("status") == "bound" else None


def outcome_of(rec: dict[str, Any] | None) -> str:
    """resolved, clarify, refusal, event_review_without_demand_forecast, proceeds_unbound, or no_reading."""
    if rec is None or rec.get("api_error") or rec.get("route_invalid") or rec.get("resolution") is None:
        return "no_reading"
    res = rec["resolution"]
    rq = res.get("requests") or {}
    if res["status"] == "refused":
        return "refusal"
    if res["status"] != "ok":
        return "clarify"
    if _bound(rq, "forecast") or _bound(rq, "maximum"):
        return "resolved"
    if res.get("intent") == "market_event_review" and not set(rec.get("tools_offered") or []) & DEMAND_TOOLS and \
            _named(rq):
        return "event_review_without_demand_forecast"
    return "proceeds_unbound"


def _run_want(gres: dict[str, Any] | None) -> tuple[Any, ...]:
    run = (gres or {}).get("run") or {"rule": "none"}
    if run["rule"] in ("last_issued_before", "issued_at"):
        return ("bound", run["rule"], run["half_hour_end_utc"], run.get("issued_at_utc") if run["rule"] == "issued_at"
                else None)
    return ("as_of_availability",) if run["rule"] == "as_of_availability" else ("absent",)


def _run_got(fr: dict[str, Any]) -> tuple[Any, ...]:
    if fr.get("status") == "bound":
        return ("bound", fr.get("selection"), (fr.get("half_hour_utc") or [None, None])[1],
                fr.get("issued_at_utc") if fr.get("selection") == "issued_at" else None)
    return (fr.get("status") or "absent",)


def binding_mismatches(fa: dict[str, Any] | None, fr: dict[str, Any] | None, mx: dict[str, Any] | None,
                       gres: dict[str, Any] | None, partial_ok: bool) -> list[str]:
    """Bound requests other than the gold's, or bound where the gold resolves none (what C3 prohibits in a resolution
    that proceeds). ``partial_ok``: a question with two asked supported requests and no gold resolution, whose one
    binding is partial handling, not this."""
    out = []
    if fa:
        if gres is None or gres["operation"] is None:
            if not partial_ok:
                out.append(f"a forecast request is bound ({fa.get('operation')}) where the gold resolves none")
        else:
            s = gres["scope"]
            got = (fa.get("operation"), fa.get("target_utc") or fa.get("window_utc"), fa.get("half_hours"))
            want = (gres["operation"], [s["start_utc"], s["end_utc"]], s["half_hours"])
            if got != want:
                out.append(f"forecast {got}, gold {want}")
    if fr and not (gres is None and partial_ok) and _run_got(fr) != _run_want(gres):
        out.append(f"run {_run_got(fr)}, gold {_run_want(gres)}")
    if mx:
        gm = (gres or {}).get("maximum")
        if gm is None:
            if not partial_ok:
                out.append(f"a maximum is bound ({mx.get('measures')}) where the gold resolves none")
        else:
            got_mx = (mx.get("measures"), mx.get("window_kind"), mx.get("window_utc"))
            want_mx = ([MEASURE[gm["measure"]]], WINDOW[gm["window_kind"]], [gm["start_utc"], gm["end_utc"]])
            if got_mx != want_mx:
                out.append(f"maximum {got_mx}, gold {want_mx}")
    return out


def assess_resolution(rec: dict[str, Any] | None, g: dict[str, Any], set_: str) -> dict[str, Any]:
    """Outcome, critical violations, retained bindings, silent omission, partial handling, unsupported parts,
    eligibility and exact resolution (PROTOCOL.md, "Layer 2", as amended by AMENDMENT_1.md)."""
    out: dict[str, Any] = {"outcome": outcome_of(rec), "violations": [], "silent_omission": False, "partial": False,
                           "served_not_bound": False, "retained_mis_binding": [], "unsupported_parts": None,
                           "exact": False, "acceptable": False, "eligibility_ok": None}
    if rec is None:
        return out
    v: list[str] = []
    sc = rec.get("score") or {}
    if sc.get("case_note_files_written") or sc.get("tools_executed"):  # C6: execution, from the record's own counts
        v.append(f"C6: {sc.get('tools_executed')} tool(s) executed, {sc.get('case_note_files_written')} case-note "
                 "file(s) written")
    res = rec.get("resolution")
    if res is None:
        out["violations"] = v
        return out
    q = rec["question"]
    rq = res.get("requests") or {}
    fa, fr, mx = _bound(rq, "forecast"), _bound(rq, "forecast_run"), _bound(rq, "maximum")
    proceeds = res["status"] == "ok"
    tools = set(rec.get("tools_offered") or [])
    gres = g["resolution"]
    sup = asked_supported(g)
    multi = len(sup) >= 2
    has_reading = reading(rec) is not None
    if has_reading:  # C4, whatever the status; a retained one is labelled apart (AMENDMENT_1.md)
        inact = inactive_anchors(g)
        ev = [tuple(o) for b in (fa, fr, mx) if b for s in b.get("spans") or [] if s.get("role") in EVIDENCE_ROLES
              for o in s.get("occurrences") or []]
        hit = [a for a in inact if any(_overlaps(o, s) for o in ev for s in _spans(a, q))]
        if hit:
            where = "" if proceeds else " (retained in a sent-back record)"
            v.append(f"C4{where}: a bound request's words overlap the declined or background words {hit}")
    if proceeds:
        if g["demand_forecast_tools"] == "not_used" and tools & DEMAND_TOOLS:
            v.append(f"C1: {sorted(tools & DEMAND_TOOLS)} offered where the gold says demand tools are not used")
        if res.get("as_of_utc") != g["cutoff_utc"]:
            v.append(f"C2: cutoff {res.get('as_of_utc')}, gold {g['cutoff_utc']}")
        if res.get("region") is not None and res["region"] != g["region"]:
            v.append(f"C3: region {res['region']}, gold {g['region']}")
        v += [f"C3: {x}" for x in binding_mismatches(fa, fr, mx, gres, multi and gres is None)]
        if set_ == "control":
            v.append("C5: a known-unsupported control proceeds")
        nk = noted(rec)
        out["unsupported_parts"] = unsupported_parts(g, nk)
        maxima = [m for m in sup if m["kind"] == "demand_maximum"]
        unbound_max = max(0, len(maxima) - (1 if mx else 0))
        unbound_fc = max(0, len(sup) - len(maxima) - (1 if fa else 0))
        served = unbound_fc > 0 and res.get("intent") in g["intents"] and \
            g["demand_forecast_tools"] == "eligible" and bool(tools & DEMAND_TOOLS)
        out["served_not_bound"] = served
        out["silent_omission"] = unbound_max > 0 or (unbound_fc > 0 and not served and not nk["unclear"])
        out["partial"] = multi and not out["silent_omission"] and not served and bool(fa or mx) and \
            unbound_max + unbound_fc > 0
    elif has_reading:  # a binding retained in a sent-back record that C3 would prohibit: reported, not critical
        out["retained_mis_binding"] = binding_mismatches(fa, fr, mx, gres, False)
    out["violations"] = v
    d = g["demand_forecast_tools"]
    out["eligibility_ok"] = None if d == "not_restricted" else (bool(tools & DEMAND_TOOLS) == (d == "eligible"))
    if out["outcome"] == "resolved" and gres is not None and not v and not out["silent_omission"] and \
            not out["partial"]:  # partial handling is never exact (AMENDMENT_1.md)
        mism = []
        if res.get("region") != g["region"]:
            mism.append("region")
        if res.get("intent") not in g["intents"]:
            mism.append("intent")
        if gres["operation"] is not None:
            s = gres["scope"]
            if not fa or fa.get("scope") not in s["kinds"] or fa.get("operation") != gres["operation"] or \
                    (fa.get("target_utc") or fa.get("window_utc")) != [s["start_utc"], s["end_utc"]] or \
                    fa.get("half_hours") != s["half_hours"]:
                mism.append("forecast")
            if mx:
                mism.append("an extra maximum")
        if gres["maximum"] is not None:
            if not mx:
                mism.append("maximum")
            if fa:
                mism.append("an extra forecast")
        if _run_got(rq.get("forecast_run") or {}) != _run_want(gres):
            mism.append("run")
        if res.get("as_of_utc") != g["cutoff_utc"]:
            mism.append("cutoff")
        parts = out["unsupported_parts"]
        if parts["named"] != sorted(gres["not_answered"]) or not parts["accounted"]:
            mism.append(f"not answered {parts['named']}, gold {sorted(gres['not_answered'])}")
        if out["eligibility_ok"] is False:
            mism.append("tool eligibility")
        out["exact"] = not mism
        out["mismatch"] = mism
    review_ok = out["outcome"] != "event_review_without_demand_forecast" or bool(
        out["unsupported_parts"] and out["unsupported_parts"]["accounted"])
    out["acceptable"] = out["outcome"] in g["acceptable_outcomes"] and not v and not out["silent_omission"] and \
        not out["partial"] and (out["outcome"] != "resolved" or out["exact"]) and \
        out["eligibility_ok"] is not False and review_ok
    return out


CELLS = {("correct", "correct"): "correct end to end", ("correct", "sent back"): "correct reading rejected by code",
         ("correct", "wrong"): "correct reading mis-resolved by code",
         ("incorrect", "correct"): "incorrect reading caught by code",
         ("incorrect", "sent back"): "incorrect reading caught by code",
         ("incorrect", "wrong"): "incorrect reading accepted by code"}


def attribution(ext: dict[str, Any], l2: dict[str, Any]) -> str:
    if ext["reading"] == "none" or l2["outcome"] == "no_reading":
        return "no reading"
    if l2["violations"] or l2["silent_omission"] or l2["partial"] or l2["outcome"] == "proceeds_unbound" or \
            (l2["outcome"] == "resolved" and not l2["acceptable"]):
        res = "wrong"
    elif l2["acceptable"]:
        res = "correct"
    else:
        res = "sent back"
    return CELLS[(ext["reading"], res)]


def control_safe(rec: dict[str, Any] | None) -> bool:
    """A control slot sent back safely: a saved resolution that does not proceed, binds nothing and offers no
    demand-forecast tool. An API error or an interrupted slot demonstrates nothing."""
    if rec is None or rec.get("api_error") or rec.get("resolution") is None:
        return False
    rq = rec["resolution"].get("requests") or {}
    return rec["resolution"]["status"] != "ok" and not any(_bound(rq, k) for k in ("forecast", "forecast_run",
                                                                                     "maximum")) and \
        not set(rec.get("tools_offered") or []) & DEMAND_TOOLS


# ------------------------------------------------------------------------------------------------ records
def read_log(live: Path = LIVE) -> list[dict[str, Any]]:
    p = live / LOG_NAME / "run_log.jsonl"
    return [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()] if p.exists() else []


def records(freeze: dict[str, Any], log: list[dict[str, Any]], live: Path = LIVE
            ) -> dict[int, tuple[str | None, dict[str, Any] | None, dict[str, Any] | None]]:
    """Each slot's terminal outcome (from the log; None: no terminal record), saved record and log entry."""
    ends = {e["slot"]: e for e in log if e.get("event") in ("slot_end", "interrupted")}
    out = {}
    for s in freeze["slots"]:
        e = ends.get(s["slot"])
        term = e["outcome"] if e and e["outcome"] in ("saved", "api_error", "interrupted") else None
        p = live / freeze["label"] / f"{s['case']}.json"
        rec = json.loads(p.read_text()) if term in ("saved", "api_error") and p.exists() else None
        if term in ("saved", "api_error") and rec is None:
            term = None  # the log says it was recorded, but the record is missing
        out[s["slot"]] = (term, rec, e)
    return out


# ------------------------------------------------------------------------------------------------ V0
def recompile_v0(rec: dict[str, Any]) -> dict[str, Any] | None:
    """B's recorded plan compiled offline under V0 (descriptive only): the record with its resolution and tools
    replaced, and the kinds of its not-answered notes captured. None when the slot has no plan."""
    if not rec or not rec.get("decision") or "plan" not in rec["decision"]:
        return None
    rr = _run_route()
    res, calls = resolve_capturing(rec, "V0")
    return {**rec, "resolution": rr.resolution_record(res), "tools_offered": rr.tools_offered(res),
            "_note_calls": calls}


# ------------------------------------------------------------------------------------------------ the verdict
def bootstrap(per_q: dict[str, tuple[int, int, int]], resamples: int = RESAMPLES, seed: int = SEED) -> dict[str, Any]:
    """Paired, clustered by question: (A exact, B exact, repeats) per question; B's availability minus A's."""
    qs = sorted(per_q)
    if not qs:
        return {"low": None, "high": None, "resamples": 0}
    rng = random.Random(seed)
    diffs = []
    for _ in range(resamples):
        draw = [qs[rng.randrange(len(qs))] for _ in qs]
        n = sum(per_q[x][2] for x in draw)
        diffs.append((sum(per_q[x][1] for x in draw) - sum(per_q[x][0] for x in draw)) / n)
    diffs.sort()
    def pick(p: float) -> float:
        return diffs[math.ceil(p * resamples) - 1]
    return {"low": round(pick(LOW), 6), "high": round(pick(HIGH), 6),
            "resamples": resamples, "seed": seed, "method": BOOTSTRAP["percentile"]}


def _rate(x: int, n: int) -> float | None:
    return round(x / n, 6) if n else None


def decide(freeze: dict[str, Any], gold: dict[str, dict[str, Any]], recs: dict[int, Any],
           v0: bool = True) -> dict[str, Any]:
    den = freeze["denominators"]
    answerable = set(den["answerable_heldout_configs"])
    rows = []
    for s in freeze["slots"]:
        term, rec, entry = recs[s["slot"]]
        g = gold[s["config"]]
        ext = assess_extraction(rec, g)
        l2 = assess_resolution(rec, g, s["set"])
        rc = (rec or {}).get("route_call") or {}
        rows.append({"slot": s["slot"], "case": s["case"], "config": s["config"], "set": s["set"], "arm": s["arm"],
                     "family": g.get("family", "development"), "repeat": s["repeat"], "terminal": term,
                     "extraction": ext, **l2, "attribution": attribution(ext, l2),
                     "control_safe": control_safe(rec) if s["set"] == "control" else None,
                     "route_status": rc.get("status"), "incomplete": rc.get("status") == "incomplete",
                     "input_tokens": rc.get("input_tokens"), "output_tokens": rc.get("output_tokens"),
                     "reasoning_tokens": rc.get("reasoning_tokens"), "reported_model": rc.get("reported"),
                     "settled_usd": (entry or {}).get("settled_usd"), "observed_usd": (entry or {}).get("observed_usd"),
                     "conservative_usd": (entry or {}).get("conservative_usd"),
                     "reserved_usd": s["reservation_usd"], "unresolved": (entry or {}).get("unresolved"),
                     "api_error": (rec or {}).get("api_error"), "v0": None})
        if v0 and s["arm"] == "B" and rec is not None:
            r0 = recompile_v0(rec)
            if r0 is not None:
                rows[-1]["v0"] = assess_resolution(r0, g, s["set"])
    arm = {a: [r for r in rows if r["arm"] == a] for a in ("A", "B")}

    def summary(rs: list[dict[str, Any]], a: str) -> dict[str, Any]:
        avail = [r for r in rs if r["config"] in answerable]
        held = [r for r in rs if r["set"] in ("heldout", "control")]
        per_q = Counter(sum(r["exact"] for r in avail if r["config"] == c) for c in answerable)
        settled = [r["settled_usd"] for r in rs if r["terminal"] == "saved" and r["settled_usd"] is not None]
        return {
            "slots": len(rs),
            "availability": {"exact": sum(r["exact"] for r in avail), "of": den["availability_slots_per_arm"],
                             "rate": _rate(sum(r["exact"] for r in avail), den["availability_slots_per_arm"]),
                             "questions_by_exact_repeats": {str(k): per_q.get(k, 0) for k in (3, 2, 1, 0)}},
            "incomplete": {"count": sum(r["incomplete"] for r in held), "of": den["incomplete_rate_slots_per_arm"],
                           "rate": _rate(sum(r["incomplete"] for r in held), den["incomplete_rate_slots_per_arm"])},
            "outcomes_by_set": {st: dict(Counter(r["outcome"] for r in rs if r["set"] == st))
                                for st in ("heldout", "control", "development")},
            "acceptable_by_set": {st: f"{sum(r['acceptable'] for r in rs if r['set'] == st)} of "
                                      f"{sum(1 for r in rs if r['set'] == st)}"
                                  for st in ("heldout", "control", "development")},
            "violations": {code: sum(any(x.startswith(code) for x in r["violations"]) for r in rs)
                           for code in ("C1", "C2", "C3", "C4", "C5", "C6")},
            "violation_slots": [f"{r['case']}: {x}" for r in rs for x in r["violations"]],
            "c4_retained_in_sent_back_records": sum(any(x.startswith("C4 (retained") for x in r["violations"])
                                                    for r in rs),
            "retained_mis_bindings": [f"{r['case']}: {x}" for r in rs for x in r["retained_mis_binding"]],
            "silent_omissions": [r["case"] for r in rs if r["silent_omission"]],
            "partial": [r["case"] for r in rs if r["partial"]],
            "served_not_bound": [r["case"] for r in rs if r["served_not_bound"]],
            "unsupported_parts_not_accounted": [
                f"{r['case']}: missing {p['missing']}, extra {p['extra']}, unclear missing {p['unclear_missing']}"
                for r in rs if (p := r["unsupported_parts"]) and not p["accounted"]],
            "not_answered_kinds_source": dict(Counter(r["unsupported_parts"]["source"] for r in rs
                                                      if r["unsupported_parts"])),
            "infrastructure": {"api_error": sum(r["terminal"] == "api_error" for r in rs),
                               "interrupted": sum(r["terminal"] == "interrupted" for r in rs),
                               "no_terminal_record": sum(r["terminal"] is None for r in rs)},
            "controls_safe": f"{sum(bool(r['control_safe']) for r in rs if r['set'] == 'control')} of "
                             f"{den['control_slots_per_arm']}",
            "median_settled_usd": statistics.median(settled) if settled else None, "settled_calls": len(settled),
            "attribution": dict(Counter(r["attribution"] for r in rs)),
            "layer_1": {"readings": dict(Counter(r["extraction"]["reading"] for r in rs)),
                        "errors_by_item": dict(Counter(k for r in rs for k, ok in r["extraction"]["items"].items()
                                                       if not ok)),
                        "by_set": {st: dict(Counter(r["extraction"]["reading"] for r in rs if r["set"] == st))
                                   for st in ("heldout", "control", "development")}},
            "eligibility_wrong": [r["case"] for r in rs if r["eligibility_ok"] is False],
            "reported_models": sorted({str(r["reported_model"]) for r in rs if r["reported_model"]}),
            "families": {f: f"{sum(r['acceptable'] for r in rs if r['family'] == f)} acceptable of "
                            f"{sum(1 for r in rs if r['family'] == f)}" for f in sorted({r["family"] for r in rs})},
        }
    s_a, s_b = summary(arm["A"], "A"), summary(arm["B"], "B")
    per_q = {c: (sum(r["exact"] for r in arm["A"] if r["config"] == c),
                 sum(r["exact"] for r in arm["B"] if r["config"] == c),
                 sum(1 for r in arm["B"] if r["config"] == c)) for c in sorted(answerable)}
    interval = bootstrap(per_q)
    b_fail = s_b["violation_slots"] or s_b["silent_omissions"]
    missing = [r["case"] for r in rows if r["terminal"] is None]
    limit = den["infrastructure_threshold"]["max_count"]
    infra = {a: s["infrastructure"]["api_error"] + s["infrastructure"]["interrupted"]
             for a, s in (("A", s_a), ("B", s_b))}
    unmet = []
    ra, rb = s_a["availability"]["rate"] or 0.0, s_b["availability"]["rate"] or 0.0
    gain = round(rb - ra, 6)
    if not (gain >= CRITERIA["gain_points"] - 1e-12 and interval["low"] is not None and interval["low"] > 0):
        unmet.append(f"1. availability gain {gain} (B {rb}, A {ra}) with interval low {interval['low']}: needs ≥ 0.15 "
                     "and a lower bound above 0")
    if not rb >= CRITERIA["availability_floor"] - 1e-12:
        unmet.append(f"2. B's availability {rb} is below 0.80")
    ia, ib = s_a["incomplete"]["rate"] or 0.0, s_b["incomplete"]["rate"] or 0.0
    if not ib - ia <= CRITERIA["incomplete_margin_points"] + 1e-12:
        unmet.append(f"3. B's incomplete rate {ib} is more than 5 points above A's {ia}")
    safe_b = sum(bool(r["control_safe"]) for r in arm["B"] if r["set"] == "control")
    if safe_b != den["control_slots_per_arm"]:
        unmet.append(f"4. {safe_b} of {den['control_slots_per_arm']} B control slots sent back safely")
    ma, mb = s_a["median_settled_usd"], s_b["median_settled_usd"]
    if ma is None or mb is None or mb > CRITERIA["cost_ratio"] * ma + 1e-12:
        unmet.append(f"5. B's median settled cost {mb} against 1.5 × A's {ma}")
    if b_fail:
        verdict = "B FAILS"
    elif missing:
        verdict = "INCOMPLETE"
    elif max(infra.values()) > limit:
        verdict = "INCONCLUSIVE"
    else:
        verdict = "MET" if not unmet else "NOT MET"
    v0_rows = [r for r in arm["B"] if r["v0"] is not None]
    return {
        "verdict": verdict,
        "verdict_reasons": {"b_critical_or_omission": bool(b_fail), "slots_without_terminal_record": missing,
                            "infrastructure_by_arm": infra, "infrastructure_limit": limit,
                            "criteria_unmet": unmet if verdict in ("MET", "NOT MET") else None,
                            "criteria_evaluated_anyway": unmet},
        "not_claimed": NOT_CLAIMED,
        "availability_difference": {"b_minus_a": gain, "interval_90": interval,
                                    "interval_limits": "questions selected by family, not sampled; repeats kept "
                                                       "together; describes the stability of the difference over these "
                                                       "questions under these settings, not a population rate"},
        "arms": {"A": s_a, "B": s_b},
        "v0_descriptive": {
            "note": "B's recorded plans compiled offline under V0: descriptive only, never a verdict or a selection",
            "slots": len(v0_rows),
            "availability_exact": sum(r["v0"]["exact"] for r in v0_rows if r["config"] in answerable),
            "outcomes": dict(Counter(r["v0"]["outcome"] for r in v0_rows)),
            "violation_slots": [f"{r['case']}: {x}" for r in v0_rows for x in r["v0"]["violations"]],
            "silent_omissions": [r["case"] for r in v0_rows if r["v0"]["silent_omission"]]},
        "accounting": accounting(rows),
        "slots": rows,
    }


def accounting(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def total(rs: list[dict[str, Any]]) -> dict[str, Any]:
        attempted = [r for r in rs if r["terminal"] is not None]
        return {"attempted_slots": len(attempted),
                "reserved_usd": round(sum(r["reserved_usd"] for r in attempted), 6),
                "settled_usd": round(sum(r["settled_usd"] or 0.0 for r in attempted), 6),
                "observed_usd": round(sum(r["observed_usd"] or 0.0 for r in attempted), 6),
                "observed_slots": sum(r["observed_usd"] is not None for r in attempted),
                "unresolved_slots": sum(bool(r["unresolved"]) for r in attempted),
                "conservative_usd": round(sum(r["conservative_usd"] or 0.0 for r in attempted), 6)}
    return {"A": total([r for r in rows if r["arm"] == "A"]), "B": total([r for r in rows if r["arm"] == "B"]),
            "total": total(rows), "billed": "not observed by the API; recorded only in BILLED.md if the owner reads it"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", default=str(LIVE))
    ap.add_argument("--out", default=None, help="write the scored report here (e.g. SCORE.json)")
    args = ap.parse_args()
    freeze = json.loads((HERE / "FREEZE.json").read_text())
    gold = {g["config"]: g for g in json.loads((HERE / "GOLD.json").read_text())["cases"]}
    live = Path(args.live)
    out = decide(freeze, gold, records(freeze, read_log(live), live))
    end = next((e for e in reversed(read_log(live)) if e.get("event") == "end"), None)
    out["run_end"] = end
    text = json.dumps(out, indent=1, default=str)
    if args.out:
        Path(args.out).write_text(text + "\n")
    print(json.dumps({k: out[k] for k in ("verdict", "verdict_reasons", "availability_difference")}, indent=1,
                     default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
