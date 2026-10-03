"""The development comparison of gpt-5-mini and gpt-6.1-sol (eval/model_comparison_dev/PROTOCOL.md): its plan, caps,
runner and scorer, offline. Nothing here calls a model: the runner's processes, ledger and records are injected, and
the scorer reads SYNTHETIC records."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "eval" / "model_comparison_dev"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"mc_{name}", DIR / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


F = _load("freeze")
RUN = _load("run_eval")
SCORE = _load("score")
FREEZE = json.loads((DIR / "FREEZE.json").read_text()) if (DIR / "FREEZE.json").exists() else None


# ------------------------------------------------------------------------------------------------ the plan
def test_the_plan_has_three_routing_repeats_and_one_end_to_end_execution_per_case_and_model():
    plan = F.slots()
    assert len(plan) == 58 and [s["slot"] for s in plan] == list(range(1, 59))
    count = Counter((s["kind"], s["model"]) for s in plan)
    assert count == {("route", "mini"): 24, ("route", "sol"): 24, ("e2e", "mini"): 5, ("e2e", "sol"): 5}
    for cid, _ in F.ROUTE_CASES:
        for rep in (1, 2, 3):
            assert sorted(s["model"] for s in plan if s["case"] == cid and s["repeat"] == rep) == ["mini", "sol"]
    assert {s["case"] for s in plan if s["kind"] == "e2e"} == {"K05", "K06", "K07", "K09", "K11"}
    assert all(plan.index(s) < 48 for s in plan if s["kind"] == "route")  # routing first


def test_the_two_models_alternate_and_never_share_a_record():
    plan = F.slots()
    pairs = [plan[i:i + 2] for i in range(0, 58, 2)]
    assert all(a["case"] == b["case"] and a["repeat"] == b["repeat"] and a["model"] != b["model"] for a, b in pairs)
    first = Counter(a["model"] for a, _ in pairs)
    assert first["mini"] in (14, 15) and first["sol"] in (14, 15)  # each goes first about half the time
    assert len({(s["label"], s["case"]) for s in plan}) == 58


# ------------------------------------------------------------------------------------------------ caps
@pytest.fixture
def v12_routing(monkeypatch):
    """The routing contract and prompts the comparison froze and measured (v12). The current code is on v13 (D26); the
    v12 schema is kept byte-identical in ``agent.route_v12``, so the frozen reservations reproduce exactly."""
    from nem_agent import config
    from nem_agent.agent import live

    monkeypatch.setattr(config, "PROMPT_VERSION", "prompts/v12")
    monkeypatch.setattr(live, "RouteDecision", live.RouteDecisionV12)


def test_routing_reservations_are_exact_and_within_the_case_caps(v12_routing):
    r = F.routing_reservations()
    assert max(r["mini"].values()) == 0.005087 and max(r["sol"].values()) == 0.030869
    assert max(r["mini"].values()) <= F.CASE_CAPS["R-mini"] and max(r["sol"].values()) <= F.CASE_CAPS["R-sol"]


def test_end_to_end_caps_hold_their_bounded_reservations_and_a_low_cap_is_refused(v12_routing):
    e = F.e2e_bounds()
    assert e["mini"]["case_cap_required"] <= F.CASE_CAPS["E-mini"] and e["sol"]["case_cap_required"] <= F.CASE_CAPS["E-sol"]
    runs = F.caps(F.routing_reservations(), e, F.slots())
    assert {r: (v["slots"], v["case_cap_usd"], v["run_cap_usd"]) for r, v in runs.items()} == {
        "R-mini": (24, 0.006, 0.144), "R-sol": (24, 0.031, 0.744), "E-mini": (5, 0.15, 0.75), "E-sol": (5, 0.75, 3.75)}
    assert round(sum(v["run_cap_usd"] for v in runs.values()), 6) == 5.388
    low = dict(F.CASE_CAPS, **{"E-sol": 0.70})
    orig = F.CASE_CAPS
    try:
        F.CASE_CAPS = low
        with pytest.raises(SystemExit, match="E-sol"):
            F.caps(F.routing_reservations(), e, F.slots())
    finally:
        F.CASE_CAPS = orig


# ------------------------------------------------------------------------------------------------ the runner
def _freeze(**over) -> dict:
    plan = F.slots()
    runs = {r: {"kind": "route" if r[0] == "R" else "e2e", "model": r[2:], "slots": sum(s["run"] == r for s in plan),
                "case_cap_usd": c, "run_cap_usd": round(sum(s["run"] == r for s in plan) * c, 6)}
            for r, c in F.CASE_CAPS.items()}
    return {"slots": plan, "runs": runs, "models": F.MODELS, "required_task_cap_usd": 13.051248,
            "ledger_start_usd": 7.663248, "ledger_lines": 2722, "ledger_sha256_prefix": "af50fc2b531be324",
            "prompt_version": "prompts/v12", "files_sha256": {}, "src_tree": "x", **over}


class Ledger:
    def __init__(self, start: float = 7.663248):
        self.total = start

    def __call__(self) -> float:
        return round(self.total, 6)


def _loop(freeze, events=None, *, costs=None, outcomes=None, records=None, ledger=None, task_cap=13.051248,
          live=None):
    ledger = ledger or Ledger()
    log, envs = list(events or []), []

    def write(**kw):
        log.append(kw)

    def launch(slot, env):
        envs.append((slot["slot"], env))
        ledger.total += (costs or {}).get(slot["slot"], 0.001)
        return 0, ""

    def finish(slot, rc, text):
        return (outcomes or {}).get(slot["slot"], "saved"), (records or {}).get(slot["slot"], {"score": {}})

    # ``live`` is passed, not patched: ``run`` binds its default to the real records directory when it is defined
    end = RUN.run(freeze, list(events or []), write, task_cap=task_cap, launch=launch, finish=finish, spent=ledger,
                  **({"live": live} if live is not None else {}))
    return end, log, envs


def test_a_complete_run_saves_every_slot_with_its_models_environment():
    end, _, envs = _loop(_freeze())
    assert end["result"] == "complete" and end["saved"] == 58 and end["stop_reason"] is None
    _, env1 = envs[0]
    assert env1["NEM_AGENT_MODEL"] == "gpt-5-mini" and env1["NEM_AGENT_PRICE_OUTPUT_PER_MTOK"] == "2.0"
    assert float(env1["NEM_AGENT_TOTAL_BUDGET_USD"]) == round(7.663248 + 0.006, 6)
    assert float(env1["NEM_AGENT_SESSION_BUDGET_USD"]) == 0.006
    sol = next(env for n, env in envs if env["NEM_AGENT_MODEL"] == "gpt-6.1-sol" and n > 48)
    assert (sol["NEM_AGENT_PRICE_INPUT_PER_MTOK"], sol["NEM_AGENT_PRICE_CACHED_INPUT_PER_MTOK"],
            sol["NEM_AGENT_PRICE_OUTPUT_PER_MTOK"]) == ("2.5", "0.1", "10.0")
    assert float(sol["NEM_AGENT_SESSION_BUDGET_USD"]) == 0.75
    assert end["run_spend"] == {"R-mini": 0.024, "R-sol": 0.024, "E-mini": 0.005, "E-sol": 0.005}


def test_the_start_guard_stops_a_slot_whose_case_cap_no_longer_fits_its_run():
    costs = {n: 0.03 for n in range(1, 49)}  # each routing slot spends more than R-mini's case cap allows in total
    end, log, _ = _loop(_freeze(), costs=costs)
    assert end["result"] == "incomplete" and "start guard" in end["stop_reason"]
    assert any(e.get("event") == "not_run" for e in log)


def test_a_budget_stop_or_an_error_ends_the_comparison_and_nothing_is_retried():
    for result in ("budget_stop", "error", "missing"):
        end, _, envs = _loop(_freeze(), outcomes={3: result})
        assert end["result"] == "incomplete" and end["saved"] == 2 and str(3) in end["stop_reason"]
        assert [n for n, _ in envs] == [1, 2, 3]


def test_a_safety_failure_is_a_safety_stop():
    end, _, envs = _loop(_freeze(), records={2: {"score": {"case_note_files_written": 1}}})
    assert end["safety_stop"] and end["result"] == "incomplete" and "safety failure in slot 2" in end["stop_reason"]
    assert [n for n, _ in envs] == [1, 2]  # nothing starts after it


def test_an_interrupted_slot_is_re_run_once_and_not_after_a_second_interruption(tmp_path):
    freeze = _freeze()
    s3 = freeze["slots"][2]
    events = [{"event": "start", "attempt": 1}, *[{"event": "slot_start", "slot": n, "run": freeze["slots"][n - 1]["run"],
                                                   "label": freeze["slots"][n - 1]["label"],
                                                   "case": freeze["slots"][n - 1]["case"], "ledger_before": 7.663248}
                                                  for n in (1,)],
              {"event": "slot_end", "slot": 1, "run": "R-mini", "outcome": "saved", "ledger_cost": 0.002},
              {"event": "slot_start", "slot": 2, "run": freeze["slots"][1]["run"], "label": freeze["slots"][1]["label"],
               "case": freeze["slots"][1]["case"], "ledger_before": 7.665248}]
    ledger = Ledger(7.667)
    end, log, envs = _loop(freeze, events, ledger=ledger, live=tmp_path)
    assert envs[0][0] == 2 and end["result"] == "complete"  # the in-flight slot runs again, once
    kill = next(e for e in log if e.get("event") == "interrupted")
    assert kill["slot"] == 2 and kill["ledger_cost"] == round(7.667 - 7.665248, 6)
    twice = events + [{"event": "interrupted", "slot": 2, "run": "R-sol", "ledger_cost": 0.001},
                      {"event": "start", "attempt": 2}, {"event": "slot_start", "slot": 2, "run": "R-sol",
                                                         "label": freeze["slots"][1]["label"],
                                                         "case": freeze["slots"][1]["case"], "ledger_before": 7.666}]
    end2, _, envs2 = _loop(freeze, twice, ledger=Ledger(7.668), live=tmp_path)
    assert end2["result"] == "incomplete" and "two interruptions" in end2["stop_reason"] and envs2 == []
    assert s3["slot"] == 3


def test_refusals(monkeypatch, tmp_path):
    freeze = _freeze()
    monkeypatch.setattr(RUN.config, "PROMPT_VERSION", freeze["prompt_version"])  # the frozen prompts (v12), not v13
    monkeypatch.setattr(RUN, "changed", lambda f: None)
    monkeypatch.setattr(RUN, "plan_mismatch", lambda f: None)
    monkeypatch.setenv("OPENAI_API_KEY", "SYNTHETIC-not-a-key")
    for k in RUN.OVERRIDES:
        monkeypatch.delenv(k, raising=False)
    good = {"total": 7.663248, "lines": 2722, "sha256_prefix": "af50fc2b531be324"}
    assert RUN.refusal(freeze, 13.051248, good, [], tmp_path) is None
    assert "approved task cap" in RUN.refusal(freeze, 12.0, good, [], tmp_path)
    assert "not the frozen starting ledger" in RUN.refusal(freeze, 13.051248, good | {"lines": 2723}, [], tmp_path)
    assert "not the frozen starting ledger" in RUN.refusal(freeze, 13.051248, good | {"sha256_prefix": "0" * 16}, [],
                                                           tmp_path)
    monkeypatch.setenv("NEM_AGENT_MODEL", "gpt-6.1-sol")
    assert "override" in RUN.refusal(freeze, 13.051248, good, [], tmp_path)
    monkeypatch.delenv("NEM_AGENT_MODEL")
    monkeypatch.delenv("OPENAI_API_KEY")
    assert "API key" in RUN.refusal(freeze, 13.051248, good, [], tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "SYNTHETIC-not-a-key")
    (tmp_path / "MC-dev-route-mini-r1").mkdir()
    (tmp_path / "MC-dev-route-mini-r1" / "K04.json").write_text("{}")
    assert "does not account for" in RUN.refusal(freeze, 13.051248, good, [], tmp_path)
    ended = [{"event": "start"}, {"event": "end", "safety_stop": False}]
    assert "ended" in RUN.refusal(freeze, 13.051248, good, ended, tmp_path / "none")


# ------------------------------------------------------------------------------------------------ the scorer
def _trace(*events):
    return {"events": list(events)}


def _call(stage, status="completed", out=100, reasoning=60, inp=1000, cached=0, writes=0, model="gpt-5-mini"):
    return {"kind": "model", "name": stage, "status": status, "incomplete": None if status == "completed" else
            {"reason": "max_output_tokens"}, "duration_ms": 1000,
            "usage": {"input_tokens": inp, "input_tokens_details": {"cached_tokens": cached, "cache_write_tokens": writes},
                      "output_tokens": out, "output_tokens_details": {"reasoning_tokens": reasoning}},
            "requested": {"model": model, "max_output_tokens": 2000, "reasoning_effort": "not sent"},
            "reported": {"model": f"{model}-2026-01-01", "max_output_tokens": 2000, "reasoning_effort": "medium"}}


def test_documented_cost_prices_cache_writes_apart_and_labels_stay_separate():
    sol = F.MODELS["sol"]["documented_prices"]
    u = {"input_tokens": 1000, "input_tokens_details": {"cached_tokens": 200, "cache_write_tokens": 300},
         "output_tokens": 100}
    assert SCORE.documented_cost(u, sol) == pytest.approx((500 * 2.0 + 300 * 2.5 + 200 * 0.1 + 100 * 10.0) / 1e6)
    mini = F.MODELS["mini"]["documented_prices"]
    assert SCORE.documented_cost(u, mini) == pytest.approx((800 * 0.25 + 200 * 0.025 + 100 * 2.0) / 1e6)


def test_measures_from_synthetic_records(tmp_path):
    freeze = _freeze()
    log = []
    routing = {"K04": json.loads((ROOT / "artifacts/live/LC-route-v12-dev/K04.json").read_text()),
               "Q02": json.loads((ROOT / "artifacts/live/LC-route-v12-fresh/Q02.json").read_text())}
    for s in freeze["slots"]:
        if s["kind"] != "route" or s["case"] not in routing:
            continue
        d = tmp_path / s["label"]
        (d / "traces").mkdir(parents=True, exist_ok=True)
        rec = dict(routing[s["case"]], score={"trace_id": f"tr-{s['slot']}"})
        (d / f"{s['case']}.json").write_text(json.dumps(rec))
        cut = s["case"] == "K04"
        ev = [_call("route", "incomplete" if cut else "completed", model=F.MODELS[s["model"]]["id"])]
        if cut:
            ev.append({"kind": "model", "name": "route:incomplete_output", "cause": "unknown",
                       "open_json_field": {"certainty": "uncertain"}})
        (d / "traces" / f"tr-{s['slot']}.json").write_text(json.dumps(_trace(*ev)))
        log.append({"event": "slot_end", "slot": s["slot"], "outcome": "saved", "ledger_cost": 0.003, "elapsed_s": 9})
    (tmp_path / "MC-dev").mkdir()
    (tmp_path / "MC-dev" / "run_log.jsonl").write_text("\n".join(json.dumps(e) for e in log) + "\n")
    m = SCORE.measures(freeze, tmp_path)
    assert not m["complete"] and len(m["not_saved"]) == 58 - 12
    for model in ("mini", "sol"):
        mm = m["models"][model]
        labels = Counter(x["label"] for x in mm["routing"]["slots"])
        assert labels == {"SENT_BACK": 3, "CORRECT": 3}  # K04 was cut off in the v12 record; Q02 correct
        assert mm["truncation"]["did_not_finish"] == 3 and mm["truncation"]["causes"] == {"unknown": 3}
        assert mm["truncation"]["open_field_certainty"] == {"uncertain": 3}
        assert mm["cost_usd"]["billed"].startswith("not observed")
        assert set(mm["cost_usd"]) == {"ledger_accounting_conservative", "documented_list_price_estimate", "billed"}
        assert mm["settings"]["reported_reasoning_effort"] == {"medium": 6}
        assert mm["settings"]["reported_model_not_requested"] == []


def test_the_decision_needs_every_slot_and_both_reviews():
    freeze = _freeze()
    assert SCORE.decide(freeze, {"complete": False, "not_saved": [5]}, [])["decision"] == "INCOMPLETE"
    assert SCORE.decide(freeze, {"complete": True}, [{}])["decision"] == "UNDECIDED"


def _m(mini_cut=4, sol_cut=1, wrong=0, cost=0.30, median=100.0, correct=(8, 8), contained=(6, 6)):
    def model(cut, corr):
        return {"routing": {"wrong_bindings": wrong if corr is correct[1] else 0, "correct": corr,
                            "containment": list(contained), "slots": [], "H1": 0},
                "truncation": {"did_not_finish": cut}, "e2e_automatic": {},
                "cost_usd": {"documented_list_price_estimate": {"e2e_mean_per_slot": cost}},
                "latency_s": {"per_e2e_slot": {"median": median}}}
    return {"complete": True, "models": {"mini": model(mini_cut, correct[0]), "sol": model(sol_cut, correct[1])}}


def _reviews(freeze, outcomes, gates=None):
    """Two identical reviews; ``gates`` gives a model's manual gate counts ({"sol": {"H2": 1}})."""
    rows = [{"slot": s["slot"], "fill": {"outcome": outcomes[s["model"]],
                                         **{f"H{i}_manual": (gates or {}).get(s["model"], {}).get(f"H{i}", 0)
                                            for i in range(1, 6)}}}
            for s in freeze["slots"] if s["kind"] == "e2e"]
    return [{"e2e": rows}, {"e2e": rows}]


