"""Freeze the comparison (PROTOCOL.md, "Caps and accounting"; "Slots, stops and completeness"). Offline; no model call.

Writes `FREEZE.json`:
- **the code:** the commit, its `src/` tree (which must be `main` `76c4341`'s) and the prompts v16 and v17 trees;
- **the arms:** each arm's environment, route contract and prompts, checked on the actual controller;
- **the reservations:** each configuration's worst-case reservation in each arm, measured on the actual runner code
  path (``run_route.route_call``; ``budget.reserve`` captured, which stops the call before anything is sent and
  writes nothing to any ledger);
- **the order:** the 161 (configuration, repeat) pairs shuffled once (``ORDER_SEED``), each pair's two arms adjacent in
  an order drawn from the same generator, so the arms interleave throughout;
- **the run cap:** the exact sum of the 322 slot reservations, refused above USD 2.00 (``MAX_PREPARED_USD``);
- **the denominators:** from the frozen gold (`GOLD.json`): the answerable held-out configurations, the availability
  and incomplete-rate denominators, and the infrastructure threshold;
- **the accounting paths**, and the SHA-256 of every frozen file;
- **the amendment** it is frozen under (AMENDMENT_1.md, before any run), and the freeze it supersedes, kept
  unchanged as `FREEZE_1.json`.

Usage: .venv/bin/python eval/compare_route_v15_v16/freeze.py [--check]   (--check: recompute and compare, write nothing)
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import random
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "src"))

from nem_agent import budget, config  # noqa: E402

BASE_COMMIT = "76c4341"  # main after D31 (PR #80): the code both arms run
ORDER_SEED = 20261005
MAX_PREPARED_USD = 2.00  # the maximum approved budget prepared against; not an authorization to spend
LABEL = "CMP-route-v15-v16-run"
AMENDMENT = "AMENDMENT_1.md (before any run)"
SUPERSEDES = {"commit": "6c06348fb3953f1c45bdf99692b38df12b95ef70", "file": "FREEZE_1.json"}  # the first freeze
ARM_CONTRACT = {"A": ("v15", config.PROMPT_VERSION), "B": ("v16", config.PLAN_PROMPT_VERSION)}
FROZEN_FILES = ("PROTOCOL.md", "AMENDMENT_1.md", "FREEZE_1.json", "CAPABILITIES.md", "GOLD_FORMAT.md", "WRITER_BRIEF.md", "REVIEW_BRIEF.md",
                "RECONCILE_BRIEF.md", "PROVENANCE.md", "WRITER_REPORT.md", "REVIEW_REPORT.md", "WRITER_OUTPUT.json",
                "REVIEW.json", "REVIEW_IDS.json",
                "RECONCILED.json", "GOLD.json", "cases.json", "configs.py", "gold.py", "build_kit.py", "run_route.py",
                "run_eval.py", "score.py", "freeze.py")
TEST_FILE = "tests/eval/test_compare_route_v15_v16.py"


def _sibling(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"compare_route_v15_v16_{name}", HERE / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class _Captured(budget.BudgetExceeded):
    pass


def measure_reservations(cases: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Each configuration's reservation in each arm, from ``budget.reserve`` on the runner's own path. The capture
    raises before the transport is reached, so nothing is sent and no ledger is written."""
    rr = _sibling("run_route")
    captured: list[tuple[str, str, float]] = []

    def capture(model: str, stage: str, worst_case_usd: float) -> str:
        captured.append((model, stage, worst_case_usd))
        raise _Captured("reservation captured")

    saved_env = {k: os.environ.get(k) for k in rr.PLAN_SETTINGS}
    saved_reserve = budget.reserve
    budget.reserve = capture
    out: dict[str, dict[str, float]] = {}
    try:
        for arm in ("A", "B"):
            for k in rr.PLAN_SETTINGS:
                os.environ.pop(k, None)
            os.environ.update(rr.ARM_ENV[arm])
            for c in cases:
                captured.clear()
                with contextlib.suppress(_Captured):
                    rr.route_call(c, arm, client=_NoTransport(), write_trace=False)
                if len(captured) != 1 or captured[0][1] != "route" or captured[0][0] != live_model():
                    raise SystemExit(f"{c['config']} arm {arm}: expected one routing reservation, got {captured}")
                out.setdefault(c["config"], {})[arm] = captured[0][2]
    finally:
        budget.reserve = saved_reserve
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return out


