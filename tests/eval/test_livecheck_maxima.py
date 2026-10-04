"""The Live acceptance check of computed demand maxima (eval/livecheck_maxima/PROTOCOL.md): its cases, gold, exporter,
runner, scorer and freeze, offline. Nothing here calls a model:
- the runner's processes, ledger and records are injected;
- the exporter runs on saved Live records replayed through the SYNTHETIC fake transport, or in Replay mode;
- the scorer's verdict is tested on SYNTHETIC automatic fields and readings.

Scripted variants (a tampered record, a forced verification outcome) are labelled as such."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
from datetime import date
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "eval" / "livecheck_maxima"
LIVE = ROOT / "artifacts" / "live"


def _load(name: str):
    """Under a name of its own: other evaluation directories have modules called `score`, `freeze` and `run_eval`."""
    spec = importlib.util.spec_from_file_location(f"lcmax_{name}", DIR / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


EXPORT = _load("export")
GOLD = _load("gold")
CASE = _load("run_case")
RUN = _load("run_eval")
SCORE = _load("score")
FRZ = _load("freeze")
CASES = json.loads((DIR / "cases.json").read_text())["cases"]
BY_ID = {c["case_id"]: c for c in CASES}
GOLD_JSON = json.loads((DIR / "GOLD.json").read_text())
FREEZE = json.loads((DIR / "FREEZE.json").read_text()) if (DIR / "FREEZE.json").exists() else None
LC, V6 = "eval/livecheck_i15_17/cases.json", "eval/holdout_v6/cases.json"
OWN = ("case_id", "check_group", "origin", "intended")


def _origin(rel: str, cid: str) -> dict:
    return next(c for c in json.loads((ROOT / rel).read_text())["cases"] if c["case_id"] == cid)


# ------------------------------------------------------------------------------------------------ the cases
def test_reused_cases_are_copied_unchanged_but_for_their_id():
    for cid, (rel, src) in {"D01": (LC, "K09"), "D02": (LC, "K11"), "D03": (V6, "Z04"), "R01": (LC, "K05"),
                            "R02": (LC, "K06"), "R03": (LC, "K07"), "R04": (LC, "K14")}.items():
        c, o = BY_ID[cid], _origin(rel, src)
        assert c["origin"] == {"file": rel, "case_id": src}
        assert {k: v for k, v in c.items() if k not in OWN} == {k: v for k, v in o.items() if k != "case_id"}


def test_d04_is_z04_with_only_the_cutoff_added():
    d, z = BY_ID["D04"], _origin(V6, "Z04")
    assert d["question"] == z["question"] and z["request"] == {} and d["request"] == {"as_of_utc": "2026-07-29T05:00:00Z"}
    assert d["origin"]["changed"] == {"request.as_of_utc": "2026-07-29T05:00:00Z"}
    assert d["intended"]["expected_outcome"] == "not_established" and d["intended"]["as_of_utc"] == d["request"]["as_of_utc"]


def test_fresh_cases_are_the_writers_output_and_meet_their_strata(selection):
    written = {c["case_id"]: c for c in json.loads((DIR / "WRITER_OUTPUT.json").read_text())["cases"]}
    fresh = [c for c in CASES if c["check_group"] == "fresh"]
    assert [c["case_id"] for c in fresh] == [f"F0{i}" for i in range(1, 9)]
    for c in fresh:
        w = written[c["case_id"]]
        assert (c["question"], c["request"], c["intended"]) == (w["question"], w["request"], w["intended"])
    it = {c["case_id"]: c["intended"] for c in fresh}
    day = ["2026-07-28T14:00:00Z", "2026-07-29T14:00:00Z"]
    assert {it["F01"]["measure"], it["F02"]["measure"]} == {"total demand"}
    assert it["F01"]["region"] != it["F02"]["region"] and not {it["F01"]["region"], it["F02"]["region"]} & {"NSW1", "TAS1"}
    assert (it["F03"]["measure"], it["F03"]["window_kind"]) == ("operational demand", "day") and it["F03"]["region"] != "QLD1"
    assert it["F04"]["measure"] == "operational demand" and it["F04"]["region"] in ("NSW1", "SA1", "TAS1", "VIC1")
    assert GOLD.local_day(date(2026, 4, 5), it["F04"]["region"]) == tuple(GOLD.ts(x) for x in it["F04"]["window_utc"])
    assert it["F05"]["window_kind"] == "explicit" and BY_ID["F05"]["request"] == {
        "window_start_utc": it["F05"]["window_utc"][0], "window_end_utc": it["F05"]["window_utc"][1]}
    assert it["F05"]["measure"] != it["F06"]["measure"] and it["F06"]["window_kind"] == "event"
    ev = next(e for e in selection.events if e.event_id == it["F06"]["event_id"])
    assert [ev.window_start_utc, ev.window_end_utc] == it["F06"]["window_utc"]
    f7 = it["F07"]
    assert f7["measure"] == "operational demand" and BY_ID["F07"]["request"] == {"as_of_utc": f7["as_of_utc"]}
    assert f7["window_utc"][0] < f7["as_of_utc"] < f7["window_utc"][1] and f7["expected_outcome"] == "not_established"
    assert it["F08"]["expected_outcome"] == "clarification" and (it["F08"]["measure"] is None
                                                                   or it["F08"]["window_kind"] is None)
    assert all(BY_ID[f"F0{i}"]["request"] == {} for i in (1, 2, 3, 4, 6, 8))
    assert it["F01"]["window_utc"] == day and it["F03"]["window_utc"] == day


# ------------------------------------------------------------------------------------------------ gold
def test_gold_is_reproducible_and_agrees_with_the_frozen_gold_of_the_reused_cases(real_store):
    assert GOLD.build(CASES) == GOLD_JSON
    g = {c["case_id"]: c for c in GOLD_JSON["cases"]}
    assert all(g[cid]["frozen_gold"]["agrees"] for cid in ("D01", "D02", "D03"))
    assert {cid: g[cid]["result"]["status"] for cid in g if g[cid]["result"]} == {
        **{cid: "established" for cid in ("D01", "D02", "D03", "F01", "F02", "F03", "F04", "F05", "F06")},
        "D04": "not_established", "F07": "not_established"}
    assert g["F08"]["result"] is None
    assert g["F04"]["result"]["intervals_in_window"] == 50  # the 25-hour day
    assert all(len(g[cid]["result"]["interval_ends_utc"]) == 1 for cid in g if g[cid]["result"])  # no ties in the sample


def _synthetic_con(rows: list[tuple]) -> duckdb.DuckDBPyConnection:
    """SYNTHETIC operational-demand rows: (row_id, interval_end, value, revision, published_at, available_at)."""
    con = duckdb.connect()
    con.execute("CREATE TABLE opdemand_actual (row_id VARCHAR, region VARCHAR, interval_end_utc TIMESTAMPTZ, "
                "operational_demand_mw DOUBLE, revision VARCHAR, published_at_utc TIMESTAMPTZ, "
                "available_at_utc TIMESTAMPTZ)")
    for r in rows:
        con.execute("INSERT INTO opdemand_actual VALUES (?, 'SA1', ?::TIMESTAMPTZ, ?, ?, ?::TIMESTAMPTZ, ?::TIMESTAMPTZ)",
                    list(r))
    return con


def test_gold_takes_the_latest_eligible_revision_never_a_later_one_unavailable_at_the_cutoff():
    con = _synthetic_con([
        ("a-i", "2026-01-01T00:30:00Z", 100.0, "initial", "2026-01-01T03:00:00Z", "2026-01-01T03:00:00Z"),
        ("a-u", "2026-01-01T00:30:00Z", 120.0, "updated", "2026-01-02T03:00:00Z", "2026-01-02T03:00:00Z"),
        ("b-i", "2026-01-01T01:00:00Z", 110.0, "initial", "2026-01-01T03:30:00Z", "2026-01-01T03:30:00Z"),
        # published after the cutoff although its availability stamp is before it: not eligible
        ("b-u", "2026-01-01T01:00:00Z", 130.0, "updated", "2026-01-01T09:00:00Z", "2026-01-01T04:00:00Z")])
    w = ("2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z")
    late = GOLD.compute(con, "operational demand", "SA1", w, None)
    assert (late["status"], late["value"], late["source_row_ids"]) == ("established", 130.0, ["b-u"])
    cut = GOLD.compute(con, "operational demand", "SA1", w, "2026-01-01T05:00:00Z")
    assert (cut["status"], cut["value"], cut["source_row_ids"]) == ("established", 110.0, ["b-i"])
    assert cut["excluded_rows_by_as_of"] == 2 and cut["revisions_used"] == {"initial": 2, "updated": 0}
    early = GOLD.compute(con, "operational demand", "SA1", w, "2026-01-01T03:10:00Z")
    assert (early["status"], early["value"], early["intervals_held"], early["intervals_without_eligible_row"],
            early["excluded_rows_by_as_of"]) == ("not_established", 100.0, 1, 1, 3)
    none = GOLD.compute(con, "operational demand", "SA1", w, "2026-01-01T01:00:00Z")
    assert none["status"] == "unavailable" and none["value"] is None


def test_gold_keeps_every_tied_interval():
    con = _synthetic_con([
        ("a", "2026-01-01T00:30:00Z", 100.0, "updated", "2026-01-01T03:00:00Z", "2026-01-01T03:00:00Z"),
        ("b", "2026-01-01T01:00:00Z", 100.0, "updated", "2026-01-01T03:00:00Z", "2026-01-01T03:00:00Z")])
    r = GOLD.compute(con, "operational demand", "SA1", ("2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"), None)
    assert r["interval_ends_utc"] == ["2026-01-01T00:30:00Z", "2026-01-01T01:00:00Z"] and r["source_row_ids"] == ["a", "b"]
    assert r["runner_up"] is None


def test_the_gold_comparison_is_exact():
    assert GOLD.compare(GOLD_JSON, copy.deepcopy(GOLD_JSON)) == []
    other = copy.deepcopy(GOLD_JSON)
    other["cases"][0]["result"]["value"] += 0.01
    other["cases"][1]["reading"]["window_kind"] = "event"
    other["cases"] = other["cases"][:-1]
    diffs = GOLD.compare(GOLD_JSON, other)
    assert any("D01: result value" in d for d in diffs) and any("D02: reading window_kind" in d for d in diffs)
    assert any("only in GOLD" in d for d in diffs)


# ------------------------------------------------------------------------------------------------ the exporter
def test_the_frozen_exporters_are_unchanged():
    frozen = json.loads((ROOT / "eval" / "model_comparison_dev" / "FREEZE.json").read_text())["files_sha256"]
    for rel in ("scripts/live_diagnose.py", "eval/livecheck_i15_17/run_case.py"):
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == frozen[rel]


def _fake(label: str, cid: str):
    """SYNTHETIC transport replaying a saved Live record: its route, tool calls, draft and repair."""
    from tests.provider.fake_model import FakeModel

    rec = json.loads((LIVE / label / f"{cid}.json").read_text())
    trace = json.loads((LIVE / label / "traces" / f"{rec['score']['trace_id']}.json").read_text())["events"]
    draft = rec["drafts"]["synthesis:draft"]
    patch = next((e.get("patch") for e in trace if e["name"] == "repair:scoped"), None)
    repaired = rec["drafts"].get("repair:draft")

    def saved(kw):
        return copy.deepcopy(patch if kw["text"]["format"]["name"] == "RepairPatch" else repaired)

    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    return FakeModel(rec["route"], [calls], lambda kw: copy.deepcopy(draft), saved if (patch or repaired) else None)


def _export(monkeypatch, tmp_path, cid: str, src: str | None, mode: str = "live"):
    """Run one case through the new exporter: Live through the fake transport (replaying ``src``), or Replay."""
    from nem_agent.evaluation import runner

    real = runner.investigate
    fake = _fake("MC-dev-e2e-mini", src) if src else None
    monkeypatch.setattr(runner, "investigate", lambda req, **kw: real(req, live_client=fake, write_trace=False))
    line = CASE.run_one(BY_ID[cid], tmp_path, mode=mode)
    rec = json.loads((tmp_path / f"{cid}.json").read_text())
    trace = json.loads((tmp_path / "traces" / f"{rec['trace_id']}.json").read_text())
    return line, rec, trace


def _gold(cid: str) -> dict:
    return next(c for c in GOLD_JSON["cases"] if c["case_id"] == cid)


@pytest.fixture(scope="module")
def store_sel():
    from nem_agent.service import _shared

    return _shared()


def test_the_exporter_keeps_the_full_format_2_report_and_it_round_trips(monkeypatch, tmp_path, real_store, store_sel):
    store, sel = store_sel
    line, rec, trace = _export(monkeypatch, tmp_path, "D02", "K11")
    rep = rec["report"]
    assert "format=2 answer=1" in line and rec["exporter"] == EXPORT.EXPORTER
    assert rep["schema_version"] == "2" and rep["answer"][0]["status"] == "established"
    assert rep["results"][0]["server_verification"]["outcome"] == "verified"
    assert rep["validation"]["interpretation"] == "validated" and not rep["validation"]["fallback_applied"]
    assert rec["display"]["report_format"] == "2" and rec["display"]["summary_v1"][0] == rep["answer"][0]["statement"]
    assert rec["drafts"] and rec["tools"] and rec["model_calls"] and rec["route"]
    assert EXPORT.integrity_problems(rec, trace, store=store, selection=sel) == []
    assert EXPORT.format_problems(rec) == [] and EXPORT.fallback_problems(rec) == []
    probs, correct = EXPORT.result_problems(rec, _gold("D02")["result"], _gold("D02")["reading"])
    assert probs == [] and correct


def test_a_fallback_is_labelled_and_never_counted_as_supplied(monkeypatch, tmp_path, real_store, store_sel):
    store, sel = store_sel
    _, rec, trace = _export(monkeypatch, tmp_path, "D01", "K09")  # this saved draft falls back under the current code
    assert rec["report"]["validation"]["fallback_applied"]
    assert EXPORT.fallback_problems(rec) == [] and EXPORT.format_problems(rec) == []
    a = SCORE.automatic(BY_ID["D01"], rec, trace, _gold("D01"), store=store, selection=sel)
    assert a["usability_floor"] == "F" and a["correct_result_produced"]  # availability apart from usability
    d = SCORE.decide([BY_ID["D01"]], {"D01": a}, {"D01": SCORE.merge([_reading("S"), _reading("S")])})
    assert d["usability"]["D01"] == "F" and d["overrides"] and not d["criteria"]["5_fallback_classification"]["violations"]


def test_a_regression_control_exports_its_requested_point_as_format_2(monkeypatch, tmp_path, real_store, store_sel):
    """D27 changed this outcome (it exported format 1, no computed answer, when the check ran; its frozen record is
    unchanged): K07 asks about one run and half-hour, so the controller's comparison of them is its computed answer,
    unavailable because the run is not provably public by the cutoff."""
    _, rec, _ = _export(monkeypatch, tmp_path, "R03", "K07")
    rep = rec["report"]
    assert rep["schema_version"] == "2" and [(a["kind"], a["status"]) for a in rep["answer"]] == [
        ("forecast_point", "unavailable")]
    assert [r["result"]["schema_version"] for r in rep["results"]] == ["forecast_result/1"]
    assert EXPORT.format_problems(rec) == []
    assert rec["display"]["summary_v1"] == [rep["answer"][0]["statement"], *rep["summary"]]  # read as format 1 (D25)


def test_replay_mode_exports_the_cutoff_case_as_not_established(monkeypatch, tmp_path, real_store, store_sel):
    store, sel = store_sel
    _, rec, trace = _export(monkeypatch, tmp_path, "D04", None, mode="replay")
    assert rec["report"]["answer"][0]["status"] == "not_established"
    a = SCORE.automatic(BY_ID["D04"], rec, trace, _gold("D04"), store=store, selection=sel)
    assert a["correct_result_produced"] and not any(a["problems"].values())


def test_scripted_tampering_is_caught(monkeypatch, tmp_path, real_store, store_sel):
    """SCRIPTED: edits of a saved record that the export checks must catch."""
    store, sel = store_sel
    _, rec, trace = _export(monkeypatch, tmp_path, "D02", "K11")
    bad = copy.deepcopy(rec)
    bad["report"]["results"][0]["result"]["maximum"] += 1
    assert any("re-verify" in p for p in EXPORT.integrity_problems(bad, trace, store=store, selection=sel))
    bad = copy.deepcopy(rec)
    del bad["report"]["schema_version"]
    assert any("no schema_version" in p for p in EXPORT.integrity_problems(bad, trace, store=store, selection=sel))
    bad = copy.deepcopy(rec)
    bad["report"]["summary"] = [*bad["report"]["summary"], bad["report"]["answer"][0]["statement"]]
    assert any("repeated in summary" in p for p in EXPORT.format_problems(bad))
    bad = copy.deepcopy(rec)
    bad["report"]["schema_version"] = "1"
    assert any("not '2'" in p for p in EXPORT.format_problems(bad))
    t2 = copy.deepcopy(trace)
    t2["events"] = [e for e in t2["events"] if e.get("name") != "max_answer"]
    assert any("max_answer" in p for p in EXPORT.integrity_problems(rec, t2, store=store, selection=sel))
    t3 = copy.deepcopy(trace)
    t3["events"] = [e for e in t3["events"] if e.get("kind") != "result"]
    assert any("result events" in p for p in EXPORT.integrity_problems(rec, t3, store=store, selection=sel))
    g = copy.deepcopy(_gold("D02"))
    g["result"]["value"] += 1
    probs, correct = EXPORT.result_problems(rec, g["result"], g["reading"])
    assert not correct and "value" in probs[0]
    probs, correct = EXPORT.result_problems(rec, None, None)  # an admitted result in a case with no gold result
    assert not correct and "no gold result" in probs[0]


def test_an_unadmitted_result_renders_no_value(monkeypatch, tmp_path, real_store):
    """SCRIPTED: re-derivation disagrees, so the computed result is not admitted."""
    from nem_agent.agent import demand_max as DM

    real = DM.rederive

    def failed(identity, store, selection):
        r = real(identity, store, selection)
        keep = ("status", "reason", "metric", "unit", "interval_ends_utc", "highest_held",
                "highest_held_interval_ends_utc", "coverage", "source_row_ids", "limitations", "transient")
        return DM.make_result(r.identity, **{k: getattr(r, k) for k in keep}, maximum=(r.maximum or 0) + 1)

    monkeypatch.setattr(DM, "rederive", failed)
    _, rec, _ = _export(monkeypatch, tmp_path, "D02", "K11")
    assert rec["report"]["answer"][0]["status"] == "not_verified"
    probs, n = EXPORT.unadmitted_problems(rec)
    assert probs == [] and n == 1 and EXPORT.admitted(rec) == []
    bad = copy.deepcopy(rec)
    bad["report"]["answer"][0]["statement"] += " (7548 MW)"
    assert any("value" in p for p in EXPORT.unadmitted_problems(bad)[0])


# ------------------------------------------------------------------------------------------------ the verdict
def _reading(outcome: str | None, **kw) -> dict:
    return {"outcome": outcome, "H2_manual": 0, "H4_manual": 0, "correct_result_shown": True,
            "unadmitted_or_observation_presented_as_maximum": False, "interpretation_contradicts_answer": False,
            "gold_items": [], **kw}


def _auto(correct: bool = True, **kw) -> dict:
    return {"H1": 0, "H2_auto": 0, "H3": 0, "H4_auto": 0, "H5": 0, "problems": {k: [] for k in SCORE.CRITERIA[1:]},
            "correct_result_produced": correct, "miss_cause": None if correct else "sent back by routing",
            "interpretation": "validated", "fallback": False, "usability_floor": None, "schema_version": "2",
            "gold_numbers_aid": [None, None], **kw}


def _all(correct: int = 11, **over) -> tuple[dict, dict]:
    ans = [c["case_id"] for c in CASES if SCORE.answerable(c)]
    auto = {c["case_id"]: _auto(correct=c["case_id"] in ans[:correct]) for c in CASES}
    merged = {c["case_id"]: SCORE.merge([_reading("S"), _reading("S")]) for c in CASES}
    for cid, a in over.items():
        auto[cid] = a
    return auto, merged


def test_verdict_precedence():
    auto, merged = _all()
    assert len([c for c in CASES if SCORE.answerable(c)]) == 11
    d = SCORE.decide(CASES, auto, merged)
    assert d["verdict"] == "PASS" and d["coverage"]["cases_saved"] == 16 and d["availability"]["correct_verified_results"] == 11
    auto8, _ = _all(correct=8)
    assert SCORE.decide(CASES, auto8, merged)["verdict"] == "PASS"
    auto7, _ = _all(correct=7)
    d7 = SCORE.decide(CASES, auto7, merged)
    assert d7["verdict"] == "INCONCLUSIVE" and len(d7["availability"]["misses"]) == 4
    missing = {k: v for k, v in auto.items() if k != "F03"}
    di = SCORE.decide(CASES, missing, merged)
    assert di["verdict"] == "INCOMPLETE" and di["coverage"]["not_saved"] == ["F03"]
    unreviewed = dict(merged, F03=SCORE.merge([_reading("S"), None]))
    assert SCORE.decide(CASES, auto, unreviewed)["verdict"] == "INCOMPLETE"
    # a demonstrated violation is FAIL even with incomplete coverage
    bad = dict(missing, F01=_auto(problems={**{k: [] for k in SCORE.CRITERIA[1:]}, "2_result_correctness": ["x"]}))
    df = SCORE.decide(CASES, bad, merged)
    assert df["verdict"] == "FAIL" and df["coverage"]["not_saved"] == ["F03"]
    assert SCORE.decide(CASES, dict(missing, R01=_auto(H5=1)), merged)["verdict"] == "FAIL"
    x = dict(merged, F02=SCORE.merge([_reading("S"), _reading("X")]))
    assert SCORE.decide(CASES, auto, x)["verdict"] == "FAIL"
    contra = dict(merged, F02=SCORE.merge([_reading("S"), _reading("S", interpretation_contradicts_answer=True)]))
    assert SCORE.decide(CASES, auto, contra)["cases"]["F02"]["outcome"] == "X"
    seen = dict(merged, F04=SCORE.merge([_reading("S"), _reading("S", unadmitted_or_observation_presented_as_maximum=True)]))
    assert SCORE.decide(CASES, auto, seen)["verdict"] == "FAIL"
    manual = dict(merged, D02=SCORE.merge([_reading("S", H4_manual=1), _reading("S")]))
    assert SCORE.decide(CASES, auto, manual)["verdict"] == "FAIL"


def test_the_stricter_reading_prevails():
    m = SCORE.merge([_reading("S", H2_manual=1), _reading("F", correct_result_shown=False)])
    assert (m["outcome"], m["H2_manual"], m["correct_result_shown"], m["disagreement"]) == ("F", 1, False, True)
    assert SCORE.merge([_reading(None), _reading("S")])["reviewed"] is False


def test_the_blind_sheet_hides_ids_and_groups(tmp_path):
    freeze = {"label": "LC-maxima-run", "slots": FRZ.plan(CASES),
              "review_blind_order": {f"A{i + 1:02d}": c["case_id"] for i, c in enumerate(reversed(CASES))}}
    SCORE.sheets(freeze, tmp_path, live=tmp_path / "none")
    blind = json.loads((tmp_path / "blind_sheet.json").read_text())
    assert len(blind["answers"]) == 16 and all("case_id" not in a and "check_group" not in a for a in blind["answers"])
    assert (tmp_path / "REVIEW_BRIEF.md").exists()
    back = SCORE.readings_of(blind, freeze)
    assert set(back) == set(BY_ID)
    dev = json.loads((tmp_path / "developer_sheet.json").read_text())
    assert [c["case_id"] for c in dev["cases"]] == [c["case_id"] for c in CASES]


# ------------------------------------------------------------------------------------------------ the runner
def _freeze(**over) -> dict:
    slots = FRZ.plan(CASES)
    runs = {r: {"cases": sum(s["run"] == r for s in slots), "case_cap_usd": 0.15,
                "run_cap_usd": round(sum(s["run"] == r for s in slots) * 0.15, 6)} for r in ("D", "F", "R")}
    src = subprocess.run(["git", "rev-parse", "HEAD:src"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return {"slots": slots, "runs": runs, "model": "gpt-5-mini", "label": "LC-maxima-run",
            "required_task_cap_usd": 10.92205, "ledger_start_usd": 8.52205, "ledger_lines": 2905,
            "ledger_sha256_prefix": "e8bcc3be401caec5", "prompt_version": "prompts/v12", "files_sha256": {},
            "src_tree": src, "code_commit": "x", **over}


class Ledger:
    def __init__(self, start: float = 8.52205):
        self.total = start

    def __call__(self) -> float:
        return round(self.total, 6)


def _loop(freeze, events=None, *, costs=None, outcomes=None, records=None, ledger=None, task_cap=10.92205, live=None):
    ledger = ledger or Ledger()
    log, envs = list(events or []), []

    def write(**kw):
        log.append(kw)

    def launch(slot, env, live_, label):
        envs.append((slot["case"], env))
        ledger.total += (costs or {}).get(slot["case"], 0.03)
        return 0, ""

    def finish(slot, rc, text, live_, label):
        return (outcomes or {}).get(slot["case"], "saved"), (records or {}).get(slot["case"], {"score": {}})

    end = RUN.run(freeze, list(events or []), write, task_cap=task_cap, launch=launch, finish=finish, spent=ledger,
                  **({"live": live} if live is not None else {}))
    return end, log, envs


def test_the_plan_runs_every_case_once_in_order_and_the_caps_sum_to_the_required_task_cap():
    slots = FRZ.plan(CASES)
    assert [s["case"] for s in slots] == [f"D0{i}" for i in range(1, 5)] + [f"F0{i}" for i in range(1, 9)] + [
        f"R0{i}" for i in range(1, 5)]
    assert [s["run"] for s in slots] == ["D"] * 4 + ["F"] * 8 + ["R"] * 4
    f = _freeze()
    assert {r: v["run_cap_usd"] for r, v in f["runs"].items()} == {"D": 0.6, "F": 1.2, "R": 0.6}
    assert round(8.52205 + sum(v["run_cap_usd"] for v in f["runs"].values()), 6) == 10.92205
    b = FRZ.e2e_bound()
    assert b["traces"] >= 10 and b["case_cap_required_usd"] <= FRZ.CASE_CAP


def test_a_complete_run_saves_every_case_with_the_frozen_model_and_caps():
    end, _, envs = _loop(_freeze())
    assert end["result"] == "complete" and end["saved"] == 16 and end["stop_reason"] is None
    case, env = envs[0]
    assert case == "D01" and env["NEM_AGENT_MODEL"] == "gpt-5-mini"
    assert float(env["NEM_AGENT_TOTAL_BUDGET_USD"]) == round(8.52205 + 0.15, 6)
    assert float(env["NEM_AGENT_SESSION_BUDGET_USD"]) == 0.15
    assert end["run_spend"] == {"D": 0.12, "F": 0.24, "R": 0.12}


def test_the_start_guard_stops_a_case_that_no_longer_fits():
    end, _, envs = _loop(_freeze(), costs={"D01": 0.5})  # D01 spends past what run D can still hold
    assert end["result"] == "incomplete" and "start guard" in end["stop_reason"] and [c for c, _ in envs] == ["D01"]
    end2, _, envs2 = _loop(_freeze(), task_cap=round(8.52205 + 0.15 + 0.06, 6))  # the task cap binds first
    assert "start guard" in end2["stop_reason"] and len(envs2) == 3


def test_a_stop_ends_the_check_and_nothing_is_retried():
    for result in ("budget_stop", "error", "missing"):
        end, _, envs = _loop(_freeze(), outcomes={"F02": result})
        assert end["result"] == "incomplete" and "F02" in end["stop_reason"] and [c for c, _ in envs][-1] == "F02"
        assert end["saved"] == 5
    end, _, envs = _loop(_freeze(), records={"D02": {"score": {"forbidden_calls": 1}}})
    assert end["safety_stop"] and [c for c, _ in envs] == ["D01", "D02"]


def test_an_interrupted_case_is_re_run_once_and_not_after_a_second_interruption(tmp_path):
    f = _freeze()
    events = [{"event": "start", "attempt": 1},
              {"event": "slot_start", "slot": 1, "run": "D", "case": "D01", "ledger_before": 8.52205},
              {"event": "slot_end", "slot": 1, "run": "D", "case": "D01", "outcome": "saved", "ledger_cost": 0.03},
              {"event": "slot_start", "slot": 2, "run": "D", "case": "D02", "ledger_before": 8.55205}]
    end, log, envs = _loop(f, events, ledger=Ledger(8.56), live=tmp_path)
    assert envs[0][0] == "D02" and end["result"] == "complete"
    kill = next(e for e in log if e.get("event") == "interrupted")
    assert kill["slot"] == 2 and kill["ledger_cost"] == round(8.56 - 8.55205, 6)
    twice = events + [{"event": "interrupted", "slot": 2, "run": "D", "ledger_cost": 0.01},
                      {"event": "start", "attempt": 2},
                      {"event": "slot_start", "slot": 2, "run": "D", "case": "D02", "ledger_before": 8.56}]
    end2, _, envs2 = _loop(f, twice, ledger=Ledger(8.57), live=tmp_path)
    assert end2["result"] == "incomplete" and "two interruptions" in end2["stop_reason"] and envs2 == []


def test_refusals(monkeypatch, tmp_path):
    f = _freeze()
    ok = {"total": 8.52205, "lines": 2905, "sha256_prefix": "e8bcc3be401caec5"}
    monkeypatch.delenv("NEM_AGENT_BUDGET_LEDGER", raising=False)  # refusal() reads no ledger: it is given one
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-key")
    monkeypatch.setattr(RUN.config, "PROMPT_VERSION", "prompts/v12")  # the frozen prompts; the code is on v13 (D26)
    assert RUN.refusal(f, 10.92205, ok, [], tmp_path) is None
    assert "at least USD 10.92205" in RUN.refusal(f, 10.9, ok, [], tmp_path)
    assert "not the frozen starting ledger" in RUN.refusal(f, 10.92205, dict(ok, lines=2906), [], tmp_path)
    monkeypatch.setenv("NEM_AGENT_MODEL", "gpt-6.1-sol")
    assert "override" in RUN.refusal(f, 10.92205, ok, [], tmp_path)
    monkeypatch.delenv("NEM_AGENT_MODEL")
    monkeypatch.delenv("OPENAI_API_KEY")
    assert "no API key" in RUN.refusal(f, 10.92205, ok, [], tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-key")
    assert "prompt version" in RUN.refusal(dict(f, prompt_version="prompts/v11"), 10.92205, ok, [], tmp_path)
    assert "src/" in RUN.refusal(dict(f, src_tree="0" * 40), 10.92205, ok, [], tmp_path)
    assert "differs from FREEZE" in RUN.refusal(dict(f, files_sha256={"eval/livecheck_maxima/score.py": "0"}),
                                               10.92205, ok, [], tmp_path)
    assert "plan" in RUN.refusal(dict(f, slots=f["slots"][:-1]), 10.92205, ok, [], tmp_path)
    (tmp_path / "LC-maxima-run").mkdir()
    (tmp_path / "LC-maxima-run" / "F01.json").write_text("{}")
    assert "does not account for" in RUN.refusal(f, 10.92205, ok, [], tmp_path)
    (tmp_path / "LC-maxima-run" / "F01.json").unlink()
    ended = [{"event": "start"}, {"event": "end", "safety_stop": False}]
    assert "has ended" in RUN.refusal(f, 10.92205, ok, ended, tmp_path)
    assert "safety stop" in RUN.refusal(f, 10.92205, ok, [{"event": "start"}, {"event": "end", "safety_stop": True}],
                                        tmp_path)
    resumed = [{"event": "start", "ledger_committed": 8.6}]
    assert "below the last recorded" in RUN.refusal(f, 10.92205, dict(ok, total=8.59), resumed, tmp_path)


# ------------------------------------------------------------------------------------------------ the freeze
@pytest.mark.skipif(FREEZE is None, reason="FREEZE.json not written yet")
def test_the_freeze_matches_the_protocol():
    assert FREEZE["code_commit"].startswith("761290d") and FREEZE["prompt_version"] == "prompts/v12"
    assert FREEZE["model"] == "gpt-5-mini" and FREEZE["label"] == "LC-maxima-run"
    assert (FREEZE["ledger_start_usd"], FREEZE["ledger_lines"], FREEZE["ledger_sha256_prefix"]) == (
        8.52205, 2905, "e8bcc3be401caec5")
    assert FREEZE["required_task_cap_usd"] == 10.92205 and FREEZE["run_caps_total_usd"] == 2.4
    assert FREEZE["slots"] == FRZ.plan(CASES)
    assert sorted(FREEZE["review_blind_order"].values()) == sorted(BY_ID)
    # the check has run (PR #68). On any later src/ (D26 onwards) its runner refuses to start, before every case too,
    # so it can never run on other code; on the frozen tree it would not refuse for that reason
    head = subprocess.run(["git", "rev-parse", "HEAD:src"], cwd=ROOT, capture_output=True, text=True,
                          check=True).stdout.strip()
    if head != FREEZE["src_tree"]:
        assert RUN.changed(FREEZE) == "the checkout's src/ is not the frozen tree"
    if subprocess.run(["git", "cat-file", "-e", f"{FREEZE['code_commit']}^{{commit}}"], cwd=ROOT,
                      capture_output=True).returncode == 0:
        src = subprocess.run(["git", "rev-parse", f"{FREEZE['code_commit']}:src"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout.strip()
        assert src == FREEZE["src_tree"]
    for rel, want in FREEZE["files_sha256"].items():
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == want, rel
    assert RUN.plan_mismatch(FREEZE) is None
