"""The end-to-end Live acceptance check of v13 request resolution (eval/livecheck_e2e_v13/PROTOCOL.md): its cases,
gold, exporter, review kit, runner, scorer and freeze, offline. Nothing here calls a model:
- all 8 cases run end to end through the SYNTHETIC fake transport. Each is driven by its question's v13 route decision
  as saved by the routing-only Live check, with a SYNTHETIC draft, or with the development comparison's saved tool calls
  and drafts;
- the runner's processes, ledger and records are injected;
- the scorer's verdict is tested on SYNTHETIC automatic fields and readings.

Scripted variants (a tampered record, an incomplete routing response, edited gold) are labelled as such."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "eval" / "livecheck_e2e_v13"
LIVE = ROOT / "artifacts" / "live"


def _load(name: str):
    """Under a name of its own: other evaluation directories have modules called `score`, `freeze` and `run_eval`."""
    spec = importlib.util.spec_from_file_location(f"lce2e_{name}", DIR / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BUILD = _load("build_cases")
EXPORT = _load("export")
KIT = _load("kit")
CASE = _load("run_case")
RUN = _load("run_eval")
SCORE = _load("score")
FRZ = _load("freeze")
CASES = json.loads((DIR / "cases.json").read_text())["cases"]
BY_ID = {c["case_id"]: c for c in CASES}
GOLD_JSON = json.loads((DIR / "GOLD.json").read_text())
GOLD = {g["case_id"]: g for g in GOLD_JSON["cases"]}
FREEZE = json.loads((DIR / "FREEZE.json").read_text()) if (DIR / "FREEZE.json").exists() else None
MAXIMA = {c["case_id"]: c for c in json.loads((ROOT / "eval/livecheck_maxima/cases.json").read_text())["cases"]}
ANSWERABLE = ["D01", "D02", "F02", "F06", "F07"]
# each question's v13 route decision, as saved by the routing-only Live check of route contract v13 (its first slot)
ROUTE_SLOT = {"D01": "01-C03", "D02": "04-C01", "F02": "03-C02", "F06": "10-C04", "F07": "09-C05", "F07N": "02-C06",
              "F08": "06-C07", "R02": "08-C10"}
DRAFT = {"status": "answered", "headline": "SYNTHETIC answer.", "summary": ["SYNTHETIC."], "document_statements": [],
         "observation_evidence_ids": [], "possible_explanations": [], "published_findings": [], "citations": [],
         "uncertainties": [], "missing_evidence": [], "forecast_mae_evidence_id": None, "numeric_claims": []}


def _route(cid: str) -> dict:
    return json.loads((LIVE / "LC-route-v13-run" / f"{ROUTE_SLOT[cid]}.json").read_text())["route"]


# ------------------------------------------------------------------------------------------------ cases and gold
def test_the_cases_are_copied_unchanged_but_for_the_added_keys():
    assert [c["case_id"] for c in CASES] == ["D01", "D02", "F02", "F06", "F07", "F07N", "F08", "R02"]
    assert {c["case_id"]: c["e2e_group"] for c in CASES} == {
        **{cid: "answerable" for cid in ANSWERABLE}, "F07N": "clarification_control", "F08": "clarification_control",
        "R02": "non_maximum_control"}
    sha = hashlib.sha256((ROOT / "eval/livecheck_maxima/cases.json").read_bytes()).hexdigest()
    for c in CASES:
        assert c["source"]["file"] == "eval/livecheck_maxima/cases.json" and c["source"]["sha256"] == sha
        if c["case_id"] != "F07N":
            assert c["source"]["case_id"] == c["case_id"] and c["source"]["changed"] == {}
            assert {k: v for k, v in c.items() if k not in ("e2e_group", "source")} == MAXIMA[c["case_id"]]


def test_f07n_is_f07_without_its_request_field_and_records_every_difference():
    n, f = BY_ID["F07N"], MAXIMA["F07"]
    assert n["source"]["case_id"] == "F07" and n["question"] == f["question"]
    assert (f["request"], n["request"]) == ({"as_of_utc": "2025-10-05T02:00:00Z"}, {})
    assert n["expected"] == MAXIMA["F08"]["expected"]  # the maxima check's must-clarify shape
    assert {k: v for k, v in n["intended"].items() if k not in ("as_of_utc", "expected_outcome")} == {
        k: v for k, v in f["intended"].items() if k not in ("as_of_utc", "expected_outcome")}
    same = {k for k in f if k not in ("case_id", "request", "expected", "intended")}
    assert all(n[k] == f[k] for k in same)
    assert set(n["source"]["changed"]) == {"case_id", "request", "expected", "intended.as_of_utc",
                                           "intended.expected_outcome"}


def test_the_gold_is_copied_unchanged_from_independently_checked_sources():
    assert BUILD.build() == (json.loads((DIR / "cases.json").read_text()), GOLD_JSON)
    mg = {c["case_id"]: c for c in json.loads((ROOT / "eval/livecheck_maxima/GOLD.json").read_text())["cases"]}
    rg = {c["config"]: c for c in json.loads((ROOT / "eval/livecheck_route_v13/GOLD.json").read_text())["cases"]}
    for cid, config in {"D01": "C03", "D02": "C01", "F02": "C02", "F06": "C04", "F07": "C05", "F07N": "C06",
                        "F08": "C07", "R02": "C10"}.items():
        g = GOLD[cid]
        assert g["routing"] == rg[config]
        if cid in ANSWERABLE:
            assert g["maxima_gold"] == mg[cid] and (g["reading"], g["result"]) == (mg[cid]["reading"], mg[cid]["result"])
        else:
            assert g["result"] is None and g["reading"] is None
    assert [GOLD[c]["result"]["status"] for c in ANSWERABLE] == ["established"] * 4 + ["not_established"]
    assert GOLD["F07"]["result"]["intervals_held"] == 8 and GOLD["F07"]["result"]["excluded_rows_by_as_of"] == 40
    assert GOLD["F07N"]["routing"]["missing"] == ["cutoff"] and GOLD["F08"]["maxima_gold"]["result"] is None
    assert GOLD["R02"]["answer"] == {k: MAXIMA["R02"]["expected"][k] for k in ("gold_run", "gold_numbers")}
    for rel, want in GOLD_JSON["sources_sha256"].items():
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == want, rel


def test_the_copy_refuses_when_the_independent_gold_check_disagrees(monkeypatch):
    """SCRIPTED: the maxima check's gold comparison reports a difference."""
    class Disagrees:
        @staticmethod
        def compare(a, b):
            return ["D01: result value 10954.2 vs 10954.3"]

    monkeypatch.setattr(BUILD, "_maxima_gold_module", lambda: Disagrees)
    with pytest.raises(SystemExit, match="disagree"):
        BUILD.build()


