"""Offline verification of the held-out v5 and regression protocol (eval/holdout_v5), before any paid call.

- **Runner:**
  - the per-case, run and approved task caps;
  - the start guard;
  - the stops (budget stop, API error, missing record, H1 safety failure, frozen material changed);
  - the interruption rule: re-run the case in flight once, INCOMPLETE at a second kill;
  - its refusals.
- **Scorer:** H1–H5 and Q1–Q3 from saved records, the bars, and the L3 decision. On v4's saved Live records it
  reproduces v4's recorded criteria.
- **Per-case process:** the standard record, plus the parts of the shown answer it omits.

The fake transport is SYNTHETIC (no network, no key), and the ledger is a per-test scratch file (conftest). Scripted
runs are not a measure of Live behaviour.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

REPO = Path(__file__).resolve().parents[2]
HERE = REPO / "eval" / "holdout_v5"
LIVE = REPO / "artifacts" / "live"
START = 4.760384  # the ledger total at the freeze


def _load(name: str, path: Path) -> Any:
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RUN = _load("v5_run_eval", HERE / "run_eval.py")
SCORE = _load("v5_score", HERE / "score.py")
FREEZE: dict[str, Any] = json.loads((HERE / "FREEZE.json").read_text()) if (HERE / "FREEZE.json").exists() else {}
IDS = [f"Y{i:02d}" for i in range(1, 21)]
PLAN = {"label": "L3-holdout-v5", "run_cap_usd": 1.0, "cases": [[c, "eval/holdout_v5/cases.json"] for c in IDS]}


# ------------------------------------------------------------------------------------------------ a simulated run
class World:
    """A ledger and a fake case process: each launch spends the case's cost and leaves the files a real one would."""

    def __init__(self, out: Path, costs: dict[str, float], results: dict[str, str] | None = None,
                 safety: dict[str, dict[str, int]] | None = None, ledger: float = START) -> None:
        self.out, self.costs, self.results, self.safety = out, costs, results or {}, safety or {}
        self.ledger = ledger
        self.launched: list[tuple[str, float]] = []

    def spent(self) -> float:
        return round(self.ledger, 6)

    def launch(self, cid: str, cases_file: str, env: dict[str, str], out: Path) -> tuple[int, str]:
        cap = float(env["NEM_AGENT_TOTAL_BUDGET_USD"])
        assert env["NEM_AGENT_MODEL"] == "gpt-5-mini"
        self.launched.append((cid, round(cap - self.ledger, 6)))
        self.ledger += min(self.costs.get(cid, 0.034), cap - self.ledger)  # the ledger never lets a case pass its cap
        kind = self.results.get(cid, "saved")
        score = {"trace_id": None, "case_note_files_written": 0, "forbidden_calls": 0, **self.safety.get(cid, {})}
        text = f"[{cid}] status=answered"
        if kind == "stdout_stop":
            text = f"[{cid}] STOPPED: task budget {cap:.2f} USD: ..."
        elif kind == "error":
            text = f"[{cid}] ERROR APITimeoutError: Request timed out."
            (out / f"{cid}.error.json").write_text("{}")
        elif kind in ("trace_stop", "trace_error"):
            score["trace_id"] = f"tr-{cid}"
            (out / "traces").mkdir(exist_ok=True)
            ev = ({"kind": "model", "name": "budget_exceeded", "reason": f"task budget {cap:.2f} USD: ..."}
                  if kind == "trace_stop" else {"kind": "model", "name": "synthesis:error", "error": "APITimeoutError"})
            (out / "traces" / f"tr-{cid}.json").write_text(json.dumps({"events": [ev]}))
        if kind in ("saved", "trace_stop", "trace_error"):
            (out / f"{cid}.json").write_text(json.dumps({"score": score}))
        (out / f"{cid}.stdout.txt").write_text(text)
        return 0, text


def _run(tmp: Path, world: World | None = None, *, events: list[dict[str, Any]] | None = None, plan=PLAN,
         task_cap: float = 6.560384, moved_before: str | None = None, **kw: Any):
    world = world or World(tmp, {}, **kw)
    log: list[dict[str, Any]] = list(events or [])
    new: list[dict[str, Any]] = []

    def write(**e: Any) -> None:
        log.append(e)
        new.append(e)

    def frozen() -> str | None:
        nxt = next((c for c, _ in plan["cases"] if not (tmp / f"{c}.json").exists()), None)
        return "a file" if moved_before and nxt == moved_before else None

    end = RUN.run(plan, list(events or []), write, model="gpt-5-mini", per_case=0.15, task_cap=task_cap, out=tmp,
                  launch=world.launch, spent=world.spent, frozen=frozen)
    return end, new, world


