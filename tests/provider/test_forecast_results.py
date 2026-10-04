"""D27 (docs/decisions.md): typed forecast-comparison results, offline. The comparison the request asks for is the
computed answer; no other comparison is typed, rendered or stated.

- **Saved records:** R02 (the end-to-end Live check's FAIL), its saved route, tool calls and drafts replayed through the
  SYNTHETIC fake transport; K14 and FC01-FC10 in Replay; saved maxima for compatibility.
- **SYNTHETIC store:** forecast runs and actuals written as parquet and read by the real Store, so the real comparison
  tool, run lookup, verifier, renderer and validator run on controlled data. These controls test design properties,
  not generalisation.

No test accepts a known false statement because it cites the primary: the scope rule is a provenance restriction, and
every other check still applies."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import duckdb
import pytest

from nem_agent.agent import forecast_compare as fc
from nem_agent.agent.dispatcher import Dispatcher
from nem_agent.agent.request import ForecastRequest, InvestigateRequest, Resolution
from nem_agent.evidence import EvidenceRegistry
from nem_agent.render import render_result
from nem_agent.report import InvestigationReport, NumericClaim
from nem_agent.results import ForecastResult, ReportedResult, ResultRegistry, verify_loaded
from nem_agent.service import investigate
from nem_agent.store import Store
from nem_agent.timeutil import iso_utc
from nem_agent.trace import Trace
from nem_agent.validation import validate
from tests.provider.fake_model import FakeModel, outputs

ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "artifacts" / "live"
E2E = LIVE / "LC-e2e-v13-run"
DRAFT = {"status": "answered", "headline": "SYNTHETIC answer.", "summary": ["SYNTHETIC."], "document_statements": [],
         "observation_evidence_ids": [], "possible_explanations": [], "published_findings": [], "citations": [],
         "uncertainties": [], "missing_evidence": [], "forecast_mae_evidence_id": None, "numeric_claims": []}


def T(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ------------------------------------------------------------------------------------------------ saved replays
def _saved_fake(cid: str) -> tuple[dict, FakeModel]:
    """The end-to-end Live check's saved record of ``cid``: its route, model tool calls and drafts (SYNTHETIC replay)."""
    rec = json.loads((E2E / f"{cid}.json").read_text())
    trace = json.loads((E2E / "traces" / f"{rec['trace_id']}.json").read_text())["events"]
    draft = rec["drafts"]["synthesis:draft"]
    patch = next((e.get("patch") for e in trace if e["name"] == "repair:scoped"), None)
    repaired = rec["drafts"].get("repair:draft")

    def repair(kw: dict) -> dict:
        return copy.deepcopy(patch if kw["text"]["format"]["name"] == "RepairPatch" else repaired)
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if t["origin"] == "model" and t["status"] != "blocked"]
    return rec, FakeModel(rec["route"], [calls], lambda kw: copy.deepcopy(draft), repair if (patch or repaired) else None)


def _live(question: str, fake: FakeModel, **request: Any) -> Any:
    return investigate(InvestigateRequest(question=question, mode="live", **request), live_client=fake,
                       write_trace=False)


def _shown(report: InvestigationReport) -> str:
    return json.dumps([report.headline, *report.summary, *[a.statement for a in report.answer],
                       *[h.statement for h in report.possible_explanations], *report.uncertainties,
                       *report.missing_evidence, *[f"{o.metric} {o.value}" for o in report.observations]])


@pytest.fixture(scope="module")
def r02(real_store):
    rec, fake = _saved_fake("R02")
    return rec, _live(rec["question"], fake, **rec["request"])


def test_r02_the_requested_point_is_the_computed_answer(r02):
    """A1: the point primary, admitted and rendered: the run, its values, the error convention and its rows."""
    _, res = r02
    (a,) = res.report.answer
    assert (a.kind, a.status, a.verification) == ("forecast_point", "established", "verified")
    (rep,) = res.report.results
    r = rep.result
    assert isinstance(r, ForecastResult) and r.identity.run_selection == "last_issued_before"
    assert r.identity.target_utc == ("2026-08-19T22:00:00Z", "2026-08-19T22:30:00Z")
    (p,) = r.pairs
    assert (p.run_id, p.run_issued_at_utc) == ("PUBLIC_FORECAST_OPERATIONAL_DEMAND_HH_202608200830_20260820080131",
                                               "2026-08-19T21:57:01Z")
    assert (p.poe50_mw, p.poe10_mw, p.poe90_mw, p.actual_mw, p.actual_revision) == (1594.0, 1663.0, 1525.0, 1567.0,
                                                                                     "updated")
    assert (p.error_mw, p.abs_error_mw, p.error_pct) == (27.0, 27.0, 1.72)
    assert r.source_row_ids == (p.forecast_row_id, p.actual_row_id) and r.targets_expected == 1 and not r.excluded
    assert p.forecast_row_id == "OPDEM_FORECAST_HH:PUBLIC_FORECAST_OPERATIONAL_DEMAND_HH_202608200830_20260820080131:L835"
    assert "1594 MW" in a.statement and "1567 MW" in a.statement and "+27 MW" in a.statement
    assert "positive means the forecast was above the actual" in a.statement and "one forecast/actual pair" in a.statement
    assert res.report.forecast_comparison is None


def test_r02_the_unrequested_aggregate_and_the_misleading_sentence_are_not_shown(r02):
    """B1: the saved sentence giving 149.81 MW is rejected by scope provenance and the answer falls back; the original
    draft, the violations and the fallback classification are kept in the diagnostics."""
    _, res = r02
    rep, v = res.report, res.report.validation
    assert "149.81" not in _shown(rep) and "run/actual pair" not in _shown(rep)
    assert all(o.evidence_id != "ev0676" for o in rep.observations)
    assert v["fallback_applied"] and v["interpretation"].startswith("withheld")
    assert "FORECAST_SCOPE_NOT_PRIMARY" in v["pre_repair_codes"]
    initial = [x for x in v["initial"]["violations"] if x["code"] == "FORECAST_SCOPE_NOT_PRIMARY"]
    assert initial and all("ev0676" in x["detail"] for x in initial)
    assert v["fallback_result"]["retained"][0]["result_id"] == rep.answer[0].result_id
    events = res.trace.as_dict()["events"]
    drafts = [e for e in events if e["name"] in ("synthesis:draft", "repair:draft")]
    assert any("149.81" in json.dumps(e["report"]) for e in drafts)  # the original draft is kept, unshown
    assert res.resolution.forecast_primary["admitted"] and res.resolution.forecast_primary["kind"] == "forecast_point"