class _NoTransport:
    def create(self, **kw: Any) -> Any:
        raise AssertionError("the reservation capture must stop the call before the transport")


def live_model() -> str:
    from nem_agent.agent.live import model_id_from_env

    return model_id_from_env()


def arm_check() -> dict[str, dict[str, Any]]:
    """Each arm's route contract and prompts, read from the actual controller under its environment."""
    rr = _sibling("run_route")
    from nem_agent.agent.live import LiveController
    from nem_agent.evidence import EvidenceRegistry
    from nem_agent.report import Versions

    out = {}
    saved = {k: os.environ.get(k) for k in rr.PLAN_SETTINGS}
    try:
        for arm in ("A", "B"):
            for k in rr.PLAN_SETTINGS:
                os.environ.pop(k, None)
            os.environ.update(rr.ARM_ENV[arm])
            lc = LiveController(None, EvidenceRegistry(), Versions(code="", data="", corpus="", prompt="", model=None,
                                                                   controller="live"), client=_NoTransport())
            got = ("v16" if lc.request_plan else "v15", lc.prompt_version)
            if got != ARM_CONTRACT[arm]:
                raise SystemExit(f"arm {arm} runs {got}, expected {ARM_CONTRACT[arm]}")
            out[arm] = {"env": dict(rr.ARM_ENV[arm]), "route_contract": got[0], "prompt_version": got[1]}
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return out


def plan_slots(cases: list[dict[str, Any]], reservations: dict[str, dict[str, float]],
               seed: int = ORDER_SEED) -> list[dict[str, Any]]:
    """The frozen order: (configuration, repeat) pairs shuffled once, each pair's arms adjacent in a drawn order."""
    rng = random.Random(seed)
    pairs = [(c, r) for c in cases for r in range(1, c["repeats"] + 1)]
    rng.shuffle(pairs)
    slots: list[dict[str, Any]] = []
    for c, r in pairs:
        arms = ["A", "B"]
        rng.shuffle(arms)
        for arm in arms:
            slots.append({"slot": len(slots) + 1, "config": c["config"], "set": c["set"], "arm": arm, "repeat": r,
                          "case": f"{len(slots) + 1:03d}-{arm}-{c['config']}-r{r}",
                          "reservation_usd": reservations[c["config"]][arm]})
    return slots


def denominators(gold: list[dict[str, Any]], cases: list[dict[str, Any]]) -> dict[str, Any]:
    sets = {c["config"]: c["set"] for c in cases}
    reps = {c["config"]: c["repeats"] for c in cases}
    answerable = sorted(g["config"] for g in gold if sets[g["config"]] == "heldout" and g["answerable"])
    heldout = [c for c in cases if c["set"] in ("heldout", "control")]
    per_arm = sum(reps.values())
    return {"answerable_heldout_configs": answerable, "answerable_heldout_questions": len(answerable),
            "availability_slots_per_arm": sum(reps[c] for c in answerable),
            "incomplete_rate_slots_per_arm": sum(c["repeats"] for c in heldout),
            "control_slots_per_arm": sum(c["repeats"] for c in cases if c["set"] == "control"),
            "slots_per_arm": per_arm, "infrastructure_threshold": {"share": 0.05, "max_count": int(per_arm * 0.05)}}


def supersedes() -> dict[str, Any]:
    """The first freeze, kept unchanged as FREEZE_1.json: its commit, hash and what it froze."""
    first_p = HERE / SUPERSEDES["file"]
    first = json.loads(first_p.read_text())
    return {**SUPERSEDES, "sha256": _sha(first_p), "frozen_at": first["frozen_at"],
            "code_commit": first["code_commit"], "run_cap_usd": first["run_cap_usd"]}


def frozen_files() -> dict[str, str]:
    out = {}
    for name in FROZEN_FILES:
        p = HERE / name
        if p.exists():
            out[str(p.relative_to(REPO))] = _sha(p)
    t = REPO / TEST_FILE
    if t.exists():
        out[TEST_FILE] = _sha(t)
    return out