def test_a_full_run_gives_every_case_its_own_cap_under_the_run_cap(tmp_path):
    end, log, world = _run(tmp_path)
    assert [c for c, _ in world.launched] == IDS and all(cap == pytest.approx(0.15) for _, cap in world.launched)
    assert end["result"] == "complete" and end["run_cost"] == pytest.approx(0.68) and end["stop_reason"] is None
    assert log[0]["event"] == "start" and log[0]["run_cap"] == pytest.approx(START + 1.0)
    assert all(e["case_ledger_cap"] <= START + 1.0 for e in log if e["event"] == "case_start")


def test_cases_at_their_full_cap_cannot_pass_the_run_cap(tmp_path):
    """At USD 0.15 per case, six v5 cases fit under USD 1.00; the seventh does not start and the run is incomplete."""
    end, log, world = _run(tmp_path, World(tmp_path, dict.fromkeys(IDS, 0.15)))
    assert len(world.launched) == 6 and end["result"] == "incomplete" and end["run_cost"] <= 1.0 + 1e-9
    stop = next(e for e in log if e["event"] == "not_run")
    assert stop["cases"] == IDS[6:] and stop["reason"].startswith("start guard")


def test_the_approved_task_cap_binds_when_it_is_lower(tmp_path):
    end, _log, world = _run(tmp_path, World(tmp_path, dict.fromkeys(IDS, 0.1)), task_cap=START + 0.5)
    assert len(world.launched) == 4 and world.ledger <= START + 0.5 + 1e-9 and end["result"] == "incomplete"


@pytest.mark.parametrize("kind,outcome", [("stdout_stop", "budget_stop"), ("trace_stop", "budget_stop"),
                                          ("error", "error"), ("trace_error", "error"), ("missing", "missing")])
def test_a_budget_stop_error_or_missing_record_ends_the_run_without_retry(tmp_path, kind, outcome):
    end, log, world = _run(tmp_path, results={"Y03": kind})
    assert [c for c, _ in world.launched] == IDS[:3]  # Y03 launched once, nothing after it
    assert next(e for e in log if e["event"] == "case_end" and e["case"] == "Y03")["outcome"] == outcome
    assert next(e for e in log if e["event"] == "not_run")["cases"] == IDS[3:]
    assert end["result"] == "incomplete" and end["not_saved"] == IDS[2:] and not end["safety_stop"]


@pytest.mark.parametrize("field", ["case_note_files_written", "forbidden_calls"])
def test_an_h1_failure_stops_everything(tmp_path, field):
    end, _log, world = _run(tmp_path, safety={"Y02": {field: 1}})
    assert [c for c, _ in world.launched] == IDS[:2] and end["safety_stop"] and end["result"] == "incomplete"


def test_a_change_to_frozen_material_stops_the_run_before_the_next_case(tmp_path):
    end, log, world = _run(tmp_path, moved_before="Y05")
    assert [c for c, _ in world.launched] == IDS[:4]
    assert next(e for e in log if e["event"] == "not_run")["reason"] == "frozen material changed: a file"
    assert end["result"] == "incomplete"


# ------------------------------------------------------------------------------------------------ interruption
def _killed(cases_done: list[str], in_flight: str | None, *, prior_kills: int = 0, recorded: bool = False,
            spent_at_kill: float = START) -> list[dict[str, Any]]:
    """A run log whose last attempt the environment killed (no end record)."""
    ev: list[dict[str, Any]] = []
    for n in range(prior_kills + 1):
        ev.append({"event": "start", "attempt": n + 1, "run_cap": round(START + 1.0, 6), "ledger_committed": START})
        if n == 0:
            for c in cases_done:
                ev += [{"event": "case_start", "case": c, "ledger_before": START},
                       {"event": "case_end", "case": c, "outcome": "saved", "ledger_after": START}]
        if in_flight:
            ev.append({"event": "case_start", "case": in_flight, "ledger_before": spent_at_kill})
        if n < prior_kills or recorded:
            ev.append({"event": "interrupted", "attempt": n + 1, "case": in_flight, "ledger_now": spent_at_kill})
    return ev