REPLAY_POINTS = {"H05": "holdout_v2", "V07": "holdout_v3", "V08": "holdout_v3", "W07": "holdout_v4", "W08": "holdout_v4",
                 "Y05": "holdout_v5", "Y06": "holdout_v5", "Z05": "holdout_v6"}


def _case(cid: str, directory: str) -> dict:
    return next(c for c in json.loads((ROOT / "eval" / directory / "cases.json").read_text())["cases"]
                if c["case_id"] == cid)


@pytest.mark.parametrize("cid", sorted(REPLAY_POINTS))
def test_replay_point_requests_are_the_named_runs_point(cid, real_store):
    """A2, as amended (D27): every saved question Replay resolves as one run and half-hour gets the point result of that
    run and half-hour, equal to its frozen gold; no window comparison is made or stated."""
    case = _case(cid, REPLAY_POINTS[cid])
    res = investigate(InvestigateRequest(question=case["question"], as_of_utc=case.get("as_of_utc")), write_trace=False)
    wanted = res.resolution.requests.forecast_run.forecast_request()
    (a,) = res.report.answer
    r = res.report.results[0].result
    assert (a.kind, a.status, a.verification) == ("forecast_point", "established", "verified")
    assert isinstance(r, ForecastResult) and r.identity.run_selection == wanted.run and len(r.pairs) == 1
    p = r.pairs[0]
    gold = {g["metric"]: g for g in case["expected"]["gold_numbers"]}
    assert (p.poe50_mw, p.actual_mw) == (gold["opdemand_forecast_poe50"]["value"], gold["opdemand_actual"]["value"])
    assert p.forecast_row_id == gold["opdemand_forecast_poe50"]["source_row_id"]
    assert p.target_end_utc == iso_utc(wanted.half_hour[1]) and p.error_mw == p.poe50_mw - p.actual_mw
    cmps = [x for x in res.records if x.name == "compare_forecast_actual"]
    span = (iso_utc(wanted.half_hour[0]), iso_utc(wanted.half_hour[1]))
    assert cmps and all((x.args["target_start_utc"], x.args["target_end_utc"]) == span for x in cmps)
    assert res.resolution.forecast_run["run_id"] == p.run_id  # recorded: the I-9 checks run in Replay too
    assert res.report.forecast_comparison is None and "mean absolute error" not in _shown(res.report)
    assert not res.report.validation["fallback_applied"]


def test_k14_in_replay_binds_no_half_hour_so_its_named_run_is_reviewed_over_the_window(real_store):
    """The amendment to A2 (D27), a stated limitation: Replay's question parser does not read K14's "half-hour ending at
    8:00 am AEST, 31 July 2026" (in Live the routing model's quoted words give it, D26), so its resolved request names
    the run without a half-hour. By the decision's rule that is a window review of the named run: no point is computed,
    and nothing under another run selection is stated (the 24-half-hour MAE under another policy that was Replay's
    headline before)."""
    case = _case("K14", "livecheck_i15_17")
    res = investigate(InvestigateRequest(question=case["question"]), write_trace=False)
    wanted = res.resolution.requests.forecast_run.forecast_request()
    assert wanted.run == "issued_at" and wanted.half_hour is None and res.resolution.forecast_run is None
    (a,) = res.report.answer
    r = res.report.results[0].result
    assert (a.kind, a.status, a.verification) == ("forecast_aggregate", "partial", "verified")
    assert isinstance(r, ForecastResult) and r.identity.run_selection == "run_id"
    gold = case["expected"]["gold_run"]
    assert r.identity.named_issued_at_utc == gold["issued_at_utc"] and {p.run_id for p in r.pairs} == {gold["run_id"]}
    assert res.report.forecast_comparison.mae_mw == r.mae_mw
    other_calls = {x.call_id for x in res.records
                   if x.name == "compare_forecast_actual" and x.args["run_selector"] != "run_id"}
    others = {ev.evidence_id for ev in res.registry.items.values() if ev.tool_call_id in other_calls}
    assert others and not others & {o.evidence_id for o in res.report.observations}
    assert not others & {c.evidence_id for c in res.report.numeric_claims}
    assert not res.report.validation["fallback_applied"]


FC_CASES = {c["case_id"]: c for c in json.loads((ROOT / "eval/cases.json").read_text())["cases"]
            if (c.get("expected") or {}).get("gold_forecast")}


@pytest.mark.parametrize("cid", sorted(FC_CASES))
def test_window_reviews_in_replay_get_their_aggregate_primary(cid, real_store):
    """A3: the aggregate primary equals the frozen forecast gold; forecast_comparison is unchanged; the day-ahead view,
    a comparison the question did not ask for, is not stated."""
    case = FC_CASES[cid]
    g = case["expected"]["gold_forecast"]
    res = investigate(InvestigateRequest(question=case["question"], **case.get("request", {})), write_trace=False)
    (a,) = res.report.answer
    r = res.report.results[0].result
    assert isinstance(r, ForecastResult) and r.identity.kind == "forecast_aggregate" and a.verification == "verified"
    assert r.identity.run_selection == g["selector"] and list(r.identity.window_utc) == g["targets_utc"]
    assert len(r.pairs) == g["n_pairs"]
    if g["n_pairs"]:
        assert (r.mae_mw, r.mean_error_mw) == (g["mae_mw"], g["mean_error_mw"])
        assert r.status == ("established" if g["n_pairs"] == r.targets_expected else "partial")
        fcomp = res.report.forecast_comparison
        assert fcomp is not None and (fcomp.n_pairs, fcomp.mae_mw) == (g["n_pairs"], g["mae_mw"])
    else:
        assert r.status == "unavailable" and a.status == "unavailable"
    assert "day-ahead" not in _shown(res.report)
    assert not res.report.validation["fallback_applied"]


