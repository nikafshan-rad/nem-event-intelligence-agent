"""The configurations and gold of the routing-only Live check of route contract v13 (PROTOCOL.md). Offline.

It writes:
- `cases.json`: the 11 configurations, with questions copied unchanged from their source files;
- `GOLD.json`: each configuration's expected outcome and binding, copied from independently checked sources, with
  those sources' SHA-256.

Nothing here is computed from the application's resolver. The consistency checks are mechanical:
- a whole-day window is the region's local day of its date;
- a half-hour ends at its gold target;
- the sources' questions are the ones copied.

Usage: python eval/livecheck_route_v13/gold.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
MAXIMA, MAXIMA_GOLD = "eval/livecheck_maxima/cases.json", "eval/livecheck_maxima/GOLD.json"
MAXIMA_CHECK = "eval/livecheck_maxima/GOLD_CHECK.json"
ROUTING, ROUTING_VER = "eval/livecheck_routing_v12/cases.json", "eval/livecheck_routing_v12/VERIFICATION.json"
LC, LC_VER = "eval/livecheck_i15_17/cases.json", "eval/livecheck_i15_17/VERIFICATION.json"
SOURCES = [MAXIMA, MAXIMA_GOLD, MAXIMA_CHECK, ROUTING, ROUTING_VER, LC, LC_VER]
TZ = {"NSW1": "Australia/Sydney", "QLD1": "Australia/Brisbane", "SA1": "Australia/Adelaide",
      "TAS1": "Australia/Hobart", "VIC1": "Australia/Melbourne"}
KIND = {"day": "day", "event": "event", "explicit": "explicit"}

# (config, source file, source case, request fields, kind, purpose, repeats)
CONFIGS: list[tuple[str, str, str, dict[str, Any], str, str, int]] = [
    ("C01", MAXIMA, "D02", {}, "supply", "truncation variability (reported apart)", 5),
    ("C02", MAXIMA, "F02", {}, "supply", "truncation variability (reported apart)", 5),
    ("C03", MAXIMA, "D01", {}, "supply", "extraction of a reading v12 rejected", 3),
    ("C04", MAXIMA, "F06", {}, "supply", "extraction of a reading v12 rejected", 3),
    ("C05", MAXIMA, "F07", {"as_of_utc": "2025-10-05T02:00:00Z"}, "supply", "the cutoff from the request field", 3),
    ("C06", MAXIMA, "F07", {}, "containment", "\"noon\" cannot be converted: sent back for the cutoff", 3),
    ("C07", MAXIMA, "F08", {}, "containment", "no measure named: sent back", 2),
    ("C08", ROUTING, "Q17", {}, "containment", "a run's half-hour with no date: sent back", 2),
    ("C09", ROUTING, "Q21", {}, "containment", "no maximum requested (demand at the price peak)", 2),
    ("C10", LC, "K06", {}, "supply", "run selection: the last run issued before a half-hour", 2),
    ("C11", LC, "K14", {}, "supply", "run selection: a run named by its issue time", 2),
]


def _cases(rel: str) -> dict[str, dict[str, Any]]:
    return {c["case_id"]: c for c in json.loads((REPO / rel).read_text())["cases"]}


def _sha(rel: str) -> str:
    return hashlib.sha256((REPO / rel).read_bytes()).hexdigest()


def _local_day(d: date, region: str) -> list[str]:
    z = ZoneInfo(TZ[region])
    a = datetime.combine(d, datetime.min.time(), z).astimezone(ZoneInfo("UTC"))
    b = datetime.combine(d + timedelta(days=1), datetime.min.time(), z).astimezone(ZoneInfo("UTC"))
    return [a.strftime("%Y-%m-%dT%H:%M:%SZ"), b.strftime("%Y-%m-%dT%H:%M:%SZ")]


def _t(s: str, minutes: int = 0) -> str:
    t = datetime.fromisoformat(s.replace("Z", "+00:00")) + timedelta(minutes=minutes)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def gold_of(config: str, src: str, cid: str, request: dict[str, Any]) -> dict[str, Any]:
    """The configuration's gold: its expected outcome, region, maximum, forecast run and cutoff."""
    if src == MAXIMA:
        g = next(c for c in json.loads((REPO / MAXIMA_GOLD).read_text())["cases"] if c["case_id"] == cid)
        r = g["reading"]
        if r["expected_outcome"] == "clarification":
            return {"outcome": "clarify", "region": r["region"], "maximum": None, "forecast_run": None,
                    "as_of_utc": None, "missing": ["measure"], "source": f"{MAXIMA_GOLD} {cid}"}
        if r["window_kind"] == "day":  # mechanical check: the gold window is the region's local day of its date
            d = (datetime.fromisoformat(r["window_utc"][0].replace("Z", "+00:00")) + timedelta(hours=12)).astimezone(
                ZoneInfo(TZ[r["region"]])).date()
            if _local_day(d, r["region"]) != r["window_utc"]:
                raise SystemExit(f"{config}: {cid}'s window is not the local day of {d}")
        maximum = {"measure": r["measure"], "window_kind": KIND[r["window_kind"]], "window_utc": r["window_utc"]}
        if config == "C06":  # no request field, and "noon" cannot be converted (D26): sent back for the cutoff
            return {"outcome": "clarify", "region": r["region"], "maximum": maximum, "forecast_run": None,
                    "as_of_utc": None, "missing": ["cutoff"], "source": f"{MAXIMA_GOLD} {cid}, without its request field"}
        if r["as_of_utc"] != request.get("as_of_utc"):
            raise SystemExit(f"{config}: the gold cutoff {r['as_of_utc']} is not the request field's")
        return {"outcome": "bound", "region": r["region"], "maximum": maximum, "forecast_run": None,
                "as_of_utc": r["as_of_utc"], "source": f"{MAXIMA_GOLD} {cid}"}
    if src == ROUTING:
        e = _cases(ROUTING)[cid]["expected"]
        if e["outcome"] == "clarify":
            return {"outcome": "clarify", "region": e["region"], "maximum": None, "forecast_run": None,
                    "as_of_utc": None, "missing": e.get("missing") or [], "source": f"{ROUTING} {cid}"}
        if e["outcome"] == "no_request":
            return {"outcome": "no_request", "region": e["region"], "maximum": None, "forecast_run": None,
                    "as_of_utc": None, "source": f"{ROUTING} {cid}"}
        raise SystemExit(f"{config}: unexpected outcome {e['outcome']}")
    e = _cases(LC)[cid]["expected"]
    run = e["gold_run"]
    selection = "issued_at" if cid == "K14" else "last_issued_before"
    if e.get("as_of_utc"):
        raise SystemExit(f"{config}: {cid} has a cutoff")
    return {"outcome": "bound", "region": _region(cid),
            "maximum": None,
            "forecast_run": {"selection": selection, "half_hour_utc": [_t(run["target_end_utc"], -30),
                                                                       run["target_end_utc"]],
                             "issued_at_utc": run["issued_at_utc"] if selection == "issued_at" else None},
            "as_of_utc": None, "source": f"{LC} {cid} (gold_run)"}