# ------------------------------------------------------------------------------------------------ offline end to end
def _investigate_with(monkeypatch, fake) -> None:
    """The evaluation runner's `investigate`, through ``fake``. The original is the service's, so a second case never
    wraps the first case's patch."""
    from nem_agent import service
    from nem_agent.evaluation import runner

    monkeypatch.setattr(runner, "investigate",
                        lambda req, **kw: service.investigate(req, live_client=fake, write_trace=False))


def _synthetic(cid: str):
    from tests.provider.fake_model import FakeModel

    return FakeModel(_route(cid), [[]], lambda kw: copy.deepcopy(DRAFT))


def _saved(cid: str, saved: str):
    """The development comparison's saved tool calls and drafts (`saved`), under the v13 route decision of `cid`."""
    from tests.provider.fake_model import FakeModel

    rec = json.loads((LIVE / "MC-dev-e2e-mini" / f"{saved}.json").read_text())
    trace = json.loads((LIVE / "MC-dev-e2e-mini" / "traces" / f"{rec['score']['trace_id']}.json").read_text())["events"]
    draft = rec["drafts"]["synthesis:draft"]
    patch = next((e.get("patch") for e in trace if e["name"] == "repair:scoped"), None)
    repaired = rec["drafts"].get("repair:draft")

    def repair(kw):
        return copy.deepcopy(patch if kw["text"]["format"]["name"] == "RepairPatch" else repaired)

    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    return FakeModel(_route(cid), [calls], lambda kw: copy.deepcopy(draft), repair if (patch or repaired) else None)


def _run(mp, out: Path, cid: str, fake) -> tuple[str, dict, dict]:
    _investigate_with(mp, fake)
    line = CASE.run_one(BY_ID[cid], out)
    rec = json.loads((out / f"{cid}.json").read_text())
    trace = json.loads((out / "traces" / f"{rec['trace_id']}.json").read_text())
    return line, rec, trace


@pytest.fixture(scope="module")
def store_sel():
    from nem_agent.service import _shared

    return _shared()


@pytest.fixture(scope="module")
def offline(tmp_path_factory, store_sel):
    """All 8 cases once, end to end through the SYNTHETIC fake transport (v13 route decisions, SYNTHETIC draft)."""
    from nem_agent import budget

    assert os.environ.get("NEM_AGENT_BUDGET_LEDGER") and "live_budget" not in str(budget.ledger_path())
    out = tmp_path_factory.mktemp("e2e")
    got = {}
    with pytest.MonkeyPatch.context() as mp:
        for c in CASES:
            got[c["case_id"]] = _run(mp, out, c["case_id"], _synthetic(c["case_id"]))
    return got


def _auto(cid: str, rec: dict, trace: dict, store_sel) -> dict:
    store, sel = store_sel
    return SCORE.automatic(BY_ID[cid], rec, trace, GOLD[cid], store=store, selection=sel)


@pytest.mark.parametrize("cid", ANSWERABLE)
def test_offline_the_answerable_cases_compute_their_gold_results_verified(offline, store_sel, cid, real_store):
    line, rec, trace = offline[cid]
    a = _auto(cid, rec, trace, store_sel)
    assert "format=2 answer=1" in line and rec["exporter"] == EXPORT.EXPORTER
    assert a["correct_result_produced"] and a["miss_cause"] is None and a["auto_x"] == []
    assert not any(a["problems"].values()), a["problems"]
    (r,) = rec["report"]["results"]
    assert r["server_verification"]["outcome"] == "verified" and r["result"]["status"] == GOLD[cid]["result"]["status"]
    assert rec["resolution"]["status"] == "ok" and rec["evidence"] and rec["route"]["requested"]
    assert a["usability_floor"] == "F" and a["fallback"]  # the SYNTHETIC draft cites nothing, so it falls back
    assert KIT.missing(KIT.evidence_view(rec, store_sel[0])) == []