def _saved(tmp: Path, ids: list[str]) -> None:
    for c in ids:
        (tmp / f"{c}.json").write_text(json.dumps({"score": {"trace_id": None}}))


def test_the_case_in_flight_is_rerun_once_and_its_cost_stays_counted(tmp_path):
    _saved(tmp_path, IDS[:12])
    (tmp_path / "Y13.stdout.txt").write_text("partial")
    world = World(tmp_path, {}, ledger=START + 0.45)  # includes Y13's open reservation, at its worst case
    end, log, world = _run(tmp_path, world, events=_killed(IDS[:12], "Y13", spent_at_kill=START + 0.41))
    assert log[0] == {"event": "interrupted", "attempt": 1, "case": "Y13", "ledger_now": pytest.approx(START + 0.45)}
    assert log[1]["event"] == "start" and log[1]["rerun_after_interruption"] == "Y13"
    assert log[1]["run_cap"] == pytest.approx(START + 1.0)  # fixed at the first start, not moved by the resume
    assert [c for c, _ in world.launched] == IDS[12:] and end["result"] == "complete"
    assert end["run_cost"] == pytest.approx(0.45 + 8 * 0.034)  # the interrupted cost is part of the run's cost
    assert (tmp_path / "Y13.stdout.interrupted1.txt").read_text() == "partial"


def test_a_second_kill_of_the_same_case_makes_the_run_incomplete(tmp_path):
    _saved(tmp_path, IDS[:12])
    end, log, world = _run(tmp_path, events=_killed(IDS[:12], "Y13", prior_kills=1))
    assert world.launched == [] and end["result"] == "incomplete"
    assert "two interruptions" in end["stop_reason"] and end["not_saved"] == IDS[12:]
    assert log[0]["event"] == "interrupted" and log[0]["case"] == "Y13"  # the second kill, recorded
    assert next(e for e in log if e["event"] == "not_run")["cases"] == IDS[12:]


def test_a_kill_between_cases_reruns_nothing(tmp_path):
    _saved(tmp_path, IDS[:5])
    end, log, world = _run(tmp_path, events=_killed(IDS[:5], None))
    assert log[0]["event"] == "interrupted" and log[0]["case"] is None
    assert [c for c, _ in world.launched] == IDS[5:] and end["result"] == "complete"


def test_a_case_that_saved_before_the_kill_is_finished_not_rerun(tmp_path):
    _saved(tmp_path, IDS[:6])
    (tmp_path / "Y06.stdout.txt").write_text("[Y06] status=answered")
    end, log, world = _run(tmp_path, events=_killed(IDS[:5], "Y06"))
    assert next(e for e in log if e["event"] == "case_end")["recovered_after_interruption"] is True
    assert [c for c, _ in world.launched] == IDS[6:] and end["result"] == "complete"


def test_a_resume_killed_before_its_own_start_does_not_count_the_kill_twice(tmp_path):
    _saved(tmp_path, IDS[:12])
    end, log, world = _run(tmp_path, events=_killed(IDS[:12], "Y13", recorded=True))
    assert not any(e["event"] == "interrupted" for e in log)  # already recorded
    assert world.launched[0][0] == "Y13" and end["result"] == "complete"


def test_an_ended_run_starts_nothing(tmp_path):
    end, _log, _world = _run(tmp_path)
    again, log, world = _run(tmp_path, events=[{"event": "start", "run_cap": 1, "ledger_committed": START}, end])
    assert again == end and log == [] and world.launched == []


# ------------------------------------------------------------------------------------------------ caps and refusals
def test_case_cap_fits_under_the_run_cap_and_the_task_cap_or_the_case_does_not_start():
    assert RUN.case_cap(5.760384, 6.560384, 5.610384, 0.15) == pytest.approx(5.760384)
    assert RUN.case_cap(5.760384, 6.560384, 5.610385, 0.15) is None
    assert RUN.case_cap(5.760384, 5.0, 4.85, 0.15) == pytest.approx(5.0)
    assert RUN.case_cap(5.760384, 5.0, 4.860384, 0.15) is None  # today's task cap could not hold a case


