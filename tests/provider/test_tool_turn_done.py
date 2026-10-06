"""D37: the opt-in DONE prompt variant for Standard Live's tool-selection turns. SYNTHETIC fake model and scratch
ledgers only (conftest): nothing leaves the process.

With ``NEM_AGENT_LIVE_TOOL_TURN_DONE`` on, the tool-selection turns' instructions gain one instruction: request further
tools when needed, otherwise reply DONE and nothing else. Amendment 1 (variant 2) adds the evidence limits for
synthesis and repair and the status lowering (tests/provider/test_evidence_limits.py). Everything else is the
controller's existing behaviour:

- the same model replies give the same tool calls, reminders, corrections, failure notes, synthesis input (apart from
  the evidence-limits block and instructions), repair and report, setting on or off: DONE is a reply without tool
  calls, handled as any such reply;
- the turn stays, so the model can still ask for optional follow-up evidence;
- a reply other than DONE is recorded and kept in the conversation as before, never truncated or salvaged;
- with the setting off or unset, every request is exactly as before; Replay and the experimental workflow ignore it.
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from nem_agent.agent.live import (
    EVIDENCE_LIMITS_HEADING,
    TOOL_TURN_DONE_ENV,
    TOOL_TURN_DONE_VARIANT,
    VARIANT_PARTS,
    prompt,
    tool_turn_done_variant,
    tool_turn_instructions,
)
from nem_agent.agent.request import InvestigateRequest
from nem_agent.service import investigate
from tests.provider.fake_model import FakeModel, calls, msg
from tests.provider.test_live_loop import _good_report, _required_turn, _route, _w

pytestmark = pytest.mark.synthetic
ROOT = Path(__file__).resolve().parents[2]
QUESTION = "What happened around the SA1 price spike on 2026-07-31?"
SYSTEM = prompt("system", "prompts/v16")
VARIANT_TEXT = prompt("tool_turn_done_v1", "prompts/variants").strip()
SYNTHESIS_LIMITS = prompt("synthesis_limits_v1", "prompts/variants")
REPAIR_LIMITS = prompt("repair_limits_v1", "prompts/variants").strip()
PROSE =("The price peaked at the interval shown in the price timeline, demand rose in the morning and generation "
         "shifted between units; a fuller account follows. ") * 8


@pytest.fixture
def ev(selection):
    return selection.primary


class Scripted(FakeModel):
    """The tool-selection turns' replies, scripted turn by turn: a list of tool calls, or a text (DONE, prose or "")."""

    def __init__(self, ev: Any, replies: list[Any], report_fn: Any = _good_report, repair_fn: Any = None) -> None:
        super().__init__(_route(ev), [], report_fn, repair_fn)
        self.replies = list(replies)

    def create(self, **kw: Any) -> dict[str, Any]:
        if ((kw.get("text") or {}).get("format") or {}).get("name"):
            return super().create(**kw)
        self.requests.append(copy.deepcopy(kw))
        reply = self.replies.pop(0) if self.replies else "DONE"
        if isinstance(reply, list):
            resp = calls(*reply)
            self.issued += resp["output"]
            return resp
        return msg(reply)


def _kinds(fake: FakeModel) -> list[str]:
    return [((kw.get("text") or {}).get("format") or {}).get("name") or "tools" for kw in fake.requests]


def _run(fake: FakeModel) -> Any:
    return investigate(InvestigateRequest(question=QUESTION, mode="live"), live_client=fake, write_trace=False)


def _ids(text: str) -> str:
    return re.sub(r'"(call|resp|fc)_\d+"', lambda m: f'"{m.group(1)}_N"', text)


def without_limits(items: Any) -> Any:
    """A request's input without what amendment 1 adds: the evidence-limits block and the instructions after the
    synthesis prompt and the repair message. What remains must be what the setting-off run sent."""
    if not isinstance(items, list):
        return items
    out = []
    for it in items:
        if isinstance(it, dict) and isinstance(it.get("content"), str):
            if it["content"].startswith(EVIDENCE_LIMITS_HEADING):
                continue
            it = {**it, "content": it["content"].replace(f"\n\n{SYNTHESIS_LIMITS}", "").replace(f"\n{REPAIR_LIMITS}", "")}
        out.append(it)
    return out


def _outcome(fake: FakeModel, res: Any) -> tuple[Any, ...]:
    """What the controller did and produced: the model calls, the tool calls, the inputs it sent after the first tool
    turn (apart from amendment 1's additions), and the report, without the ids the fake numbers from a counter shared
    by every test."""
    records = [(r.name, r.origin, json.dumps(r.args, sort_keys=True, default=str), r.status) for r in res.records]
    inputs = [_ids(json.dumps(without_limits(kw.get("input")), sort_keys=True, default=str)) for kw in fake.requests]
    rep = res.report.model_dump(mode="json")
    for k in ("trace_id", "source_manifest"):
        rep.pop(k)
    return _kinds(fake), records, inputs, _ids(json.dumps(rep, sort_keys=True, default=str))