@pytest.mark.parametrize("cid", ["F07N", "F08"])
def test_offline_the_clarification_controls_stop_before_any_tool(offline, store_sel, cid, real_store):
    line, rec, trace = offline[cid]
    a = _auto(cid, rec, trace, store_sel)
    assert "status=needs_clarification format=1 answer=0" in line and "tools=0" in line
    assert rec["tools"] == [] and rec["report"]["results"] == [] and rec["report"]["observations"] == []
    assert a["model_calls"] == 1 and not any(a["problems"].values()), a["problems"]
    assert a["control"]["demonstrated"], a["control"]
    inter = a["control"]["intermediate"]
    if cid == "F07N":  # partial resolution, as C06: the maximum is resolved, the cutoff cannot be read
        assert inter["maximum"]["status"] == "bound" and inter["cutoff"]["status"] == "unresolved"
    else:
        assert inter["maximum"] == {"status": "unresolved", "missing": ["measure"],
                                    "detected_by": inter["maximum"]["detected_by"]}


def test_offline_the_non_maximum_control_binds_no_maximum(offline, store_sel, real_store):
    _, rec, trace = offline["R02"]
    a = _auto("R02", rec, trace, store_sel)
    assert a["problems"]["8_non_maximum_control"] == [] and rec["report"]["schema_version"] == "1"
    assert a["control"]["intermediate"]["maximum"]["status"] == "absent"
    assert a["control"]["intermediate"]["forecast_run"]["status"] == "bound"
    # with no tool data the SYNTHETIC run abstains, so the control is contained but not demonstrated
    assert rec["report"]["status"] == "abstained" and not a["control"]["demonstrated"]


def test_offline_every_record_round_trips_and_keeps_its_evidence(offline, store_sel, real_store):
    store, sel = store_sel
    for cid, (_, rec, trace) in offline.items():
        assert EXPORT.integrity_problems(rec, trace, store=store, selection=sel) == [], cid
        assert EXPORT.evidence_problems(rec) == [], cid
        assert rec["resolution"] is not None and "requests" in rec["resolution"]


def test_saved_drafts_give_a_validated_interpretation_a_fallback_and_the_control_answer(tmp_path, store_sel,
                                                                                        real_store, monkeypatch):
    """The development comparison's saved tool calls and drafts under the v13 route decisions: K11 (D02) validates,
    K09 (D01) falls back with the correct computed answer, K06 (R02) answers format 1 with its gold run."""
    store, _ = store_sel
    _, d02, t02 = _run(monkeypatch, tmp_path, "D02", _saved("D02", "K11"))
    a = _auto("D02", d02, t02, store_sel)
    assert a["interpretation"] == "validated" and a["usability_floor"] is None and a["correct_result_produced"]
    _, d01, t01 = _run(monkeypatch, tmp_path, "D01", _saved("D01", "K09"))
    b = _auto("D01", d01, t01, store_sel)
    assert b["fallback"] and b["usability_floor"] == "F" and b["correct_result_produced"] and b["auto_x"] == []
    _, r02, tr = _run(monkeypatch, tmp_path, "R02", _saved("R02", "K06"))
    c = _auto("R02", r02, tr, store_sel)
    assert c["control"]["demonstrated"] and not any(c["problems"].values()), c["problems"]
    for rec in (d02, d01, r02):
        view = KIT.evidence_view(rec, store)
        assert KIT.missing(view) == [] and view["observations"]
        for o in view["observations"]:
            assert o["label"] and o["definition"]["source"] and o["source"]["evidence_id"]
            assert o["availability"]["derived"] or o["availability"]["available_at_utc"]
    derived = [o for o in KIT.evidence_view(r02, store)["observations"] if o["availability"]["derived"]]
    assert derived and all(o["definition"]["derivation"] for o in derived)  # e.g. the MAE, with its derivation
    assert KIT.evidence_view(d02, store)["cited_passages"][0]["text"]


# ------------------------------------------------------------------------------------------------ the review kit
def test_the_kit_gives_f07s_availability_for_every_half_hour(offline, store_sel, real_store):
    view = KIT.evidence_view(offline["F07"][1], store_sel[0])
    (r,) = view["computed_results"]
    av = r["availability"]
    assert (r["status"], r["value"], r["value_is"]) == ("not_established", 5693.0, "highest held, not a maximum")
    assert av["cutoff_utc"] == "2025-10-05T02:00:00Z" and len(av["intervals"]) == 48
    assert (av["intervals_eligible_at_cutoff"], av["intervals_without_eligible_row"], av["rows_excluded_by_cutoff"]) == (
        8, 40, 40)
    assert all(x["eligible_at_cutoff"] == (x["available_at_utc"] <= "2025-10-05T02:00:00Z") for x in av["intervals"])
    assert r["source_rows"][0]["available_at_utc"] and r["definition"]["aemo_definition"]
    obs = view["observations"][0]
    assert obs["availability"]["available_by_cutoff"] is True and obs["label"] and obs["source"]["source_rows"]