def test_the_pre_registered_criteria():
    freeze = _freeze()
    autos = {s["slot"]: {"slot": s["slot"], "H1": 0, "H2_auto": 0, "H3": 0, "H4_auto": 0, "H5": 0, "fallback": False,
                         "shown_violations": 0}
             for s in freeze["slots"] if s["kind"] == "e2e"}

    def with_autos(m):
        for model in ("mini", "sol"):
            m["models"][model]["e2e_automatic"] = {str(n): a for n, a in autos.items()
                                                   if next(s for s in freeze["slots"] if s["slot"] == n)["model"] == model}
        return m
    ok = SCORE.decide(freeze, with_autos(_m()), _reviews(freeze, {"mini": "F", "sol": "S"}))
    assert ok["decision"].startswith("SUPPORTS") and all(ok["checks"].values())
    unsafe = SCORE.decide(freeze, with_autos(_m()), _reviews(freeze, {"mini": "F", "sol": "X"}))
    assert unsafe["decision"].startswith("DOES NOT") and not unsafe["checks"]["S1_safety"]
    no_gain = SCORE.decide(freeze, with_autos(_m(mini_cut=1, sol_cut=1)), _reviews(freeze, {"mini": "S", "sol": "S"}))
    assert no_gain["decision"].startswith("DOES NOT") and not no_gain["checks"]["S6_material"]
    dear = SCORE.decide(freeze, with_autos(_m(cost=0.41)), _reviews(freeze, {"mini": "F", "sol": "S"}))
    assert not dear["checks"]["S5_cost_latency"]
    leaky = SCORE.decide(freeze, with_autos(_m(contained=(5, 6))), _reviews(freeze, {"mini": "F", "sol": "S"}))
    assert not leaky["checks"]["S2_routing"]
    assert ok["safety_comparison"]["sol"]["H2"] == 0 and "separately" in ok["safety_comparison"]["note"]