def _both(ev: Any, monkeypatch: pytest.MonkeyPatch, replies: list[Any], **kw: Any) -> tuple[Any, Any, Any, Any]:
    """The same scripted replies, with the setting off and then on."""
    monkeypatch.delenv(TOOL_TURN_DONE_ENV, raising=False)
    off_fake = Scripted(ev, replies, **kw)
    off = _run(off_fake)
    monkeypatch.setenv(TOOL_TURN_DONE_ENV, "1")
    on_fake = Scripted(ev, replies, **kw)
    on = _run(on_fake)
    return off_fake, off, on_fake, on


def _tool_instructions(fake: FakeModel) -> set[str]:
    return {kw["instructions"] for kw, k in zip(fake.requests, _kinds(fake), strict=True) if k == "tools"}


def _other_instructions(fake: FakeModel) -> set[str]:
    return {kw["instructions"] for kw, k in zip(fake.requests, _kinds(fake), strict=True)
            if k not in ("tools", "RouteDecision")}


# -- the setting --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("value, variant", [(None, None), ("0", None), ("off", None), ("false", None), ("1", TOOL_TURN_DONE_VARIANT),
                                            ("on", TOOL_TURN_DONE_VARIANT), ("TRUE", TOOL_TURN_DONE_VARIANT)])
def test_the_setting_is_off_by_default(value, variant, monkeypatch):
    if value is None:
        monkeypatch.delenv(TOOL_TURN_DONE_ENV, raising=False)
    else:
        monkeypatch.setenv(TOOL_TURN_DONE_ENV, value)
    assert tool_turn_done_variant() == variant


def test_an_unknown_value_is_refused_before_any_call(ev, monkeypatch):
    monkeypatch.setenv(TOOL_TURN_DONE_ENV, "maybe")
    fake = Scripted(ev, [_required_turn(ev)])
    with pytest.raises(ValueError, match=TOOL_TURN_DONE_ENV):
        _run(fake)
    assert fake.requests == []


def test_the_variant_is_the_approved_instruction_and_only_the_tool_turns_get_it():
    assert VARIANT_TEXT == ("When further tools are needed, request them. When no further tool is needed, reply DONE "
                            "and nothing else; the report is written in the synthesis stage.")
    assert tool_turn_instructions("prompts/v16", None) == SYSTEM
    assert tool_turn_instructions("prompts/v16", TOOL_TURN_DONE_VARIANT) == f"{SYSTEM}\n\n{VARIANT_TEXT}\n"


# -- the default path: unchanged --------------------------------------------------------------------------------------
def test_with_the_setting_off_every_request_is_as_before(ev, monkeypatch):
    for value in (None, "0"):
        if value is None:
            monkeypatch.delenv(TOOL_TURN_DONE_ENV, raising=False)
        else:
            monkeypatch.setenv(TOOL_TURN_DONE_ENV, value)
        fake = Scripted(ev, [_required_turn(ev), "done"])
        res = _run(fake)
        assert _tool_instructions(fake) == {SYSTEM} and _other_instructions(fake) == {SYSTEM}
        assert not [e for e in res.trace.events if e["name"].startswith("tool_turn")]
        assert not [e for e in res.trace.events if "prompt_variant" in e]
        # amendment 1: no evidence limits, the synthesis prompt alone, no status lowering
        sent = [it for kw in fake.requests for it in kw.get("input") or [] if isinstance(it, dict)]
        assert not [it for it in sent if str(it.get("content", "")).startswith(EVIDENCE_LIMITS_HEADING)]
        assert prompt("synthesis", "prompts/v16") in [it.get("content") for it in sent]
        assert not [it for it in sent if SYNTHESIS_LIMITS.strip() in str(it.get("content", ""))]
        assert not [e for e in res.trace.events if e["name"] in ("evidence_limits", "status_lowered")]
        assert "status_lowered" not in res.report.validation