def test_the_kit_refuses_to_leave_out_evidence_and_the_blind_sheet_hides_ids(offline, store_sel, tmp_path, real_store):
    """SCRIPTED: an evidence item dropped from a record, and a label blanked."""
    store, _ = store_sel
    recs = {cid: v[1] for cid, v in offline.items()}
    order = {f"A{i + 1:02d}": c["case_id"] for i, c in enumerate(reversed(CASES))}
    dev, blind = KIT.build(CASES, GOLD, recs, order, store)
    assert [c["case_id"] for c in dev["cases"]] == [c["case_id"] for c in CASES]
    text = json.dumps(blind)
    assert len(blind["answers"]) == 8 and all("case_id" not in a and "e2e_group" not in a for a in blind["answers"])
    assert not any(f"GOLD.json {cid}" in text or f"cases.json {cid}" in text for cid in BY_ID)
    dropped = copy.deepcopy(recs)
    dropped["F07"]["evidence"] = {}
    with pytest.raises(KIT.IncompleteKit, match=r"F07: observation .* not in the record"):
        KIT.build(CASES, GOLD, dropped, order, store)
    blank = copy.deepcopy(recs)
    next(iter(blank["D02"]["evidence"].values()))["label"] = ""
    blank["D02"]["report"]["observations"][0]["label"] = ""
    with pytest.raises(KIT.IncompleteKit, match="no label"):
        KIT.build(CASES, GOLD, blank, order, store)


def test_score_writes_both_sheets_and_the_brief(offline, tmp_path, monkeypatch, real_store):
    live = tmp_path / "live"
    label = live / "LC-e2e-v13-run"
    (label / "traces").mkdir(parents=True)
    (live / "LC-e2e-v13").mkdir(parents=True)
    log = []
    for cid, (_, rec, trace) in offline.items():
        (label / f"{cid}.json").write_text(json.dumps(rec))
        (label / "traces" / f"{rec['trace_id']}.json").write_text(json.dumps(trace))
        log.append({"event": "slot_end", "case": cid, "outcome": "saved"})
    (live / "LC-e2e-v13" / "run_log.jsonl").write_text("\n".join(json.dumps(e) for e in log) + "\n")
    freeze = {"label": "LC-e2e-v13-run", "slots": FRZ.plan(CASES),
              "review_blind_order": {f"A{i + 1:02d}": c["case_id"] for i, c in enumerate(CASES)}}
    SCORE.sheets(freeze, tmp_path / "kit", live)
    assert (tmp_path / "kit" / "REVIEW_BRIEF.md").read_text() == (DIR / "REVIEW_BRIEF.md").read_text()
    blind = json.loads((tmp_path / "kit" / "blind_sheet.json").read_text())
    assert set(SCORE.readings_of(blind, freeze)) == set(BY_ID)
    m = SCORE.measures(freeze, live)
    assert m["coverage"] == {"saved": 8, "of": 8, "not_saved": []}


# ------------------------------------------------------------------------------------------------ clarification 1
def test_x_is_never_lowered_to_f():
    assert SCORE.final_outcome("X", [], "F") == ("X", None)
    assert SCORE.final_outcome("X", [], "C") == ("X", None)
    out, note = SCORE.final_outcome("S", [], "F")
    assert out == "F" and "classified F" in note
    out, note = SCORE.final_outcome("F", ["incorrect computed result shown: value"], "F")
    assert out == "X" and "automatic X" in note
    assert SCORE.final_outcome("U", [], "F")[0] == "F" and SCORE.final_outcome("F", [], "C") == ("F", None)


def test_an_incorrect_fallback_is_x_and_fails(offline, store_sel, real_store):
    """SCRIPTED: D01's fallback shows its computed result, scored against gold edited by one MW, so what it shows is
    incorrect. Reviewers who read F do not lower it."""
    _, rec, trace = offline["D01"]
    store, sel = store_sel
    g = copy.deepcopy(GOLD["D01"])
    g["result"]["value"] += 1
    a = SCORE.automatic(BY_ID["D01"], rec, trace, g, store=store, selection=sel)
    assert a["fallback"] and a["auto_x"] and a["problems"]["2_result_correctness"]
    d = SCORE.decide([BY_ID["D01"]], {"D01": a}, {"D01": SCORE.merge([_reading("F"), _reading("F")])})
    assert d["verdict"] == "FAIL" and d["report_b_interpretation_and_fallback"]["usability"]["D01"] == "X"
    assert any("incorrect shown (X)" in v for v in d["criteria"]["1_safety"]["violations"])


