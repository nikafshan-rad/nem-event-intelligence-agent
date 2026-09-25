#!/usr/bin/env python
"""Non-interactive API smoke test: start uvicorn, GET /health, POST the verified real-event question, validate the
InvestigationReport, check bounded errors, stop the server. Exit 0 only if every check passes."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nem_agent.report import InvestigationReport  # noqa: E402
from nem_agent.selection import load_selection  # noqa: E402
from nem_agent.timeutil import parse_iso, region_zone  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--transcript", default="artifacts/api_smoke_transcript.json")
    args = ap.parse_args()
    base = f"http://127.0.0.1:{args.port}"
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "nem_agent.api:app", "--host", "127.0.0.1",
                             "--port", str(args.port)], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    transcript: dict = {"base": base, "steps": []}
    ok = True
    try:
        for _ in range(60):
            try:
                if httpx.get(f"{base}/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.5)
        h = httpx.get(f"{base}/health", timeout=10).json()
        print("GET /health ->", h)
        transcript["steps"].append({"GET /health": h})
        ok &= h["status"] == "ok" and h["replay_available"]
        ev = load_selection().primary
        day = parse_iso(ev.peak_interval_end_utc).astimezone(region_zone(ev.region)).date().isoformat()
        body = {"question": f"What happened around the {ev.region} price spike on {day}?", "mode": "replay"}
        r = httpx.post(f"{base}/investigate", json=body, timeout=120)
        data = r.json()
        rep = InvestigationReport.model_validate(data["report"])
        print(f"POST /investigate -> {r.status_code} status={rep.status} validation_passed="
              f"{rep.validation.get('final_passed')} tool_calls={[t['name'] for t in data['tool_calls']]}")
        print("   headline:", rep.headline)
        transcript["steps"].append({"POST /investigate": body, "http": r.status_code, "status": rep.status,
                                    "headline": rep.headline, "trace_id": rep.trace_id,
                                    "first_observation": rep.observations[0].model_dump() if rep.observations else None})
        ok &= r.status_code == 200 and rep.status in ("answered", "answered_with_caveats") and bool(rep.validation.get("final_passed"))
        row = rep.observations[0].source_row_ids[0]
        e = httpx.get(f"{base}/evidence/{row}", timeout=30).json()
        print(f"GET /evidence/{row} -> {e['source_url']} line {e['line_no']}: {e['raw_line'][:90]}...")
        transcript["steps"].append({"GET /evidence": row, "source_url": e["source_url"], "raw_line": e["raw_line"][:200]})
        ok &= e["container_sha256_recorded"] == e["container_sha256_recomputed"]
        bad = httpx.post(f"{base}/investigate", json={"question": "x", "region": "WA1"}, timeout=30)
        print(f"POST /investigate (bad input) -> {bad.status_code} {bad.json()}")
        transcript["steps"].append({"bad_input": bad.status_code, "body": bad.json()})
        ok &= bad.status_code == 422 and bad.json()["error"] == "invalid_request"
        live = httpx.post(f"{base}/investigate", json={"question": body["question"], "mode": "live"}, timeout=30)
        print(f"POST /investigate (live, no key) -> {live.status_code} {live.json()}")
        ok &= live.status_code in (400, 200)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    Path(args.transcript).parent.mkdir(parents=True, exist_ok=True)
    Path(args.transcript).write_text(json.dumps(transcript, indent=2, default=str))
    print("API-SMOKE:", "PASS" if ok else "FAIL", "(server stopped)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