def test_on_it_changes_the_tool_turns_instructions_adds_the_limits_and_is_recorded(ev, monkeypatch):
    off_fake, off, on_fake, on = _both(ev, monkeypatch, [_required_turn(ev), "DONE"])
    assert _tool_instructions(on_fake) == {f"{SYSTEM}\n\n{VARIANT_TEXT}\n"}
    assert _other_instructions(on_fake) == _other_instructions(off_fake) == {SYSTEM}  # synthesis, repair: same instructions
    assert _outcome(off_fake, off) == _outcome(on_fake, on)  # the same replies, the same run, apart from the limits
    synthesis = next(kw for kw, k in zip(on_fake.requests, _kinds(on_fake), strict=True) if k == "ModelReport")
    assert synthesis["input"][-1]["content"] == f"{prompt('synthesis', 'prompts/v16')}\n\n{SYNTHESIS_LIMITS}"
    assert [it for it in synthesis["input"] if str(it.get("content", "")).startswith(EVIDENCE_LIMITS_HEADING)]
    variant = [e for e in on.trace.events if e["name"] == "tool_turn_variant"]
    assert [(e["variant"], e["setting"], e["instruction"], tuple(e["parts"])) for e in variant] == [
        (TOOL_TURN_DONE_VARIANT, TOOL_TURN_DONE_ENV, VARIANT_TEXT, VARIANT_PARTS)]
    tool_calls = [e for e in on.trace.events if e["kind"] == "model" and e["name"] == "tools"]
    assert tool_calls and all(e["prompt_variant"] == TOOL_TURN_DONE_VARIANT for e in tool_calls)
    replies = [(e["turn"], e["reply"]) for e in on.trace.events if e["name"] == "tool_turn_reply"]
    assert replies == [(1, "calls"), (2, "done")]


# -- DONE never bypasses the controller ---------------------------------------------------------------------------------
def test_optional_follow_up_tools_can_still_be_requested(ev, monkeypatch):
    follow_up = [("get_generation_change", {**_w(ev), "start_utc": ev.window_start_utc,
                                            "end_utc": ev.peak_interval_end_utc, "top_n": 5, "as_of_utc": None})]
    off_fake, off, on_fake, on = _both(ev, monkeypatch, [_required_turn(ev), follow_up, "DONE"])
    assert _kinds(on_fake) == ["RouteDecision", "tools", "tools", "tools", "ModelReport"]
    assert [r.name for r in on.records][-1] == "get_generation_change"
    assert _outcome(off_fake, off) == _outcome(on_fake, on)


def test_done_with_a_required_tool_missing_gets_the_reminder(ev, monkeypatch):
    first = [c for c in _required_turn(ev) if c[0] in ("get_price_timeline", "get_actual_demand")]
    rest = [c for c in _required_turn(ev) if c[0] not in ("get_price_timeline", "get_actual_demand")]
    off_fake, off, on_fake, on = _both(ev, monkeypatch, [first, "DONE", rest, "DONE"])
    assert _kinds(on_fake) == ["RouteDecision", "tools", "tools", "tools", "tools", "ModelReport"]
    reminder = on_fake.requests[3]["input"][-1]["content"]  # the turn after the first DONE
    assert reminder.startswith("Required tools not yet called:")
    assert {r.name for r in on.records} >= {n for n, _ in _required_turn(ev)}
    assert _outcome(off_fake, off) == _outcome(on_fake, on)


def test_done_again_after_the_reminder_leaves_the_tool_missing_as_before(ev, monkeypatch):
    first = [c for c in _required_turn(ev) if c[0] != "retrieve_public_evidence"]
    off_fake, off, on_fake, on = _both(ev, monkeypatch, [first, "DONE", "DONE"])
    assert _kinds(on_fake) == ["RouteDecision", "tools", "tools", "tools", "ModelReport"]  # one reminder, then synthesis
    assert "retrieve_public_evidence" not in {r.name for r in on.records}
    assert _outcome(off_fake, off) == _outcome(on_fake, on)


def test_a_blocked_and_a_failed_call_are_handled_as_before(ev, monkeypatch):
    turn = [(n, {**a, "max_results": 100} if n == "find_market_events" else  # blocked: over its limit
             {**a, "start_utc": "2020-01-01T00:00:00Z", "end_utc": "2020-01-02T00:00:00Z"} if n == "get_actual_demand"
             else a) for n, a in _required_turn(ev)]  # get_actual_demand: unavailable (no rows held for 2020)
    off_fake, off, on_fake, on = _both(ev, monkeypatch, [turn, "DONE"])
    statuses = {r.name: r.status for r in on.records}
    assert statuses["find_market_events"] == "blocked" and statuses["get_actual_demand"] == "unavailable"
    # the blocked required tool still gets its reminder turn; both failures are reported as missing evidence
    assert _kinds(on_fake) == ["RouteDecision", "tools", "tools", "tools", "ModelReport"]
    assert any("market-event search was blocked" in m for m in on.report.missing_evidence)
    assert any("actual-demand data was unavailable" in m for m in on.report.missing_evidence)
    assert _outcome(off_fake, off) == _outcome(on_fake, on)


