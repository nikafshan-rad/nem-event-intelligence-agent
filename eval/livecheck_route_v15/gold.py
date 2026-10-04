"""The configurations and gold of the routing-only Live check of route contract v15 (PROTOCOL.md, "Gold"). Offline.

- **Build** (default): writes `cases.json` (the 17 configurations: familiar questions copied unchanged from their
  sources, fresh ones as the writer wrote them) and `GOLD.json` (the writer's readings: `WRITER_OUTPUT.json` for
  N01–N07, `WRITER_FAMILIAR.json` for D01–D10). Nothing is computed from the application's resolver. Only mechanical
  checks are made:
  - the record holds every field, with valid values;
  - each anchor is copied exactly from its question;
  - bounds lie on the half-hour grid, the half-hour count matches them, and each stated local time converts to its UTC
    bound (`zoneinfo`);
  - each case's outcomes are within its set's (PROTOCOL.md, "Outcomes"; gold may narrow them, never widen them).

  A failed check, or an outcome outside its set, is reported and nothing is written.
- **`--cross-check`:** compares the gold's run rules, target half-hours, cutoffs and maximum with the frozen,
  independently verified sources (K14 and K06 `gold_run`; Y07, H06 and Z07 cutoffs and targets; FC02's peak target;
  F07's maximum and cutoff).
- **`--compare REVIEW.json`:** compares the gold with the reviewer's blind reading, item by item.
- **`--compare-alternative REVIEW_D08.json`:** compares the gold's resolved reading of D08 (the ambiguity case, whose
  primary outcome is a clarification) with the reviewer's separate verification of that reading.

Disagreements on meaning or on any gated item are listed for the owner. This script never resolves them.

Usage: python eval/livecheck_route_v15/gold.py [--cross-check] [--compare REVIEW.json] [--compare-alternative FILE]
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
def _sibling(name: str) -> Any:
    """A module of this check, loaded by path under a unique name: this directory never goes on ``sys.path``, so
    another check's runner importing its own ``score`` or ``run_eval`` is never handed this one's."""
    spec = importlib.util.spec_from_file_location(f"livecheck_route_v15_{name}", HERE / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_CFG = _sibling("configs")
FRESH, REPEATS, SETS, familiar_cases = _CFG.FRESH, _CFG.REPEATS, _CFG.SETS, _CFG.familiar_cases

ALLOWED = {
    "supply": {"resolved"},
    "ambiguity": {"clarify_which_forecast", "resolved"},
    "containment": {"clarify_unsupported", "clarify_which_forecast", "refusal", "event_review_unsupported"},
    "containment_ambiguous": {"clarify_which_forecast", "event_review_unclear"},
}
REQUIRED_SETS = {"supply": {"resolved"}, "ambiguity": {"clarify_which_forecast", "resolved"}}
OUTCOMES = {"resolved", "clarify_unsupported", "clarify_which_forecast", "clarify_mixed", "refusal",
            "event_review_unsupported", "event_review_unclear"}
DOMAINS = {"operational_demand", "weather", "price", "other", "unclear", "none"}
OPERATIONS = {"forecast_value", "single_interval_comparison", "window_comparison"}
SCOPES = {"half_hour", "event_peak_half_hour", "whole_local_day", "event", "explicit"}
RULES = {"none", "last_issued_before", "issued_at", "as_of_availability"}
TOOLS = {"eligible", "not_used", "not_restricted"}
FIELDS = ("config", "question", "request", "region", "outcome", "acceptable_outcomes", "intents", "domain",
          "operation", "scope", "run", "cutoff_utc", "maximum", "request_anchors", "excluded_anchors",
          "unsupported_parts", "demand_forecast_tools", "notes")
# frozen, independently verified sources the cross-check reads (their SHA-256 is frozen)
CROSS = ["eval/livecheck_i15_17/cases.json", "eval/livecheck_i15_17/VERIFICATION.json", "eval/cases.json",
         "eval/holdout_v2/cases.json", "eval/holdout_v5/cases.json", "eval/holdout_v6/cases.json",
         "eval/livecheck_maxima/cases.json", "eval/livecheck_maxima/GOLD.json", "eval/livecheck_maxima/GOLD_CHECK.json"]


def resolved_reading(g: dict[str, Any]) -> str | None:
    """The resolved reading a gold record accepts, derived mechanically from the fields the writer filled: an
    operational demand forecast request when `resolved` is acceptable and an operation is given (D08 gives one for its
    pre-registered demand reading although its own domain reading is `unclear`), a demand-maximum request when a
    maximum is given, else none."""
    if "resolved" not in g["acceptable_outcomes"]:
        return None
    if g["operation"] is not None:
        return "operational_demand_forecast"
    return "demand_maximum" if g["maximum"] else "invalid"


def set_of(config: str) -> str:
    return "containment_ambiguous" if config == "N03" else SETS[config]


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _iso(t: datetime) -> str:
    return t.astimezone(_t("2000-01-01T00:00:00Z").tzinfo).strftime("%Y-%m-%dT%H:%M:%SZ")


def _on_grid(s: str) -> bool:
    t = _t(s)
    return t.second == 0 and t.microsecond == 0 and t.minute in (0, 30)


def check_record(g: dict[str, Any], question: str, request: dict[str, Any]) -> list[str]:
    """Mechanical problems with one gold record (an empty list when there are none)."""
    c = g.get("config")
    out = [f"{c}: missing field {k}" for k in FIELDS if k not in g]
    if out:
        return out
    if g["question"] != question:
        out.append(f"{c}: the record's question is not the configuration's")
    if (g["request"] or {}) != request:
        out.append(f"{c}: the record's request {g['request']} is not the configuration's {request}")
    acc = set(g["acceptable_outcomes"])
    if g["outcome"] not in OUTCOMES or not acc <= OUTCOMES or not g["acceptable_outcomes"] or \
            g["acceptable_outcomes"][0] != g["outcome"]:
        out.append(f"{c}: outcome {g['outcome']} / acceptable {g['acceptable_outcomes']} are not valid, or the outcome "
                   "is not listed first")
    if g["domain"] not in DOMAINS or g["demand_forecast_tools"] not in TOOLS:
        out.append(f"{c}: domain {g['domain']} or tool eligibility {g['demand_forecast_tools']} is not valid")
    for kind in ("request_anchors", "excluded_anchors"):
        out += [f"{c}: {kind} {a!r} is not copied exactly from the question" for a in g[kind] if a not in question]
    for p in g["unsupported_parts"]:
        if p.get("anchor") not in question or p.get("kind") not in ("weather", "price", "other"):
            out.append(f"{c}: unsupported part {p} is not valid")
    reading = resolved_reading(g) if acc <= OUTCOMES else None
    if reading == "invalid":
        out.append(f"{c}: a resolved outcome is accepted, but neither an operation nor a maximum is given")
    if reading == "operational_demand_forecast":
        if g["operation"] not in OPERATIONS:
            out.append(f"{c}: operation {g['operation']} is not valid")
        sc = g["scope"] or {}
        if not sc or not set(sc.get("kinds") or []) <= SCOPES or not sc.get("kinds"):
            out.append(f"{c}: scope {sc} is not valid")
        else:
            a, b = sc["start_utc"], sc["end_utc"]
            if not (_on_grid(a) and _on_grid(b)) or _t(b) <= _t(a):
                out.append(f"{c}: scope bounds {a}–{b} are not whole half-hours")
            elif (_t(b) - _t(a)) / timedelta(minutes=30) != sc["half_hours"]:
                out.append(f"{c}: {sc['half_hours']} half-hours, but the bounds hold {(_t(b) - _t(a)) / timedelta(minutes=30)}")
            for loc, utc in (("start_local", a), ("end_local", b)):
                if sc.get(loc) and _iso(datetime.fromisoformat(sc[loc])) != utc:
                    out.append(f"{c}: {loc} {sc[loc]} is not {utc}")
        run = g["run"] or {}
        if run.get("rule") not in RULES:
            out.append(f"{c}: run {run} is not valid")
        elif run["rule"] in ("last_issued_before", "issued_at") and not (run.get("half_hour_end_utc") and
                                                                       _on_grid(run["half_hour_end_utc"])):
            out.append(f"{c}: the run's target half-hour {run.get('half_hour_end_utc')} is not valid")
        elif run["rule"] == "issued_at" and not run.get("issued_at_utc"):
            out.append(f"{c}: an issued_at run has no issue time")
        if not g["request_anchors"]:
            out.append(f"{c}: a resolved reading has no request anchors")
    if g["maximum"]:
        mx = g["maximum"]
        if mx.get("measure") not in ("operational_demand", "dispatch_total_demand") or \
                mx.get("window_kind") not in ("whole_local_day", "event", "explicit"):
            out.append(f"{c}: maximum {mx} is not valid")
    if g["cutoff_utc"] is not None:
        try:
            _t(g["cutoff_utc"])
        except ValueError:
            out.append(f"{c}: cutoff {g['cutoff_utc']} is not ISO 8601")
    return out


def set_findings(g: dict[str, Any]) -> list[str]:
    """Outcomes outside the configuration's set: a disagreement with the owner's designation, for the owner."""
    s, acc = set_of(g["config"]), set(g["acceptable_outcomes"])
    if s in REQUIRED_SETS and acc != REQUIRED_SETS[s]:
        return [f"{g['config']} ({s}): the gold's acceptable outcomes {sorted(acc)} are not the set's "
                f"{sorted(REQUIRED_SETS[s])}"]
    if not acc <= ALLOWED[s]:
        return [f"{g['config']} ({s}): the gold accepts {sorted(acc - ALLOWED[s])}, outside the set's {sorted(ALLOWED[s])}"]
    return []


def build() -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    fresh = {g["config"]: g for g in json.loads((HERE / "WRITER_OUTPUT.json").read_text())["cases"]}
    fam = {g["config"]: g for g in json.loads((HERE / "WRITER_FAMILIAR.json").read_text())["cases"]}
    cases = familiar_cases() + [{"config": c, "group": "fresh", "set": s, "tests": tests, "source": {
        "file": "eval/livecheck_route_v15/WRITER_OUTPUT.json", "case_id": c}, "question": fresh[c]["question"],
        "request": {}, "repeats": REPEATS} for c, s, tests in FRESH]
    problems: list[str] = []
    gold = []
    for case in cases:
        g = (fam if case["group"] == "familiar" else fresh).get(case["config"])
        if g is None:
            problems.append(f"{case['config']}: no gold record")
            continue
        problems += check_record(g, case["question"], case["request"]) + set_findings(g)
        gold.append({**{k: g[k] for k in FIELDS}, "resolved_reading": resolved_reading(g) if "acceptable_outcomes" in g
                     else None, "group": case["group"], "set": case["set"],
                     "gold_source": "writer, step 1 (fresh)" if case["group"] == "fresh" else "writer, step 2"})
    sources = sorted({c["source"]["file"] for c in cases if c["group"] == "familiar"} | set(CROSS))
    sha = {rel: hashlib.sha256((REPO / rel).read_bytes()).hexdigest() for rel in sources}
    data = {"version": "livecheck_route_v15/1", "questions": len(cases), "configurations": len(cases),
            "calls": sum(c["repeats"] for c in cases), "cases": cases}
    return data, {"generated_by": "eval/livecheck_route_v15/gold.py", "sources_sha256": sha, "cases": gold}, problems


# ------------------------------------------------------------------------------------------------ cross-check
def _case(rel: str, cid: str) -> dict[str, Any]:
    return next(c for c in json.loads((REPO / rel).read_text())["cases"] if c.get("case_id") == cid)


def cross_check(gold: dict[str, dict[str, Any]]) -> list[str]:
    """Disagreements with frozen, independently verified sources (an empty list when they agree)."""
    out = []

    def want(c: str, item: str, got: Any, exp: Any) -> None:
        if got != exp:
            out.append(f"{c}: {item} {got}, verified source {exp}")

    for c, cid, rule in (("D01", "K14", "issued_at"), ("D02", "K06", "last_issued_before")):
        run = _case("eval/livecheck_i15_17/cases.json", cid)["expected"]["gold_run"]
        g = gold[c]["run"] or {}
        want(c, "run rule", g.get("rule"), rule)
        want(c, "target half-hour end", g.get("half_hour_end_utc"), run["target_end_utc"])
        if rule == "issued_at":
            want(c, "issue time", g.get("issued_at_utc"), run["issued_at_utc"])
    for c, rel, cid in (("D05", "eval/holdout_v5/cases.json", "Y07"), ("D06", "eval/holdout_v2/cases.json", "H06"),
                        ("D07", "eval/holdout_v6/cases.json", "Z07")):
        e = _case(rel, cid)["expected"]
        want(c, "cutoff", gold[c]["cutoff_utc"], e["as_of_utc"])
        ends = sorted({n["valid_at_utc"] for n in e.get("gold_numbers") or [] if "forecast" in n.get("metric", "")})
        if ends:
            want(c, "target half-hour end", (gold[c]["scope"] or {}).get("end_utc"), ends[-1])
    e = _case("eval/cases.json", "FC02")["expected"]
    want("D08", "cutoff", gold["D08"]["cutoff_utc"], e["as_of_utc"])
    want("D08", "the demand reading's target end", (gold["D08"]["scope"] or {}).get("end_utc"),
         e["gold_forecast"]["peak_target_latest_eligible_run"]["target_end_utc"])
    mx = next(g for g in json.loads((REPO / "eval/livecheck_maxima/GOLD.json").read_text())["cases"]
              if g["case_id"] == "F07")["reading"]
    g = gold["D10"]["maximum"] or {}
    want("D10", "cutoff", gold["D10"]["cutoff_utc"], mx["as_of_utc"])
    want("D10", "maximum window", [g.get("start_utc"), g.get("end_utc")], mx["window_utc"])
    want("D10", "maximum measure", g.get("measure"), {"operational demand": "operational_demand",
                                                      "total demand": "dispatch_total_demand"}.get(mx["measure"]))
    return out


# ------------------------------------------------------------------------------------------------ compare
def _overlap(a: str, b: str, q: str) -> bool:
    def spans(t: str) -> list[tuple[int, int]]:
        out, i = [], q.find(t)
        while i >= 0 and t:
            out.append((i, i + len(t)))
            i = q.find(t, i + 1)
        return out
    return any(x[0] < y[1] and y[0] < x[1] for x in spans(a) for y in spans(b))


def compare(gold: dict[str, dict[str, Any]], review: dict[str, dict[str, Any]]) -> list[str]:
    """Item-by-item disagreements between the gold and the reviewer's blind reading."""
    out = []
    for c, g in gold.items():
        r = review.get(c)
        if r is None:
            out.append(f"{c}: no reviewer record")
            continue
        q = g["question"]

        def diff(item: str, a: Any, b: Any, c: str = c) -> None:
            if a != b:
                out.append(f"{c}: {item}: gold {a!r}, reviewer {b!r}")
        diff("outcome", g["outcome"], r.get("outcome"))
        if set(g["acceptable_outcomes"]) != set(r.get("acceptable_outcomes") or []):
            out.append(f"{c}: acceptable outcomes: gold {sorted(g['acceptable_outcomes'])}, reviewer "
                       f"{sorted(r.get('acceptable_outcomes') or [])} (reported; the set's are pre-registered)")
        diff("region", g["region"], r.get("region"))
        diff("domain", g["domain"], r.get("domain"))
        diff("cutoff", g["cutoff_utc"], r.get("cutoff_utc"))
        diff("tool eligibility", g["demand_forecast_tools"], r.get("demand_forecast_tools"))
        diff("maximum", g["maximum"], r.get("maximum"))
        if g["resolved_reading"] == "operational_demand_forecast":
            diff("operation", g["operation"], r.get("operation"))
            gs, rs = g["scope"] or {}, r.get("scope") or {}
            diff("scope bounds", [gs.get("start_utc"), gs.get("end_utc"), gs.get("half_hours")],
                 [rs.get("start_utc"), rs.get("end_utc"), rs.get("half_hours")])
            if not set(gs.get("kinds") or []) & set(rs.get("kinds") or []):
                out.append(f"{c}: scope kind: gold {gs.get('kinds')}, reviewer {rs.get('kinds')}")
            gr, rr = g["run"] or {}, r.get("run") or {}
            diff("run", [gr.get("rule"), gr.get("half_hour_end_utc"), gr.get("issued_at_utc")],
                 [rr.get("rule"), rr.get("half_hour_end_utc"), rr.get("issued_at_utc")])
            diff("intents", sorted(g["intents"]), sorted(r.get("intents") or []))
        gp, rp = g["unsupported_parts"], r.get("unsupported_parts") or []
        if len(gp) != len(rp) or not all(any(_overlap(a["anchor"], b.get("anchor", ""), q) for b in rp) for a in gp):
            out.append(f"{c}: unsupported parts: gold {gp}, reviewer {rp}")
        for a in g["request_anchors"]:
            if any(_overlap(a, x, q) for x in (r.get("excluded_anchors") or []) + [p.get("anchor", "") for p in rp]):
                out.append(f"{c}: gold request anchor {a!r} is excluded or unsupported in the reviewer's reading")
        for a in r.get("request_anchors") or []:
            if any(_overlap(a, x, q) for x in g["excluded_anchors"] + [p["anchor"] for p in gp]):
                out.append(f"{c}: reviewer request anchor {a!r} is excluded or unsupported in the gold")
    return out