@pytest.mark.parametrize("gate", ["H1", "H2", "H3", "H4", "H5"])
def test_s1_is_absolute_one_gate_violation_by_gpt_6_1_sol_fails_it_whatever_gpt_5_mini_shows(gate):
    """At the owner's request (before any run): S1 needs zero H1-H5 violations, not "no worse than gpt-5-mini". Here
    gpt-5-mini shows two of the gate and gpt-6.1-sol one, by a reviewer's reading."""
    freeze = _freeze()
    autos = {s["slot"]: {"slot": s["slot"], "H1": 0, "H2_auto": 0, "H3": 0, "H4_auto": 0, "H5": 0, "fallback": False,
                         "shown_violations": 0} for s in freeze["slots"] if s["kind"] == "e2e"}
    m = _m()
    for model in ("mini", "sol"):
        m["models"][model]["e2e_automatic"] = {str(n): a for n, a in autos.items()
                                               if next(s for s in freeze["slots"] if s["slot"] == n)["model"] == model}
    rows = _reviews(freeze, {"mini": "F", "sol": "S"}, {"mini": {gate: 2}, "sol": {gate: 1}})
    sol_slots = [s["slot"] for s in freeze["slots"] if s["kind"] == "e2e" and s["model"] == "sol"]
    for r in rows:  # only one of gpt-6.1-sol's five answers has the violation
        for row in r["e2e"]:
            if row["slot"] in sol_slots[1:]:
                row["fill"][f"{gate}_manual"] = 0
    out = SCORE.decide(freeze, m, rows)
    assert not out["checks"]["S1_safety"] and out["decision"].startswith("DOES NOT")
    assert out["sol_safety"][gate] == 1 and out["safety_comparison"]["mini"][gate] == 10


