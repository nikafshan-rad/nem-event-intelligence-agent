"""F07 end to end through the fake transport (D26): the exact input, where each resolved value comes from, and the
computed result against independently checked gold. Offline: no network, no key, a scratch ledger.

The input has three kinds, kept apart:
- **question-derived:** read by code from the question's words;
- **request override:** the case's request field `as_of_utc`, which is authoritative over the question's wording;
- **scripted reading:** a SYNTHETIC v13 routing decision written by the developer as a careful model would answer.
  It is not Live evidence, and the Live check never ran F07 under v13.

**The cutoff:**
- **The question's words** ("published by noon Brisbane time on Sunday 5 October 2025") name a cutoff that code
  cannot convert: "noon" is not a clock time code reads, a recorded limitation.
- **With the request field,** the cutoff is that field (the override). The question's words are located, so they
  hold "noon" and it does not narrow the window, but they are never converted or applied. A note says they could not
  be compared with the request's cutoff.
- **Without the request field,** the cutoff cannot be pinned down, and the question is sent back before any tool runs
  (contrast b).

Usage: python eval/route_v13/f07_end_to_end.py OUT.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from tests.provider.fake_model import FakeModel  # noqa: E402

from nem_agent.agent.request import InvestigateRequest, extract_dates, extract_regions  # noqa: E402
from nem_agent.service import investigate  # noqa: E402

CASE = next(c for c in json.loads((REPO / "eval/livecheck_maxima/cases.json").read_text())["cases"]
            if c["case_id"] == "F07")
GOLD = next(c for c in json.loads((REPO / "eval/livecheck_maxima/GOLD.json").read_text())["cases"]
            if c["case_id"] == "F07")
QUESTION = CASE["question"]
REQUEST = CASE["request"]  # {"as_of_utc": "2025-10-05T02:00:00Z"}: the case's request field
CUTOFF_WORDS = "published by noon Brisbane time on Sunday 5 October 2025"
SCRIPTED = {  # SYNTHETIC: the developer's v13 reading, as a careful model would give it
    "intent": "market_event_review", "region": "QLD1", "event_date": "2025-10-05", "as_of_text": CUTOFF_WORDS,
    "needs_clarification": False, "clarification_reason": None, "clarification": None, "out_of_scope": False,
    "requested": {"forecast_run": {"selection": "none", "selection_text": None, "half_hour_text": None},
                  "maximum": {"kind": "maximum", "measure": "operational_demand", "measure_text": "operational demand",
                              "peak_text": "highest", "window": "whole_local_day",
                              "window_text": "that entire local day"}}}
DRAFT = {"status": "answered", "headline": "SYNTHETIC answer.", "summary": ["SYNTHETIC."], "document_statements": [],
         "observation_evidence_ids": [], "possible_explanations": [], "published_findings": [], "citations": [],
         "uncertainties": [], "missing_evidence": [], "forecast_mae_evidence_id": None, "numeric_claims": []}


def _z(t: Any) -> str | None:
    return t.isoformat().replace("+00:00", "Z") if t is not None else None


def run(decision: dict[str, Any], request: dict[str, Any]) -> tuple[Any, FakeModel]:
    fake = FakeModel(decision, [[]], lambda kw: dict(DRAFT))
    res = investigate(InvestigateRequest(question=QUESTION, mode="live", **request), live_client=fake,
                      write_trace=False)
    return res, fake


def main() -> dict[str, Any]:
    res, fake = run(SCRIPTED, REQUEST)
    rz = res.resolution
    rq = rz.requests
    mx, co = rq.maximum, rq.cutoff
    (r,) = res.report.results
    result = r.result
    value = result.maximum if result.status == "established" else result.highest_held
    ends = list(result.interval_ends_utc or result.highest_held_interval_ends_utc)
    g = GOLD["result"]
    record = {
        "input": {"question": QUESTION, "request_override": REQUEST, "scripted_reading": SCRIPTED,
                  "scripted_reading_note": "SYNTHETIC: written by the developer; not Live evidence"},
        "resolution": {
            "region": {"value": rz.region, "question_parser": extract_regions(QUESTION),
                       "scripted_reading": SCRIPTED["region"]},
            "date": {"value": str(extract_dates(QUESTION)[0]), "question_parser": [str(d) for d in extract_dates(QUESTION)],
                     "scripted_reading": SCRIPTED["event_date"]},
            "measure": {"value": mx.measures, "provenance": mx.provenance["measure"].as_dict()},
            "window": {"kind": mx.window_kind, "utc": [_z(t) for t in mx.window],
                       "provenance": mx.provenance["window"].as_dict(),
                       "how": "the scripted reading's words 'that entire local day', located in the question and "
                              "checked for the whole-day role; the day is the question's only date, and code builds "
                              "its local window in Australia/Brisbane"},
            "cutoff": {"value": _z(rz.as_of), "provenance": co.provenance["as_of"].as_dict(),
                       "question_words": co.stated_words, "question_words_read_as": _z(co.stated),
                       "spans": [s.as_dict() for s in co.spans],
                       "how": "the request field (override). The question's own cutoff words are located (they hold "
                              "'noon', so it does not narrow the window), but code cannot convert 'noon', so they are "
                              "neither compared nor applied"},
            "notes_shown": rq.notes,
            "model_calls": len(fake.requests),
        },
        "result": {"status": result.status, "value": value, "interval_ends_utc": ends,
                   "source_row_ids": list(result.source_row_ids),
                   "coverage": result.coverage.model_dump() if result.coverage else None,
                   "server_verification": r.server_verification.outcome, "answer": res.report.answer[0].statement},
        "gold": {"reading": GOLD["reading"], "result": {k: g[k] for k in (
            "status", "value", "interval_ends_utc", "source_row_ids", "intervals_held", "intervals_in_window",
            "excluded_rows_by_as_of")}},
    }
    record["matches_gold"] = {
        "window": record["resolution"]["window"]["utc"] == GOLD["reading"]["window_utc"]
        and mx.window_kind == GOLD["reading"]["window_kind"],
        "cutoff": record["resolution"]["cutoff"]["value"] == GOLD["reading"]["as_of_utc"],
        "measure": mx.measures == [GOLD["reading"]["measure"]],
        "result": (result.status, value, ends, list(result.source_row_ids)) == (
            g["status"], g["value"], g["interval_ends_utc"], g["source_row_ids"])
        and result.coverage is not None and (result.coverage.intervals_held, result.coverage.intervals_in_window,
                                             result.coverage.excluded_by_as_of) == (
            g["intervals_held"], g["intervals_in_window"], g["excluded_rows_by_as_of"]),
    }
    # contrasts: (b) no request field, so the cutoff cannot be pinned down; (c) the cutoff's words not quoted, so
    # "noon" cannot be attributed to the cutoff and may narrow the window
    b, fb = run(SCRIPTED, {})
    c, fc = run({**SCRIPTED, "as_of_text": None}, REQUEST)
    record["contrasts"] = {
        "b_no_request_field": {"status": b.report.status, "reasons": b.resolution.reasons,
                               "cutoff": b.resolution.requests.cutoff.status, "model_calls": len(fb.requests),
                               "results": len(b.report.results)},
        "c_cutoff_words_not_quoted": {"status": c.report.status, "reasons": c.resolution.reasons,
                                      "maximum": c.resolution.requests.maximum.status,
                                      "unused": c.resolution.requests.maximum.unused, "model_calls": len(fc.requests),
                                      "results": len(c.report.results)},
    }
    return record


if __name__ == "__main__":
    out = main()
    Path(sys.argv[1]).write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({"matches_gold": out["matches_gold"], "cutoff": out["resolution"]["cutoff"]["provenance"],
                      "notes": out["resolution"]["notes_shown"],
                      "contrasts": {k: (v["status"], v["model_calls"]) for k, v in out["contrasts"].items()}}, indent=1))
