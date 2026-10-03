"""Deterministic time conversion against independently checked gold (D26, correction 2). Offline: no model call.

For every saved Live routing decision and every decision of the I-18 paraphrase matrix (`eval/structured_requests`),
each time the v12 routing model wrote as a timestamp is compared with code's conversion of the question's words:
- **the target half-hour's end:** `half_hour_from_text` on the model's quoted half-hour words;
- **a run's issue time:** `issue_time_from_text` on the model's quoted selection words;
- **an explicit maximum window:** `window_from_text` on the model's quoted window words;
- **the as-of cutoff:** the question parser (`extract_as_of`, else `question_as_of`). v12 quoted no cutoff words.

Each is checked against the gold wherever an independently checked gold exists for the question:
- `eval/livecheck_i15_17/cases.json`;
- `eval/livecheck_routing_v12/cases.json` and `DEV_GOLD.json`;
- `eval/structured_requests/matrix.json`.

Historical model timestamps are not ground truth. Each difference is reported with its cause, and none has to be
reproduced.

Usage: python eval/route_v13/time_conversion.py OUT.json
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from resolve_saved_routes import _routes  # noqa: E402

from nem_agent.agent.request import extract_as_of, extract_dates, extract_regions  # noqa: E402
from nem_agent.agent.structured import (  # noqa: E402
    half_hour_from_text,
    issue_time_from_text,
    question_as_of,
    quoted_in,
    window_from_text,
)
from nem_agent.timeutil import iso_utc, parse_iso  # noqa: E402


def _gold() -> dict[str, dict[str, Any]]:
    """Question -> the independently checked times: half-hour end, issue time, explicit window, cutoff."""
    out: dict[str, dict[str, Any]] = {}

    def put(q: str, **kw: Any) -> None:
        out.setdefault(q, {}).update({k: v for k, v in kw.items() if v})
    for c in json.loads((REPO / "eval/livecheck_i15_17/cases.json").read_text())["cases"]:
        e = c["expected"]
        run = e.get("gold_run") or {}
        put(c["question"], half_hour_end=run.get("target_end_utc"), as_of=e.get("as_of_utc"))
    by_sha: dict[str, str] = {}
    for c in json.loads((REPO / "eval/livecheck_routing_v12/cases.json").read_text())["cases"]:
        e = c["expected"]
        fr, mx = e.get("forecast_run") or {}, e.get("maximum") or {}
        put(c["question"], half_hour_end=fr.get("target_half_hour_end_utc"), issued_at=fr.get("issued_at_utc"),
            window=mx.get("window_utc") if mx.get("window_kind") == "explicit" else None, as_of=e.get("as_of_utc"))
    for rel in ("eval/cases.json", "eval/holdout_v6/cases.json", "eval/livecheck_i15_17/cases.json"):
        for c in json.loads((REPO / rel).read_text())["cases"]:
            by_sha[hashlib.sha256(c["question"].encode()).hexdigest()] = c["question"]
    for c in json.loads((REPO / "eval/livecheck_routing_v12/DEV_GOLD.json").read_text())["cases"]:
        q = by_sha.get(c["question_sha256"])
        if q:
            e = c["expected"]
            fr, mx = e.get("forecast_run") or {}, e.get("maximum") or {}
            put(q, half_hour_end=fr.get("target_half_hour_end_utc"), issued_at=fr.get("issued_at_utc"),
                window=mx.get("window_utc") if mx.get("window_kind") == "explicit" else None, as_of=e.get("as_of_utc"))
    for c in json.loads((REPO / "eval/structured_requests/matrix.json").read_text())["cases"]:
        e = c["expected"]
        fr, mx = e.get("forecast_run") or {}, e.get("maximum") or {}
        put(c["question"], half_hour_end=fr.get("target_half_hour_end_utc"), issued_at=fr.get("issued_at_utc"),
            window=mx.get("window_utc") if mx.get("window_kind") == "explicit" else None, as_of=e.get("as_of_utc"))
    return out


def _t(s: Any) -> str | None:
    return iso_utc(parse_iso(s)) if isinstance(s, str) and s else None


def _verdict(model: str | None, code: str | None, gold: str | None, why_none: str) -> str:
    if model is None and code is None:
        return "neither"
    if code is None:
        return f"code: none ({why_none})" + ("" if gold is None else "; model " + ("= gold" if model == gold else "!= gold"))
    if gold is not None:
        return ("code = gold" if code == gold else "code != gold") + ("" if model is None else
                                                                    "; model = gold" if model == gold else "; model != gold")
    return "code = model" if model == code else ("code only" if model is None else "code != model (no gold)")


def main() -> int:
    gold = _gold()
    rows: list[dict[str, Any]] = []
    decisions = [(r["key"], r["question"], r["request"], r["decision"]) for r in _routes()]
    matrix = {c["id"]: c for c in json.loads((REPO / "eval/structured_requests/matrix.json").read_text())["cases"]}
    for f in json.loads((REPO / "eval/structured_requests/fields.json").read_text())["cases"]:
        decisions.append((f"matrix/{f['id']}", matrix[f["id"]]["question"], matrix[f["id"]].get("request") or {},
                          f["route"]))
    for key, q, req, dec in decisions:
        rq = dec.get("requested") or {}
        fr, mx = rq.get("forecast_run") or {}, rq.get("maximum") or {}
        regions = extract_regions(q)
        region = req.get("region") or dec.get("region") or (regions[0] if len(regions) == 1 else None)
        g = gold.get(q, {})
        if fr.get("half_hour_text") and quoted_in(fr["half_hour_text"], q):
            hh, missing, _ = half_hour_from_text(fr["half_hour_text"], q, region)
            code = iso_utc(hh[1]) if hh else None
            rows.append({"key": key, "field": "half_hour_end", "model": _t(fr.get("target_half_hour_end_utc")),
                         "code": code, "gold": _t(g.get("half_hour_end")),
                         "verdict": _verdict(_t(fr.get("target_half_hour_end_utc")), code,
                                             _t(g.get("half_hour_end")), "+".join(missing))})
        if fr.get("selection") == "issued_at" and fr.get("selection_text") and quoted_in(fr["selection_text"], q):
            t, _ = issue_time_from_text(fr["selection_text"], q, region)
            code = iso_utc(t) if t else None
            rows.append({"key": key, "field": "issued_at", "model": _t(fr.get("issued_at_utc")), "code": code,
                         "gold": _t(g.get("issued_at")),
                         "verdict": _verdict(_t(fr.get("issued_at_utc")), code, _t(g.get("issued_at")),
                                             "no issue time read from the words")})
        if mx.get("window") == "explicit" and mx.get("window_text") and quoted_in(mx["window_text"], q):
            w, _ = window_from_text(mx["window_text"], q, region)
            code = f"{iso_utc(w[0])}/{iso_utc(w[1])}" if w else None
            model = (f"{_t(mx.get('window_start_utc'))}/{_t(mx.get('window_end_utc'))}"
                     if mx.get("window_start_utc") and mx.get("window_end_utc") else None)
            gw = g.get("window")
            gs = f"{_t(gw[0])}/{_t(gw[1])}" if gw else None
            rows.append({"key": key, "field": "explicit_window", "model": model, "code": code, "gold": gs,
                         "verdict": _verdict(model, code, gs, "no start and end read from the words")})
        if dec.get("as_of_utc") or req.get("as_of_utc") or g.get("as_of"):
            dates = extract_dates(q)
            parsed = extract_as_of(q, region, dates[0] if len(dates) == 1 else None) or question_as_of(q, region)[0]
            code = _t(req.get("as_of_utc")) or (iso_utc(parsed) if parsed else None)
            rows.append({"key": key, "field": "as_of", "model": _t(dec.get("as_of_utc")), "code": code,
                         "gold": _t(g.get("as_of")), "request_field": bool(req.get("as_of_utc")),
                         "verdict": _verdict(_t(dec.get("as_of_utc")), code, _t(g.get("as_of")),
                                             "the parser reads no cutoff in the words; v12 quoted none")})
    summary = {f: dict(Counter(r["verdict"] for r in rows if r["field"] == f))
               for f in ("half_hour_end", "issued_at", "explicit_window", "as_of")}
    Path(sys.argv[1]).write_text(json.dumps({"summary": summary, "rows": rows}, indent=1) + "\n")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