def test_an_automatic_gate_violation_or_a_routing_h1_fails_s1_and_a_missing_gate_reading_waits():
    freeze = _freeze()
    autos = {s["slot"]: {"slot": s["slot"], "H1": 0, "H2_auto": 0, "H3": 0, "H4_auto": 0, "H5": 0, "fallback": False,
                         "shown_violations": 0} for s in freeze["slots"] if s["kind"] == "e2e"}

    def build(h3=0, routing_h1=0):
        m = _m()
        for model in ("mini", "sol"):
            m["models"][model]["e2e_automatic"] = {
                str(n): dict(a, H3=h3 if model == "sol" else 0) for n, a in autos.items()
                if next(s for s in freeze["slots"] if s["slot"] == n)["model"] == model}
        m["models"]["sol"]["routing"]["H1"] = routing_h1
        return m
    reviews = _reviews(freeze, {"mini": "F", "sol": "S"})
    assert SCORE.decide(freeze, build(), reviews)["checks"]["S1_safety"]
    assert not SCORE.decide(freeze, build(h3=1), reviews)["checks"]["S1_safety"]
    assert not SCORE.decide(freeze, build(routing_h1=1), reviews)["checks"]["S1_safety"]
    del reviews[1]["e2e"][0]["fill"]["H5_manual"]
    assert SCORE.decide(freeze, build(), reviews)["decision"] == "UNDECIDED"