# ------------------------------------------------------------------------------------------------ a SYNTHETIC store
class Syn:
    """SYNTHETIC forecast runs and actuals, written as parquet and read by the real Store."""

    def __init__(self) -> None:
        self.f: list[dict[str, Any]] = []
        self.a: list[dict[str, Any]] = []

    def run(self, region: str, run_id: str, issued: str, values: dict[str, float], *, published: str | None = None,
            available: str | None = None, band: float = 50.0) -> None:
        pub = T(published) if published else T(issued) + timedelta(minutes=4)
        avail = T(available) if available else pub + timedelta(minutes=166)
        for end, v in values.items():
            self.f.append({"row_id": f"SYN_FC:{run_id}:{region}:{end}", "region": region, "run_id": run_id,
                           "target_start_utc": T(end) - timedelta(minutes=30), "target_end_utc": T(end),
                           "issued_at_utc": T(issued), "published_at_utc": pub, "available_at_utc": avail,
                           "poe10_mw": v + band, "poe50_mw": v, "poe90_mw": v - band, "source_url": "synthetic://fc",
                           "unit": "MW", "definition": "SYNTHETIC"})

    def actual(self, region: str, end: str, value: float, revision: str = "updated", *, published: str | None = None,
               available: str | None = None) -> None:
        pub = T(published) if published else T(end) + timedelta(hours=4)
        avail = T(available) if available else pub + timedelta(hours=2)
        self.a.append({"row_id": f"SYN_ACT:{region}:{end}:{revision}", "region": region,
                       "interval_start_utc": T(end) - timedelta(minutes=30), "interval_end_utc": T(end),
                       "operational_demand_mw": value, "revision": revision, "published_at_utc": pub,
                       "available_at_utc": avail, "source_url": "synthetic://act", "member": "SYNTHETIC",
                       "unit": "MW", "definition": "SYNTHETIC"})

    def store(self, path: Path, version: str = "synthetic00001") -> Store:
        path.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect()
        con.execute("SET TimeZone='UTC'")
        for name, rows, cols in (
                ("opdemand_forecast", self.f, "row_id VARCHAR, region VARCHAR, run_id VARCHAR, target_start_utc "
                 "TIMESTAMPTZ, target_end_utc TIMESTAMPTZ, issued_at_utc TIMESTAMPTZ, published_at_utc TIMESTAMPTZ, "
                 "available_at_utc TIMESTAMPTZ, poe10_mw DOUBLE, poe50_mw DOUBLE, poe90_mw DOUBLE, source_url VARCHAR, "
                 "unit VARCHAR, definition VARCHAR"),
                ("opdemand_actual", self.a, "row_id VARCHAR, region VARCHAR, interval_start_utc TIMESTAMPTZ, "
                 "interval_end_utc TIMESTAMPTZ, operational_demand_mw DOUBLE, revision VARCHAR, published_at_utc "
                 "TIMESTAMPTZ, available_at_utc TIMESTAMPTZ, source_url VARCHAR, member VARCHAR, unit VARCHAR, "
                 "definition VARCHAR")):
            con.execute(f"CREATE TABLE t_{name} ({cols})")
            keys = [c.split()[0] for c in cols.split(", ")]
            for r in rows:
                con.execute(f"INSERT INTO t_{name} VALUES ({', '.join('?' for _ in keys)})", [r[k] for k in keys])
            con.execute(f"COPY t_{name} TO '{(path / f'{name}.parquet').as_posix()}' (FORMAT PARQUET)")
        (path / "snapshot.json").write_text(json.dumps({"data_version": version, "row_counts": {
            "opdemand_forecast": len(self.f), "opdemand_actual": len(self.a)}}))
        return Store(path)


def _ends(start: str, n: int) -> list[str]:
    return [iso_utc(T(start) + timedelta(minutes=30 * (i + 1))) for i in range(n)]


def _res(region: str, *, point: ForecastRequest | None = None, window: tuple[str, str] | None = None,
         as_of: str | None = None, named: ForecastRequest | None = None) -> Resolution:
    req = InvestigateRequest(question=f"SYNTHETIC forecast question for {region}", as_of_utc=as_of)
    fr = point or named
    requests = SimpleNamespace(forecast_run=SimpleNamespace(forecast_request=lambda: fr),
                               maximum=SimpleNamespace(status="absent", measures=[]))
    w = (T(window[0]), T(window[1])) if window else None
    return Resolution(request=req, intent="forecast_review", region=region, event=None, window=w,
                      as_of=T(as_of) if as_of else None, requests=requests)


def _dispatcher(store: Store, selection: Any, res: Resolution) -> Dispatcher:
    return Dispatcher(store, selection, Trace(), EvidenceRegistry(), "forecast_review", res.as_of)


def _primary(store: Store, selection: Any, res: Resolution, identity: Any = None) -> tuple[Dispatcher, ForecastResult]:
    d = _dispatcher(store, selection, res)
    if identity is None:
        p = fc.point_request(res)
        identity = fc.point_identity(res, p, store.data_version) if p else fc.window_identity(res, store.data_version)
    r = fc.compute(d, identity)
    fc.submit(d, res, r)
    return d, r


