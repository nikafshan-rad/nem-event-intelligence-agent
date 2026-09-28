"""The pre-registered interruption rule (eval/holdout_v4/PASS_RULE.md), as applied by scripts/live_resumable.py.
Pure planning logic only: nothing is started and no key is needed."""

from __future__ import annotations

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("live_resumable",
                                              Path(__file__).resolve().parents[2] / "scripts" / "live_resumable.py")
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
plan_attempt = mod.plan_attempt
IDS = ["W01", "W02", "W03", "W04"]


def test_a_fresh_run_starts_every_case():
    plan, att = plan_attempt(IDS, set(), set(), [], "t0")
    assert plan == {"action": "run", "remaining": IDS} and att[-1]["n"] == 1 and att[-1]["rerun_after_interruption"] is None


def test_a_killed_run_resumes_without_repeating_saved_cases():
    _, att = plan_attempt(IDS, set(), set(), [], "t0")                  # attempt 1 is killed while W03 runs
    plan, att = plan_attempt(IDS, {"W01", "W02"}, set(), att, "t1")
    assert att[0]["interrupted_case"] == "W03"
    assert plan["remaining"] == ["W03", "W04"] and att[-1]["rerun_after_interruption"] == "W03"


def test_a_second_kill_of_the_same_case_is_incomplete():
    _, att = plan_attempt(IDS, set(), set(), [], "t0")
    _, att = plan_attempt(IDS, {"W01", "W02"}, set(), att, "t1")        # W03 interrupted once, re-run ...
    plan, att = plan_attempt(IDS, {"W01", "W02"}, set(), att, "t2")     # ... and interrupted again
    assert plan["action"] == "incomplete" and "W03" in plan["reason"] and len(att) == 2  # no third start


def test_kills_of_different_cases_are_each_allowed_once():
    _, att = plan_attempt(IDS, set(), set(), [], "t0")
    _, att = plan_attempt(IDS, {"W01"}, set(), att, "t1")               # W02 interrupted
    plan, att = plan_attempt(IDS, {"W01", "W02", "W03"}, set(), att, "t2")  # W04 interrupted
    assert plan["action"] == "run" and plan["remaining"] == ["W04"]


def test_an_error_or_a_budget_stop_is_incomplete_and_not_retried():
    plan, _ = plan_attempt(IDS, {"W01"}, {"W02"}, [], "t0")
    assert plan["action"] == "incomplete" and "W02" in plan["reason"]
    att = [{"n": 1, "started_at": "t0", "remaining": IDS, "ended_at": "t1", "result": "stopped"}]
    plan, _ = plan_attempt(IDS, {"W01"}, set(), att, "t2")
    assert plan["action"] == "incomplete" and "stopped" in plan["reason"]


def test_a_finished_run_starts_nothing():
    att = [{"n": 1, "started_at": "t0", "remaining": IDS, "ended_at": "t1", "result": "ok"}]
    plan, att2 = plan_attempt(IDS, set(IDS), set(), att, "t2")
    assert plan == {"action": "done", "remaining": []} and att2 == att
