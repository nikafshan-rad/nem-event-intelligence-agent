"""Copy the cases and gold of the end-to-end Live acceptance check of v13 request resolution (PROTOCOL.md) from their
frozen sources. Offline: nothing is computed, and nothing calls a model.

It writes:
- `cases.json`: the 8 cases, copied unchanged from the maxima check's `cases.json` with two keys added, `e2e_group` and
  `source`. F07N is F07 without its request field: `source.changed` records exactly what differs;
- `GOLD.json`: per case, the maxima check's gold entry (reading and result), the routing-only check's gold for its
  question, and for R02 the answer gold already in its case (K06's), each copied unchanged, with the sources' SHA-256.

It refuses to copy unless the maxima check's gold and its independent check (`GOLD_CHECK.json`) agree exactly.

Usage: python eval/livecheck_e2e_v13/build_cases.py
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
MAXIMA, MAXIMA_GOLD = "eval/livecheck_maxima/cases.json", "eval/livecheck_maxima/GOLD.json"
MAXIMA_CHECK = "eval/livecheck_maxima/GOLD_CHECK.json"
ROUTE_GOLD = "eval/livecheck_route_v13/GOLD.json"
SOURCES = [MAXIMA, MAXIMA_GOLD, MAXIMA_CHECK, ROUTE_GOLD]

# (case ID, group, maxima case, routing-only configuration of the same question and request)
PLAN: list[tuple[str, str, str, str]] = [
    ("D01", "answerable", "D01", "C03"),
    ("D02", "answerable", "D02", "C01"),
    ("F02", "answerable", "F02", "C02"),
    ("F06", "answerable", "F06", "C04"),
    ("F07", "answerable", "F07", "C05"),
    ("F07N", "clarification_control", "F07", "C06"),
    ("F08", "clarification_control", "F08", "C07"),
    ("R02", "non_maximum_control", "R02", "C10"),
]
# F07N: F07 without its request field. Its expectation is the routing-only check's C06 (sent back for the cutoff);
# `expected` takes the shape of F08's, the maxima check's must-clarify case.
F07N_EXPECTED = {"area": "demand_max", "expected_outcome": "clarification", "intent": "market_event_review",
                 "answerable": False, "status_in": ["needs_clarification"], "required_tools": []}


def _read(rel: str) -> Any:
    return json.loads((REPO / rel).read_text())


def _sha(rel: str) -> str:
    return hashlib.sha256((REPO / rel).read_bytes()).hexdigest()


def _maxima_gold_module() -> Any:
    spec = importlib.util.spec_from_file_location("livecheck_maxima_gold_for_e2e", REPO / "eval/livecheck_maxima/gold.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def f07n(f07: dict[str, Any]) -> dict[str, Any]:
    """F07 without its request field: sent back for the cutoff. Only `case_id`, `request`, `expected` and two fields of
    `intended` differ, and each difference is recorded."""
    c = copy.deepcopy(f07)
    c["case_id"] = "F07N"
    c["request"] = {}
    c["expected"] = dict(F07N_EXPECTED)
    c["intended"] = dict(f07["intended"], as_of_utc=None, expected_outcome="clarification")
    changed = {"case_id": {"from": "F07", "to": "F07N"},
               "request": {"from": f07["request"], "to": {}},
               "expected": {"from": f07["expected"], "to": c["expected"]},
               "intended.as_of_utc": {"from": f07["intended"]["as_of_utc"], "to": None},
               "intended.expected_outcome": {"from": f07["intended"]["expected_outcome"], "to": "clarification"}}
    return c | {"_changed": changed}


def build() -> tuple[dict[str, Any], dict[str, Any]]:
    gold_mod = _maxima_gold_module()
    mg, check = _read(MAXIMA_GOLD), _read(MAXIMA_CHECK)
    diffs = gold_mod.compare(mg, check)
    if diffs:
        raise SystemExit("the maxima check's gold and its independent check disagree:\n" + "\n".join(diffs))
    src = {c["case_id"]: c for c in _read(MAXIMA)["cases"]}
    mgold = {c["case_id"]: c for c in mg["cases"]}
    rgold = {c["config"]: c for c in _read(ROUTE_GOLD)["cases"]}
    sha = {rel: _sha(rel) for rel in SOURCES}
    cases, gold = [], []
    for cid, group, from_id, config in PLAN:
        base = src[from_id]
        c = f07n(base) if cid == "F07N" else copy.deepcopy(base)
        changed = c.pop("_changed", {})
        c["e2e_group"] = group
        c["source"] = {"file": MAXIMA, "case_id": from_id, "sha256": sha[MAXIMA], "changed": changed}
        cases.append(c)
        mx = mgold.get(from_id)
        clarify = group == "clarification_control"
        gold.append({
            "case_id": cid, "e2e_group": group,
            "expected_outcome": ("clarification" if clarify else "forecast_run" if group == "non_maximum_control"
                                 else mx["reading"]["expected_outcome"]),
            # the maxima check's gold, unchanged; F07N has none of its own (it must be sent back)
            "maxima_gold": None if cid == "F07N" else copy.deepcopy(mx),
            "reading": None if clarify or mx is None else copy.deepcopy(mx["reading"]),
            "result": None if clarify or mx is None else copy.deepcopy(mx["result"]),
            "routing": copy.deepcopy(rgold[config]),
            "answer": ({k: copy.deepcopy(base["expected"][k]) for k in ("gold_run", "gold_numbers")}
                       if group == "non_maximum_control" else None),
            "copied_from": {"maxima": f"{MAXIMA_GOLD} {from_id}" if mx and cid != "F07N" else None,
                            "routing": f"{ROUTE_GOLD} {config}",
                            "answer": f"{MAXIMA} {from_id} expected (K06's frozen gold)"
                            if group == "non_maximum_control" else None},
        })
    return ({"version": "livecheck_e2e_v13/1", "cases": cases},
            {"generated_by": "eval/livecheck_e2e_v13/build_cases.py", "sources_sha256": sha,
             "maxima_gold_check_agrees": True, "cases": gold})


def main() -> int:
    cases, gold = build()
    (HERE / "cases.json").write_text(json.dumps(cases, indent=1) + "\n")
    (HERE / "GOLD.json").write_text(json.dumps(gold, indent=1) + "\n")
    for g in gold["cases"]:
        r = g["result"] or {}
        print(g["case_id"], g["e2e_group"], g["expected_outcome"], r.get("status"), r.get("value"),
              r.get("interval_ends_utc"), g["routing"]["outcome"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