def _check_properties(r: ForecastResult, store: Store, selection: Any, d: Dispatcher, syn: Syn) -> None:
    """The properties every result must have, whatever its data: exact pairs, exclusions, sign, aggregates and
    verification (in the run and on load)."""
    by_row = {x["row_id"]: x for x in syn.f} | {x["row_id"]: x for x in syn.a}
    ends = fc._ends(r.identity)
    assert sorted([p.target_end_utc for p in r.pairs] + [x.target_end_utc for x in r.excluded]) == ends
    for p in r.pairs:
        f, a = by_row[p.forecast_row_id], by_row[p.actual_row_id]
        assert (p.run_id, p.run_issued_at_utc, p.run_available_at_utc, p.run_published_at_utc) == (
            f["run_id"], iso_utc(f["issued_at_utc"]), iso_utc(f["available_at_utc"]), iso_utc(f["published_at_utc"]))
        assert iso_utc(f["target_end_utc"]) == iso_utc(a["interval_end_utc"]) == p.target_end_utc
        assert (p.poe50_mw, p.actual_mw) == (f["poe50_mw"], a["operational_demand_mw"])
        assert p.error_mw == round(f["poe50_mw"] - a["operational_demand_mw"], 2) and p.abs_error_mw == abs(p.error_mw)
        assert (p.error_mw > 0) == (f["poe50_mw"] > a["operational_demand_mw"])  # positive: forecast above actual
    if r.identity.kind == "forecast_aggregate" and r.pairs:
        errs = [p.error_mw for p in r.pairs]
        assert r.mae_mw == round(sum(abs(e) for e in errs) / len(errs), 2)
        assert r.mean_error_mw == round(sum(errs) / len(errs), 2)
    assert d.results.verified(r.result_id) is not None
    loaded = json.loads(ReportedResult(result=r, server_verification=d.results.reported()[0].server_verification)
                        .model_dump_json())
    assert verify_loaded(loaded, store=store, selection=selection).outcome == "verified"


SCENARIOS = ["point_last_issued_before_QLD1", "point_issued_at_SA1", "aggregate_runs_differ_NSW1_AEDT",
             "aggregate_gap_partial_QLD1", "aggregate_one_half_hour_SA1", "aggregate_cutoff_partial_SA1",
             "aggregate_min_lead_hours_QLD1", "aggregate_initial_revision_SA1", "aggregate_no_pairs_QLD1",
             "aggregate_named_run_QLD1"]