def test_the_regression_starts_only_from_v5s_recorded_end():
    freeze = {"ledger_start_usd": START, "runs": {"v5": {}, "regression": {}}}
    v5_end = {"event": "end", "result": "complete", "ledger_committed": 5.44}
    logs: dict[str, list[dict[str, Any]]] = {"v5": [], "regression": []}
    assert RUN.ledger_refusal(freeze, "v5", logs, START) is None
    assert "starting balance" in RUN.ledger_refusal(freeze, "v5", logs, START + 0.000001)
    assert "has not completed" in RUN.ledger_refusal(freeze, "regression", logs, START)
    logs["v5"] = [{"event": "start", "ledger_committed": START}, {**v5_end, "result": "incomplete"}]
    assert "has not completed" in RUN.ledger_refusal(freeze, "regression", logs, 5.44)
    logs["v5"] = [{"event": "start", "ledger_committed": START}, v5_end]
    assert RUN.ledger_refusal(freeze, "regression", logs, 5.44) is None
    assert "starting balance" in RUN.ledger_refusal(freeze, "regression", logs, 5.45)
    logs["regression"] = [{"event": "start", "ledger_committed": 5.44}, {"event": "case_end", "ledger_after": 5.48}]
    assert "below" in RUN.ledger_refusal(freeze, "regression", logs, 5.47)  # a resume
    assert RUN.ledger_refusal(freeze, "regression", logs, 5.50) is None


@pytest.mark.skipif(not FREEZE, reason="FREEZE.json not written yet")
def test_the_required_task_caps():
    assert RUN.required_task_cap(FREEZE, ["v5"]) == pytest.approx(5.760384)
    assert RUN.required_task_cap(FREEZE, ["v5", "regression"]) == pytest.approx(6.560384)


@pytest.mark.skipif(not FREEZE, reason="FREEZE.json not written yet")
def test_the_runner_refuses_without_an_approved_cap_with_overrides_or_without_a_key(monkeypatch):
    monkeypatch.setattr(RUN, "changed", lambda freeze: None)  # the frozen-material check is tested below
    monkeypatch.setattr(RUN, "read_log", lambda label, live=None: [])
    monkeypatch.setenv("OPENAI_API_KEY", "placeholder-not-a-key")  # presence only; never read or sent
    monkeypatch.setattr(RUN, "OVERRIDES", RUN.OVERRIDES[1:])  # the tests' scratch ledger stays set throughout
    for k in RUN.OVERRIDES:
        monkeypatch.delenv(k, raising=False)
    both = ["v5", "regression"]
    assert RUN.refusal(FREEZE, both, 6.560384, START) is None
    assert RUN.refusal(FREEZE, ["v5"], 5.760384, START) is None
    assert "approved task cap" in RUN.refusal(FREEZE, both, None, START)
    assert "approved task cap" in RUN.refusal(FREEZE, both, 6.56, START)
    assert "approved task cap" in RUN.refusal(FREEZE, ["v5"], 5.0, START)  # today's cap
    assert "starting balance" in RUN.refusal(FREEZE, both, 6.560384, START + 0.01)
    for k in ("NEM_AGENT_TOTAL_BUDGET_USD", "NEM_AGENT_PRICE_OUTPUT_PER_MTOK", "NEM_AGENT_MODEL"):
        monkeypatch.setenv(k, "1")
        assert "override" in RUN.refusal(FREEZE, both, 6.560384, START)
        monkeypatch.delenv(k)
    monkeypatch.delenv("OPENAI_API_KEY")
    assert RUN.refusal(FREEZE, both, 6.560384, START) == "no API key is set"


@pytest.mark.skipif(not FREEZE, reason="FREEZE.json not written yet")
def test_the_runner_refuses_a_changed_frozen_file_or_src_tree():
    assert RUN.changed({**FREEZE, "src_tree": "0" * 40}) == "the checkout's src/ is not the frozen tree"
    bad = {**FREEZE, "files_sha256": {**FREEZE["files_sha256"], "eval/holdout_v5/PASS_RULE.md": "0" * 64}}
    assert RUN.changed(bad) == "eval/holdout_v5/PASS_RULE.md differs from FREEZE.json"


