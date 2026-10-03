"""Adversarial controls for the demand-extreme backstop's window (I-18 review before merging PR #56), offline.

Each control is a SYNTHETIC answer stating a TAS1 dispatch total demand (TOTALDEMAND) extreme, with SYNTHETIC tool
records and evidence, validated with ``validation.validate``. The question each asks: is the stated extreme certified
only when code computed it over the window the answer claims, for the same measure and region, with every interval
held?

SYNTHETIC day (29 July 2026, AEST; 288 five-minute intervals): 1000 MW everywhere except
- the day's maximum, 1400 MW, in the interval ending 21:55Z (07:55 AEST);
- the day's minimum, 900 MW, ending 17:00Z (03:00 AEST);
- in a two-hour subset (02:00Z to 04:00Z): its maximum 1200 MW (ending 03:00Z) and its minimum 950 MW (ending 02:30Z);
- in an "event" window (00:00Z to 06:00Z): its maximum 1300 MW (ending 05:00Z) -- the subset lies inside it;
- before an as-of cutoff at 20:00Z (06:00 AEST), when only the first six hours are public: their maximum 1100 MW
  (ending 19:00Z); the day's maximum comes later.

Usage: python eval/structured_requests/backstop_window_controls.py [OUT.json]
Prints one line per control: expected, observed, and whether they agree. Runs on any revision with the backstop.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from nem_agent import config
from nem_agent.evidence import EvidenceRegistry
from nem_agent.report import InvestigationReport, NumericClaim, Versions
from nem_agent.timeutil import UTC, iso_utc, parse_iso
from nem_agent.validation import validate

DAY = (datetime(2026, 7, 28, 14, tzinfo=UTC), datetime(2026, 7, 29, 14, tzinfo=UTC))
SUBSET = (datetime(2026, 7, 29, 2, tzinfo=UTC), datetime(2026, 7, 29, 4, tzinfo=UTC))
EVENT = (datetime(2026, 7, 29, 0, tzinfo=UTC), datetime(2026, 7, 29, 6, tzinfo=UTC))
SPECIAL = {"2026-07-28T21:55:00Z": 1400.0, "2026-07-28T17:00:00Z": 900.0, "2026-07-29T03:00:00Z": 1200.0,
           "2026-07-29T02:30:00Z": 950.0, "2026-07-29T05:00:00Z": 1300.0, "2026-07-28T19:00:00Z": 1100.0}
CUTOFF = datetime(2026, 7, 28, 20, tzinfo=UTC)  # the tools return only intervals public by then


def _ends(w: tuple[datetime, datetime]) -> list[str]:
    n = int((w[1] - w[0]) / timedelta(minutes=5))
    return [iso_utc(w[0] + timedelta(minutes=5 * (i + 1))) for i in range(n)]


def _world() -> tuple[EvidenceRegistry, dict[str, str]]:
    """A registry with one TOTALDEMAND evidence item per interval of the day; interval end -> evidence ID."""
    reg = EvidenceRegistry()
    ids = {}
    for t in _ends(DAY):
        ev = reg.add(evidence_class="observed", metric="dispatch_totaldemand", value=SPECIAL.get(t, 1000.0), unit="MW",
                     region="TAS1", valid_at_utc=t, interval_minutes=5, source_row_ids=[f"SYN:{t}"],
                     source_urls=["https://example.invalid"], tool_call_id="syn", label="SYNTHETIC")
        ids[t] = ev.evidence_id
    return reg, ids


def _call(ids: dict[str, str], w: tuple[datetime, datetime], upto: datetime | None = None) -> Any:
    """A get_price_timeline record for the window (only intervals ending by ``upto``, as under an as-of cutoff)."""
    series = [{"interval_end_utc": t, "totaldemand_mw": SPECIAL.get(t, 1000.0), "totaldemand_evidence_id": ids[t]}
              for t in _ends(w) if upto is None or parse_iso(t) <= upto]
    return SimpleNamespace(name="get_price_timeline", status="ok", call_id="syn", view={},
                           args={"region": "TAS1", "start_utc": iso_utc(w[0]), "end_utc": iso_utc(w[1]),
                                 "as_of_utc": iso_utc(upto) if upto else None}, data={"series": series})


def _codes(sentence: str, value: float, end: str, calls: list[Any], window: tuple[datetime, datetime],
           as_of: datetime | None = None) -> list[str]:
    reg, ids = _world()
    records = [c(ids) for c in calls]
    report = InvestigationReport(
        question="SYNTHETIC", mode="replay", intent="market_event_review", region="TAS1",
        as_of=iso_utc(as_of) if as_of else None, event_window=None, headline="SYNTHETIC answer.", summary=[sentence],
        status="answered_with_caveats", trace_id="t", generator="x",
        versions=Versions(code="x", data="x", corpus=None, prompt=config.PROMPT_VERSION, model=None, controller="x"),
        numeric_claims=[NumericClaim(claim_id="n1", text=f"{value} MW", value=value, unit="MW", evidence_id=ids[end],
                                     rounding=0.05)])
    res = validate(report, reg, window=window, records=records, as_of=as_of)
    return sorted({v.code for v in res.critical if v.code == "DEMAND_EXTREME_UNVERIFIED"})


def controls() -> list[dict[str, Any]]:
    full_day = lambda ids: _call(ids, DAY)  # noqa: E731
    subset = lambda ids: _call(ids, SUBSET)  # noqa: E731
    event = lambda ids: _call(ids, EVENT)  # noqa: E731
    before_cutoff = lambda ids: _call(ids, DAY, upto=CUTOFF)  # noqa: E731
    cases = [
        ("subset maximum claimed as the whole-day maximum",
         "TAS1 dispatch total demand was highest for the day at 1200.0 MW.", 1200.0, "2026-07-29T03:00:00Z",
         [subset], DAY, None, "rejected"),
        ("subset minimum claimed as the whole-day minimum",
         "TAS1 dispatch total demand was lowest for the day at 950.0 MW.", 950.0, "2026-07-29T02:30:00Z",
         [subset], DAY, None, "rejected"),
        ("an event window's maximum claimed as the day's (the whole day also retrieved)",
         "TAS1 dispatch total demand was highest for the day at 1300.0 MW.", 1300.0, "2026-07-29T05:00:00Z",
         [full_day, event], DAY, None, "rejected"),
        ("a subset's maximum claimed as the event window's (the event window also retrieved)",
         "Over the event window, TAS1 dispatch total demand peaked at 1200.0 MW.", 1200.0, "2026-07-29T03:00:00Z",
         [event, subset], EVENT, None, "rejected"),
        ("partial coverage under an as-of cutoff, claimed as the whole day's maximum",
         "TAS1 dispatch total demand was highest for the day at 1100.0 MW.", 1100.0, "2026-07-28T19:00:00Z",
         [before_cutoff], DAY, CUTOFF, "rejected"),
        ("control: the whole day's maximum, with the whole day held",
         "TAS1 dispatch total demand was highest for the day at 1400.0 MW.", 1400.0, "2026-07-28T21:55:00Z",
         [full_day], DAY, None, "allowed"),
        ("control: the whole day's minimum, with the whole day held",
         "TAS1 dispatch total demand was lowest for the day at 900.0 MW.", 900.0, "2026-07-28T17:00:00Z",
         [full_day], DAY, None, "allowed"),
        ("control: the event window's maximum, with the event window held",
         "Over the event window, TAS1 dispatch total demand peaked at 1300.0 MW.", 1300.0, "2026-07-29T05:00:00Z",
         [event], EVENT, None, "allowed"),
        ("control: under the cutoff, the highest value held, said as such",
         "Not every interval of the day is public by the cutoff; the highest TAS1 dispatch total demand held is "
         "1100.0 MW.", 1100.0, "2026-07-28T19:00:00Z", [before_cutoff], DAY, CUTOFF, "allowed"),
    ]
    out = []
    for name, sentence, value, end, calls, window, as_of, expected in cases:
        codes = _codes(sentence, value, end, calls, window, as_of)
        observed = "rejected" if codes else "allowed"
        out.append({"control": name, "sentence": sentence, "expected": expected, "observed": observed,
                    "agrees": observed == expected})
    return out


def main() -> int:
    rows = controls()
    for r in rows:
        print(f"{'ok  ' if r['agrees'] else 'MISS'} expected {r['expected']:8} observed {r['observed']:8} {r['control']}")
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(json.dumps({"controls": rows}, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