@pytest.mark.parametrize("name", SCENARIOS)
def test_synthetic_matrix(name, tmp_path, selection):
    """A4: regions with three time zones, every existing policy, windows of 1, 3 and 24 half-hours with a gap, 0, 1,
    partial and complete pair sets, with and without a cutoff, and revision policies."""
    syn = Syn()
    ident_update: dict[str, Any] = {}
    if name == "point_last_issued_before_QLD1":
        syn.run("QLD1", "R1", "2026-05-01T07:40:00Z", {"2026-05-01T08:30:00Z": 6000.0})
        syn.run("QLD1", "R0", "2026-05-01T06:40:00Z", {"2026-05-01T08:30:00Z": 6100.0})
        syn.actual("QLD1", "2026-05-01T08:30:00Z", 6080.0)
        res = _res("QLD1", point=ForecastRequest("last_issued_before", None, (T("2026-05-01T08:00:00Z"),
                                                                               T("2026-05-01T08:30:00Z"))))
        want = {"status": "established", "runs": {"R1"}}
    elif name == "point_issued_at_SA1":
        syn.run("SA1", "RA", "2026-05-02T03:57:01Z", {"2026-05-02T05:00:00Z": 1500.0})
        syn.run("SA1", "RB", "2026-05-02T04:27:01Z", {"2026-05-02T05:00:00Z": 1450.0})
        syn.actual("SA1", "2026-05-02T05:00:00Z", 1470.0)
        res = _res("SA1", point=ForecastRequest("issued_at", T("2026-05-02T03:55:00Z"), (T("2026-05-02T04:30:00Z"),
                                                                                         T("2026-05-02T05:00:00Z"))))
        want = {"status": "established", "runs": {"RA"}}
    elif name == "aggregate_runs_differ_NSW1_AEDT":
        start = "2026-01-15T00:00:00Z"
        ends = _ends(start, 24)
        for h in range(-2, 12):  # a run every hour; each half-hour takes the latest available before it
            issued = iso_utc(T(start) + timedelta(hours=h) - timedelta(minutes=170))
            syn.run("NSW1", f"H{h:+03d}", issued, {e: 9000.0 + 10 * h + i for i, e in enumerate(ends)},
                    published=iso_utc(T(issued) + timedelta(minutes=4)),
                    available=iso_utc(T(issued) + timedelta(minutes=170)))
        for i, e in enumerate(ends):
            syn.actual("NSW1", e, 9000.0 + (i % 5) * 7)
        res = _res("NSW1", window=(start, ends[-1]))
        want = {"status": "established", "min_runs": 3}
    elif name == "aggregate_gap_partial_QLD1":
        start = "2026-05-03T00:00:00Z"
        ends = _ends(start, 3)
        syn.run("QLD1", "G1", "2026-05-02T20:00:00Z", {e: 5000.0 + i for i, e in enumerate(ends)})
        syn.actual("QLD1", ends[0], 5010.0)
        syn.actual("QLD1", ends[2], 4990.0)  # no actual for the middle half-hour
        res = _res("QLD1", window=(start, ends[-1]))
        want = {"status": "partial", "reasons": {"no_actual"}}
    elif name == "aggregate_one_half_hour_SA1":
        start = "2026-05-04T02:00:00Z"
        ends = _ends(start, 1)
        syn.run("SA1", "S1", "2026-05-03T22:00:00Z", {ends[0]: 1600.0})
        syn.actual("SA1", ends[0], 1650.0)
        res = _res("SA1", window=(start, ends[-1]))
        want = {"status": "established", "runs": {"S1"}}
    elif name == "aggregate_cutoff_partial_SA1":
        start = "2026-05-05T00:00:00Z"
        ends = _ends(start, 4)
        syn.run("SA1", "C1", "2026-05-04T18:00:00Z", {e: 1500.0 + 5 * i for i, e in enumerate(ends)})
        for i, e in enumerate(ends):  # the last two actuals are published after the cutoff
            syn.actual("SA1", e, 1490.0 + i, published=iso_utc(T(e) + timedelta(minutes=10)),
                       available=iso_utc(T(e) + timedelta(minutes=20)))
        res = _res("SA1", window=(start, ends[-1]), as_of=iso_utc(T(ends[1]) + timedelta(minutes=30)))
        want = {"status": "partial", "reasons": {"not_public_by_cutoff"}}
    elif name == "aggregate_min_lead_hours_QLD1":
        start = "2026-05-06T10:00:00Z"
        ends = _ends(start, 3)
        syn.run("QLD1", "DAY", "2026-05-05T04:00:00Z", {e: 7000.0 for e in ends})  # available more than a day ahead
        syn.run("QLD1", "LATE", "2026-05-06T06:00:00Z", {e: 7100.0 for e in ends})
        for e in ends:
            syn.actual("QLD1", e, 7050.0)
        res = _res("QLD1", window=(start, ends[-1]))
        ident_update = {"run_selection": "min_lead_hours", "min_lead_hours": 24.0}
        want = {"status": "established", "runs": {"DAY"}}
    elif name == "aggregate_initial_revision_SA1":
        start = "2026-05-07T00:00:00Z"
        ends = _ends(start, 2)
        syn.run("SA1", "I1", "2026-05-06T18:00:00Z", {e: 1400.0 for e in ends})
        for e in ends:
            syn.actual("SA1", e, 1380.0, "initial", published=iso_utc(T(e) + timedelta(minutes=5)),
                       available=iso_utc(T(e) + timedelta(minutes=10)))
            syn.actual("SA1", e, 1420.0, "updated")
        res = _res("SA1", window=(start, ends[-1]))
        ident_update = {"actual_revision_policy": "initial"}
        want = {"status": "established", "revision": "initial"}
    elif name == "aggregate_no_pairs_QLD1":
        start = "2026-05-08T00:00:00Z"
        ends = _ends(start, 2)
        syn.run("QLD1", "N1", "2026-05-07T18:00:00Z", {e: 6000.0 for e in ends})  # no actual at all
        res = _res("QLD1", window=(start, ends[-1]))
        want = {"status": "unavailable"}
    else:  # aggregate_named_run_QLD1: a review naming a run by its issue time, without a half-hour
        start = "2026-05-09T00:00:00Z"
        ends = _ends(start, 3)
        syn.run("QLD1", "NAMED", "2026-05-08T20:10:00Z", {e: 6200.0 for e in ends})
        syn.run("QLD1", "OTHER", "2026-05-08T22:00:00Z", {e: 6300.0 for e in ends})
        for e in ends:
            syn.actual("QLD1", e, 6250.0)
        res = _res("QLD1", window=(start, ends[-1]), named=ForecastRequest("issued_at", T("2026-05-08T20:12:00Z"), None))
        want = {"status": "established", "runs": {"NAMED"}}
    store = syn.store(tmp_path / "store")
    identity = None
    if ident_update:
        identity = fc.window_identity(res, store.data_version).model_copy(update=ident_update)
    d, r = _primary(store, selection, res, identity)
    assert r.status == want["status"], (r.status, r.reason)
    assert r.identity.region == res.region and r.identity.cutoff_utc == (iso_utc(res.as_of) if res.as_of else None)
    if "runs" in want:
        assert {p.run_id for p in r.pairs} == want["runs"]
    if "min_runs" in want:
        assert len({p.run_id for p in r.pairs}) >= want["min_runs"]
        assert any(x.code == "RUNS_DIFFER" for x in r.limitations)
    if "reasons" in want:
        assert {x.reason for x in r.excluded} == want["reasons"]
    if "revision" in want:
        assert {p.actual_revision for p in r.pairs} == {want["revision"]} and all(p.actual_mw == 1380.0 for p in r.pairs)
    _check_properties(r, store, selection, d, syn)


@pytest.mark.parametrize("case,code", [("run_not_held", "run_not_held"), ("tied", "tied_runs"),
                                       ("not_public", "run_not_public_by_cutoff"), ("no_actual", None),
                                       ("actual_not_public", None)])
def test_an_unavailable_point_is_not_substituted(case, code, tmp_path, selection):
    """A5: the point is unavailable with its reason; no other run, half-hour or window is computed or stated."""
    syn = Syn()
    hh = (T("2026-05-10T08:00:00Z"), T("2026-05-10T08:30:00Z"))
    end = "2026-05-10T08:30:00Z"
    as_of = None
    if case == "run_not_held":
        syn.run("QLD1", "AFTER", "2026-05-10T08:10:00Z", {end: 6000.0})  # issued after the half-hour starts
    elif case == "tied":
        syn.run("QLD1", "T1", "2026-05-10T07:40:00Z", {end: 6000.0})
        syn.run("QLD1", "T2", "2026-05-10T07:40:00Z", {end: 6050.0})
    elif case == "not_public":
        syn.run("QLD1", "P1", "2026-05-10T07:40:00Z", {end: 6000.0}, available="2026-05-10T10:30:00Z")
        as_of = "2026-05-10T09:00:00Z"
    else:
        syn.run("QLD1", "OK", "2026-05-10T07:40:00Z", {end: 6000.0}, available="2026-05-10T07:50:00Z")
        if case == "actual_not_public":
            syn.actual("QLD1", end, 6020.0, published="2026-05-10T12:00:00Z", available="2026-05-10T12:05:00Z")
            as_of = "2026-05-10T09:00:00Z"
    if case != "run_not_held":  # an older public run that must not stand in (it would be the run asked for otherwise)
        syn.run("QLD1", "OLDER", "2026-05-10T05:00:00Z", {end: 5900.0}, available="2026-05-10T05:10:00Z")
    syn.actual("QLD1", "2026-05-10T09:00:00Z", 6010.0)  # a neighbouring half-hour that must not stand in
    store = syn.store(tmp_path / "store")
    res = _res("QLD1", point=ForecastRequest("last_issued_before", None, hh), as_of=as_of)
    d, r = _primary(store, selection, res)
    assert r.status == "unavailable" and not r.pairs and r.mae_mw is None
    if code is not None:
        assert [x.reason for x in r.excluded] == [code]
        assert not [x for x in d.records if x.name == "compare_forecast_actual"]  # no comparison made in its place
    else:
        assert [x.reason for x in r.excluded] == ["not_public_by_cutoff" if case == "actual_not_public" else
                                                 "no_actual"]
        (call,) = [x for x in d.records if x.name == "compare_forecast_actual"]
        assert (call.args["target_start_utc"], call.args["target_end_utc"]) == (iso_utc(hh[0]), iso_utc(hh[1]))
    answer = render_result(d.results.reported()[0], d.results, "QLD1", lambda e: "x")
    assert answer.status == "unavailable" and "cannot be given" in answer.statement
    assert "No other forecast run or half-hour is given in its place" in answer.statement


