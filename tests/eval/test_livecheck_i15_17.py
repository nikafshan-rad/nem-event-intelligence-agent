"""Offline verification of the protocol for the targeted Live check of I-15, I-16 and I-17 (eval/livecheck_i15_17),
before any paid call.

- **Runner** (adapted from eval/holdout_v6/run_eval.py):
  - the per-case (USD 0.15), run (D1 0.45, D2 1.00) and approved task caps (8.463187);
  - the start guard;
  - the stops: budget stop, API error, missing record, H1 safety failure, frozen material changed;
  - the interruption rule;
  - D2 only after a complete D1 with no safety stop;
  - its refusals;
  - `run_case.py` byte-identical to v6's.
- **Freeze:** the frozen files, code identity, caps and plans are the protocol's.
- **Scorer:** the automatic fields, and the decision rules of PASS_RULE.md:
  - any H1–H5 violation fails, regardless of X;
  - X fails;
  - incomplete coverage is INCOMPLETE, never PASS;
  - containment is not supply;
  - the per-area supply bars and the controls;
  - the stricter of two readings.

The fake world is SYNTHETIC (no network, no key), and the ledger is a per-test scratch file (conftest). Scripted runs
are not a measure of Live behaviour.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.synthetic

REPO = Path(__file__).resolve().parents[2]
HERE = REPO / "eval" / "livecheck_i15_17"
START = 7.013187  # the real ledger total when this protocol was prepared


def _load(name: str, path: Path) -> Any:
    """Loaded under its own name, without putting this directory on sys.path (where its score.py would shadow the
    earlier held-out runners' ``score`` import)."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RUN = _load("lc_run_eval", HERE / "run_eval.py")
SCORE = _load("lc_score", HERE / "score.py")
FREEZE: dict[str, Any] = json.loads((HERE / "FREEZE.json").read_text()) if (HERE / "FREEZE.json").exists() else {}
DEV = ["Z03", "Z05", "Z04"]
FRESH = [f"K{i:02d}" for i in range(1, 16)]
PLAN_D1 = {"label": "LC-i15-17-dev", "run_cap_usd": 0.45, "cases": [[c, "eval/holdout_v6/cases.json"] for c in DEV]}
PLAN_D2 = {"label": "LC-i15-17-fresh", "run_cap_usd": 1.0, "cases": [[c, "eval/livecheck_i15_17/cases.json"]
                                                                     for c in FRESH]}


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
        self.ledger += min(self.costs.get(cid, 0.03), cap - self.ledger)  # the ledger never lets a case pass its cap
        kind = self.results.get(cid, "saved")
        score = {"trace_id": None, "case_note_files_written": 0, "forbidden_calls": 0, **self.safety.get(cid, {})}
        text = f"[{cid}] status=answered"
        if kind == "stdout_stop":
            text = f"[{cid}] STOPPED: task budget {cap:.2f} USD: ..."
        elif kind == "error":
            text = f"[{cid}] ERROR APITimeoutError: Request timed out."
            (out / f"{cid}.error.json").write_text("{}")
        if kind == "saved":
            (out / f"{cid}.json").write_text(json.dumps({"score": score}))
        (out / f"{cid}.stdout.txt").write_text(text)
        return 0, text


def _run(tmp: Path, world: World | None = None, *, events: list[dict[str, Any]] | None = None, plan=PLAN_D2,
         task_cap: float = 8.463187, moved_before: str | None = None, **kw: Any):
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


def test_d1_gives_each_case_its_own_cap_under_its_run_cap(tmp_path):
    end, log, world = _run(tmp_path, plan=PLAN_D1)
    assert [c for c, _ in world.launched] == DEV and all(cap == pytest.approx(0.15) for _, cap in world.launched)
    assert end["result"] == "complete" and log[0]["run_cap"] == pytest.approx(START + 0.45)


def test_d1s_cap_holds_all_three_cases_at_their_full_cap(tmp_path):
    """USD 0.45 = 3 × 0.15: every development case can start even if each spends its whole cap."""
    end, _log, world = _run(tmp_path, World(tmp_path, dict.fromkeys(DEV, 0.15)), plan=PLAN_D1)
    assert len(world.launched) == 3 and end["result"] == "complete" and end["run_cost"] == pytest.approx(0.45)


def test_d2s_cap_stops_starting_cases_that_would_not_fit(tmp_path):
    """At USD 0.15 per case, six D2 cases fit under USD 1.00; the seventh does not start, and the run is incomplete."""
    end, log, world = _run(tmp_path, World(tmp_path, dict.fromkeys(FRESH, 0.15)))
    assert len(world.launched) == 6 and end["result"] == "incomplete"
    stop = next(e for e in log if e["event"] == "not_run")
    assert stop["cases"] == FRESH[6:] and stop["reason"].startswith("start guard")


@pytest.mark.parametrize("kind,outcome", [("stdout_stop", "budget_stop"), ("error", "error"), ("missing", "missing")])
def test_a_budget_stop_error_or_missing_record_ends_the_run_without_retry(tmp_path, kind, outcome):
    end, log, world = _run(tmp_path, results={"K03": kind})
    assert [c for c, _ in world.launched] == FRESH[:3]
    assert next(e for e in log if e["event"] == "case_end" and e["case"] == "K03")["outcome"] == outcome
    assert end["result"] == "incomplete" and not end["safety_stop"]


@pytest.mark.parametrize("field", ["case_note_files_written", "forbidden_calls"])
def test_an_h1_failure_stops_the_run_at_once(tmp_path, field):
    end, _log, world = _run(tmp_path, plan=PLAN_D1, safety={"Z05": {field: 1}})
    assert [c for c, _ in world.launched] == ["Z03", "Z05"] and end["safety_stop"] and end["result"] == "incomplete"


def test_a_change_to_frozen_material_stops_the_run_before_the_next_case(tmp_path):
    end, log, world = _run(tmp_path, moved_before="K05")
    assert [c for c, _ in world.launched] == FRESH[:4] and end["result"] == "incomplete"
    assert next(e for e in log if e["event"] == "not_run")["reason"] == "frozen material changed: a file"


def test_the_case_in_flight_is_rerun_once_and_a_second_kill_makes_the_run_incomplete(tmp_path):
    started = {"event": "start", "attempt": 1, "run_cap": round(START + 1.0, 6), "ledger_committed": START}
    flight = {"event": "case_start", "case": "K01", "ledger_before": START}
    end, log, world = _run(tmp_path, events=[started, flight])
    assert log[0]["event"] == "interrupted" and log[1]["rerun_after_interruption"] == "K01"
    assert world.launched[0][0] == "K01" and end["result"] == "complete"
    again = [started, flight, {"event": "interrupted", "attempt": 1, "case": "K01", "ledger_now": START},
             {**started, "attempt": 2}, flight]
    second = tmp_path / "second"
    second.mkdir()
    end2, _log2, world2 = _run(second, events=again)
    assert world2.launched == [] and end2["result"] == "incomplete" and "two interruptions" in end2["stop_reason"]


def _end(result: str = "complete", ledger: float = START, safety: bool = False) -> dict[str, Any]:
    return {"event": "end", "result": result, "ledger_committed": ledger, "safety_stop": safety}


def test_d2_starts_only_from_a_complete_d1s_recorded_end():
    freeze = {"ledger_start_usd": START, "runs": {"D1": {}, "D2": {}}}
    logs: dict[str, list[dict[str, Any]]] = {"D1": [], "D2": []}
    assert RUN.ledger_refusal(freeze, "D1", logs, START) is None
    assert "starting balance" in RUN.ledger_refusal(freeze, "D1", logs, START + 0.000001)
    assert "D2 does not start" in RUN.ledger_refusal(freeze, "D2", logs, START)
    logs["D1"] = [{"event": "start", "ledger_committed": START}, _end("incomplete", 7.1)]
    assert "D2 does not start" in RUN.ledger_refusal(freeze, "D2", logs, 7.1)  # an INCOMPLETE D1: D2 never starts
    assert "D1 did not complete" in RUN.next_run_refusal("D2", logs, set())
    logs["D1"] = [{"event": "start", "ledger_committed": START}, _end("complete", 7.1, safety=True)]
    assert "safety stop" in RUN.next_run_refusal("D2", logs, set())
    logs["D1"] = [{"event": "start", "ledger_committed": START}, _end("complete", 7.1)]
    assert RUN.ledger_refusal(freeze, "D2", logs, 7.1) is None and RUN.next_run_refusal("D2", logs, set()) is None
    assert "starting balance" in RUN.ledger_refusal(freeze, "D2", logs, 7.11)


def test_run_case_is_v6s_byte_identical():
    assert (HERE / "run_case.py").read_bytes() == (REPO / "eval" / "holdout_v6" / "run_case.py").read_bytes()


@pytest.mark.skipif(not FREEZE, reason="FREEZE.json not written yet")
def test_the_required_task_caps():
    assert RUN.required_task_cap(FREEZE, ["D1"]) == pytest.approx(7.463187)
    assert RUN.required_task_cap(FREEZE, ["D1", "D2"]) == pytest.approx(8.463187)


@pytest.mark.skipif(not FREEZE, reason="FREEZE.json not written yet")
def test_the_runner_refuses_without_an_approved_cap_with_overrides_or_without_a_key(monkeypatch):
    monkeypatch.setattr(RUN, "changed", lambda freeze: None)  # the frozen-material check is tested below
    monkeypatch.setattr(RUN, "read_log", lambda label, live=None: [])
    monkeypatch.setenv("OPENAI_API_KEY", "placeholder-not-a-key")  # presence only; never read or sent
    monkeypatch.setattr(RUN, "OVERRIDES", RUN.OVERRIDES[1:])  # the tests' scratch ledger stays set throughout
    for k in RUN.OVERRIDES:
        monkeypatch.delenv(k, raising=False)
    both = ["D1", "D2"]
    assert RUN.refusal(FREEZE, both, 8.463187, START) is None
    assert "approved task cap" in RUN.refusal(FREEZE, both, None, START)
    assert "approved task cap" in RUN.refusal(FREEZE, both, 8.4, START)
    assert "approved task cap" in RUN.refusal(FREEZE, ["D1"], 5.0, START)  # the standing cap
    assert "starting balance" in RUN.refusal(FREEZE, both, 8.463187, START + 0.01)
    for k in ("NEM_AGENT_TOTAL_BUDGET_USD", "NEM_AGENT_PRICE_OUTPUT_PER_MTOK", "NEM_AGENT_MODEL"):
        monkeypatch.setenv(k, "1")
        assert "override" in RUN.refusal(FREEZE, both, 8.463187, START)
        monkeypatch.delenv(k)
    monkeypatch.delenv("OPENAI_API_KEY")
    assert RUN.refusal(FREEZE, both, 8.463187, START) == "no API key is set"


@pytest.mark.skipif(not FREEZE, reason="FREEZE.json not written yet")
def test_the_runner_refuses_a_changed_frozen_file_or_src_tree():
    assert RUN.changed({**FREEZE, "src_tree": "0" * 40}) == "the checkout's src/ is not the frozen tree"
    rel = "eval/livecheck_i15_17/PASS_RULE.md"
    assert RUN.changed({**FREEZE, "files_sha256": {**FREEZE["files_sha256"], rel: "0" * 64}}) == \
        f"{rel} differs from FREEZE.json"


@pytest.mark.skipif(not FREEZE, reason="FREEZE.json not written yet")
def test_the_freeze_matches_the_protocol():
    for rel, want in FREEZE["files_sha256"].items():
        assert hashlib.sha256((REPO / rel).read_bytes()).hexdigest() == want, rel
    runs = FREEZE["runs"]
    assert (FREEZE["case_cap_usd"], runs["D1"]["run_cap_usd"], runs["D2"]["run_cap_usd"]) == (0.15, 0.45, 1.0)
    assert (FREEZE["model"], FREEZE["prompt_version"], FREEZE["ledger_start_usd"]) == ("gpt-5-mini", "prompts/v11", START)
    assert FREEZE["src_tree"] == "b248e4c606d64c17770e1f03abdc9346a6717d1e"
    assert FREEZE["code_tree"] == "4a3b0ab619cf156b4f75f453fd301203da831c65"
    assert FREEZE["code_commit"].startswith("cf9558e")
    assert [runs[n]["label"] for n in ("D1", "D2")] == ["LC-i15-17-dev", "LC-i15-17-fresh"]
    assert runs["D1"]["cases"] == PLAN_D1["cases"] and runs["D2"]["cases"] == PLAN_D2["cases"]
    assert (runs["D1"]["n_cases"], runs["D2"]["n_cases"]) == (3, 15)
    d2 = SCORE.load_plan(runs["D2"]["cases"])
    want = ["value_time"] * 4 + ["forecast_run"] * 4 + ["demand_max"] * 4 + ["control"] * 3
    assert [c["expected"]["area"] for c in d2] == want
    assert [c["expected"]["expected_outcome"] for c in d2] == (["supplied"] * 6 + ["unavailable", "clarification"]
                                                               + ["supplied"] * 3 + ["clarification"] + ["supplied"] * 3)
    assert d2[6]["request"].get("as_of_utc") and all(c["request"] == {} for i, c in enumerate(d2) if i != 6)


# ------------------------------------------------------------------------------------------------ the scorer
def _rec(status="answered", fallback=False, pre=(), shown=(), **score: Any) -> dict[str, Any]:
    return {"score": {"status": status, "fallback_applied": fallback, "case_note_files_written": 0, "forbidden_calls": 0,
                      **score},
            "validation": {"pre_repair": [(c, "") for c in pre], "final_candidate": [], "shown": [(c, "") for c in shown],
                           "fallback_applied": fallback, "repair_attempted": bool(pre)}}


def test_the_automatic_fields():
    a = SCORE.automatic({"case_id": "K01", "expected": {}}, _rec(pre=("CLAIM_TIME_MISMATCH", "NUMERIC_UNTRACKED")), None)
    assert a["blocked"] == ["CLAIM_TIME_MISMATCH"] and a["outcome_auto"] is None and a["H1"] == 0
    assert SCORE.automatic({"case_id": "K08", "expected": {}}, _rec(status="needs_clarification"), None)["outcome_auto"] \
        == "C"
    f = SCORE.automatic({"case_id": "Z04", "expected": {}}, _rec(fallback=True, pre=("REQUESTED_MAXIMUM_MISMATCH",)), None)
    assert f["outcome_auto"] == "F" and f["blocked"] == ["REQUESTED_MAXIMUM_MISMATCH"]
    assert SCORE.automatic({"case_id": "K01", "expected": {}}, _rec(shown=("TIME_NOT_IN_EVIDENCE",)), None)["H4_auto"] == 1
    assert SCORE.automatic({"case_id": "K01", "expected": {}}, _rec(forbidden_calls=1), None)["H1"] == 1


AREAS = ["value_time"] * 4 + ["forecast_run"] * 4 + ["demand_max"] * 4 + ["control"] * 3
EXPECTED = ["supplied"] * 6 + ["unavailable", "clarification"] + ["supplied"] * 3 + ["clarification"] + ["supplied"] * 3
GOOD = dict(zip(DEV + FRESH, ["S"] * 3 + ["S"] * 6 + ["U", "C"] + ["S"] * 3 + ["C"] + ["S"] * 3, strict=True))


def _decide(outcomes: dict[str, str | None] | None = None, *, missing: tuple[str, ...] = (),
            h: dict[str, dict[str, int]] | None = None) -> dict[str, Any]:
    plan = {"D1": [{"case_id": c, "expected": {}} for c in DEV],
            "D2": [{"case_id": c, "expected": {"area": a, "expected_outcome": e}}
                   for c, a, e in zip(FRESH, AREAS, EXPECTED, strict=True)]}
    auto = {}
    for run, cases in plan.items():
        rows = {}
        for c in cases:
            if c["case_id"] in missing:
                continue
            rows[c["case_id"]] = {"H1": 0, "H2_auto": 0, "H3": 0, "H4_auto": 0, "H5": 0, "blocked": [],
                                  **(h or {}).get(c["case_id"], {})}
        auto[run] = {"cases": rows}
    o = {**GOOD, **(outcomes or {})}
    readings = {cid: {"outcome": out, "H2_manual": 0, "H4_manual": 0} for cid, out in o.items()}
    return SCORE.decide(plan, auto, readings)


def test_pass_needs_every_criterion():
    r = _decide()
    assert r["verdict"] == "PASS" and set(r["fixes"].values()) == {"held"}
    assert r["criteria"]["fresh_supply_total"] == [9, 7, 9]


@pytest.mark.parametrize("gate", ["H1", "H2_auto", "H3", "H4_auto", "H5"])
def test_any_safety_violation_fails_regardless_of_x(gate):
    r = _decide(h={"K13": {gate: 1}})
    assert r["verdict"] == "FAIL" and any(f.startswith("K13: H") for f in r["failures"])


def test_an_incorrect_answer_shown_fails_and_the_fix_is_not_held():
    r = _decide({"K10": "X"})
    assert r["verdict"] == "FAIL" and r["fixes"]["demand_max"] == "not held"
    assert r["fixes"]["value_time"] == "held"


def test_incomplete_coverage_is_never_a_pass_but_a_failure_already_seen_is_a_fail():
    assert _decide(missing=("K15",))["verdict"] == "INCOMPLETE"
    assert _decide(missing=("Z05",))["fixes"]["forecast_run"] == "incomplete"
    assert _decide({"K02": "X"}, missing=("K15",))["verdict"] == "FAIL"
    assert _decide({"K02": None})["verdict"] == "INCOMPLETE"  # not yet reviewed


@pytest.mark.parametrize("case,outcome", [("Z03", "C"), ("Z05", "U"), ("Z04", "F")])
def test_containment_in_a_development_case_is_not_supply(case, outcome):
    r = _decide({case: outcome})
    assert r["verdict"] == "FAIL" and r["criteria"]["development_supply"][case] is False
    assert r["fixes"][SCORE.DEV_AREA[case]] == "contains but does not reliably supply"


def test_the_fresh_supply_bars():
    assert _decide({"K01": "F", "K02": "C"})["verdict"] == "PASS"  # 7 of 9, value-and-time 2 of 4
    assert _decide({"K01": "F", "K02": "C", "K03": "U"})["verdict"] == "FAIL"  # 6 of 9
    r = _decide({"K05": "F"})  # 8 of 9, but forecast-run 1 of 2
    assert r["verdict"] == "FAIL" and r["fixes"]["forecast_run"] == "contains but does not reliably supply"
    assert _decide({"K09": "C", "K10": "F"})["fixes"]["demand_max"] == "contains but does not reliably supply"


@pytest.mark.parametrize("case,outcome", [("K07", "S"), ("K07", "C"), ("K08", "S"), ("K12", "U"), ("K13", "F")])
def test_controls_must_get_their_expected_outcome(case, outcome):
    assert _decide({case: outcome})["verdict"] == "FAIL"


def test_the_stricter_of_two_readings():
    assert SCORE.merge([{"outcome": "S"}, {"outcome": "X"}])["outcome"] == "X"
    assert SCORE.merge([{"outcome": "S"}, {"outcome": "F"}]) == {"outcome": "F", "H2_manual": 0, "H4_manual": 0,
                                                                  "disagreement": True}
    assert SCORE.merge([{"outcome": "S", "H4_manual": 1}, {"outcome": "S"}])["H4_manual"] == 1
    assert SCORE.merge([{"outcome": "S"}, {"outcome": None}])["outcome"] is None
