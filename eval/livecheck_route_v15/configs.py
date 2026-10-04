"""The 17 configurations of the routing-only Live check of route contract v15 (PROTOCOL.md, "Scope"), shared by
`build_kit.py`, `gold.py` and the tests. Familiar questions are copied unchanged from their sources; fresh ones are the
writer's (`WRITER_OUTPUT.json`)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

# (config, source file, case ID or None for a question quoted in a test file, the question when quoted, request
# fields, set, what it tests)
FAMILIAR: list[tuple[str, str, str | None, str | None, dict[str, Any], str, str]] = [
    ("D01", "eval/livecheck_i15_17/cases.json", "K14", None, {}, "supply",
     "named run; forecast and actual for one half-hour"),
    ("D02", "eval/livecheck_i15_17/cases.json", "K06", None, {}, "supply",
     "last run issued before a half-hour; forecast and actual"),
    ("D03", "eval/cases.json", "FC04", None, {}, "supply", "window comparison over a day"),
    ("D04", "tests/provider/test_forecast_request.py", None,
     "How did the operational demand forecasts compare with actual demand in SA1 between 18:00 and 21:00 ACST on "
     "31 July 2026?", {}, "supply", "a stated window, used exactly"),
    ("D05", "eval/holdout_v5/cases.json", "Y07", None, {}, "supply", "target, window and cutoff separation"),
    ("D06", "eval/holdout_v2/cases.json", "H06", None, {}, "supply",
     "mixed: a demand forecast and a weather expectation"),
    ("D07", "eval/holdout_v6/cases.json", "Z07", None, {}, "supply",
     "mixed: a demand forecast and a temperature expectation"),
    ("D08", "eval/cases.json", "FC02", None, {}, "ambiguity", "an ambiguous forecast reference"),
    ("D09", "tests/provider/test_forecast_domain.py", None,
     "What was the weather forecast for Adelaide on 31 July 2026?", {}, "containment", "weather only"),
    ("D10", "eval/livecheck_maxima/cases.json", "F07", None, {"as_of_utc": "2025-10-05T02:00:00Z"}, "supply",
     "demand-maximum regression control"),
]
FRESH: list[tuple[str, str, str]] = [
    ("N01", "containment", "a temperature forecast only, asking for its highest value"),
    ("N02", "containment", "AEMO's price forecasts only, for a past day"),
    ("N03", "containment", "a genuinely ambiguous reference to the forecasts"),
    ("N04", "supply", "negation: a weather forecast declined, the operational demand forecast asked"),
    ("N05", "containment", "negation: the operational demand forecast declined, a weather forecast asked"),
    ("N06", "containment", "quoted background about a demand forecast; a temperature or weather forecast asked"),
    ("N07", "supply", "quoted background about a weather forecast; the demand forecast compared with actual demand"),
]
SETS: dict[str, str] = {f[0]: f[5] for f in FAMILIAR} | {f[0]: f[1] for f in FRESH}
SUPPLY = [c for c, s in SETS.items() if s == "supply"]
CONTAINMENT = [c for c, s in SETS.items() if s == "containment"]
AMBIGUITY = [c for c, s in SETS.items() if s == "ambiguity"]
REPEATS = 2


def _joined(text: str) -> str:
    """Source text with adjacent Python string literals joined, so a question split over lines reads as one."""
    return re.sub(r"\"\s*\n\s*\"", "", text)


def familiar_question(src: str, cid: str | None, quoted: str | None) -> str:
    """A familiar question, read from its source (a case file), or checked against it (a test file's quotation)."""
    if cid is not None:
        cases = json.loads((REPO / src).read_text())["cases"]
        return str(next(c for c in cases if c.get("case_id") == cid)["question"])
    assert quoted is not None
    if quoted not in _joined((REPO / src).read_text()):
        raise SystemExit(f"{src} does not hold the question {quoted!r}")
    return quoted


def familiar_cases() -> list[dict[str, Any]]:
    out = []
    for config, src, cid, quoted, request, set_, tests in FAMILIAR:
        out.append({"config": config, "group": "familiar", "set": set_, "tests": tests,
                    "source": {"file": src, "case_id": cid}, "question": familiar_question(src, cid, quoted),
                    "request": request, "repeats": REPEATS})
    return out