def test_a_live_point_request_gets_no_window_guidance_even_when_its_run_is_unavailable(real_store):
    """A5: point or window is decided from the resolved request: R02's question under a cutoff before its run is
    public still gets no window to compare, and its answer says the comparison cannot be given."""
    rec, _ = _saved_fake("R02")
    fake = FakeModel(rec["route"], [[]], lambda kw: copy.deepcopy(DRAFT))
    res = _live(rec["question"], fake, as_of_utc="2026-08-19T22:00:00Z")
    context = next(i["content"] for i in fake.requests[1]["input"] if isinstance(i, dict)
                   and str(i.get("content", "")).startswith("Investigation context"))
    assert "forecast_targets_utc" not in context and "24 half-hours" not in context
    (a,) = res.report.answer
    assert a.kind == "forecast_point" and a.status == "unavailable" and "not provably public" in a.statement
    assert not [x for x in res.records if x.call_id == fc.POINT_CALL_ID]


def test_a_live_window_review_keeps_its_window_guidance(real_store):
    """The window guidance is unchanged where the request asks about a window (FC01's question), and
    ``forecast_comparison`` is the controller's aggregate primary although the draft names no MAE (D27: never filled
    from the model's ``forecast_mae_evidence_id``)."""
    rec, _ = _saved_fake("R02")
    route = copy.deepcopy(rec["route"]) | {"event_date": "2026-07-31"}
    route["requested"]["forecast_run"] = {"selection": "none", "selection_text": None, "half_hour_text": None}
    a, b = "2026-07-30T11:00:00Z", "2026-07-30T23:00:00Z"  # the 12-hour focus window around FC01's event peak
    turn = [("get_forecast_runs", {"region": "SA1", "target_start_utc": a, "target_end_utc": b, "as_of_utc": None,
                                   "max_runs": 4}),
            ("get_actual_demand", {"region": "SA1", "start_utc": a, "end_utc": b, "revision_policy": "latest_available",
                                   "as_of_utc": None}),
            ("compare_forecast_actual", {"region": "SA1", "target_start_utc": a, "target_end_utc": b,
                                         "run_selector": "latest_before_target", "min_lead_hours": None, "run_id": None,
                                         "as_of_utc": None, "actual_revision": "latest_available",
                                         "actual_metric": "OPERATIONAL_DEMAND"}),
            ("retrieve_public_evidence", {"query": "operational demand forecast POE", "region": None,
                                          "event_start_utc": None, "event_end_utc": None, "as_of_utc": None, "top_k": 3,
                                          "doc_types": ["definition"]})]

    def draft(kw: dict) -> dict:
        cmp = next(v["result"] for v in outputs(kw).values() if "mae_mw" in v.get("result", {}))
        return copy.deepcopy(DRAFT) | {"observation_evidence_ids": [cmp["mae_mw"]["evidence_id"]]}
    fake = FakeModel(route, [turn], draft)
    res = _live(FC_CASES["FC01"]["question"], fake)
    context = next(i["content"] for i in fake.requests[1]["input"] if isinstance(i, dict)
                   and str(i.get("content", "")).startswith("Investigation context"))
    assert "forecast_targets_utc" in context and "24 half-hours" in context
    r = res.report.results[0].result
    assert isinstance(r, ForecastResult) and r.identity.kind == "forecast_aggregate" and r.status == "established"
    assert not res.report.validation["fallback_applied"]
    fcomp = res.report.forecast_comparison
    assert fcomp is not None and (fcomp.mae_mw, fcomp.n_pairs) == (r.mae_mw, len(r.pairs))
    assert fcomp.mae_evidence_id == res.resolution.forecast_primary["mae_evidence_id"]


# ------------------------------------------------------------------------------------------------ scope provenance
def _two_scopes(tmp_path: Path, selection: Any) -> tuple[Dispatcher, Resolution, ForecastResult, Any]:
    """SYNTHETIC: the point asked about (error +30 at 08:30Z) and a model's own comparison over two half-hours whose
    errors are -30 and +30, so its MAE equals the point's error: equal values from different scopes."""
    syn = Syn()
    syn.run("SA1", "RUN", "2026-05-11T07:30:00Z", {"2026-05-11T08:00:00Z": 1470.0, "2026-05-11T08:30:00Z": 1530.0},
            available="2026-05-11T07:40:00Z")
    syn.actual("SA1", "2026-05-11T08:00:00Z", 1500.0)
    syn.actual("SA1", "2026-05-11T08:30:00Z", 1500.0)
    store = syn.store(tmp_path / "store")
    res = _res("SA1", point=ForecastRequest("last_issued_before", None, (T("2026-05-11T08:00:00Z"),
                                                                          T("2026-05-11T08:30:00Z"))))
    d = _dispatcher(store, selection, res)
    other = d.call("compare_forecast_actual", {"region": "SA1", "target_start_utc": "2026-05-11T07:30:00Z",
                                               "target_end_utc": "2026-05-11T08:30:00Z", "run_selector": "run_id",
                                               "run_id": "RUN"}, call_id="model_call", origin="model")
    r = fc.compute(d, fc.point_identity(res, fc.point_request(res), store.data_version))
    fc.submit(d, res, r)
    return d, res, r, other