def test_a_correct_fallback_stays_f_and_still_counts_as_available():
    auto, merged = _all()
    auto["D01"] = _a(fallback=True, usability_floor="F", interpretation="withheld: it failed validation")
    d = SCORE.decide(CASES, auto, merged)
    assert d["verdict"] == "PASS" and d["report_b_interpretation_and_fallback"]["usability"]["D01"] == "F"
    assert d["report_a_computed_results"]["availability"]["correct_verified_results"] == 5
    assert any(o.startswith("D01: reviewed S, classified F") for o in d["report_b_interpretation_and_fallback"]["overrides"])
    x = dict(merged, D01=SCORE.merge([_reading("S"), _reading("X")]))
    dx = SCORE.decide(CASES, auto, x)
    assert dx["verdict"] == "FAIL" and dx["report_b_interpretation_and_fallback"]["usability"]["D01"] == "X"


# ------------------------------------------------------------------------------------------------ clarification 2
def test_partial_resolution_followed_by_the_required_clarification_is_accepted(offline, store_sel, real_store):
    _, rec, trace = offline["F07N"]
    a = _auto("F07N", rec, trace, store_sel)
    assert a["control"]["intermediate"]["maximum"]["status"] == "bound"  # an intermediate field, not executed
    assert not any(a["problems"].values()) and a["control"]["demonstrated"]
    auto, merged = _all()
    auto["F07N"] = a
    assert SCORE.decide(CASES, auto, merged)["verdict"] == "PASS"


def test_a_control_that_executes_fails(offline, real_store):
    """SCRIPTED: F08's record given D01's tool records, computed result, answer and observations."""
    _, rec, _ = offline["F08"]
    _, d01, d01_trace = offline["D01"]
    bad = copy.deepcopy(rec)
    bad["report"]["status"] = "answered_with_caveats"
    bad["tools"] = d01["tools"]
    for k in ("results", "answer", "observations", "numeric_claims"):
        bad["report"][k] = d01["report"][k]
    probs, _ = EXPORT.control_problems(bad, d01_trace)
    assert any("proceeded" in p for p in probs) and any("tool(s) ran" in p for p in probs)
    assert any("analytical calculation" in p for p in probs) and any("computed answer" in p for p in probs)
    assert any("values were shown" in p for p in probs)
    auto, merged = _all()
    auto["F08"] = _a(control={"demonstrated": False}, problems={**_none(), "7_clarification_controls": probs})
    assert SCORE.decide(CASES, auto, merged)["verdict"] == "FAIL"


def test_a_control_sent_back_after_an_incomplete_routing_response_is_contained_not_demonstrated(tmp_path, monkeypatch,
                                                                                                store_sel, real_store):
    """SCRIPTED: the routing response stops at its output cap and is rejected before parsing."""
    from tests.provider.fake_model import FakeModel

    class Truncated(FakeModel):
        def create(self, **kw: Any) -> dict[str, Any]:
            self.requests.append(kw)
            return {"id": "resp_x", "status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
                    "output": [{"type": "message", "role": "assistant",
                                "content": [{"type": "output_text", "text": '{"intent": "market' + " \r" * 400}]}],
                    "usage": {"input_tokens": 1513, "output_tokens": 2000,
                              "output_tokens_details": {"reasoning_tokens": 832}}}

    _, rec, trace = _run(monkeypatch, tmp_path, "F07N", Truncated({}, [], lambda kw: {}))
    a = _auto("F07N", rec, trace, store_sel)
    assert a["problems"]["7_clarification_controls"] == [] and not a["control"]["demonstrated"]
    assert "incomplete" in a["control"]["detail"]
    auto, merged = _all()
    auto["F07N"] = a
    d = SCORE.decide(CASES, auto, merged)
    assert d["verdict"] == "INCONCLUSIVE" and d["controls_not_demonstrated"] == ["F07N"]
    # the same on an answerable case is an attributed availability miss
    _, rec2, _ = _run(monkeypatch, tmp_path, "D02", Truncated({}, [], lambda kw: {}))
    assert SCORE.miss_cause(rec2, False) == "a response that did not finish (routing)"


def test_the_non_maximum_control_violations(offline, real_store):
    """SCRIPTED: R02's record with a maximum bound, a wrong run, and its run never bound."""
    _, rec, trace = offline["R02"]
    g = GOLD["R02"]
    assert EXPORT.non_maximum_problems(rec, trace, g) == []
    bad = copy.deepcopy(rec)
    bad["resolution"]["requests"]["maximum"]["status"] = "bound"
    assert any("maximum was bound" in p for p in EXPORT.non_maximum_problems(bad, trace, g))
    bad = copy.deepcopy(rec)
    bad["resolution"]["requests"]["forecast_run"]["half_hour_utc"] = ["2026-08-19T22:30:00Z", "2026-08-19T23:00:00Z"]
    assert any("wrong binding: run" in p for p in EXPORT.non_maximum_problems(bad, trace, g))
    bad = copy.deepcopy(rec)
    bad["resolution"]["requests"]["forecast_run"]["status"] = "absent"
    assert any("missed request" in p for p in EXPORT.non_maximum_problems(bad, trace, g))


# ------------------------------------------------------------------------------------------------ the verdict
def _reading(outcome: str | None, **kw) -> dict:
    return {"outcome": outcome, "H2_manual": 0, "H4_manual": 0, "correct_result_shown": True,
            "unadmitted_or_observation_presented_as_maximum": False, "interpretation_contradicts_answer": False,
            "gold_items": [], "interpretation_note": "", **kw}


