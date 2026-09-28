"""Blind compatibility check of a held-out case file before it is frozen. It prints counts, case IDs and problem codes
only, never questions, gold values or answers, so the developer stays blind to the set.

Checks: the category mix; the split and ID uniqueness; `status_in`, intent and `request` (every case must build an
InvestigateRequest); every row-backed gold number resolves in the repository's store with its value; every gold
snippet is verbatim in its document in the repository's index; no 6-word overlap with earlier questions or prompts.

Usage: python scripts/blind_check_heldout.py eval/holdout_v4/cases.json --split holdout_v4 \
           --prior eval/cases.json eval/holdout_v2/cases.json eval/holdout_v3/cases.json --prompts src/nem_agent/prompts/v11
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

MIX = {"market_event": 4, "forecast": 4, "document": 4, "notice": 3, "ambiguous_unavailable": 2, "adversarial": 2,
       "injection": 1}
TABLE = {"dispatch_rrp": ("price_5min", "rrp"), "dispatch_totaldemand": ("regionsum_5min", "totaldemand_mw"),
         "opdemand_actual": ("opdemand_actual", "operational_demand_mw"),
         "opdemand_forecast_poe50": ("opdemand_forecast", "poe50_mw")}


def grams(t: str, n: int = 6) -> set[str]:
    w = re.findall(r"[a-z0-9']+", t.lower())
    return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cases")
    ap.add_argument("--split", required=True)
    ap.add_argument("--prior", nargs="*", default=[])
    ap.add_argument("--prompts", default=None)
    args = ap.parse_args()
    from nem_agent.agent.request import InvestigateRequest
    from nem_agent.store import Store

    d = json.loads(Path(args.cases).read_text())
    cases = d["cases"]
    problems: list[str] = []
    cats = Counter(c["category"] for c in cases)
    print("version", d.get("version"), "| cases", len(cases), "| by category", dict(cats))
    if dict(cats) != MIX:
        problems.append(f"MIX {dict(cats)} != {MIX}")
    ids = [c["case_id"] for c in cases]
    if len(set(ids)) != len(ids):
        problems.append("DUPLICATE_IDS")
    print("ids", ids)
    st = Store()
    db = sqlite3.connect(REPO / "data" / "index" / "corpus.sqlite")
    n_num = n_ok = n_derived = n_cit = n_cit_ok = gold_cases = as_of_fc = 0
    statuses: Counter[str] = Counter()
    for c in cases:
        e, cid = c.get("expected", {}), c["case_id"]
        if c.get("split") != args.split:
            problems.append(f"{cid}: split")
        for k in ("question", "expected", "provenance"):
            if not c.get(k):
                problems.append(f"{cid}: missing {k}")
        try:
            InvestigateRequest(question=c["question"], mode="live", **c.get("request", {}))
        except Exception as exc:
            problems.append(f"{cid}: request does not build ({type(exc).__name__})")
        st_in = tuple(e.get("status_in") or ())
        statuses["/".join(st_in)] += 1
        if not st_in or not set(st_in) <= {"answered", "answered_with_caveats", "refused", "needs_clarification"}:
            problems.append(f"{cid}: status_in")
        if e.get("intent") not in (None, "market_event_review", "forecast_review", "source_explanation"):
            problems.append(f"{cid}: intent")
        if c["category"] == "forecast" and e.get("as_of_utc"):
            as_of_fc += 1
        if e.get("gold_numbers") or e.get("gold_citation") or e.get("gold_forecast"):
            gold_cases += 1
        for g in e.get("gold_numbers") or []:
            n_num += 1
            if g.get("source_row_id") is None:
                n_derived += 1
                if g.get("metric") != "intervals_meeting_threshold":
                    problems.append(f"{cid}: gold number without a row, metric {g.get('metric')}")
                continue
            t = TABLE.get(g.get("metric"))
            if t is None:
                problems.append(f"{cid}: unknown metric {g.get('metric')}")
                continue
            rows = st.query(f"SELECT {t[1]} AS v FROM {t[0]} WHERE row_id=?", [g["source_row_id"]])
            if not rows:
                problems.append(f"{cid}: gold row not in store")
            elif any(abs(r["v"] - g["value"]) <= (g.get("tolerance") or 0) + 1e-6 for r in rows):
                n_ok += 1
            else:
                problems.append(f"{cid}: gold value differs from its row")
        gc = e.get("gold_citation")
        if gc:
            n_cit += 1
            texts = [r[0] for r in db.execute("SELECT text FROM chunks WHERE doc_id=?", (gc["doc_id"],))]
            if not texts:
                problems.append(f"{cid}: citation document not in index")
            elif len(gc["snippet"]) >= 20 and any(gc["snippet"] in t for t in texts):
                n_cit_ok += 1
            else:
                problems.append(f"{cid}: snippet not verbatim in its document")
    print(f"gold numbers {n_ok}/{n_num - n_derived} row-backed resolve; {n_derived} derived counts; gold citations "
          f"{n_cit_ok}/{n_cit} verbatim; cases with gold labels G={gold_cases} -> Q3 bar {math.ceil(0.8 * gold_cases)}; "
          f"forecast cases with as_of: {as_of_fc}")
    print("status_in patterns", dict(statuses))
    prior = [c["question"] for p in args.prior for c in json.loads(Path(p).read_text())["cases"]]
    pg = set().union(*(grams(q) for q in prior)) if prior else set()
    prompt_g = set().union(*(grams(f.read_text()) for f in Path(args.prompts).glob("*.md"))) if args.prompts else set()
    exact = {q.strip().lower() for q in prior}
    ov_prior = [c["case_id"] for c in cases if grams(c["question"]) & pg]
    ov_prompt = [c["case_id"] for c in cases if grams(c["question"]) & prompt_g]
    dup = [c["case_id"] for c in cases if c["question"].strip().lower() in exact]
    print(f"6-word overlap with the {len(prior)} earlier questions:", ov_prior or "none", "| with prompts:",
          ov_prompt or "none", "| exact duplicates:", dup or "none")
    if ov_prior or ov_prompt or dup:
        problems.append("OVERLAP")
    print("PROBLEMS:", problems or "none")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