def _region(cid: str) -> str:
    """K06 asks about South Australia, K14 about Tasmania (their gold labels name the region)."""
    label = _cases(LC)[cid]["expected"]["gold_numbers"][0]["label"]
    return next(r for r in TZ if label.startswith(r))


def build() -> tuple[dict[str, Any], dict[str, Any]]:
    cases, gold = [], []
    for config, src, cid, request, kind, purpose, repeats in CONFIGS:
        q = _cases(src)[cid]["question"]
        cases.append({"config": config, "source": {"file": src, "case_id": cid}, "question": q, "request": request,
                      "kind": kind, "purpose": purpose, "repeats": repeats})
        gold.append({"config": config, **gold_of(config, src, cid, request)})
    sources = {rel: _sha(rel) for rel in SOURCES}
    return ({"version": "livecheck_route_v13/1", "questions": len({(c["source"]["file"], c["source"]["case_id"])
                                                                    for c in cases}),
             "configurations": len(cases), "calls": sum(c["repeats"] for c in cases), "cases": cases},
            {"generated_by": "eval/livecheck_route_v13/gold.py", "sources_sha256": sources, "cases": gold})


def main() -> int:
    cases, gold = build()
    (HERE / "cases.json").write_text(json.dumps(cases, indent=1) + "\n")
    (HERE / "GOLD.json").write_text(json.dumps(gold, indent=1) + "\n")
    print(f"{cases['questions']} questions, {cases['configurations']} configurations, {cases['calls']} calls")
    for g in gold["cases"]:
        print(g["config"], g["outcome"], g["region"], g["maximum"], g["forecast_run"], g["as_of_utc"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