def _none() -> dict:
    return {k: [] for k in SCORE.CRITERIA[1:]}


def _a(correct: bool = True, **kw) -> dict:
    return {"H1": 0, "H2_auto": 0, "H3": 0, "H4_auto": 0, "H5": 0, "problems": _none(), "auto_x": [],
            "correct_result_produced": correct, "miss_cause": None if correct else "sent back by routing",
            "interpretation": "validated", "fallback": False, "repair_attempted": False, "rule_firings": [],
            "usability_floor": None, "control": {}, **kw}


def _all(correct: int = 5) -> tuple[dict, dict]:
    auto = {}
    for c in CASES:
        cid = c["case_id"]
        if c["e2e_group"] == "answerable":
            auto[cid] = _a(correct=cid in ANSWERABLE[:correct])
        else:
            auto[cid] = _a(correct=False, interpretation=None, control={"demonstrated": True},
                           usability_floor="C" if c["e2e_group"] == "clarification_control" else None)
    merged = {c["case_id"]: SCORE.merge([_reading("S" if c["e2e_group"] != "clarification_control" else "C")] * 2)
              for c in CASES}
    return auto, merged


def test_verdict_precedence():
    auto, merged = _all()
    d = SCORE.decide(CASES, auto, merged)
    assert d["verdict"] == "PASS" and d["coverage"]["cases_saved"] == 8 and d["verdict_of"] == SCORE.VERDICT_OF
    assert d["report_a_computed_results"]["availability"] == {"correct_verified_results": 5, "of": 5, "bar": 5,
                                                              "misses": {}}
    auto4, _ = _all(correct=4)
    d4 = SCORE.decide(CASES, auto4, merged)
    assert d4["verdict"] == "INCONCLUSIVE" and d4["report_a_computed_results"]["availability"]["misses"] == {
        "F07": "sent back by routing"}
    undemo = dict(auto, R02=_a(correct=False, interpretation=None, control={"demonstrated": False}))
    assert SCORE.decide(CASES, undemo, merged)["verdict"] == "INCONCLUSIVE"
    missing = {k: v for k, v in auto.items() if k != "F06"}
    di = SCORE.decide(CASES, missing, merged)
    assert di["verdict"] == "INCOMPLETE" and di["coverage"]["not_saved"] == ["F06"]
    unreviewed = dict(merged, F06=SCORE.merge([_reading("S"), None]))
    assert SCORE.decide(CASES, auto, unreviewed)["verdict"] == "INCOMPLETE"
    # a demonstrated violation is FAIL even with incomplete coverage
    bad = dict(missing, F02=_a(problems={**_none(), "2_result_correctness": ["x"]}))
    df = SCORE.decide(CASES, bad, merged)
    assert df["verdict"] == "FAIL" and df["coverage"]["not_saved"] == ["F06"]
    for crit in SCORE.CRITERIA[1:]:
        one = dict(auto, D02=_a(problems={**_none(), crit: ["x"]}))
        assert SCORE.decide(CASES, one, merged)["verdict"] == "FAIL", crit
    assert SCORE.decide(CASES, dict(auto, R02=_a(H3=1, control={"demonstrated": True})), merged)["verdict"] == "FAIL"


def test_usefulness_is_reported_not_gated_but_contradictions_x_and_h_are():
    auto, merged = _all()
    poor = dict(merged, D02=SCORE.merge([_reading("S", interpretation_note="not useful: vague and repetitive"),
                                         _reading("S", interpretation_note="unhelpful")]))
    d = SCORE.decide(CASES, auto, poor)
    assert d["verdict"] == "PASS"
    assert d["report_b_interpretation_and_fallback"]["interpretation"]["D02"]["notes_usefulness_not_gated"] == [
        "not useful: vague and repetitive", "unhelpful"]
    contra = dict(merged, D02=SCORE.merge([_reading("S"), _reading("S", interpretation_contradicts_answer=True)]))
    dc = SCORE.decide(CASES, auto, contra)
    assert dc["verdict"] == "FAIL" and dc["cases"]["D02"]["outcome"] == "X"
    seen = dict(merged, F02=SCORE.merge([_reading("S"), _reading("S", unadmitted_or_observation_presented_as_maximum=True)]))
    ds = SCORE.decide(CASES, auto, seen)
    assert ds["verdict"] == "FAIL" and ds["criteria"]["3_unadmitted_results"]["violations"]
    assert SCORE.decide(CASES, auto, dict(merged, F06=SCORE.merge([_reading("S", H2_manual=1), _reading("S")])))[
        "verdict"] == "FAIL"
    assert SCORE.decide(CASES, auto, dict(merged, F07=SCORE.merge([_reading("S"), _reading("X")])))["verdict"] == "FAIL"


def test_the_stricter_reading_prevails():
    m = SCORE.merge([_reading("S", H2_manual=1), _reading("F", correct_result_shown=False)])
    assert (m["outcome"], m["H2_manual"], m["correct_result_shown"], m["disagreement"]) == ("F", 1, False, True)
    assert SCORE.merge([_reading(None), _reading("S")])["reviewed"] is False