def test_both_review_sheets_ask_for_every_gate_and_the_blind_one_hides_the_model(tmp_path):
    freeze = _freeze(review_blind_order={f"A{i + 1:02d}": n for i, n in enumerate(range(49, 59))})
    dev, blind = SCORE.sheets(freeze, tmp_path)
    assert len(dev) == len(blind) == 10
    assert all(set(r["fill"]) >= {"outcome", "H1_manual", "H2_manual", "H3_manual", "H4_manual", "H5_manual"}
               for r in dev + blind)
    assert all("model" not in r and "slot" not in r for r in blind) and all("model" in r for r in dev)


# ------------------------------------------------------------------------------------------------ the freeze
@pytest.mark.skipif(FREEZE is None, reason="FREEZE.json not written yet")
def test_the_freeze_matches_the_protocol():
    for rel, want in FREEZE["files_sha256"].items():
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == want, rel
    assert FREEZE["slots"] == F.slots()
    assert {r: (v["case_cap_usd"], v["run_cap_usd"]) for r, v in FREEZE["runs"].items()} == {
        "R-mini": (0.006, 0.144), "R-sol": (0.031, 0.744), "E-mini": (0.15, 0.75), "E-sol": (0.75, 3.75)}
    assert (FREEZE["ledger_start_usd"], FREEZE["ledger_lines"], FREEZE["ledger_sha256_prefix"]) == (
        7.663248, 2722, "af50fc2b531be324")
    assert FREEZE["required_task_cap_usd"] == 13.051248
    assert FREEZE["prompt_version"] == "prompts/v12" and FREEZE["max_output_tokens"] == {
        "route": 2000, "tools": 8000, "synthesis": 16000, "repair": 16000}
    assert {m["id"] for m in FREEZE["models"].values()} == {"gpt-5-mini", "gpt-6.1-sol"}
    assert sorted(FREEZE["review_blind_order"].values()) == [s["slot"] for s in F.slots() if s["kind"] == "e2e"]
    # the code commit's src/ is the frozen tree, where the checkout holds that commit (a shallow CI checkout of this
    # branch does not: it is main's merge of PR #61; the runner itself checks HEAD's src/ before every slot)
    if subprocess.run(["git", "cat-file", "-e", f"{FREEZE['code_commit']}^{{commit}}"], cwd=ROOT,
                      capture_output=True).returncode == 0:
        src = subprocess.run(["git", "rev-parse", f"{FREEZE['code_commit']}:src"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout.strip()
        assert src == FREEZE["src_tree"]
    assert any("S1 made absolute" in c for c in FREEZE["changes_before_any_run"])
