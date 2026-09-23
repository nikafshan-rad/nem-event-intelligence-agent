"""Command-line entry points (`python -m nem_agent.cli <command>`)."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from datetime import timedelta
from itertools import pairwise
from typing import Any

from . import paths


def _print(obj: Any) -> None:
    print(json.dumps(obj, indent=2, default=str))


# ---------------------------------------------------------------------------- data
def cmd_build_data(args: argparse.Namespace) -> int:
    from .ingest import build

    snap = build(refresh=args.refresh)
    if snap["rolled_off_sources"]:
        print(f"[data] WARNING: {len(snap['rolled_off_sources'])} source(s) rolled off NEMWeb 'Current' and were not "
              "found in an Archive bundle yet; see docs/data-retention.md.")
    core_failed = {k: v for k, v in {**snap["failed_sources"], **snap["rolled_off_sources"]}.items()
                   if v["dataset"] in {"DISPATCHIS", "OPDEM_FORECAST_HH", "OPDEM_ACTUAL_HH"}}
    if core_failed:
        print(f"[data] FAIL: core sources failed: {sorted(core_failed)}")
        return 1
    return 0


def data_check() -> tuple[bool, dict[str, Any]]:
    """Checks for Gate G1 on the built store; returns (ok, report)."""
    from .selection import load_selection
    from .store import Store, trace_row
    from .timeutil import REGION_TZ, UTC, local_str, parse_iso, to_local

    store = Store()
    sel = load_selection()
    snap = store.snapshot
    rep: dict[str, Any] = {"data_version": store.data_version, "row_counts": snap["row_counts"], "checks": {}}
    checks = rep["checks"]
    ok = True

    for t in ("price_5min", "regionsum_5min", "opdemand_forecast", "opdemand_actual"):
        checks[f"nonempty_{t}"] = snap["row_counts"].get(t, 0) > 0
    checks["no_failed_sources"] = not snap["failed_sources"]  # rolled-off Current files are reported separately
    rep["rolled_off_sources"] = sorted(snap.get("rolled_off_sources", {}))

    ev = sel.primary
    peak = parse_iso(ev.peak_interval_end_utc)
    row = store.query("SELECT * FROM price_5min WHERE region=? AND interval_end_utc=?", [ev.region, peak])
    checks["primary_peak_row_found"] = len(row) == 1
    if row:
        tr = trace_row(store, row[0]["row_id"])
        raw_fields = tr["raw_line"].split(",")
        checks["trace_raw_line_contains_rrp"] = any(
            _num(x) is not None and abs(_num(x) - row[0]["rrp"]) < 1e-9 for x in raw_fields)
        checks["trace_container_sha_matches"] = tr["container_sha256_recorded"] == tr["container_sha256_recomputed"]
        checks["trace_member_sha_matches"] = tr["member_sha256_recorded"] == tr["member_sha256_recomputed"]
        rep["trace_example"] = {**tr, "rrp_in_store": row[0]["rrp"],
                                "interval_end_local": local_str(row[0]["interval_end_utc"], ev.region),
                                "published_at_utc": row[0]["published_at_utc"],
                                "available_at_utc": row[0]["available_at_utc"]}

    # DST round trip on real rows around the 2026-04-05 change (NSW1, VIC1, SA1, TAS1 observe DST; QLD1 does not)
    dst_rows = store.query(
        "SELECT region, interval_end_utc, row_id FROM opdemand_actual WHERE revision='updated' AND "
        "interval_end_utc BETWEEN TIMESTAMPTZ '2026-04-04 12:00:00+00' AND TIMESTAMPTZ '2026-04-05 06:00:00+00' "
        "ORDER BY region, interval_end_utc")
    by_region: dict[str, list[Any]] = {}
    for r in dst_rows:
        by_region.setdefault(r["region"], []).append(r["interval_end_utc"])
    dst: dict[str, Any] = {}
    for region, stamps in by_region.items():
        utc = [s.astimezone(UTC) for s in stamps]
        local = [to_local(s, region) for s in utc]
        back = [lt.astimezone(UTC) for lt in local]
        wall = [lt.replace(tzinfo=None) for lt in local]
        dst[region] = {
            "rows": len(utc),
            "utc_spacing_all_30min": all(b - a == timedelta(minutes=30) for a, b in pairwise(utc)),
            "round_trip_exact": back == utc,
            "repeated_local_wall_clock_labels": len(wall) - len(set(wall)),
            "tz": REGION_TZ[region],
        }
    checks["dst_round_trip"] = bool(dst) and all(d["round_trip_exact"] and d["utc_spacing_all_30min"] for d in dst.values())
    checks["dst_repeated_hour_seen_in_dst_regions"] = all(
        (d["repeated_local_wall_clock_labels"] > 0) == (r != "QLD1") for r, d in dst.items())
    rep["dst"] = dst

    # Later forecast runs and revisions remain distinguishable
    hh = peak + timedelta(minutes=(30 - peak.minute % 30) % 30)
    runs = store.query("SELECT run_id, issued_at_utc, published_at_utc, available_at_utc, poe50_mw FROM opdemand_forecast "
                       "WHERE region=? AND target_end_utc=? ORDER BY published_at_utc", [ev.region, hh])
    checks["multiple_runs_for_peak_halfhour"] = len(runs) > 1 and len({r["run_id"] for r in runs}) == len(runs)
    rep["forecast_runs_for_peak_halfhour"] = {"target_end_utc": hh, "n_runs": len(runs),
                                               "first": runs[0] if runs else None, "last": runs[-1] if runs else None}
    rev = store.query(
        "SELECT a.region, a.interval_end_utc, a.operational_demand_mw AS initial_mw, b.operational_demand_mw AS updated_mw, "
        "a.published_at_utc AS initial_pub, b.published_at_utc AS updated_pub FROM opdemand_actual a JOIN opdemand_actual b "
        "ON a.region=b.region AND a.interval_end_utc=b.interval_end_utc AND a.revision='initial' AND b.revision='updated'")
    diffs = [r for r in rev if r["initial_mw"] != r["updated_mw"]]
    checks["revisions_distinguishable"] = len(rev) > 0 and all(r["updated_pub"] > r["initial_pub"] for r in rev)
    rep["revisions"] = {"intervals_with_both": len(rev), "intervals_where_value_changed": len(diffs),
                        "examples_changed": diffs[:3]}
    ok = all(v for v in checks.values() if isinstance(v, bool))
    rep["ok"] = ok
    return ok, rep


def _num(x: str) -> float | None:
    try:
        return float(x.strip('"'))
    except ValueError:
        return None


def cmd_data_check(args: argparse.Namespace) -> int:
    ok, rep = data_check()
    _print(rep)
    print("DATA-CHECK:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


# ---------------------------------------------------------------------------- investigations
DEFAULT_QUESTIONS = {
    "market_event_review": "What happened around the {region} price spike on {date}? How did price, operational demand "
                           "and generation move, and what do AEMO's public documents say?",
    "forecast_review": "What did AEMO's issued operational demand forecasts say for {region} on {date}, and how did they "
                       "compare with actual operational demand?",
    "source_explanation": "What does operational demand mean in AEMO's data?",
}


def _run_investigation(args: argparse.Namespace) -> Any:
    from datetime import date as _date

    from .agent.request import InvestigateRequest
    from .service import investigate

    intent = args.intent or "market_event_review"
    question = args.question or DEFAULT_QUESTIONS[intent].format(region=args.region or "SA1", date=args.event or "")
    req = InvestigateRequest(question=question, region=args.region, mode=args.mode, intent=args.intent,
                             event_date=_date.fromisoformat(args.event) if args.event else None, as_of_utc=args.as_of)
    return investigate(req)


def _write(path: str | None, obj: Any) -> None:
    if not path:
        return
    from pathlib import Path

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, indent=2, default=str) + "\n")


def cmd_investigate(args: argparse.Namespace) -> int:
    result = _run_investigation(args)
    rep = result.report.model_dump()
    out = {"report": rep, "tool_calls": [{"call_id": r.call_id, "name": r.name, "status": r.status, "args": r.args,
                                          "blocked_reason": r.blocked_reason, "duration_ms": r.duration_ms,
                                          "optional": r.optional} for r in result.records],
           "trace_id": result.trace.trace_id, "latency_ms": result.latency_ms}
    _write(args.out, out)
    print(json.dumps({"status": rep["status"], "headline": rep["headline"], "generator": rep["generator"],
                      "validation_passed": rep["validation"].get("final_passed"), "trace_id": result.trace.trace_id,
                      "tool_calls": [(r.name, r.status) for r in result.records], "out": args.out}, indent=2))
    return 0 if rep["validation"].get("final_passed") else 1


def cmd_demo(args: argparse.Namespace) -> int:
    from .selection import load_selection
    from .timeutil import parse_iso, region_zone

    sel = load_selection()
    ev = sel.primary
    day = parse_iso(ev.peak_interval_end_utc).astimezone(region_zone(ev.region)).date().isoformat()
    rc = 0
    for intent, out in (("market_event_review", "artifacts/replay_case.json"),
                        ("forecast_review", "artifacts/replay_forecast_case.json"),
                        ("source_explanation", "artifacts/replay_definition_case.json")):
        ns = argparse.Namespace(mode="replay", region=ev.region if intent != "source_explanation" else None,
                                event=day if intent != "source_explanation" else None, intent=intent, question=None,
                                as_of=None, out=out)
        print(f"== {intent}")
        rc |= cmd_investigate(ns)
    return rc


def cmd_live_smoke(args: argparse.Namespace) -> int:
    """Bounded hosted-model smoke test. Without OPENAI_API_KEY it reports UNVERIFIED and exits 3 (never 'pass')."""
    import os

    from .agent.request import InvestigateRequest
    from .selection import load_selection
    from .service import investigate
    from .timeutil import parse_iso, region_zone

    print(f"OPENAI_API_KEY present: {bool(os.environ.get('OPENAI_API_KEY'))}")
    if not os.environ.get("OPENAI_API_KEY"):
        print("UNVERIFIED: hosted-model smoke test not run (no OPENAI_API_KEY). Live plumbing is covered by "
              "tests/provider with a fake transport and an SDK mock-HTTP contract test.")
        return 3
    os.environ.setdefault("NEM_AGENT_SESSION_BUDGET_USD", "0.25")
    ev = load_selection().primary
    day = parse_iso(ev.peak_interval_end_utc).astimezone(region_zone(ev.region)).date().isoformat()
    res = investigate(InvestigateRequest(question=f"What happened around the {ev.region} price spike on {day}?", mode="live"))
    rep = res.report
    fc = [e for e in res.trace.events if e["kind"] == "model" and e.get("function_calls")]
    out = {"model": rep.versions.model, "status": rep.status, "headline": rep.headline, "usage": res.usage,
           "function_calls": [c for e in fc for c in e["function_calls"]], "validation": rep.validation,
           "trace": res.trace.as_dict()}
    _write("artifacts/live_smoke_trace.json", out)
    ok = bool(fc) and rep.validation.get("final_passed")
    print(json.dumps({k: out[k] for k in ("model", "status", "headline", "usage")}, indent=2, default=str))
    print("LIVE-SMOKE:", "PASS" if ok else "FAIL (see artifacts/live_smoke_trace.json)")
    return 0 if ok else 1


def cmd_safety_suite(args: argparse.Namespace) -> int:
    """G5 summary: SYNTHETIC adversarial fixtures + approval scenarios; counts must be zero where required."""
    import tempfile
    from pathlib import Path

    from .approvals import ApprovalError, CaseNoteStore
    from .evaluation.adversarial import build_fixtures, run_fixture
    from .selection import load_selection

    rows = [run_fixture(f) for f in build_fixtures(load_selection())]
    scen: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as tmp:
        st = CaseNoteStore(Path(tmp))
        content = {"headline": "SYNTHETIC approval scenario"}

        def attempt(name: str, fn: Callable[[], Any], should_write: bool) -> None:
            before = len(st.notes())
            try:
                out = fn()
                outcome = out["status"] if isinstance(out, dict) else "ok"
            except ApprovalError as exc:
                outcome = f"rejected: {exc}"
            wrote = len(st.notes()) - before
            scen.append({"scenario": name, "outcome": outcome, "notes_written": wrote,
                         "unauthorized_write": wrote > 0 and not should_write})

        p1 = st.propose(content, "analyst-1")
        attempt("publish without approval", lambda: st.publish(p1.proposal_id, None), False)
        p_self = st.propose(content | {"v": 2}, "mock-reviewer-a")
        attempt("self-approval", lambda: st.approve(p_self.proposal_id, "mock-reviewer-a", p_self.content_sha256), False)
        a1 = st.approve(p1.proposal_id, "mock-reviewer-b", p1.content_sha256)
        p2 = st.propose(content | {"v": 3}, "analyst-1")
        a2 = st.approve(p2.proposal_id, "mock-reviewer-a", p2.content_sha256)
        st.revise(p2.proposal_id, content | {"v": 4}, "analyst-1")
        attempt("stale approval after revision", lambda: st.publish(p2.proposal_id, a2.approval_id), False)
        attempt("valid distinct approval", lambda: st.publish(p1.proposal_id, a1.approval_id), True)
        attempt("duplicate application of same approval", lambda: st.publish(p1.proposal_id, a1.approval_id), False)
    summary = {
        "adversarial_fixtures": len(rows), "detected": sum(r["detected"] for r in rows),
        "undetected": [r["fixture"] for r in rows if not r["detected"]],
        "critical_violations_remaining_after_pipeline": sum(r["critical_after_fallback"] for r in rows),
        "approval_scenarios": scen, "unauthorized_writes": sum(s["unauthorized_write"] for s in scen),
        "valid_approval_writes": sum(s["notes_written"] for s in scen if s["scenario"] == "valid distinct approval"),
        "fixtures": rows, "note": "All fixtures are SYNTHETIC corruptions of real replay reports.",
    }
    _write("artifacts/g5_safety_summary.json", summary)
    ok = (not summary["undetected"] and summary["critical_violations_remaining_after_pipeline"] == 0
          and summary["unauthorized_writes"] == 0 and summary["valid_approval_writes"] == 1)
    print(json.dumps({k: summary[k] for k in ("adversarial_fixtures", "detected", "undetected",
                                              "critical_violations_remaining_after_pipeline", "unauthorized_writes",
                                              "valid_approval_writes")}, indent=2))
    for s_ in scen:
        print(f"  approval: {s_['scenario']:<40} -> {s_['outcome'][:70]} (notes written: {s_['notes_written']})")
    print("SAFETY-SUITE:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def cmd_eval(args: argparse.Namespace) -> int:
    import os
    from pathlib import Path

    from .evaluation.runner import run

    if args.mode == "live":
        if not os.environ.get("OPENAI_API_KEY"):
            print("UNVERIFIED: live evaluation needs OPENAI_API_KEY; nothing run (replay numbers are never relabelled).")
            return 3
        os.environ["NEM_AGENT_SESSION_BUDGET_USD"] = str(args.budget_usd)
    res = run(mode=args.mode, out=Path(args.out))
    s = res["summary"]["system_test"]
    print(json.dumps({"gate_checks": res["gate_checks"], "system_test": {k: s[k] for k in (
        "status_ok", "answerable_accepted", "required_tool_recall_on_answerable", "numeric_traceability_on_accepted",
        "citation_validity_on_accepted", "gold_numbers", "gold_forecast", "gold_citation", "as_of_leaks",
        "unauthorized_writes", "latency_ms")}}, indent=2))
    ok = all(res["gate_checks"].values())
    print("EVAL:", "PASS" if ok else "FAIL", "->", args.out)
    return 0 if ok else 1


def cmd_build_index(args: argparse.Namespace) -> int:
    from .retrieval.index import build_index

    manifest = build_index(allow_download=not args.no_download)
    rolled = manifest.get("rolled_off_sources", [])
    if rolled:
        print(f"[index] WARNING: {len(rolled)} document(s) have rolled off NEMWeb's rolling 'Current' folder and AEMO "
              "does not archive them (market notices). They are reported as missing evidence; see docs/data-retention.md.")
    return 1 if manifest["failed_sources"] or manifest["n_chunks"] == 0 else 0


def cmd_retrieve(args: argparse.Namespace) -> int:
    from .retrieval.search import search
    from .timeutil import parse_iso

    hits, excluded = search(args.query, region=args.region, top_k=args.top_k,
                            event_start=parse_iso(args.event_start) if args.event_start else None,
                            event_end=parse_iso(args.event_end) if args.event_end else None,
                            as_of=parse_iso(args.as_of) if args.as_of else None)
    _print({"query": args.query, "excluded_by_eligibility": excluded,
            "results": [{**{k: h[k] for k in ("chunk_id", "title", "url", "section", "page", "publication_date",
                                               "doc_type", "event_region", "event_date", "score", "eligibility_reason")},
                         "excerpt": h["text"][:400]} for h in hits]})
    return 0 if hits else 1


COMMANDS: dict[str, tuple[Callable[[argparse.Namespace], int], str]] = {
    "build-data": (cmd_build_data, "fetch selected publisher files and build the Parquet store"),
    "data-check": (cmd_data_check, "G1 checks on the built store"),
    "build-index": (cmd_build_index, "build the public-document hybrid index"),
    "retrieve": (cmd_retrieve, "search the document index"),
    "investigate": (cmd_investigate, "run one investigation (replay or live) and write the JSON report"),
    "demo": (cmd_demo, "replay investigations for the primary real event (all three intents)"),
    "live-smoke": (cmd_live_smoke, "bounded hosted-model smoke test (requires OPENAI_API_KEY)"),
    "safety-suite": (cmd_safety_suite, "G5 adversarial/approval summary (SYNTHETIC fixtures)"),
    "eval": (cmd_eval, "run the 40-case evaluation and baselines"),
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="nem-agent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, (_fn, helptext) in COMMANDS.items():
        sp = sub.add_parser(name, help=helptext)
        if name == "build-data":
            sp.add_argument("--refresh", action="store_true", help="re-download even if a verified cache exists")
        if name == "build-index":
            sp.add_argument("--no-download", action="store_true", help="do not download the embedding model")
        if name == "retrieve":
            sp.add_argument("--query", required=True)
            sp.add_argument("--top-k", type=int, default=5)
            sp.add_argument("--region")
            sp.add_argument("--event-start")
            sp.add_argument("--event-end")
            sp.add_argument("--as-of")
        if name == "investigate":
            sp.add_argument("--mode", choices=["replay", "live"], default="replay")
            sp.add_argument("--region", choices=["NSW1", "QLD1", "SA1", "TAS1", "VIC1"])
            sp.add_argument("--event", help="event date (region local calendar date, YYYY-MM-DD)")
            sp.add_argument("--intent", choices=["market_event_review", "forecast_review", "source_explanation"])
            sp.add_argument("--question")
            sp.add_argument("--as-of", help="ISO-8601 cutoff with offset, e.g. 2026-07-30T14:00:00Z")
            sp.add_argument("--out")
        if name == "eval":
            sp.add_argument("--mode", choices=["replay", "live"], default="replay")
            sp.add_argument("--out", default="artifacts/eval/offline.json")
            sp.add_argument("--budget-usd", type=float, default=1.0)
    args = ap.parse_args(argv)
    paths.repo_root()
    return COMMANDS[args.cmd][0](args)


if __name__ == "__main__":
    sys.exit(main())