def _report(d: Dispatcher, claims: list[NumericClaim], texts: dict[str, Any]) -> InvestigationReport:
    from nem_agent.report import Hypothesis, Versions

    v = Versions(code="x", data="x", corpus=None, prompt="x", model=None, controller="x")
    return InvestigationReport(
        schema_version="1", question="SYNTHETIC", mode="live", intent="forecast_review", region="SA1", as_of=None,
        event_window=None, headline=texts.get("headline", "SYNTHETIC."), summary=texts.get("summary", []),
        observations=[], search_scope=[], numeric_claims=claims,
        possible_explanations=[Hypothesis(statement=s, supporting_evidence_ids=[], what_would_test_it="SYNTHETIC")
                               for s in texts.get("explanations", [])],
        published_findings=[], citations=[], uncertainties=texts.get("uncertainties", []), missing_evidence=[],
        source_manifest={}, status="answered", trace_id="x", versions=v, generator="live-model:x")


def _ids(d: Dispatcher, call_id: str, metric: str, end: str | None = None) -> str:
    return next(e.evidence_id for e in d.registry.items.values() if e.tool_call_id == call_id and e.metric == metric
                and (end is None or e.valid_at_utc == end))


def _scope_violations(d: Dispatcher, res: Resolution, report: InvestigationReport) -> list[Any]:
    out = validate(report, d.registry, records=d.records, forecast_primary=res.forecast_primary)
    return [x for x in out.violations if x.code == "FORECAST_SCOPE_NOT_PRIMARY"]


WORDINGS = [("headline", "The forecast missed by 30 MW on average."),
            ("summary", "Across the comparison the mean absolute error was 30 MW."),
            ("summary", "For the half-hour asked about, the error was 30 MW."),
            ("explanations", "The 30 MW gap might reflect forecast uncertainty."),
            ("uncertainties", "An MAE of 30 MW may not be representative."),
            ("summary", "The run/actual pair yields a mean absolute error of 30 MW.")]


@pytest.mark.parametrize("where,text", WORDINGS)
def test_an_out_of_scope_value_is_rejected_whatever_the_wording(where, text, tmp_path, selection):
    """B2 and B4: the model comparison's MAE (30 MW, equal to the point's error) cited in any wording, in any field."""
    d, res, _, _ = _two_scopes(tmp_path, selection)
    claim = NumericClaim(claim_id="c1", text="MAE", value=30.0, unit="MW", evidence_id=_ids(d, "model_call", "mae_mw"))
    texts = {where: text if where == "headline" else [text]}
    found = _scope_violations(d, res, _report(d, [claim], texts))
    assert [v.detail.split(":")[0] for v in found] == ["c1"]
    assert "30" not in found[0].detail.split(":", 1)[1] and text not in found[0].detail  # generic: no value or wording (B5)


def test_true_statements_of_the_primary_pass_and_its_rows_are_in_scope(tmp_path, selection):
    """The point's own values, and the same pair's values from another comparison (the same rows), are in scope; a
    value of another half-hour from that comparison is not."""
    d, res, r, _ = _two_scopes(tmp_path, selection)
    ok = [NumericClaim(claim_id="p1", text="error", value=30.0, unit="MW",
                       evidence_id=_ids(d, fc.POINT_CALL_ID, "forecast_error_mw")),
          NumericClaim(claim_id="p2", text="POE50", value=1530.0, unit="MW",
                       evidence_id=_ids(d, "model_call", "opdemand_forecast_poe50", "2026-05-11T08:30:00Z"))]
    assert _scope_violations(d, res, _report(d, ok, {"summary": [
        "For the half-hour ending 2026-05-11T08:30:00Z, the POE50 was 1530 MW and the error was 30 MW."]})) == []
    other = NumericClaim(claim_id="o1", text="error", value=-30.0, unit="MW",
                         evidence_id=_ids(d, "model_call", "forecast_error_mw", "2026-05-11T08:00:00Z"))
    assert [v.detail.split(":")[0] for v in _scope_violations(d, res, _report(d, [other], {}))] == ["o1"]
    assert r.pairs[0].error_mw == 30.0


def test_equal_values_from_different_scopes_stay_distinct(tmp_path, selection):
    """A6: the point's error equals the other comparison's MAE, but the results and evidence differ by identity."""
    d, res, r, other = _two_scopes(tmp_path, selection)
    assert r.pairs[0].error_mw == other.view["mae_mw"]["value"] == 30.0
    window = fc.window_identity(_res("SA1", window=("2026-05-11T07:30:00Z", "2026-05-11T08:30:00Z")),
                                d.store.data_version)
    agg = fc.compute(_dispatcher(d.store, selection, res), window)
    assert agg.mae_mw == 30.0 and agg.result_id != r.result_id and agg.identity.kind != r.identity.kind
    other_region = window.model_copy(update={"region": "QLD1"})
    assert fc.compute(_dispatcher(d.store, selection, res), other_region).result_id != agg.result_id