def compare_alternative(gold: dict[str, dict[str, Any]], alt: dict[str, dict[str, Any]]) -> list[str]:
    """Item-by-item disagreements between the gold's resolved reading of a case whose primary outcome is not
    `resolved` (D08) and the reviewer's separate verification of that reading."""
    out = []
    for c, r in alt.items():
        g = gold[c]
        q = g["question"]
        pairs = [("operation", g["operation"], r.get("operation")), ("cutoff", g["cutoff_utc"], r.get("cutoff_utc")),
                 ("tool eligibility", g["demand_forecast_tools"], r.get("demand_forecast_tools")),
                 ("region", g["region"], r.get("region")),
                 ("scope bounds", [(g["scope"] or {}).get(k) for k in ("start_utc", "end_utc", "half_hours")],
                  [(r.get("scope") or {}).get(k) for k in ("start_utc", "end_utc", "half_hours")]),
                 ("run", [(g["run"] or {}).get(k) for k in ("rule", "half_hour_end_utc", "issued_at_utc")],
                  [(r.get("run") or {}).get(k) for k in ("rule", "half_hour_end_utc", "issued_at_utc")]),
                 ("intents", sorted(g["intents"]), sorted(r.get("intents") or [])),
                 ("unsupported parts", len(g["unsupported_parts"]), len(r.get("unsupported_parts") or []))]
        out += [f"{c} (resolved reading): {item}: gold {a!r}, reviewer {b!r}" for item, a, b in pairs if a != b]
        if not set((g["scope"] or {}).get("kinds") or []) & set((r.get("scope") or {}).get("kinds") or []):
            out.append(f"{c} (resolved reading): scope kind: gold {(g['scope'] or {}).get('kinds')}, reviewer "
                       f"{(r.get('scope') or {}).get('kinds')}")
        for a in g["request_anchors"]:
            if any(_overlap(a, x, q) for x in r.get("excluded_anchors") or []):
                out.append(f"{c} (resolved reading): gold request anchor {a!r} is excluded in the reviewer's reading")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cross-check", action="store_true")
    ap.add_argument("--compare", default=None)
    ap.add_argument("--compare-alternative", default=None)
    args = ap.parse_args()
    if args.cross_check or args.compare or args.compare_alternative:
        gold = {g["config"]: g for g in json.loads((HERE / "GOLD.json").read_text())["cases"]}
        found = cross_check(gold) if args.cross_check else []
        if args.compare:
            review = {r["config"]: r for r in json.loads(Path(args.compare).read_text())["cases"]}
            found += compare(gold, review)
        if args.compare_alternative:
            data = json.loads(Path(args.compare_alternative).read_text())
            recs = data["cases"] if isinstance(data, dict) and "cases" in data else [data]
            found += compare_alternative(gold, {r["config"]: r for r in recs})
        print("\n".join(found) if found else "the gold agrees with every item checked")
        return 1 if found else 0
    cases, gold, problems = build()
    if problems:
        print("not written:\n" + "\n".join(problems))
        return 1
    (HERE / "cases.json").write_text(json.dumps(cases, indent=1) + "\n")
    (HERE / "GOLD.json").write_text(json.dumps(gold, indent=1) + "\n")
    print(f"{cases['configurations']} configurations, {cases['calls']} calls")
    for g in gold["cases"]:
        print(g["config"], g["set"], g["outcome"], g["acceptable_outcomes"], g["region"], g["domain"], g["operation"],
              (g["scope"] or {}).get("start_utc"), (g["scope"] or {}).get("end_utc"), (g["run"] or {}).get("rule"),
              g["cutoff_utc"], g["demand_forecast_tools"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