# ------------------------------------------------------------------------------------------------ the runner
def _freeze(**over) -> dict:
    slots = FRZ.plan(CASES)
    src = subprocess.run(["git", "rev-parse", "HEAD:src"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return {"slots": slots, "runs": {"E": {"cases": 8, "case_cap_usd": 0.15, "run_cap_usd": 1.2}},
            "model": "gpt-5-mini", "label": "LC-e2e-v13-run", "required_task_cap_usd": 10.168449,
            "ledger_start_usd": 8.968449, "ledger_lines": 3087, "ledger_sha256_prefix": "99ea30e92377eddc",
            "prompt_version": "prompts/v13", "files_sha256": {}, "src_tree": src, "code_commit": "x", **over}


class Ledger:
    def __init__(self, start: float = 8.968449):
        self.total = start

    def __call__(self) -> float:
        return round(self.total, 6)


def _loop(freeze, events=None, *, costs=None, outcomes=None, records=None, ledger=None, task_cap=10.168449, live=None):
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


def test_the_plan_runs_every_case_once_in_one_run_and_the_caps_sum_to_the_required_task_cap():
    import random

    slots = FRZ.plan(CASES, random.Random(7))
    assert sorted(s["case"] for s in slots) == sorted(BY_ID) and {s["run"] for s in slots} == {"E"}
    assert [s["slot"] for s in slots] == list(range(1, 9)) and RUN.plan_mismatch(_freeze(slots=slots)) is None
    assert round(8.968449 + 8 * FRZ.CASE_CAP, 6) == 10.168449
    b = FRZ.e2e_bound()
    assert b["traces"] >= 20 and b["case_cap_required_usd"] <= FRZ.CASE_CAP


def test_a_complete_run_saves_every_case_with_the_frozen_model_and_caps():
    end, _, envs = _loop(_freeze())
    assert end["result"] == "complete" and end["saved"] == 8 and end["stop_reason"] is None
    case, env = envs[0]
    assert case == "D01" and env["NEM_AGENT_MODEL"] == "gpt-5-mini"
    assert float(env["NEM_AGENT_TOTAL_BUDGET_USD"]) == round(8.968449 + 0.15, 6)
    assert float(env["NEM_AGENT_SESSION_BUDGET_USD"]) == 0.15
    assert end["run_spend"] == {"E": 0.24}


def test_the_start_guard_stops_a_case_that_no_longer_fits():
    end, _, envs = _loop(_freeze(), costs={"D01": 1.1})  # D01 spends past what the run can still hold
    assert end["result"] == "incomplete" and "start guard" in end["stop_reason"] and [c for c, _ in envs] == ["D01"]
    end2, _, envs2 = _loop(_freeze(), task_cap=round(8.968449 + 0.15 + 0.06, 6))  # the task cap binds first
    assert "start guard" in end2["stop_reason"] and len(envs2) == 3


def test_a_stop_ends_the_check_and_nothing_is_retried():
    for result in ("budget_stop", "error", "missing"):
        end, _, envs = _loop(_freeze(), outcomes={"F06": result})
        assert end["result"] == "incomplete" and "F06" in end["stop_reason"] and [c for c, _ in envs][-1] == "F06"
        assert end["saved"] == 3
    end, _, envs = _loop(_freeze(), records={"D02": {"score": {"forbidden_calls": 1}}})
    assert end["safety_stop"] and [c for c, _ in envs] == ["D01", "D02"]


def test_an_interrupted_case_is_re_run_once_and_not_after_a_second_interruption(tmp_path):
    f = _freeze()
    events = [{"event": "start", "attempt": 1},
              {"event": "slot_start", "slot": 1, "run": "E", "case": "D01", "ledger_before": 8.968449},
              {"event": "slot_end", "slot": 1, "run": "E", "case": "D01", "outcome": "saved", "ledger_cost": 0.03},
              {"event": "slot_start", "slot": 2, "run": "E", "case": "D02", "ledger_before": 8.998449}]
    end, log, envs = _loop(f, events, ledger=Ledger(9.01), live=tmp_path)
    assert envs[0][0] == "D02" and end["result"] == "complete"
    kill = next(e for e in log if e.get("event") == "interrupted")
    assert kill["slot"] == 2 and kill["ledger_cost"] == round(9.01 - 8.998449, 6)
    assert end["run_spend"]["E"] == round(0.03 + kill["ledger_cost"] + 0.03 * 7, 6)  # the interrupted cost counted
    twice = events + [{"event": "interrupted", "slot": 2, "run": "E", "ledger_cost": 0.01},
                      {"event": "start", "attempt": 2},
                      {"event": "slot_start", "slot": 2, "run": "E", "case": "D02", "ledger_before": 9.01}]
    end2, _, envs2 = _loop(f, twice, ledger=Ledger(9.02), live=tmp_path)
    assert end2["result"] == "incomplete" and "two interruptions" in end2["stop_reason"] and envs2 == []


def test_refusals(monkeypatch, tmp_path):
    f = _freeze()
    ok = {"total": 8.968449, "lines": 3087, "sha256_prefix": "99ea30e92377eddc"}
    monkeypatch.delenv("NEM_AGENT_BUDGET_LEDGER", raising=False)  # refusal() reads no ledger: it is given one
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-key")
    assert RUN.refusal(f, 10.168449, ok, [], tmp_path) is None
    assert "at least USD 10.168449" in RUN.refusal(f, 10.16, ok, [], tmp_path)
    assert "not the frozen starting ledger" in RUN.refusal(f, 10.168449, dict(ok, lines=3088), [], tmp_path)
    monkeypatch.setenv("NEM_AGENT_MODEL", "gpt-6.1-sol")
    assert "override" in RUN.refusal(f, 10.168449, ok, [], tmp_path)
    monkeypatch.delenv("NEM_AGENT_MODEL")
    monkeypatch.delenv("OPENAI_API_KEY")
    assert "no API key" in RUN.refusal(f, 10.168449, ok, [], tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-key")
    assert "prompt version" in RUN.refusal(dict(f, prompt_version="prompts/v12"), 10.168449, ok, [], tmp_path)
    assert "src/" in RUN.refusal(dict(f, src_tree="0" * 40), 10.168449, ok, [], tmp_path)
    assert "differs from FREEZE" in RUN.refusal(dict(f, files_sha256={"eval/livecheck_e2e_v13/score.py": "0"}),
                                               10.168449, ok, [], tmp_path)
    assert "plan" in RUN.refusal(dict(f, slots=f["slots"][:-1]), 10.168449, ok, [], tmp_path)
    (tmp_path / "LC-e2e-v13-run").mkdir()
    (tmp_path / "LC-e2e-v13-run" / "F02.json").write_text("{}")
    assert "does not account for" in RUN.refusal(f, 10.168449, ok, [], tmp_path)
    (tmp_path / "LC-e2e-v13-run" / "F02.json").unlink()
    ended = [{"event": "start"}, {"event": "end", "safety_stop": False}]
    assert "has ended" in RUN.refusal(f, 10.168449, ok, ended, tmp_path)
    assert "safety stop" in RUN.refusal(f, 10.168449, ok, [{"event": "start"}, {"event": "end", "safety_stop": True}],
                                        tmp_path)
    resumed = [{"event": "start", "ledger_committed": 9.0}]
    assert "below the last recorded" in RUN.refusal(f, 10.168449, dict(ok, total=8.99), resumed, tmp_path)


def test_the_runner_is_the_maxima_runner_but_for_its_names_and_docstring():
    """A frozen copy: the maxima check's runner is not used or changed here."""
    def code(text: str) -> str:
        return text.split('"""', 2)[2]  # without the module docstring

    theirs = code((ROOT / "eval/livecheck_maxima/run_eval.py").read_text())
    for a, b in (("LC-maxima", "LC-e2e-v13"), ("LC_maxima", "LC_e2e_v13"), ("livecheck_maxima", "livecheck_e2e_v13")):
        theirs = theirs.replace(a, b)
    assert code((DIR / "run_eval.py").read_text()) == theirs


# ------------------------------------------------------------------------------------------------ the freeze
@pytest.mark.skipif(FREEZE is None, reason="FREEZE.json not written yet")
def test_the_freeze_matches_the_protocol():
    assert FREEZE["code_commit"].startswith("a648269") and FREEZE["prompt_version"] == "prompts/v13"
    assert FREEZE["model"] == "gpt-5-mini" and FREEZE["label"] == "LC-e2e-v13-run"
    assert (FREEZE["ledger_start_usd"], FREEZE["ledger_lines"], FREEZE["ledger_sha256_prefix"]) == (
        8.968449, 3087, "99ea30e92377eddc")
    assert FREEZE["required_task_cap_usd"] == 10.168449 and FREEZE["run_caps_total_usd"] == 1.2
    assert FREEZE["runs"] == {"E": {"cases": 8, "case_cap_usd": 0.15, "run_cap_usd": 1.2}}
    assert sorted(s["case"] for s in FREEZE["slots"]) == sorted(BY_ID)
    assert [s["slot"] for s in FREEZE["slots"]] == list(range(1, 9)) and {s["run"] for s in FREEZE["slots"]} == {"E"}
    assert sorted(FREEZE["review_blind_order"].values()) == sorted(BY_ID)
    assert FREEZE["e2e_bound"]["case_cap_required_usd"] <= 0.15
    src = subprocess.run(["git", "rev-parse", f"{FREEZE['code_commit']}:src"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout.strip()
    assert src == FREEZE["src_tree"]
    head = subprocess.run(["git", "rev-parse", "HEAD:src"], cwd=ROOT, capture_output=True, text=True,
                          check=True).stdout.strip()
    if head != FREEZE["src_tree"]:  # on any later src/ its runner refuses to start
        assert RUN.changed(FREEZE) == "the checkout's src/ is not the frozen tree"
    for rel, want in FREEZE["files_sha256"].items():
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == want, rel
    assert set(FREEZE["files_sha256"]) >= {f"eval/livecheck_e2e_v13/{f}" for f in FRZ.FILES} | set(FRZ.READ)
    assert RUN.plan_mismatch(FREEZE) is None
