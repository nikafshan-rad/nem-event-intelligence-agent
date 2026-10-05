"""Offline verification of the second development-only Live check (eval/live_check_dev2), before any paid call.

- **Budget:** each case and the run are capped before every model call, by the ledger's reservation of the call's
  worst case. Open reservations and interrupted calls count at their worst case. A refused call is never sent.
- **Case cap:** USD 0.10 cannot safely hold W19. Its 2026-09-30 run peaked at USD 0.0974 committed (spent so far plus
  the next call's reservation), and one more tool turn would be refused at 0.10. USD 0.15 holds it.
- **Runner:** its stops, start guard, coverage report and refusals.
- **Checker:** the frozen rules give the expected verdicts on offline replays, fail the controls, and reproduce the
  original failures on the saved pre-fix Live records.

The fake transport is SYNTHETIC (no network, no key), and the ledger is a per-test scratch file (conftest). Scripted
replays are not a measure of Live behaviour.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from nem_agent import budget
from nem_agent.budget import BudgetExceeded
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

REPO = Path(__file__).resolve().parents[2]
HERE = REPO / "eval" / "live_check_dev2"
LIVE = REPO / "artifacts" / "live"
C0929, C0930 = LIVE / "live-check-2026-09-29", LIVE / "live-check-p1-dev"
MODEL = "gpt-5-mini"
# W19, 2026-09-30 (trace tr-b09af6da7d95): each call's reservation and settled cost, in order, from the ledger
W19_CALLS = [("route", 0.004444, 0.000825), ("tools", 0.0175, 0.003554), ("tools", 0.024655, 0.014403),
             ("tools", 0.027702, 0.006285), ("tools", 0.028677, 0.002971), ("synthesis", 0.047242, 0.019967),
             ("repair", 0.04935, 0.017735)]


def _load(name: str, path: Path) -> Any:
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RUN = _load("dev2_run_check", HERE / "run_check.py")
CHECK = _load("dev2_check_case", HERE / "check_case.py")
FREEZE: dict[str, Any] = json.loads((HERE / "FREEZE.json").read_text()) if (HERE / "FREEZE.json").exists() else {}


# ------------------------------------------------------------------------------------------------ the ledger
def _play(calls: list[tuple[str, float, float]], cap: float) -> tuple[int, float]:
    """Reserve and settle ``calls`` in order under ``cap``; returns (calls completed, peak committed)."""
    peak = 0.0
    for i, (stage, worst, actual) in enumerate(calls):
        try:
            rid = budget.reserve(MODEL, stage, worst)
        except BudgetExceeded:
            return i, peak
        peak = max(peak, budget.spent())
        assert peak <= cap + 1e-9  # never above the cap, at any moment
        budget.settle(rid, actual)
    return len(calls), peak


def test_w19_peaks_at_its_committed_total_not_its_cost(monkeypatch):
    monkeypatch.setenv("NEM_AGENT_TOTAL_BUDGET_USD", "5.0")
    done, peak = _play(W19_CALLS, 5.0)
    assert done == 7 and peak == pytest.approx(0.097355) and budget.spent() == pytest.approx(0.06574)


def test_a_ten_cent_case_cap_cannot_safely_hold_w19(monkeypatch):
    """W19's run fits under USD 0.10 by USD 0.0026. With one more tool turn (its own third turn again, and a little
    more input after it), bringing it to the eight model calls the controller allows, the ledger refuses its repair
    call at 0.10, before it is sent, and the case is incomplete. At 0.15 both complete (peak USD 0.1138)."""
    longer = [*W19_CALLS[:5], ("tools", 0.030, 0.014403), *[(s, w + 0.002, a) for s, w, a in W19_CALLS[5:]]]
    for calls, cap, completed in ((W19_CALLS, 0.10, 7), (longer, 0.10, 7), (W19_CALLS, 0.15, 7), (longer, 0.15, 8)):
        monkeypatch.setenv("NEM_AGENT_BUDGET_LEDGER", str(Path(budget.ledger_path()).with_name(f"l{cap}{len(calls)}")))
        monkeypatch.setenv("NEM_AGENT_TOTAL_BUDGET_USD", str(cap))
        assert _play(calls, cap)[0] == completed, (len(calls), cap)


def test_open_reservations_and_interrupted_calls_count_at_worst_case(monkeypatch):
    """A reservation never settled (a crashed process, or another process's call in flight) and a call settled at
    its worst case (a timeout) both count against the cap before the next call is reserved."""
    monkeypatch.setenv("NEM_AGENT_TOTAL_BUDGET_USD", "0.15")
    budget.reserve(MODEL, "synthesis", 0.047242)  # never settled
    rid = budget.reserve(MODEL, "repair", 0.04935)
    budget.settle(rid, 0.04935)  # outcome unknown: settled at its worst case
    assert budget.spent() == pytest.approx(0.096592)
    with pytest.raises(BudgetExceeded):
        budget.reserve(MODEL, "repair", 0.0535)  # would fit without the open reservation
    budget.reserve(MODEL, "tools", 0.0534)


# ------------------------------------------------------------------------------------------------ the controller
def _rec(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _fake(path: Path, *, first_draft: bool = False, delete: str | None = None) -> FakeModel:
    rec = _rec(path)
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    patch: dict[str, Any] | None = None
    if first_draft:
        trace = _rec(path.parent / "traces" / f"{rec['score']['trace_id']}.json")
        patch = next(e for e in trace["events"] if e["name"] == "repair:scoped")["patch"]
        if delete:
            patch = {**patch, "edits": [e for e in patch["edits"] if not e["target"].startswith(delete)] +
                     [{"target": delete, "action": "delete", "text": None, "statement": None, "claim": None,
                       "citation": None}]}
    draft = rec["drafts"]["synthesis:draft"] if first_draft else (rec["drafts"].get("repair:draft")
                                                                  or rec["drafts"]["synthesis:draft"])
    return FakeModel(rec["route"], [calls], lambda kw: copy.deepcopy(draft),
                     (lambda kw: copy.deepcopy(patch)) if patch else None)


class _Sending(FakeModel):
    """Records, for each request sent, whether the ledger held an open reservation for it at that moment."""

    def __init__(self, inner: FakeModel, fail_stage: str | None = None) -> None:
        self.__dict__.update(inner.__dict__)
        self.inner, self.fail_stage = inner, fail_stage
        self.reserved_first: list[bool] = []

    def create(self, **kw: Any) -> dict[str, Any]:
        rows = [json.loads(ln) for ln in Path(budget.ledger_path()).read_text().splitlines() if ln.strip()]
        settled = {r["id"] for r in rows if r["kind"] == "settle"}
        self.reserved_first.append(bool(rows) and rows[-1]["kind"] == "reserve" and rows[-1]["id"] not in settled)
        fmt = (kw.get("text") or {}).get("format", {}).get("name")
        if self.fail_stage == "synthesis" and fmt in ("ModelReport", "DocumentReport"):
            raise TimeoutError("SYNTHETIC timeout after the request was sent")
        out = self.inner.create(**kw)
        self.requests = self.inner.requests
        return out


def _investigate(path: Path, client: Any, **kw: Any):
    from nem_agent.agent.request import InvestigateRequest
    from nem_agent.service import investigate

    return investigate(InvestigateRequest(question=_rec(path)["question"], mode="live"), live_client=client,
                       write_trace=False)


def _reservations() -> list[dict[str, Any]]:
    rows = [json.loads(ln) for ln in Path(budget.ledger_path()).read_text().splitlines() if ln.strip()]
    return [r for r in rows if r["kind"] == "reserve"]


def test_every_request_is_reserved_before_it_is_sent(monkeypatch):
    monkeypatch.setenv("NEM_AGENT_TOTAL_BUDGET_USD", "1.0")
    client = _Sending(_fake(C0930 / "W19.json", first_draft=True))
    _investigate(C0930 / "W19.json", client)
    assert client.reserved_first and all(client.reserved_first)
    assert len(_reservations()) == len(client.inner.requests)


def test_a_call_the_case_cap_refuses_is_never_sent(monkeypatch):
    """The case cap set just below what the synthesis call needs: that call is refused by the ledger, not sent, and
    the runner reads the case as a budget stop."""
    monkeypatch.setenv("NEM_AGENT_TOTAL_BUDGET_USD", "1.0")
    _investigate(C0930 / "W19.json", _fake(C0930 / "W19.json", first_draft=True))
    first = _reservations()
    i = next(n for n, r in enumerate(first) if r["stage"] == "synthesis")
    rows = [json.loads(ln) for ln in Path(budget.ledger_path()).read_text().splitlines() if ln.strip()]
    settle = {r["id"]: r["usd"] for r in rows if r["kind"] == "settle"}
    need = sum(settle[r["id"]] for r in first[:i]) + first[i]["usd"]
    monkeypatch.setenv("NEM_AGENT_BUDGET_LEDGER", str(Path(budget.ledger_path()).with_name("case.jsonl")))
    monkeypatch.setenv("NEM_AGENT_TOTAL_BUDGET_USD", f"{need - 0.0005:.6f}")
    client = _Sending(_fake(C0930 / "W19.json", first_draft=True))
    res = _investigate(C0930 / "W19.json", client)
    sent = [(r.get("text") or {}).get("format", {}).get("name") for r in client.inner.requests]
    assert "ModelReport" not in sent and len(client.inner.requests) == i == len(_reservations())
    assert budget.spent() <= need - 0.0005
    trace = res.trace.as_dict()
    assert RUN.outcome("", 0, True, trace) == "budget_stop"


def test_an_open_reservation_can_stop_a_case_before_its_first_call(monkeypatch):
    monkeypatch.setenv("NEM_AGENT_TOTAL_BUDGET_USD", "0.15")
    budget.reserve(MODEL, "repair", 0.148)  # another process's call in flight, or a crash
    client = _Sending(_fake(C0930 / "W19.json", first_draft=True))
    with pytest.raises(BudgetExceeded):
        _investigate(C0930 / "W19.json", client)
    assert client.inner.requests == []  # nothing sent; live_diagnose prints STOPPED, the runner stops the run
    assert RUN.outcome("[W19] STOPPED: task budget", 0, False, None) == "budget_stop"


def test_an_interrupted_call_is_counted_at_its_worst_case_and_ends_the_run(monkeypatch):
    monkeypatch.setenv("NEM_AGENT_TOTAL_BUDGET_USD", "1.0")
    client = _Sending(_fake(C0930 / "W19.json", first_draft=True), fail_stage="synthesis")
    with pytest.raises(TimeoutError):
        _investigate(C0930 / "W19.json", client)
    rows = [json.loads(ln) for ln in Path(budget.ledger_path()).read_text().splitlines() if ln.strip()]
    syn = next(r for r in rows if r["kind"] == "reserve" and r["stage"] == "synthesis")
    assert next(r for r in rows if r["kind"] == "settle" and r["id"] == syn["id"])["usd"] == syn["usd"]
    assert RUN.outcome("[W19] ERROR TimeoutError", 0, False, None) == "error"


# ------------------------------------------------------------------------------------------------ the runner
PLAN = [["F01", "c1"], ["F03", "c1"], ["W18", "c2"], ["W19", "c2"], ["F04", "c1"], ["W04", "c2"]]
BASE = {"cases": PLAN, "required": ["F01", "F03", "W18", "W19"], "run_cap_usd": 0.30, "case_cap_usd": 0.15,
        "model": MODEL, "prompt_version": "prompts/v11", "code_commit": "x", "src_tree": "y",
        "files_sha256": {"eval/live_check_dev2/PROTOCOL.md": "z"}}


def _simulate(costs: dict[str, float], tmp: Path, results: dict[str, str] | None = None,
              safety: dict[str, list] | None = None, moved_before: str | None = None,
              ) -> tuple[dict[str, Any], list[dict[str, Any]], list[tuple[str, float]]]:
    ledger = [4.591922]
    log: list[dict[str, Any]] = []
    launched: list[tuple[str, float]] = []

    def launch(cid: str, cases_file: str, env: dict[str, str]) -> tuple[int, str]:
        cap = float(env["NEM_AGENT_TOTAL_BUDGET_USD"])
        launched.append((cid, round(cap - ledger[0], 6)))
        assert ledger[0] + costs[cid] <= cap + 1e-9  # the ledger would refuse anything above the case cap
        ledger[0] = round(ledger[0] + costs[cid], 6)
        kind = (results or {}).get(cid, "saved")
        if kind == "saved":
            (tmp / f"{cid}.json").write_text(json.dumps({"score": {"trace_id": None}}))
        return (1 if kind == "error" else 0), {"saved": "", "error": "[x] ERROR Timeout", "budget_stop": "[x] STOPPED: task budget"}[kind]

    def frozen(freeze: dict[str, Any]) -> str | None:  # src/ is edited once the cases before ``moved_before`` ran
        return "src/ changed" if moved_before and len(launched) >= [c for c, _ in PLAN].index(moved_before) else None

    out = RUN.run(BASE, lambda **kw: log.append(kw), launch=launch, spent=lambda: ledger[0], out=tmp, frozen=frozen,
                  check=lambda d, c: {"case_verdict": "held", "safety_failures": (safety or {}).get(c, [])})
    return out, log, launched


def test_the_planned_run_with_recorded_costs(tmp_path):
    """Recorded costs of these cases' last Live runs (F01 and F03 on 2026-09-29, the rest on 2026-09-30): the four
    required cases run, F04 starts with USD 0.152 of the run cap left, and W04 does not start."""
    costs = {"F01": 0.018611, "F03": 0.017401, "W18": 0.045727, "W19": 0.06574, "F04": 0.040492, "W04": 0.040406}
    out, log, launched = _simulate(costs, tmp=tmp_path)
    assert [c for c, _ in launched] == ["F01", "F03", "W18", "W19", "F04"]
    assert all(cap == pytest.approx(0.15) for _, cap in launched)  # every case gets its own full cap
    assert out["coverage"]["full_check"] and next(e for e in log if e.get("case") == "W04")["event"] == "not_run"
    assert out["run_cost"] == pytest.approx(0.187971)


def test_expensive_cases_leave_coverage_incomplete_not_a_full_check(tmp_path):
    out, _log, launched = _simulate({c: 0.15 for c, _ in PLAN}, tmp=tmp_path)
    assert [c for c, _ in launched] == ["F01", "F03"] and out["run_cost"] <= 0.30 + 1e-9
    assert out["coverage"] == {"required_completed": ["F01", "F03"], "required_missing": ["W18", "W19"], "full_check": False}


@pytest.mark.parametrize("stop,kw", [("budget_stop", {"results": {"F03": "budget_stop"}}),
                                     ("error", {"results": {"F03": "error"}}),
                                     ("safety", {"safety": {"F03": ["tool_calls"]}})])
def test_a_budget_stop_error_or_safety_failure_ends_the_run_without_retry(tmp_path, stop, kw):
    out, log, launched = _simulate({c: 0.02 for c, _ in PLAN}, tmp=tmp_path, **kw)
    assert [c for c, _ in launched] == ["F01", "F03"]  # F03 launched once, nothing after it
    assert next(e for e in log if e["event"] == "run_stopped")["not_run"] == ["W18", "W19", "F04", "W04"]
    assert not out["coverage"]["full_check"]
    assert out["cases"]["F03"] == ("held" if stop == "safety" else "incomplete")


def test_a_change_to_frozen_material_stops_the_run_before_the_next_case(tmp_path):
    out, log, launched = _simulate({c: 0.02 for c, _ in PLAN}, tmp=tmp_path, moved_before="W18")
    assert [c for c, _ in launched] == ["F01", "F03"]
    stop = next(e for e in log if e["event"] == "run_stopped")
    assert stop["before_case"] == "W18" and stop["not_run"] == ["W18", "W19", "F04", "W04"]
    assert not out["coverage"]["full_check"]


def test_case_cap_fits_under_the_run_cap_or_the_case_does_not_start():
    assert RUN.case_cap(4.891922, 4.591922, 0.15) == pytest.approx(4.741922)
    assert RUN.case_cap(4.891922, 4.741922, 0.15) == pytest.approx(4.891922)
    assert RUN.case_cap(4.891922, 4.741923, 0.15) is None


@pytest.mark.skipif(not FREEZE, reason="FREEZE.json not written yet")
def test_the_runner_refuses_overrides_a_moved_ledger_and_a_missing_key(monkeypatch):
    frozen = {**FREEZE, "ledger_start_usd": 4.591922}
    monkeypatch.setattr(RUN, "changed", lambda freeze: None)  # the frozen-material check is tested below
    monkeypatch.setenv("OPENAI_API_KEY", "placeholder-not-a-key")  # presence only; never read or sent
    monkeypatch.setattr(RUN.budget, "spent", lambda: frozen["ledger_start_usd"])
    for k in RUN.OVERRIDES[1:]:
        monkeypatch.delenv(k, raising=False)
    assert "override" in (RUN.refusal(frozen) or "")  # the tests' own scratch ledger is an override
    monkeypatch.setattr(RUN, "OVERRIDES", RUN.OVERRIDES[1:])  # the scratch ledger stays set throughout
    # prompts v12 (I-18): the frozen runner refuses the current prompts; the other checks run under the frozen ones
    assert RUN.refusal(frozen) == "the prompt version differs"
    monkeypatch.setattr(RUN.config, "PROMPT_VERSION", FREEZE["prompt_version"])
    assert RUN.refusal(frozen) is None
    for k in ("NEM_AGENT_TOTAL_BUDGET_USD", "NEM_AGENT_PRICE_OUTPUT_PER_MTOK", "NEM_AGENT_MODEL"):
        monkeypatch.setenv(k, "1")
        assert "override" in (RUN.refusal(frozen) or "")
        monkeypatch.delenv(k)
    monkeypatch.setattr(RUN.budget, "spent", lambda: frozen["ledger_start_usd"] + 0.000001)
    assert "starting balance" in (RUN.refusal(frozen) or "")
    monkeypatch.setattr(RUN.budget, "spent", lambda: frozen["ledger_start_usd"])
    monkeypatch.delenv("OPENAI_API_KEY")
    assert RUN.refusal(frozen) == "no API key is set"


@pytest.mark.skipif(not FREEZE, reason="FREEZE.json not written yet")
def test_the_runner_refuses_a_changed_frozen_file_or_src_tree():
    assert RUN.changed({**FREEZE, "src_tree": "0" * 40}) == "the checkout's src/ is not the frozen tree"
    bad = {**FREEZE, "files_sha256": {**FREEZE["files_sha256"], "eval/live_check_dev2/PROTOCOL.md": "0" * 64}}
    assert RUN.changed(bad) == "eval/live_check_dev2/PROTOCOL.md differs from FREEZE.json"


@pytest.mark.skipif(not FREEZE, reason="FREEZE.json not written yet")
def test_the_freeze_matches_the_protocol_and_the_run():
    """The frozen files are unchanged, and the run used the frozen commit and src/ tree. The run log is the record of
    that; the checkout's own src/ may move on after the run."""
    import hashlib

    assert FREEZE["cases"] == [["F01", "eval/live_check_2026_09_29/cases.json"], ["F03", "eval/live_check_2026_09_29/cases.json"],
                               ["W18", "eval/holdout_v4/cases.json"], ["W19", "eval/holdout_v4/cases.json"],
                               ["F04", "eval/live_check_2026_09_29/cases.json"], ["W04", "eval/holdout_v4/cases.json"]]
    assert FREEZE["required"] == ["F01", "F03", "W18", "W19"]
    assert (FREEZE["run_cap_usd"], FREEZE["case_cap_usd"], FREEZE["model"]) == (0.30, 0.15, "gpt-5-mini")
    for rel, want in FREEZE["files_sha256"].items():
        assert hashlib.sha256((REPO / rel).read_bytes()).hexdigest() == want, rel
    start = json.loads((LIVE / "live-check-dev2" / "run_log.jsonl").read_text().splitlines()[0])
    assert start["event"] == "start" and start["src_tree"] == FREEZE["src_tree"]
    assert start["code_commit"] == FREEZE["code_commit"] and start["commit"].startswith("76f6aaf")
    assert start["ledger_committed"] == FREEZE["ledger_start_usd"]


# ------------------------------------------------------------------------------------------------ the checker
CASEFILES = {"F01": "eval/live_check_2026_09_29/cases.json", "F03": "eval/live_check_2026_09_29/cases.json",
             "F04": "eval/live_check_2026_09_29/cases.json", "W18": "eval/holdout_v4/cases.json",
             "W19": "eval/holdout_v4/cases.json", "W04": "eval/holdout_v4/cases.json"}


def _case(cid: str) -> dict[str, Any]:
    d = json.loads((REPO / CASEFILES[cid]).read_text())
    return next(c for c in (d if isinstance(d, list) else d["cases"]) if c["case_id"] == cid)


def _diagnose(monkeypatch, cid: str, path: Path, **kw: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """A record in live_diagnose's own format, built by its own code with the fake transport in place of OpenAI."""
    import nem_agent.agent.live as live
    import nem_agent.trace as tr

    diag = _load("dev2_live_diagnose", REPO / "scripts" / "live_diagnose.py")
    fake = _fake(path, **kw)
    monkeypatch.setattr(live, "OpenAITransport", lambda *a, **k: fake)
    monkeypatch.setattr(tr.Trace, "write", lambda self, directory=None: None)
    kept: dict[str, Any] = {}
    real = diag.run_system_case

    def keep(case: dict[str, Any], mode: str, keep: dict[str, Any] | None = None) -> dict[str, Any]:
        row = real(case, mode, keep=keep)
        kept["res"] = (keep or {}).get("result")
        return row
    monkeypatch.setattr(diag, "run_system_case", keep)
    rec = json.loads(json.dumps(diag.diagnose(_case(cid)), default=str))
    return rec, kept["res"].trace.as_dict()


REPLAYS: dict[str, tuple[Path, dict[str, Any], dict[str, str]]] = {  # case -> (saved run, options, verdicts offline)
    "F01": (C0929 / "F01.json", {}, {"I-3b": "held", "I-4": "held"}),
    "F03": (C0929 / "F03.json", {}, {"I-3a": "held", "I-3c": "held", "I-4": "not triggered"}),
    "W18": (C0930 / "W18.json", {"first_draft": True, "delete": "possible_explanations[1]"},
            {"I-7": "held", "I-3c": "held", "I-3d": "held", "I-4": "held"}),
    "W19": (C0930 / "W19.json", {"first_draft": True}, {"I-6": "held", "I-3d": "held", "I-4": "held"}),
    "F04": (C0929 / "F04.json", {}, {"I-3c": "held", "I-4": "held"}),
    "W04": (C0930 / "W04.json", {"first_draft": True}, {"I-3d": "held", "I-4": "held"}),
}


@pytest.mark.parametrize("cid", list(REPLAYS))
def test_offline_replays_get_the_expected_verdicts(monkeypatch, cid):
    path, kw, want = REPLAYS[cid]
    rec, trace = _diagnose(monkeypatch, cid, path, **kw)
    got = CHECK.check(cid, rec, trace)
    assert {f: v["verdict"] for f, v in got["fixes"].items()} == want
    assert all(v["verdict"] == "held" for v in got["regression"].values()), got["regression"]
    assert got["case_verdict"] == "held" and got["safety_failures"] == []


def test_w18_with_its_saved_repair_falls_back_and_fails(monkeypatch):
    """The recorded risk (I-7): the saved Live repair keeps the ruled-out hypothesis, so the answer falls back."""
    rec, trace = _diagnose(monkeypatch, "W18", C0930 / "W18.json", first_draft=True)
    got = CHECK.check("W18", rec, trace)
    assert got["fallback"] and got["fixes"]["I-7"]["verdict"] == "failed" and got["case_verdict"] == "failed"


def _mutate(rec: dict[str, Any], fn: Any) -> dict[str, Any]:
    out = copy.deepcopy(rec)
    fn(out)
    return out


@pytest.mark.parametrize("cid,fix,change", [
    ("F01", "I-4", lambda r: r["report"]["summary"].append("See the forecast-run data [ev0436].")),
    ("F01", "I-4", lambda r: r["report"]["missing_evidence"].append("get_forecast_runs: blocked — invalid arguments")),
    ("F01", "I-3b", lambda r: r["report"].update(summary=[s.replace(" (in MW, as the table header in the cited passage "
                                                                    "states)", "") for s in r["report"]["summary"]])),
    ("F03", "I-3a", lambda r: r["report"].update(summary=[s.split(" (NEM market time")[0] for s in r["report"]["summary"]])),
    ("F03", "I-3c", lambda r: r["report"].update(headline="Belalie-Davenport line outage")),
    ("F03", "I-4", lambda r: r["report"]["uncertainties"].append("peak_half_hour_end_utc was not returned.")),
    ("W19", "I-3d", lambda r: r["report"]["observations"].append(next(o for o in r["report"]["observations"]
                                                                      if o["value"] == 845.0))),
    ("W19", "I-6", lambda r: r["validation"].update(fallback_applied=True)),
])
def test_the_rules_fail_what_they_must(monkeypatch, cid, fix, change):
    path, kw, _ = REPLAYS[cid]
    rec, trace = _diagnose(monkeypatch, cid, path, **kw)
    got = CHECK.check(cid, _mutate(rec, change), trace)
    assert got["fixes"][fix]["verdict"] == "failed" and got["case_verdict"] == "failed", got["fixes"][fix]


def test_a_fallback_after_the_cancellation_fired_is_failed_not_untriggered(monkeypatch):
    """The first check's I-1b rule read citations from the shown report, which a fallback empties (its recorded
    ordering defect); here the trigger is read from the trace and the drafts."""
    rec, trace = _diagnose(monkeypatch, "W19", C0930 / "W19.json", first_draft=True)
    fell = _mutate(rec, lambda r: (r["validation"].update(fallback_applied=True), r["report"].update(citations=[])))
    assert CHECK.cancellation("W19", fell, trace)["verdict"] == "failed"
    assert CHECK.cancellation("W19", rec, trace)["verdict"] == "held"


def test_quoted_text_is_not_an_internal_reference(monkeypatch):
    rec, trace = _diagnose(monkeypatch, "F01", C0929 / "F01.json")
    ok = _mutate(rec, lambda r: r["report"]["summary"].append("The notice says “ev0436 and get_price_timeline as_of” [c1]."))
    assert CHECK.check("F01", ok, trace)["fixes"]["I-4"]["verdict"] == "held"


@pytest.mark.parametrize("cid,fix", [("W19", "I-6"), ("W19", "I-3d"), ("W19", "I-4"), ("W18", "I-3c"), ("W18", "I-3d"),
                                     ("W04", "I-3d"), ("W04", "I-4"), ("F04", "I-3c")])
def test_the_saved_pre_fix_runs_fail_as_they_did(cid, fix):
    """The Live records of 2026-09-30, made before these fixes: the rules reproduce what was wrong."""
    got = CHECK.check_saved(C0930, cid)
    assert got["fixes"][fix]["verdict"] == "failed", got["fixes"][fix]
    if cid == "W19":
        assert got["regression"]["I-1b"]["verdict"] == "failed"  # the protocol verdict, now also the checker's


@pytest.mark.parametrize("cid,fix", [("F03", "I-3a"), ("F03", "I-3c"), ("F01", "I-3b")])
def test_the_saved_2026_09_29_runs_fail_as_they_did(cid, fix):
    rec = _rec(C0929 / f"{cid}.json")
    tp = REPO / "artifacts" / "traces" / f"{rec['score']['trace_id']}.json"
    if not tp.exists():
        pytest.skip("the 2026-09-29 traces are in the git-ignored trace store only")
    assert CHECK.check(cid, rec, _rec(tp))["fixes"][fix]["verdict"] == "failed"