def build() -> dict[str, Any]:
    for k in ("NEM_AGENT_MODEL", "NEM_AGENT_PRICE_INPUT_PER_MTOK", "NEM_AGENT_PRICE_CACHED_INPUT_PER_MTOK",
              "NEM_AGENT_PRICE_OUTPUT_PER_MTOK", "NEM_AGENT_ROUTE_PLAN", "NEM_AGENT_PLAN_POLICY", "NEM_AGENT_HOME"):
        if os.environ.get(k):
            raise SystemExit(f"refused: {k} is set; the freeze measures the defaults")
    src_tree, base_tree = _git("rev-parse", "HEAD:src"), _git("rev-parse", f"{BASE_COMMIT}:src")
    if src_tree != base_tree or _git("status", "--porcelain", "--", "src"):
        raise SystemExit(f"refused: src/ is not {BASE_COMMIT}'s tree ({src_tree} / {base_tree}) or is modified")
    cfg = _sibling("configs")
    gold = json.loads((HERE / "GOLD.json").read_text())["cases"]
    cases = json.loads((HERE / "cases.json").read_text())["cases"]
    if sorted(c["config"] for c in cases) != sorted(g["config"] for g in gold):
        raise SystemExit("refused: cases.json and GOLD.json hold different configurations")
    if any(c["repeats"] != cfg.REPEATS[c["set"]] for c in cases):
        raise SystemExit("refused: a configuration's repeats are not its set's")
    reservations = measure_reservations(cases)
    slots = plan_slots(cases, reservations)
    run_cap = round(sum(s["reservation_usd"] for s in slots), 6)
    if run_cap > MAX_PREPARED_USD:
        raise SystemExit(f"refused: the run cap USD {run_cap} is above the USD {MAX_PREPARED_USD} prepared against")
    prices = budget.prices(live_model())
    assert prices is not None
    return {
        "protocol": "eval/compare_route_v15_v16/PROTOCOL.md, as amended by AMENDMENT_1.md",
        "amendment": AMENDMENT, "supersedes": supersedes(),
        "frozen_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "code_commit": _git("rev-parse", "HEAD"), "base_commit": _git("rev-parse", BASE_COMMIT), "src_tree": src_tree,
        "prompts_trees": {v: _git("rev-parse", f"HEAD:src/nem_agent/prompts/{v}") for v in ("v16", "v17")},
        "model": live_model(), "route_max_output_tokens": config.MAX_OUTPUT_TOKENS["route"],
        "reasoning_effort_sent": None,
        "accounting_prices_per_mtok": {"input": prices[0], "cached_input": prices[1], "output": prices[2]},
        "arms": arm_check(),
        "reservations_usd": reservations,
        "reservation_method": "measured on each configuration's routing request in each arm on the runner's own path "
                              "(run_route.route_call; budget.reserve captured before the transport; nothing written)",
        "label": LABEL, "order_seed": ORDER_SEED,
        "order_method": "(configuration, repeat) pairs shuffled once; each pair's two arms adjacent, their order drawn "
                        "from the same generator",
        "slots": slots, "run_cap_usd": run_cap, "max_prepared_usd": MAX_PREPARED_USD,
        "run_cap_note": "the exact sum of the slot reservations; neither it nor the USD 2.00 prepared against "
                        "authorizes any spend",
        "denominators": denominators(gold, cases),
        "accounting_paths": {
            "historical": {"ledger": "artifacts/live_budget/ledger.jsonl (default)",
                           "required_state": {"total": 9.336937, "lines": 3226, "sha256_prefix": "f303c2bc70aadd8f"},
                           "status": "not found on the preparing machine"},
            "evaluation": {"ledger": "artifacts/live_budget/CMP-route-v15-v16.ledger.jsonl",
                           "required_state": "absent or empty at the first start"}},
        "files_sha256": frozen_files(),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="recompute and compare with FREEZE.json; write nothing")
    args = ap.parse_args()
    out = build()
    if args.check:
        old = json.loads((HERE / "FREEZE.json").read_text())
        keys = ("src_tree", "prompts_trees", "model", "arms", "reservations_usd", "slots", "run_cap_usd",
                "denominators", "files_sha256", "amendment", "supersedes")
        diff = [k for k in keys if old.get(k) != out[k]]
        print("FREEZE.json matches" if not diff else f"FREEZE.json differs in: {diff}")
        return 1 if diff else 0
    (HERE / "FREEZE.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({"run_cap_usd": out["run_cap_usd"], "slots": len(out["slots"]),
                      "denominators": {k: v for k, v in out["denominators"].items()
                                       if k != "answerable_heldout_configs"}}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
