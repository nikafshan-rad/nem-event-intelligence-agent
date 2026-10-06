"""The 69 configurations of the comparison (PROTOCOL.md, "The sample"): 40 held-out questions (H01–H40), 6
known-unsupported controls (C01–C06), both written by the independent writer, and 23 development configurations taken
unchanged from earlier records (read only). Offline; no model call.

Development: the 17 v15 diagnostic configurations (``V15-<config>``) and the saved end-to-end records of
``LC-e2e-v13-run`` that do not duplicate one of them (``E2E-<case>``). Two end-to-end records are duplicates, by their
question and request fields: R02 of v15 D02, and F07 of v15 D10. F07N (F07's question without the request cutoff) is
kept.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
V15_CASES = REPO / "eval" / "livecheck_route_v15" / "cases.json"
E2E_DIR = REPO / "artifacts" / "live" / "LC-e2e-v13-run"
E2E_KEPT = ("D01", "D02", "F02", "F06", "F07N", "F08")
E2E_DUPLICATES = {"R02": "V15-D02", "F07": "V15-D10"}
HELDOUT = [f"H{n:02d}" for n in range(1, 41)]
CONTROLS = [f"C{n:02d}" for n in range(1, 7)]
REPEATS = {"heldout": 3, "control": 3, "development": 1}
ARMS = ("A", "B")
FAMILY_OF = {**{f"H{n:02d}": f for f, ns in (
    ("plain", range(1, 5)), ("ambiguity", range(5, 9)), ("incidental", range(9, 13)), ("negation", range(13, 17)),
    ("background", range(17, 21)), ("mixed_operations", range(21, 25)), ("mixed_kinds", range(25, 29)),
    ("shared_scope", range(29, 33)), ("time_roles", range(33, 37)), ("overrides", range(37, 41))) for n in ns},
    **{c: "control" for c in CONTROLS}}
# PROTOCOL.md, "The sample": answerable held-out questions by family (31 in all)
ANSWERABLE_QUOTA = {"plain": 4, "ambiguity": 0, "incidental": 2, "negation": 4, "background": 4, "mixed_operations": 1,
                    "mixed_kinds": 4, "shared_scope": 4, "time_roles": 4, "overrides": 4}


def _norm(q: str) -> str:
    return re.sub(r"\s+", " ", q.strip().lower())


def development_cases() -> list[dict[str, Any]]:
    """The 23 development configurations, with their source, question and request fields (read only)."""
    out = [{"config": f"V15-{c['config']}", "set": "development", "family": "development",
            "source": f"eval/livecheck_route_v15/cases.json#{c['config']}", "question": c["question"],
            "request": c.get("request") or {}} for c in json.loads(V15_CASES.read_text())["cases"]]
    for case in E2E_KEPT:
        rec = json.loads((E2E_DIR / f"{case}.json").read_text())
        out.append({"config": f"E2E-{case}", "set": "development", "family": "development",
                    "source": f"artifacts/live/LC-e2e-v13-run/{case}.json", "question": rec["question"],
                    "request": rec.get("request") or {}})
    return out


def duplicate_check() -> dict[str, Any]:
    """Every end-to-end record against the v15 configurations, by question and request fields."""
    v15 = {(_norm(c["question"]), json.dumps(c.get("request") or {}, sort_keys=True)): f"V15-{c['config']}"
           for c in json.loads(V15_CASES.read_text())["cases"]}
    found = {}
    for p in sorted(E2E_DIR.glob("*.json")):
        rec = json.loads(p.read_text())
        key = (_norm(rec["question"]), json.dumps(rec.get("request") or {}, sort_keys=True))
        if key in v15:
            found[p.stem] = v15[key]
    return {"e2e_records": sorted(p.stem for p in E2E_DIR.glob("*.json")), "duplicates": found}


def slots_per_arm(cases: list[dict[str, Any]]) -> int:
    return sum(REPEATS[c["set"]] for c in cases)