def test_synthesis_gets_every_tool_result(ev, monkeypatch):
    _, _, on_fake, on = _both(ev, monkeypatch, [_required_turn(ev), "DONE"])
    synthesis = next(kw for kw, k in zip(on_fake.requests, _kinds(on_fake), strict=True) if k == "ModelReport")
    sent = {i["call_id"] for i in synthesis["input"] if isinstance(i, dict) and i.get("type") == "function_call_output"}
    assert sent == {r.call_id for r in on.records if r.origin == "model"} and len(sent) == 4


def test_a_repair_runs_as_before(ev, monkeypatch):
    def bad(kw: dict[str, Any]) -> dict[str, Any]:
        r = _good_report(kw)
        r["headline"] = r["headline"].replace("peaked at", "peaked at 12,345 MW demand and")  # invented number
        return r

    def patch(kw: dict[str, Any]) -> dict[str, Any]:
        return {"edits": [{"target": "headline", "action": "replace", "text": _good_report(kw)["headline"],
                           "statement": None, "claim": None, "citation": None}],
                "new_numeric_claims": [], "new_citations": []}

    off_fake, off, on_fake, on = _both(ev, monkeypatch, [_required_turn(ev), "DONE"], report_fn=bad, repair_fn=patch)
    assert on.report.validation["repair_attempted"] is True and _kinds(on_fake)[-1] == "RepairPatch"
    assert _outcome(off_fake, off) == _outcome(on_fake, on)
    # amendment 1: the repair turn keeps the evidence-limit rules; without the setting, the message is as before
    assert on_fake.requests[-1]["input"][-1]["content"].endswith(f"\n{REPAIR_LIMITS}")
    assert REPAIR_LIMITS not in off_fake.requests[-1]["input"][-1]["content"]


# -- a reply other than DONE ----------------------------------------------------------------------------------------
@pytest.mark.parametrize("reply, kind", [(PROSE, "text"), ("", "empty"), ("DONE.", "text")])
def test_another_reply_is_recorded_and_kept_as_before(reply, kind, ev, monkeypatch):
    """Not truncated, not salvaged: the reply stays in the conversation as any reply does, and synthesis follows."""
    off_fake, off, on_fake, on = _both(ev, monkeypatch, [_required_turn(ev), reply])
    rec = [e for e in on.trace.events if e["name"] == "tool_turn_reply" and e["turn"] == 2]
    assert [(e["reply"], e["chars"]) for e in rec] == [(kind, len(reply.strip()))]
    if kind == "text":
        assert rec[0]["excerpt"] == reply.strip()[:300]
        synthesis = next(kw for kw, k in zip(on_fake.requests, _kinds(on_fake), strict=True) if k == "ModelReport")
        assert {"role": "assistant", "content": reply} in synthesis["input"]  # kept whole
    assert _outcome(off_fake, off) == _outcome(on_fake, on)


# -- what the setting leaves alone ----------------------------------------------------------------------------------
def test_replay_and_the_experimental_workflow_ignore_the_setting(ev, monkeypatch):
    from nem_agent.service import interpret_request

    results = []
    for value in (None, "1"):
        if value is None:
            monkeypatch.delenv(TOOL_TURN_DONE_ENV, raising=False)
        else:
            monkeypatch.setenv(TOOL_TURN_DONE_ENV, value)
        replay = investigate(InvestigateRequest(question=QUESTION, mode="replay"), write_trace=False).report
        fake = FakeModel(_route(ev), [], _good_report)
        interpret_request(QUESTION, live_client=fake, write_trace=False)
        rep = replay.model_dump(mode="json")
        rep.pop("trace_id")
        results.append((json.dumps(rep, sort_keys=True, default=str), _ids(json.dumps(fake.requests, sort_keys=True))))
    assert results[0] == results[1]


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def test_no_frozen_evaluation_runner_can_use_a_variant_its_freeze_does_not_record():
    """Every frozen runner refuses unless the code's src tree is its frozen one; each freeze predates this setting, and
    a runner frozen on code that has it must refuse it."""
    current = _git("rev-parse", "HEAD:src")
    for f in sorted(ROOT.glob("eval/*/FREEZE.json")):
        freeze = json.loads(f.read_text())
        runner = next(p for p in (f.parent / "run_eval.py", f.parent / "run_check.py") if p.exists())
        source = runner.read_text()
        assert 'rev-parse", "HEAD:src") != freeze["src_tree"]' in source, f"{runner} does not check its frozen code"
        if freeze["src_tree"] == current:
            assert TOOL_TURN_DONE_ENV in source, f"{runner} is frozen on code with the setting but allows it"
