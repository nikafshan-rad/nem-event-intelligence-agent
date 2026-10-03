"""The I-18 gate's decision on every repository question (offline): the question parsers (``requested_forecast``,
``requested_maxima``) and the bounded cues (``forecast_run_cue``, ``maximum_cue``). The paraphrase matrix and its
records are left out. Writes one row per distinct question, and prints the counts and the questions where they differ.

Usage: python eval/structured_requests/gate_review.py OUT.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from nem_agent.agent.request import requested_forecast, requested_maxima
from nem_agent.agent.structured import forecast_run_cue, maximum_cue

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    qs: dict[str, str] = {}
    for f in sorted(ROOT.glob("eval/**/*.json")) + sorted(ROOT.glob("artifacts/live/**/*.json")):
        if "traces" in f.parts or "structured_requests" in f.parts:
            continue
        try:
            d = json.loads(f.read_text())
        except (ValueError, UnicodeDecodeError):
            continue
        items = d if isinstance(d, list) else (d.get("cases") if isinstance(d, dict) else None) or \
            ([d] if isinstance(d, dict) and "question" in d else [])
        for c in items:
            if isinstance(c, dict) and isinstance(c.get("question"), str):
                qs.setdefault(c["question"], str(f.relative_to(ROOT)))
    rows = [{"question": q, "first_seen_in": src, "run_parser": requested_forecast(q) is not None,
             "run_cue": forecast_run_cue(q), "max_parser": requested_maxima(q), "max_cue": maximum_cue(q)}
            for q, src in qs.items()]
    Path(sys.argv[1]).write_text(json.dumps({"questions": len(rows), "rows": rows}, indent=1) + "\n")
    print(f"{len(rows)} distinct questions")
    print("run: parser", sum(r["run_parser"] for r in rows), "cue", sum(bool(r["run_cue"]) for r in rows))
    print("max: parser", sum(bool(r["max_parser"]) for r in rows), "cue", sum(r["max_cue"] for r in rows))
    for r in rows:
        if r["run_parser"] != bool(r["run_cue"]) or bool(r["max_parser"]) != r["max_cue"]:
            print(f"  differ: {r['first_seen_in']}: run {r['run_parser']}/{r['run_cue']} max {r['max_parser']}/"
                  f"{r['max_cue']}: {r['question'][:100]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