def test_an_aggregate_primary_admits_its_own_aggregate_and_rejects_another_policys(tmp_path, selection):
    """B3: a window review's primary aggregate may be cited; the same window under another policy may not."""
    syn = Syn()
    start = "2026-05-12T00:00:00Z"
    ends = _ends(start, 2)
    syn.run("QLD1", "DAY", "2026-05-10T20:00:00Z", {e: 6000.0 for e in ends})
    syn.run("QLD1", "NEAR", "2026-05-11T20:00:00Z", {e: 6100.0 for e in ends})
    for e in ends:
        syn.actual("QLD1", e, 6050.0)
    store = syn.store(tmp_path / "store")
    res = _res("QLD1", window=(start, ends[-1]))
    d, r = _primary(store, selection, res)
    day = d.call("compare_forecast_actual", {"region": "QLD1", "target_start_utc": start, "target_end_utc": ends[-1],
                                             "run_selector": "min_lead_hours", "min_lead_hours": 24},
                 call_id="model_day", origin="model")
    own = NumericClaim(claim_id="a1", text="MAE", value=r.mae_mw, unit="MW", evidence_id=res.forecast_primary[
        "mae_evidence_id"])
    theirs = NumericClaim(claim_id="a2", text="MAE", value=day.view["mae_mw"]["value"], unit="MW",
                          evidence_id=day.view["mae_mw"]["evidence_id"])
    found = _scope_violations(d, res, _report(d, [own, theirs], {}))
    assert [v.detail.split(":")[0] for v in found] == ["a2"]


# ------------------------------------------------------------------------------------------------ verification
def test_tampered_or_foreign_results_are_not_admitted_and_state_no_value(tmp_path, selection):
    """A7: a tampered value, pair, row, run or policy fails; another data or calculation version is unverifiable; a
    result not admitted renders with no value, and no value carrying its rows may be stated."""
    d, res, r, _ = _two_scopes(tmp_path, selection)
    store = d.store
    p = r.pairs[0]
    tampered = [
        r.model_copy(update={"pairs": (p.model_copy(update={"poe50_mw": p.poe50_mw + 1}),)}),
        r.model_copy(update={"pairs": (p.model_copy(update={"actual_row_id": "SYN_ACT:other"}),)}),
        r.model_copy(update={"pairs": (p.model_copy(update={"run_id": "ANOTHER"}),)}),
        r.model_copy(update={"identity": r.identity.model_copy(update={"run_selection": "issued_at"})}),
    ]
    for t in tampered:
        assert verify_loaded(json.loads(t.model_dump_json()), store=store, selection=selection).outcome == "failed"
    foreign = r.model_copy(update={"identity": r.identity.model_copy(update={"data_version": "other"})})
    redigested = fc.make_forecast_result(foreign.identity, **{k: getattr(r, k) for k in (
        "status", "reason", "pairs", "excluded", "targets_expected", "source_row_ids", "limitations", "transient")})
    assert verify_loaded(redigested, store=store, selection=selection).outcome == "unverifiable"
    unknown = fc.make_forecast_result(r.identity.model_copy(update={"calculation_version": "forecast_compare/0"}),
                                      **{k: getattr(r, k) for k in ("status", "reason", "pairs", "excluded",
                                                                    "targets_expected", "source_row_ids",
                                                                    "limitations", "transient")})
    assert verify_loaded(unknown, store=store, selection=selection).outcome == "unverifiable"
    registry = ResultRegistry()
    registry.submit_in_run(tampered[0], store=store, selection=selection, evidence=d.registry)
    shown = render_result(registry.reported()[0], registry, "SA1", lambda e: "NEVER")
    assert shown.status == "not_verified" and "NEVER" not in shown.statement and "1530" not in shown.statement
    res.forecast_primary = fc.scope_of(tampered[0], admitted=False)
    claim = NumericClaim(claim_id="u1", text="POE50", value=1530.0, unit="MW",
                         evidence_id=_ids(d, fc.POINT_CALL_ID, "opdemand_forecast_poe50"))
    assert [v.detail.split(":")[0] for v in _scope_violations(d, res, _report(d, [claim], {}))] == ["u1"]


# ------------------------------------------------------------------------------------------------ compatibility
@pytest.mark.parametrize("cid", ["D02", "D01"])
def test_maxima_render_and_validate_exactly_as_saved(cid, real_store):
    """C1: a saved maximum's computed answer is byte-identical, and its interpretation status is as saved."""
    rec, fake = _saved_fake(cid)
    res = _live(rec["question"], fake, **rec["request"])
    assert [a.statement for a in res.report.answer] == [a["statement"] for a in rec["report"]["answer"]]
    assert res.report.validation["interpretation"] == rec["report"]["validation"]["interpretation"]
    assert res.resolution.forecast_primary is None


def test_saved_records_with_results_still_validate_and_round_trip():
    """C2: the report schema change is additive: every saved record carrying results validates and round-trips."""
    n = 0
    for p in sorted(LIVE.glob("*/*.json")):
        rec = json.loads(p.read_text())
        rep = rec.get("report") if isinstance(rec, dict) else None
        if not isinstance(rep, dict) or not rep.get("results"):
            continue
        again = InvestigationReport.model_validate(rep).model_dump(mode="json")
        assert again == rep, p
        n += 1
    assert n >= 10


def test_prompts_v14_change_only_the_synthesis_forecast_bullet():
    """C3: routing's prompt (and system prompt) are byte-identical; synthesis changes in the one bullet."""
    v13, v14 = ROOT / "src/nem_agent/prompts/v13", ROOT / "src/nem_agent/prompts/v14"
    assert (v13 / "route.md").read_bytes() == (v14 / "route.md").read_bytes()
    assert (v13 / "system.md").read_bytes() == (v14 / "system.md").read_bytes()
    a, b = (v13 / "synthesis.md").read_text().splitlines(), (v14 / "synthesis.md").read_text().splitlines()
    import difflib

    changed = [x for x in difflib.unified_diff(a, b, lineterm="", n=0) if x[:1] in "+-" and x[:3] not in ("+++", "---")]
    assert [x for x in changed if x.startswith("-")] == [
        "-- Forecast reviews: compare the context's `forecast_targets_utc` with compare_forecast_actual, and set",
        "-  `forecast_mae_evidence_id` to the evidence_id of the MAE you report (null for other questions)."]
    assert all("forecast" in x or "controller" in x or "compare_forecast_actual" in x for x in changed)