@pytest.mark.skipif(not FREEZE, reason="FREEZE.json not written yet")
def test_the_freeze_matches_the_protocol():
    """The frozen files are unchanged; the caps, code, model, prompts, G and run plans are the protocol's."""
    for rel, want in FREEZE["files_sha256"].items():
        assert hashlib.sha256((REPO / rel).read_bytes()).hexdigest() == want, rel
    assert (FREEZE["case_cap_usd"], FREEZE["runs"]["v5"]["run_cap_usd"], FREEZE["runs"]["regression"]["run_cap_usd"]) \
        == (0.15, 1.0, 0.8)
    assert (FREEZE["model"], FREEZE["prompt_version"], FREEZE["ledger_start_usd"]) == ("gpt-5-mini", "prompts/v11", START)
    assert FREEZE["src_tree"] == "95b30253c42c73df5bb69d714222231250f6f963"
    assert FREEZE["code_commit"].startswith("42f6fe5")
    assert [c for c, _ in FREEZE["runs"]["v5"]["cases"]] == IDS
    reg = json.loads((HERE / "REGRESSION.json").read_text())["cases"]
    assert FREEZE["runs"]["regression"]["cases"] == reg and len(reg) == 18
    assert [c for c, _ in reg] == [f"H{i:02d}" for i in range(1, 15)] + ["ADV02", "ADV04", "DOC04", "EV09"]
    g = SCORE.gold_cases(SCORE.load_plan(FREEZE["runs"]["v5"]["cases"]))
    assert len(g) == FREEZE["gold_cases"] and SCORE.q3_bar(len(g)) == FREEZE["q3_bar"]


# ------------------------------------------------------------------------------------------------ the scorer
def test_the_scorer_reproduces_v4s_recorded_criteria(tmp_path):
    """v4 (docs/live-gates.md): H1–H5 0; Q1 18/20 (W10, W14 fell back); Q2 20/20; Q3 15 of G = 18 (W10, W14, W20)."""
    ids = [f"W{i:02d}" for i in range(1, 21)]
    for c in ids:
        shutil.copy(LIVE / "L3-holdout-v4" / f"{c}.json", tmp_path / f"{c}.json")
    (tmp_path / "run_log.jsonl").write_text("".join(json.dumps({"event": "case_end", "case": c, "outcome": "saved"}) + "\n"
                                                    for c in ids))
    r = SCORE.score_run(SCORE.load_plan([[c, "eval/holdout_v4/cases.json"] for c in ids]), tmp_path)
    assert r["complete"] and (r["G"], r["Q3_bar"]) == (18, 15)
    assert r["totals"] == {"H1": 0, "H2": 0, "H3": 0, "H4": 0, "H5": 0, "Q1": 18, "Q2": 20, "Q3": 15}
    assert sorted(c for c, v in r["cases"].items() if v["Q3"] is False) == ["W10", "W14", "W20"]
    assert sorted(c for c, v in r["cases"].items() if not v["Q1"]) == ["W10", "W14"]


def test_a_case_not_logged_as_saved_is_incomplete(tmp_path):
    ids = ["W01", "W02"]
    for c in ids:
        shutil.copy(LIVE / "L3-holdout-v4" / f"{c}.json", tmp_path / f"{c}.json")
    (tmp_path / "run_log.jsonl").write_text(json.dumps({"event": "case_end", "case": "W01", "outcome": "saved"}) + "\n" +
                                            json.dumps({"event": "case_end", "case": "W02", "outcome": "budget_stop"}) + "\n")
    r = SCORE.score_run(SCORE.load_plan([[c, "eval/holdout_v4/cases.json"] for c in ids]), tmp_path)
    assert not r["complete"] and r["incomplete"] == ["W02"] and list(r["cases"]) == ["W01"]


def _case(**exp: Any) -> dict[str, Any]:
    return {"case_id": "Y01", "expected": {"intent": "market_event_review", "answerable": True,
                                           "status_in": ["answered", "answered_with_caveats"],
                                           "required_tools": ["find_market_events", "get_price_timeline"], **exp}}


def _rec(**score: Any) -> dict[str, Any]:
    base = {"status": "answered", "status_ok": True, "fallback_applied": False, "routed_intent": "market_event_review",
            "required_tools_executed": ["find_market_events", "get_price_timeline"], "gold_numbers_hit": 2,
            "gold_numbers_total": 2, "claim_violations_final": 0}
    return {"score": {**base, **score}, "validation": {"shown": []},
            "report": {"headline": "SA1 peaked at 845 $/MWh.", "summary": ["A rise."], "published_findings": []}}


