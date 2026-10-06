"""Build and check the comparison's gold (PROTOCOL.md, "The gold"). Offline; no model call.

- **Development gold** (``dev_gold``) is derived from frozen, verified sources, read only: the v15 check's amended gold
  and extraction gold (`eval/livecheck_route_v15/GOLD_AMENDED.json`, `EXTRACTION_GOLD.json`) and the maxima check's
  gold (`eval/livecheck_maxima/GOLD.json`) for the end-to-end records. It is mapped into `GOLD_FORMAT.md` under this
  protocol's `CAPABILITIES.md`, whose four outcomes replace v15's seven names. Where `CAPABILITIES.md` classes a time
  as known-unsupported ("noon" in V15-N07 and E2E-F07N, with no request cutoff), the outcome is `clarify` and the
  semantic reading is kept in the reader items. The developer adds only what those sources lack: each mention's stance
  and anchors where v15 recorded none, and the end-to-end records' reader key words (``DEV_*`` tables below), which
  the reviewer's blind reading checks.
- **Held-out gold** is the writer's records (`WRITER_OUTPUT.json`), unchanged, after the mechanical checks
  (``check``) and the reviewer comparison (``compare``). The developer writes no held-out item.
- **The comparison of two records** (``gated``, ``compare``): every gated item of PROTOCOL.md. A set-valued item
  (acceptable outcomes, intents, scope kinds) agrees when the two sets share a member, and the frozen gold keeps only
  the shared members; every other item must be equal. Mentions agree when each one's anchors overlap exactly one
  mention of the other record, with the same stance, and, for an asked mention, the same kind and subject.

Usage:
    python eval/compare_route_v15_v16/gold.py check WRITER_OUTPUT.json
    python eval/compare_route_v15_v16/gold.py compare REVIEW.json      (reviewer IDs mapped by REVIEW_IDS.json)
    python eval/compare_route_v15_v16/gold.py build                    (writes GOLD.json and cases.json)
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def _sibling(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"compare_route_v15_v16_{name}", HERE / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CFG = _sibling("configs")
OUTCOMES = ("resolved", "clarify", "refusal", "event_review_without_demand_forecast")
STANCES = ("asked", "declined", "background")
KINDS = ("forecast_value", "single_interval_comparison", "window_comparison", "demand_maximum", "unclear")
SUBJECTS = ("operational_demand", "dispatch_total_demand", "demand_unspecified", "weather", "price", "other", "unclear")
SUPPORTED_FORECAST = ("operational_demand", "demand_unspecified")
SCOPE_KINDS = ("half_hour", "event_peak_half_hour", "whole_local_day", "event", "explicit")
RUN_RULES = ("none", "last_issued_before", "issued_at", "as_of_availability")
WINDOW_KINDS = ("whole_local_day", "event", "explicit")
TOOLS = ("eligible", "not_used", "not_restricted")
UNSUPPORTED_TIMES = ("noon", "midday", "part_of_day", "over_24_hours", "start_or_end_unknown", "no_time_zone")
ZONE = {"NSW1": "Australia/Sydney", "QLD1": "Australia/Brisbane", "SA1": "Australia/Adelaide",
        "TAS1": "Australia/Hobart", "VIC1": "Australia/Melbourne"}
V15_OUTCOME = {"resolved": "resolved", "clarify_unsupported": "clarify", "clarify_which_forecast": "clarify",
               "clarify_mixed": "clarify", "refusal": "refusal", "event_review_unsupported":
               "event_review_without_demand_forecast", "event_review_unclear": "event_review_without_demand_forecast"}
V15_SOURCES = ["eval/livecheck_route_v15/GOLD_AMENDED.json", "eval/livecheck_route_v15/EXTRACTION_GOLD.json",
               "eval/livecheck_maxima/GOLD.json", "eval/livecheck_route_v15/cases.json"]


def _load(rel: str) -> Any:
    return json.loads((REPO / rel).read_text())


def is_supported_request(m: dict[str, Any]) -> bool:
    """A demand forecast request, or a demand maximum (PROTOCOL.md, "Silent omission")."""
    if m["kind"] == "demand_maximum":
        return m["subject"] in ("operational_demand", "dispatch_total_demand", "demand_unspecified")
    return m["kind"] != "unclear" and m["subject"] in SUPPORTED_FORECAST


# ------------------------------------------------------------------------------------------------ development gold
# Stances and anchors of mentions the v15 gold records only as request, excluded or unsupported anchors, or not at all
# (developer-specified; checked by the reviewer's blind reading)
DEV_MENTIONS: dict[str, list[dict[str, Any]]] = {
    "D08": [{"stance": "asked", "kind": "forecast_value", "subject": "unclear",
             "anchors": ["what did the latest issued forecast say"]}],
    "D09": [{"stance": "asked", "kind": "forecast_value", "subject": "weather", "anchors": ["the weather forecast"]}],
    "N01": [{"stance": "asked", "kind": "forecast_value", "subject": "weather",
             "anchors": ["What maximum temperature was forecast"]}],
    "N02": [{"stance": "asked", "kind": "forecast_value", "subject": "price",
             "anchors": ["AEMO's predispatch price forecasts"]}],
    "N03": [{"stance": "asked", "kind": "window_comparison", "subject": "unclear",
             "anchors": ["How far off were the forecasts"]}],
    "N04": [{"stance": "declined", "kind": "forecast_value", "subject": "weather",
             "anchors": ["Leave the weather forecast out of this one"]}],
    "N05": [{"stance": "declined", "kind": "forecast_value", "subject": "operational_demand",
             "anchors": ["I don't need AEMO's operational demand forecast for this"]},
            {"stance": "asked", "kind": "forecast_value", "subject": "weather",
             "anchors": ["What did the weather forecasters expect"]}],
    "N06": [{"stance": "background", "kind": "single_interval_comparison", "subject": "operational_demand",
             "anchors": ["AEMO's demand forecast for South Australia came in well below the actuals"]},
            {"stance": "asked", "kind": "forecast_value", "subject": "weather",
             "anchors": ["What minimum temperature had been forecast"]}],
    "N07": [{"stance": "background", "kind": "forecast_value", "subject": "weather",
             "anchors": ["the Bureau was calling for a cold, drizzly morning across Brisbane"]}],
    "D06": [{"stance": "asked", "kind": "forecast_value", "subject": "weather",
             "anchors": ["was cold weather expected to push demand up that morning"]}],
    "D07": [{"stance": "asked", "kind": "forecast_value", "subject": "weather",
             "anchors": ["what temperature was then expected for Adelaide"]}],
}
# under this protocol's CAPABILITIES.md: "noon" with no request cutoff is a known-unsupported time
DEV_UNSUPPORTED_TIME = {"N07": "noon"}
# the end-to-end records (maxima): mentions and reader key words (developer-specified, from the maxima gold's reading)
DEV_E2E: dict[str, dict[str, Any]] = {
    "D01": {"anchors": ["NSW dispatch total demand highest"], "measure_kw": ["dispatch total demand"],
            "window_kw": ["whole day"], "dates": ["2026-07-29"]},
    "D02": {"anchors": ["Queensland's highest operational demand"], "measure_kw": ["operational demand"],
            "window_kw": ["29 July 2026"], "dates": ["2026-07-29"]},
    "F02": {"anchors": ["the day's top dispatch total demand"], "measure_kw": ["dispatch total demand"],
            "window_kw": ["full local day", "29 July 2026"], "dates": ["2026-07-29"]},
    "F06": {"anchors": ["how high did VIC1 dispatch total demand (TOTALDEMAND) go"],
            "measure_kw": ["dispatch total demand"], "window_kw": ["event"], "dates": ["2026-08-20"]},
    "F07N": {"anchors": ["the highest operational demand in Queensland"], "measure_kw": ["operational demand"],
             "window_kw": ["entire local day"], "dates": ["2025-10-05"],
             "cutoff_kw": ["noon", "Brisbane", "5 October 2025"], "unsupported_time": "noon"},
    "F08": {"anchors": ["how far did demand climb"], "measure_kw": ["demand"], "window_kw": ["episode"],
            "dates": ["2026-07-31"]},
}
MEASURE_OF = {"total demand": "dispatch_total_demand", "operational demand": "operational_demand", None: None}
WINDOW_OF = {"day": "whole_local_day", "event": "event", "explicit": "explicit"}


def _v15_record(cfg: str, g: dict[str, Any], x: dict[str, Any]) -> dict[str, Any]:
    acceptable = list(dict.fromkeys(V15_OUTCOME[o] for o in g["acceptable_outcomes"]))
    unsupported_time = DEV_UNSUPPORTED_TIME.get(cfg)
    if unsupported_time:
        acceptable = ["clarify"]
    resolved = acceptable == ["resolved"]
    mentions: list[dict[str, Any]] = []
    if g["maximum"]:
        mentions.append({"stance": "asked", "kind": "demand_maximum", "subject": g["maximum"]["measure"],
                         "anchors": g["request_anchors"]})
    elif g["domain"] == "operational_demand":
        mentions.append({"stance": "asked", "kind": g["operation"], "subject": "operational_demand",
                         "anchors": g["request_anchors"]})
    mentions += [dict(m) for m in DEV_MENTIONS.get(cfg, [])]
    if cfg == "N07" and not any(m["stance"] == "asked" and m["subject"] == "operational_demand" for m in mentions):
        # the demand request, read by both v15 authors, is asked
        mentions.append({"stance": "asked", "kind": "window_comparison", "subject": "operational_demand",
                         "anchors": g["request_anchors"]})
    for m in mentions:
        m["primary"] = resolved and m["stance"] == "asked" and is_supported_request(m)
    reader = None
    if g["maximum"] or g["domain"] == "operational_demand":
        mx = x["maximum"]
        reader = {"subject_key_words": (mx or {}).get("measure_key_words") or ["demand"],
                  "scope_kinds": x["scope_kinds"] or [], "scope_key_words": x["scope_key_words"] or [],
                  "run_rule": x["run_rule"] if x["run_rule"] is not None else "none",
                  "run_key_words": x["run_key_words"] or [], "cutoff_key_words": x["cutoff_key_words"] or [],
                  "maximum": mx}
    resolution = None
    if resolved:
        mx = g["maximum"]
        resolution = {"operation": g["operation"], "scope": g["scope"],
                      "run": g["run"] if g["run"] else {"rule": "none", "half_hour_end_utc": None,
                                                        "issued_at_utc": None},
                      "maximum": None if not mx else {"measure": mx["measure"], "window_kind": mx["window_kind"],
                                                      "start_utc": mx["start_utc"], "end_utc": mx["end_utc"]},
                      "not_answered": sorted({p["kind"] for p in g["unsupported_parts"]})}
    return {"config": f"V15-{cfg}", "family": "development", "question": g["question"], "request": g["request"],
            "region": g["region"], "local_dates": x["local_dates"], "answerable": resolved,
            "outcome": acceptable[0], "acceptable_outcomes": acceptable,
            "intents": (g["intents"] or x["intents"]) if resolved else [],
            "cutoff_utc": g["cutoff_utc"], "mentions": mentions, "reader": reader, "resolution": resolution,
            # a forecast request that is not resolved is "any other question that asks for a forecast"
            "demand_forecast_tools": "not_used" if unsupported_time and g["demand_forecast_tools"] == "eligible"
            else g["demand_forecast_tools"], "unsupported_time": unsupported_time,
            "notes": f"Derived from the v15 amended and extraction gold of {cfg} ({g.get('gold_source', 'gold')})."}


def _e2e_record(case: str, m: dict[str, Any], question: str, request: dict[str, Any]) -> dict[str, Any]:
    r, spec = m["reading"], DEV_E2E[case]
    measure = MEASURE_OF[r["measure"]]
    unsupported_time = spec.get("unsupported_time")
    resolved = r["expected_outcome"] in ("established", "not_established") and unsupported_time is None
    acceptable = ["resolved"] if resolved else ["clarify"]
    window = WINDOW_OF[r["window_kind"]]
    mention = {"stance": "asked", "kind": "demand_maximum", "subject": measure or "demand_unspecified",
               "anchors": spec["anchors"], "primary": resolved}
    return {"config": f"E2E-{case}", "family": "development", "question": question, "request": request,
            "region": r["region"], "local_dates": spec["dates"], "answerable": resolved,
            "outcome": acceptable[0], "acceptable_outcomes": acceptable,
            "intents": ["forecast_review", "market_event_review"] if resolved else [],
            "cutoff_utc": r["as_of_utc"] if request.get("as_of_utc") else None, "mentions": [mention],
            "reader": {"subject_key_words": spec["measure_kw"], "scope_kinds": [], "scope_key_words": [],
                       "run_rule": "none", "run_key_words": [], "cutoff_key_words": spec.get("cutoff_kw", []),
                       "maximum": {"measure": measure or "demand_unspecified", "window": window,
                                   "measure_key_words": spec["measure_kw"], "window_key_words": spec["window_kw"]}},
            "resolution": None if not resolved else {
                "operation": None, "scope": None, "run": {"rule": "none", "half_hour_end_utc": None,
                                                          "issued_at_utc": None},
                "maximum": {"measure": measure, "window_kind": window, "start_utc": r["window_utc"][0],
                            "end_utc": r["window_utc"][1]}, "not_answered": []},
            "demand_forecast_tools": "not_restricted", "unsupported_time": unsupported_time,
            "notes": f"Derived from the maxima check's gold reading of {case if case != 'F07N' else 'F07'}"
                     f"{' (the same question without the request cutoff: noon cannot be pinned down)' if case == 'F07N' else ''}."}


def dev_gold() -> list[dict[str, Any]]:
    g = {c["config"]: c for c in _load(V15_SOURCES[0])["cases"]}
    x = {c["config"]: c for c in _load(V15_SOURCES[1])["cases"]}
    maxima = {c["case_id"]: c for c in _load(V15_SOURCES[2])["cases"]}
    out = [_v15_record(cfg, g[cfg], x[cfg]) for cfg in g]
    for c in CFG.development_cases():
        if c["config"].startswith("E2E-"):
            case = c["config"][4:]
            out.append(_e2e_record(case, maxima["F07" if case == "F07N" else case], c["question"], c["request"]))
    return out


# ------------------------------------------------------------------------------------------------ mechanical checks
def _utc(s: str | None) -> datetime | None:
    return None if s is None else datetime.fromisoformat(s.replace("Z", "+00:00"))


def _grid(t: datetime) -> bool:
    return t.second == 0 and t.microsecond == 0 and t.minute in (0, 30)


def check(rec: dict[str, Any], expect_family: str | None = None) -> list[str]:
    """Format and consistency problems in one record (GOLD_FORMAT.md); [] when it is well formed."""
    p: list[str] = []
    q = rec.get("question") or ""
    cfg = rec.get("config")
    try:
        if expect_family and rec.get("family") != expect_family:
            p.append(f"family {rec.get('family')}, expected {expect_family}")
        acc = rec["acceptable_outcomes"]
        if not acc or any(o not in OUTCOMES for o in acc) or rec["outcome"] != acc[0]:
            p.append(f"outcomes {rec['outcome']} / {acc}")
        if rec["answerable"] != (acc == ["resolved"]):
            p.append("answerable must hold exactly when resolved is the only acceptable outcome")
        if rec["region"] is not None and rec["region"] not in ZONE:
            p.append(f"region {rec['region']}")
        for d in rec["local_dates"]:
            datetime.strptime(d, "%Y-%m-%d")
        if ("resolved" in acc) != (rec["resolution"] is not None):
            p.append("a resolution is needed exactly when resolved is acceptable")
        if "resolved" in acc and not rec["intents"]:
            p.append("a resolved question needs intents")
        prim = [m for m in rec["mentions"] if m.get("primary")]
        for m in rec["mentions"]:
            if m["stance"] not in STANCES or m["kind"] not in KINDS or m["subject"] not in SUBJECTS:
                p.append(f"mention {m}")
            if not m["anchors"] or any(a not in q for a in m["anchors"]):
                p.append(f"mention anchors not copied from the question: {m['anchors']}")
        for i, m in enumerate(rec["mentions"]):
            for n in rec["mentions"][i + 1:]:
                if _touch(m["anchors"], n["anchors"], q):
                    p.append(f"two mentions' anchors overlap: {m['anchors']} / {n['anchors']} (each mention's anchors "
                             "are inside its own words)")
        if rec["answerable"] and (len(prim) != 1 or prim[0]["stance"] != "asked" or not is_supported_request(prim[0])):
            p.append("an answerable question needs exactly one primary, asked, supported mention")
        if not rec["answerable"] and prim:
            p.append("only an answerable question has a primary mention")
        rd = rec["reader"]
        if rec["answerable"] and rd is None:
            p.append("an answerable question needs reader items")
        if rd is not None:
            keys = [*rd["subject_key_words"], *rd["scope_key_words"], *rd["run_key_words"], *rd["cutoff_key_words"],
                    *((rd["maximum"] or {}).get("measure_key_words") or []),
                    *((rd["maximum"] or {}).get("window_key_words") or [])]
            missing = [k for k in keys if k.lower() not in q.lower()]
            if missing:
                p.append(f"reader key words not in the question: {missing}")
            if rd["run_rule"] not in RUN_RULES or any(k not in SCOPE_KINDS for k in rd["scope_kinds"]):
                p.append(f"reader run or scope kinds: {rd['run_rule']} {rd['scope_kinds']}")
        res = rec["resolution"]
        if res is not None:
            p += _check_resolution(res, rec["region"])
            # the not-answered kinds are the asked unsupported parts, never a declined or background one
            asked = sorted({m["subject"] for m in rec["mentions"]
                            if m["stance"] == "asked" and m["subject"] in ("weather", "price", "other")})
            if sorted(res["not_answered"]) != asked:
                p.append(f"not answered {sorted(res['not_answered'])}: the asked unsupported parts are {asked}")
        if rec["cutoff_utc"] is not None:
            _utc(rec["cutoff_utc"])
        if rec["demand_forecast_tools"] not in TOOLS:
            p.append(f"tools {rec['demand_forecast_tools']}")
        if res is not None and res.get("operation") and rec["demand_forecast_tools"] != "eligible":
            p.append("a resolved forecast request makes the demand-forecast tools eligible")
        if rec["demand_forecast_tools"] == "eligible" and not (res is not None and res.get("operation")):
            p.append("the demand-forecast tools are eligible only for a resolved forecast request")
        if rec["unsupported_time"] is not None and (rec["unsupported_time"] not in UNSUPPORTED_TIMES or
                                                    "clarify" not in acc):
            p.append(f"unsupported time {rec['unsupported_time']} with outcomes {acc}")
        if cfg in CFG.CONTROLS and (rec["unsupported_time"] is None or acc != ["clarify"]):
            p.append("a control has one unsupported time and the outcome clarify only")
        if cfg in CFG.HELDOUT and CFG.FAMILY_OF[cfg] != "overrides" and rec["request"]:
            p.append("request fields are used only in H37–H40")
    except (KeyError, TypeError, ValueError) as exc:
        p.append(f"malformed: {type(exc).__name__}: {exc}")
    return p


def _check_resolution(res: dict[str, Any], region: str | None) -> list[str]:
    p: list[str] = []
    mx, sc, run = res["maximum"], res["scope"], res["run"]
    if (mx is None) == (res["operation"] is None):
        p.append("a resolution is either a forecast request (operation, scope) or a maximum")
    if res["operation"] is not None:
        if sc is None or not sc["kinds"] or any(k not in SCOPE_KINDS for k in sc["kinds"]):
            p.append(f"scope {sc}")
        else:
            a, b = _utc(sc["start_utc"]), _utc(sc["end_utc"])
            assert a is not None and b is not None
            n = (b - a) / timedelta(minutes=30)
            if not (_grid(a) and _grid(b) and b > a and n == sc["half_hours"] and b - a <= timedelta(hours=24)):
                p.append(f"scope bounds {sc['start_utc']}–{sc['end_utc']} ({sc['half_hours']} half-hours)")
            if region:
                for k in ("start", "end"):
                    loc = datetime.fromisoformat(sc[f"{k}_local"])
                    want = _utc(sc[f"{k}_utc"]).astimezone(ZoneInfo(ZONE[region]))  # type: ignore[union-attr]
                    if loc != want or loc.utcoffset() != want.utcoffset():
                        p.append(f"scope {k}_local {sc[f'{k}_local']}, from UTC {want.isoformat()}")
            single = res["operation"] in ("forecast_value", "single_interval_comparison") and sc["half_hours"] == 1
            if res["operation"] == "single_interval_comparison" and not single:
                p.append("a single-interval comparison is of one half-hour")
            if res["operation"] == "window_comparison" and sc["half_hours"] == 1 and \
                    set(sc["kinds"]) & {"half_hour", "event_peak_half_hour"}:
                p.append("a window comparison is of a period")
    if run["rule"] not in RUN_RULES:
        p.append(f"run {run}")
    if run["rule"] in ("last_issued_before", "issued_at") and run["half_hour_end_utc"] is None:
        p.append("a named run needs its target half-hour's end")
    if run["rule"] == "issued_at" and run["issued_at_utc"] is None:
        p.append("issued_at needs the issue time")
    if mx is not None:
        if mx["measure"] not in ("operational_demand", "dispatch_total_demand") or mx["window_kind"] not in WINDOW_KINDS:
            p.append(f"maximum {mx}")
        a, b = _utc(mx["start_utc"]), _utc(mx["end_utc"])
        if a is None or b is None or b <= a:
            p.append(f"maximum window {mx}")
    if any(k not in ("weather", "price", "other") for k in res["not_answered"]):
        p.append(f"not answered {res['not_answered']}")
    return p


def check_writer(cases: list[dict[str, Any]]) -> list[str]:
    """Every record, the IDs and the family quotas (PROTOCOL.md, "The sample")."""
    p: list[str] = []
    ids = [str(c.get("config")) for c in cases]
    if sorted(ids) != sorted(CFG.HELDOUT + CFG.CONTROLS):
        p.append(f"the IDs are not H01–H40 and C01–C06: {ids}")
    for c in cases:
        p += [f"{c.get('config')}: {x}" for x in check(c, CFG.FAMILY_OF.get(c.get("config"), "?"))]
    for fam, want in CFG.ANSWERABLE_QUOTA.items():
        got = sum(1 for c in cases if c.get("family") == fam and c.get("answerable"))
        if got != want:
            p.append(f"family {fam}: {got} answerable, the quota is {want}")
    return p


# ------------------------------------------------------------------------------------------------ the comparison
def _spans(text: str, q: str) -> list[tuple[int, int]]:
    out, i = [], q.find(text) if text else -1
    while i >= 0:
        out.append((i, i + len(text)))
        i = q.find(text, i + 1)
    return out


def _touch(a: list[str], b: list[str], q: str) -> bool:
    return any(x[0] < y[1] and y[0] < x[1] for s in a for x in _spans(s, q) for t in b for y in _spans(t, q))


def compare(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    """The gated items on which two records of one question disagree (PROTOCOL.md, "Gated gold items")."""
    q = a["question"]
    out: list[str] = []

    def share(k: str, x: list[Any], y: list[Any]) -> None:
        if (x and y and not set(x) & set(y)) or bool(x) != bool(y):
            out.append(f"{k}: {x} / {y}")
    share("acceptable_outcomes", a["acceptable_outcomes"], b["acceptable_outcomes"])
    for k in ("answerable", "region", "cutoff_utc", "demand_forecast_tools", "unsupported_time"):
        if a[k] != b[k]:
            out.append(f"{k}: {a[k]} / {b[k]}")
    if ("resolved" in a["acceptable_outcomes"]) != ("resolved" in b["acceptable_outcomes"]):
        out.append("resolved is acceptable to one record only")
    share("intents", a["intents"], b["intents"])
    for x, y, who in ((a, b, "first"), (b, a, "second")):
        for m in x["mentions"]:
            hits = [n for n in y["mentions"] if _touch(m["anchors"], n["anchors"], q)]
            if len(hits) != 1:
                out.append(f"mention {m['anchors']} ({who}) matches {len(hits)} mentions of the other")
                continue
            n = hits[0]
            if m["stance"] != n["stance"] or (m["stance"] == "asked" and (m["kind"], m["subject"]) !=
                                               (n["kind"], n["subject"])):
                out.append(f"mention {m['anchors']}: {m['stance']} {m['kind']} {m['subject']} / {n['stance']} "
                           f"{n['kind']} {n['subject']}")
    ra, rb = a["resolution"], b["resolution"]
    if ra is not None and rb is not None:
        for k in ("operation", "maximum"):
            if ra[k] != rb[k]:
                out.append(f"resolution.{k}: {ra[k]} / {rb[k]}")
        if sorted(ra["not_answered"]) != sorted(rb["not_answered"]):
            out.append(f"resolution.not_answered: {ra['not_answered']} / {rb['not_answered']}")
        rr = ("rule", "half_hour_end_utc", "issued_at_utc")
        if tuple(ra["run"].get(k) for k in rr) != tuple(rb["run"].get(k) for k in rr):
            out.append(f"resolution.run: {ra['run']} / {rb['run']}")
        sa, sb = ra["scope"], rb["scope"]
        if (sa is None) != (sb is None):
            out.append(f"resolution.scope: {sa} / {sb}")
        elif sa is not None and sb is not None:
            share("resolution.scope.kinds", sa["kinds"], sb["kinds"])
            for k in ("start_utc", "end_utc", "half_hours"):
                if sa[k] != sb[k]:
                    out.append(f"resolution.scope.{k}: {sa[k]} / {sb[k]}")
    return out


def merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """The frozen record of two agreeing records: the first record, with each set-valued gated item narrowed to the
    members both share."""
    out = json.loads(json.dumps(a))
    out["acceptable_outcomes"] = [o for o in a["acceptable_outcomes"] if o in b["acceptable_outcomes"]]
    out["outcome"] = out["acceptable_outcomes"][0]
    out["intents"] = [i for i in a["intents"] if i in b["intents"]]
    if a["resolution"] and a["resolution"]["scope"] and b["resolution"] and b["resolution"]["scope"]:
        out["resolution"]["scope"]["kinds"] = [k for k in a["resolution"]["scope"]["kinds"]
                                               if k in b["resolution"]["scope"]["kinds"]]
    return out


# ------------------------------------------------------------------------------------------------ build
def build() -> dict[str, Any]:
    written = json.loads((HERE / "WRITER_OUTPUT.json").read_text())["cases"]
    problems = check_writer(written)
    if problems:
        raise SystemExit("the writer's records have problems:\n  " + "\n  ".join(problems))
    rec_ = reconciled()
    review = _reviewed()
    dev = dev_gold()
    final: list[dict[str, Any]] = []
    disagreements: dict[str, list[str]] = {}
    for rec in [*dev, *written]:
        cfg = rec["config"]
        if cfg in rec_["dropped"]:
            continue
        mine, other = rec, review.get(cfg)
        if cfg in rec_["replaced"]:  # a replacement question: the writer's new record against the reviewer's blind one
            mine, other = rec_["replaced"][cfg]["writer"], rec_["replaced"][cfg]["reviewer"]
        elif cfg in rec_["final"]:  # the writer's final record, accepted by the reviewer: replaces both readings
            mine = other = rec_["final"][cfg]
        if cfg in CFG.HELDOUT + CFG.CONTROLS and mine is not rec:
            bad = check(mine, CFG.FAMILY_OF[cfg])
            if bad:
                raise SystemExit(f"{cfg}: the reconciled record has problems: {bad}")
        diff = compare(mine, other) if other else ["no reviewer record"]
        if diff:
            disagreements[cfg] = diff
        final.append(merge(mine, other) if other and not diff else mine)
    held = [r for r in final if r["config"] in CFG.HELDOUT + CFG.CONTROLS]
    unresolved = [c for c in disagreements if c in CFG.HELDOUT + CFG.CONTROLS]
    if unresolved:
        raise SystemExit(f"held-out disagreements to reconcile first (RECONCILE_BRIEF.md): {unresolved}")
    sets = {**{c["config"]: "development" for c in dev},
            **{c: ("control" if c in CFG.CONTROLS else "heldout") for c in CFG.HELDOUT + CFG.CONTROLS}}
    cases = [{"config": r["config"], "set": sets[r["config"]], "family": r.get("family", "development"),
              "question": r["question"], "request": r["request"], "repeats": CFG.REPEATS[sets[r["config"]]],
              "answerable": r["answerable"]} for r in final]
    sources = {rel: _sha(REPO / rel) for rel in V15_SOURCES} | {
        c["source"].split("#")[0]: _sha(REPO / c["source"].split("#")[0]) for c in CFG.development_cases()}
    (HERE / "GOLD.json").write_text(json.dumps({"generated_by": "eval/compare_route_v15_v16/gold.py build",
                                                "sources_sha256": sources, "dropped": sorted(rec_["dropped"]),
                                                "cases": final}, indent=1) + "\n")
    (HERE / "cases.json").write_text(json.dumps({"cases": cases}, indent=1) + "\n")
    summary = {"configurations": len(final), "heldout_answerable": sum(1 for r in held if r["answerable"]
                                                                       and r["config"] in CFG.HELDOUT),
               "reconciled": {k: sorted(v) for k, v in rec_.items()},
               "development_disagreements": {c: d for c, d in disagreements.items() if sets.get(c) == "development"}}
    print(json.dumps(summary, indent=1))
    return summary


def reconciled() -> dict[str, Any]:
    """RECONCILED.json (RECONCILE_BRIEF.md), written mechanically from the agents' replies: ``final``, records the
    reviewer accepted; ``replaced``, a replacement question's writer and reviewer records; ``dropped``, questions still
    in disagreement after the replacement round."""
    p = HERE / "RECONCILED.json"
    data = json.loads(p.read_text()) if p.exists() else {}
    return {"final": {r["config"]: r for r in data.get("final", [])},
            "replaced": {r["config"]: r for r in data.get("replaced", [])},
            "dropped": set(data.get("dropped", []))}


def _sha(p: Path) -> str:
    import hashlib

    return hashlib.sha256(p.read_bytes()).hexdigest()


def _reviewed() -> dict[str, dict[str, Any]]:
    """The reviewer's blind records under the configurations' own IDs (REVIEW_IDS.json)."""
    ids = json.loads((HERE / "REVIEW_IDS.json").read_text())["ids"]
    return {ids[r["config"]]: {**r, "config": ids[r["config"]]}
            for r in json.loads((HERE / "REVIEW.json").read_text())["cases"]}


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    if sys.argv[1] == "check":
        cases = json.loads(Path(sys.argv[2]).read_text())["cases"]
        problems = check_writer(cases)
        print("\n".join(problems) if problems else "no problems")
        return 1 if problems else 0
    if sys.argv[1] == "compare":
        written = {c["config"]: c for c in json.loads((HERE / "WRITER_OUTPUT.json").read_text())["cases"]}
        dev = {c["config"]: c for c in dev_gold()}
        review = _reviewed()
        report = {}
        for cfg, rec in {**dev, **written}.items():
            other = review.get(cfg)
            report[cfg] = compare(rec, other) if other else ["no reviewer record"]
        print(json.dumps({k: v for k, v in report.items() if v}, indent=1))
        return 0
    if sys.argv[1] == "build":
        build()
        return 0
    raise SystemExit(__doc__)


if __name__ == "__main__":
    raise SystemExit(main())