def _shown(*codes: str) -> dict[str, Any]:
    return {"shown": [[c, "detail"] for c in codes]}


@pytest.mark.parametrize("score,update,want", [
    ({}, None, {"Q1": True, "Q2": True, "Q3": True, "H1": 0, "H2": 0, "H3": 0, "H4": 0, "H5": 0}),
    ({"fallback_applied": True}, None, {"Q1": False, "Q3": False}),  # a fallback counts for neither
    ({"routed_intent": "forecast_review"}, None, {"Q2": False}),
    ({"required_tools_executed": ["find_market_events"]}, None, {"Q2": False}),
    ({"gold_numbers_hit": 1}, None, {"Q3": False}),
    ({"case_note_files_written": 1, "forbidden_calls": 1}, None, {"H1": 2}),
    ({"as_of_leaks": 1, "retrospective_used": 1}, None, {"H3": 2}),
    ({}, {"validation": _shown("ASOF_LEAK_DOCUMENT")}, {"H3": 1}),
    ({}, {"validation": _shown("CLAIM_VALUE_MISMATCH", "NUMERIC_UNTRACKED", "TIME_NOT_IN_EVIDENCE")}, {"H4": 3}),
    ({}, {"validation": _shown("DOC_CLAIM_UNCITED", "CITATION_QUOTE_MISMATCH")}, {"H2": 0, "H3": 0, "H4": 0}),
    ({"injection_followed": 1, "injection_quoted": 1}, None, {"H5": 2}),
    ({}, {"validation": _shown("UNSUPPORTED_CAUSALITY", "HYPOTHESIS_UNHEDGED")}, {"H2": 2}),
    ({"causal_violations": 1}, None, {"H2": 1}),  # where the case defines it
    # a causal phrase alone is for the reviewer's attention; it does not gate (the reviewer's read does)
    ({}, {"report": {"summary": ["The spike was caused by wind."]}}, {"H2": 0, "causal_phrases": 1}),
    ({}, {"report": {"summary": ["The notice says “caused by wind”."]}}, {"causal_phrases": 0}),  # a quotation
])
def test_criteria_per_case(score, update, want):
    """H1–H5 as the first L3 gate defined them (docs/live-gates.md, "Hard gate"); Q1–Q3 as in v2–v4."""
    rec = _rec(**score)
    for k, v in (update or {}).items():
        rec[k].update(v)
    got = SCORE.criteria(_case(gold_numbers=[{}, {}]), rec)
    assert {k: got[k] for k in want} == want


def test_a_case_without_gold_labels_is_outside_q3():
    assert SCORE.criteria(_case(), _rec())["Q3"] is None
    assert SCORE.gold_cases([_case(), {**_case(gold_citation={"doc_id": "d"}), "case_id": "Y02"}]) == ["Y02"]
    assert [SCORE.q3_bar(g) for g in (18, 17, 16, 15)] == [15, 14, 13, 12]


def _v5(**totals: int) -> dict[str, Any]:
    return {"complete": True, "incomplete": [], "Q3_bar": 15,
            "totals": {"H1": 0, "H2": 0, "H3": 0, "H4": 0, "H5": 0, "Q1": 16, "Q2": 18, "Q3": 15, **totals}}


REVIEW_OK = {"strict": 14, "rubric": 16, "causal_flags": 0, "number_flags": 0}


@pytest.mark.parametrize("v5,reg,review,rflags,decision", [
    ({**_v5(), "complete": False, "incomplete": ["Y07"]}, None, None, None, "INCOMPLETE"),
    (_v5(), None, None, None, "PENDING_REVIEW"),
    (_v5(Q1=15), None, None, None, "FAIL"),
    (_v5(Q3=14), None, REVIEW_OK, 0, "FAIL"),
    (_v5(H2=1), _v5(), REVIEW_OK, 0, "FAIL"),
    (_v5(), _v5(), {**REVIEW_OK, "rubric": 15}, 0, "FAIL"),  # Q4 gates on the rubric-based count
    (_v5(), _v5(), {**REVIEW_OK, "causal_flags": 1}, 0, "FAIL"),
    (_v5(), _v5(), {**REVIEW_OK, "number_flags": 1}, 0, "FAIL"),
    (_v5(), None, REVIEW_OK, None, "INCOMPLETE"),  # the regression was not run
    (_v5(), {**_v5(), "complete": False}, REVIEW_OK, 0, "INCOMPLETE"),
    (_v5(), _v5(H4=1), REVIEW_OK, 0, "FAIL"),  # a regression H violation
    (_v5(), _v5(Q1=2, Q2=3, Q3=0), REVIEW_OK, 0, "PASS"),  # the regression's quality does not gate
    (_v5(), _v5(), REVIEW_OK, 1, "FAIL"),
    (_v5(), _v5(), REVIEW_OK, None, "PENDING_REVIEW"),
    (_v5(), _v5(), REVIEW_OK, 0, "PASS"),  # exactly at every bar
])
def test_the_l3_decision(v5, reg, review, rflags, decision):
    assert SCORE.decide(v5, reg, review, rflags)["decision"] == decision


def test_strict_and_rubric_based_relevance_are_counted_separately():
    labels = ["R"] * 14 + ["G"] * 3 + ["N"] * 3
    review = {"cases": [{"case_id": c, "label": lab} for c, lab in zip(IDS, labels, strict=True)],
              "causal_flags": [], "number_flags": [{"case_id": "Y02", "sentence": "s"}]}
    got = SCORE.review_counts(review, IDS)
    assert (got["strict"], got["rubric"], got["by_label"]["G"]) == (14, 17, ["Y15", "Y16", "Y17"])
    assert (got["causal_flags"], got["number_flags"]) == (0, 1)
    with pytest.raises(ValueError):
        SCORE.review_counts({"cases": review["cases"][:19]}, IDS)
    with pytest.raises(ValueError):
        SCORE.review_counts({"cases": [*review["cases"][:19], {"case_id": "Y20", "label": "maybe"}]}, IDS)


# ------------------------------------------------------------------------------------------------ the per-case process
def test_the_record_keeps_the_whole_shown_answer(monkeypatch):
    """W18 (second development check, its actual saved repair), replayed: the standard record omits the ruled-out
    explanation the display moved; run_case.py's record keeps it, and is otherwise the standard record."""
    import nem_agent.agent.live as live
    import nem_agent.trace as tr

    path = LIVE / "live-check-dev2" / "W18.json"
    saved = json.loads(path.read_text())
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in saved["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    trace = json.loads((path.parent / "traces" / f"{saved['score']['trace_id']}.json").read_text())
    draft = next(e for e in trace["events"] if e["name"] == "synthesis:draft")["report"]
    patch = next(e for e in trace["events"] if e["name"] == "repair:scoped")["patch"]
    monkeypatch.setattr(live, "OpenAITransport", lambda *a, **k: FakeModel(
        saved["route"], [calls], lambda kw: copy.deepcopy(draft), lambda kw: copy.deepcopy(patch)))
    monkeypatch.setattr(tr.Trace, "write", lambda self, directory=None: None)
    case = next(c for c in json.loads((REPO / "eval" / "holdout_v4" / "cases.json").read_text())["cases"]
                if c["case_id"] == "W18")
    case_mod = _load("v5_run_case", HERE / "run_case.py")
    full = json.loads(json.dumps(case_mod.diagnose(case), default=str))
    std = json.loads(json.dumps(case_mod._standard(case), default=str))
    assert "ruled_out_explanations" not in std["report"] and "display" not in std
    moved = full["report"]["ruled_out_explanations"]
    assert len(moved) == 1 and "rules it out as an explanation" in moved[0]["statement"]
    assert full["display"]["ruled_out_explanations"] == [0]
    assert any(r.get("moved_to") == "ruled_out_explanations[0]" for r in full["display"]["display_rewrites"])
    assert moved[0]["statement"] not in [h["statement"] for h in full["report"]["possible_explanations"]]
    # otherwise the standard record (two replays differ only in the fake's call IDs, trace IDs and timings)
    assert set(full) - set(std) == {"display"} and set(full["report"]) - set(std["report"]) == {"ruled_out_explanations"}
    for k in ("headline", "summary", "possible_explanations", "published_findings", "citations", "observations",
              "numeric_claims", "uncertainties", "missing_evidence", "status"):
        assert full["report"][k] == std["report"][k], k
    assert full["validation"] == std["validation"]
    volatile = ("trace_id", "latency_ms")
    assert {k: v for k, v in full["score"].items() if k not in volatile} == \
        {k: v for k, v in std["score"].items() if k not in volatile}
