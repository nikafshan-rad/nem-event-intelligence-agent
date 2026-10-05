"""D36: progress of a standard Live investigation, and early data charts while it runs. SYNTHETIC fake model and
scratch ledgers only (conftest): nothing leaves the process.

- The stages arrive in order, with the resolved request, and the tool records after each tool turn.
- The data an early chart draws exists before the synthesis call is sent.
- Without a callback, and with one that fails, the run is the same: the same model requests, the same tool calls (none
  repeated) and the same report.
- Early charts draw only successful results matching the resolved region, window and cutoff, and say where coverage
  is partial.
- The page: the stage and elapsed time, no model text before the end, the actual outcome of a failure or a budget
  stop, and an earlier run's result cleared when a new investigation starts.

This shortens the blank wait; it does not shorten the run.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from nem_agent.agent.dispatcher import ToolCallRecord
from nem_agent.agent.request import InvestigateRequest
from nem_agent.progress import Progress
from nem_agent.service import investigate
from nem_agent.ui_data import (
    EARLY_DATA_FAILED,
    EARLY_DATA_LABEL,
    early_chart_notes,
    early_chart_records,
    frames,
)
from tests.provider.fake_model import FakeModel
from tests.provider.test_live_budget_stop import another_session_before
from tests.provider.test_live_loop import _good_report, _required_turn, _route

pytestmark = pytest.mark.synthetic
ROOT = Path(__file__).resolve().parents[2]
QUESTION = "What happened around the SA1 price spike on 2026-07-31?"


@pytest.fixture
def ev(selection):
    return selection.primary


def _fake(ev: Any, report: Any = _good_report, **kw: Any) -> FakeModel:
    return FakeModel(_route(ev), [_required_turn(ev)], report, **kw)


def _run(fake: FakeModel, progress: Any = None) -> Any:
    return investigate(InvestigateRequest(question=QUESTION, mode="live"), live_client=fake, write_trace=False,
                       progress=progress)


def _kinds(fake: FakeModel) -> list[str]:
    return [((kw.get("text") or {}).get("format") or {}).get("name") or "tools" for kw in fake.requests]


def _outcome(fake: FakeModel, res: Any) -> tuple[Any, ...]:
    """What a run did and produced, without what differs between any two runs: the trace id, timings, and the call and
    response ids the fake numbers from a counter shared by every test."""
    calls = [(r.name, r.origin, json.dumps(r.args, sort_keys=True, default=str), r.status) for r in res.records]
    rep = res.report.model_dump(mode="json")
    for k in ("trace_id", "source_manifest"):
        rep.pop(k)
    ids = re.sub(r'"(call|resp)_[0-9]+"', lambda m: f'"{m.group(1)}_N"', json.dumps(rep, sort_keys=True, default=str))
    return _kinds(fake), calls, ids


class Recorder:
    def __init__(self, fake: FakeModel) -> None:
        self.fake, self.events, self.sent = fake, [], []

    def __call__(self, p: Progress) -> None:
        self.events.append(p)
        self.sent.append(_kinds(self.fake))


# -- the callback -------------------------------------------------------------------------------------------------
def test_the_stages_arrive_in_order_with_the_resolved_request_and_the_records(ev):
    fake = _fake(ev)
    rec = Recorder(fake)
    res = _run(fake, rec)
    assert [(p.stage, p.turn) for p in rec.events] == [
        ("routing", None), ("routed", None), ("tools", 1), ("tool_results", 1), ("tools", 2), ("tool_results", None),
        ("synthesis", None), ("checking", None), ("finalizing", None)]
    r = res.resolution
    assert rec.events[1].status == "ok"
    assert all((p.region, p.window, p.as_of) == (r.region, r.window, r.as_of) for p in rec.events[1:])
    assert [x.name for x in rec.events[3].records] == [n for n, _ in _required_turn(ev)]
    assert len(rec.events[5].records) == len(res.records)  # the controller's own computations included
    # each stage is told before its call is sent: the synthesis stage before the report is asked for
    assert "ModelReport" not in rec.sent[6] and _kinds(fake).count("ModelReport") == 1


def test_the_early_charts_have_their_data_before_the_synthesis_call_is_sent(ev):
    fake = _fake(ev)
    rec = Recorder(fake)
    _run(fake, rec)
    first = next(i for i, p in enumerate(rec.events) if p.stage == "tool_results")
    p = rec.events[first]
    used = early_chart_records(p.records, p.region, p.window, p.as_of)
    pdf, ddf = frames(used, p.region)
    assert {u.name for u in used} == {"get_price_timeline", "get_actual_demand"}
    assert len(pdf) > 0 and len(ddf) > 0
    assert rec.sent[first] == ["RouteDecision", "tools"]  # no synthesis request yet


def test_a_repair_is_its_own_stage(ev):
    def bad(kw):
        r = _good_report(kw)
        r["headline"] = r["headline"].replace("peaked at", "peaked at 12,345 MW demand and")  # invented number
        return r

    def patch(kw):
        return {"edits": [{"target": "headline", "action": "replace", "text": _good_report(kw)["headline"],
                           "statement": None, "claim": None, "citation": None}],
                "new_numeric_claims": [], "new_citations": []}

    fake = _fake(ev, bad, repair_fn=patch)
    rec = Recorder(fake)
    res = _run(fake, rec)
    stages = [p.stage for p in rec.events]
    assert stages[-3:] == ["checking", "repair", "finalizing"]
    assert res.report.validation["repair_attempted"] is True
    assert _kinds(fake)[-1] == "RepairPatch" and "RepairPatch" not in rec.sent[stages.index("repair")]


def test_without_a_callback_and_with_one_the_run_is_the_same(ev):
    a_fake, b_fake = _fake(ev), _fake(ev)
    a, b = _run(a_fake), _run(b_fake, Recorder(b_fake))
    assert _outcome(a_fake, a) == _outcome(b_fake, b)
    assert [(e["kind"], e["name"]) for e in a.trace.events] == [(e["kind"], e["name"]) for e in b.trace.events]


@pytest.mark.parametrize("fails_at", ["routing", "tool_results", "synthesis", "finalizing"])
def test_a_callback_that_fails_is_dropped_and_the_run_is_the_same(fails_at, ev):
    """No retry, no repeated tool or model call: the run is the one without a callback, plus one trace note."""
    told: list[str] = []

    def breaks(p: Progress) -> None:
        told.append(p.stage)
        if p.stage == fails_at:
            raise RuntimeError("the display broke")

    a_fake, b_fake = _fake(ev), _fake(ev)
    a, b = _run(a_fake), _run(b_fake, breaks)
    assert told[-1] == fails_at and told.count(fails_at) == 1  # never called again after it failed
    assert _outcome(a_fake, a) == _outcome(b_fake, b)
    notes = [e for e in b.trace.events if e["kind"] == "progress"]
    assert [(n["name"], n["stage"], n["error"]) for n in notes] == [("callback_failed", fails_at, "RuntimeError")]


def test_a_budget_stop_before_synthesis_ends_the_stages_there(ev, monkeypatch):
    another_session_before(monkeypatch, 4)  # route, two tool turns, then synthesis: refused before it is sent
    fake = _fake(ev)
    rec = Recorder(fake)
    res = _run(fake, rec)
    assert [p.stage for p in rec.events][-3:] == ["tool_results", "synthesis", "finalizing"]
    assert "ModelReport" not in _kinds(fake) and res.report.validation["stopped"]["stage"] == "synthesis"


def test_replay_and_the_api_path_ignore_progress(ev):
    told: list[Any] = []
    res = investigate(InvestigateRequest(question=QUESTION, mode="replay"), write_trace=False, progress=told.append)
    assert told == [] and res.report.mode == "replay"


# -- which results an early chart draws, and what it says about them ----------------------------------------------------
T0 = datetime(2026, 7, 31, 0, 0, tzinfo=UTC)
WINDOW = (T0, T0 + timedelta(hours=1))


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _price(region: str = "SA1", start: datetime = T0, end: datetime = T0 + timedelta(hours=1), as_of: str | None = None,
           ends: list[datetime] | None = None, excluded: int = 0, status: str = "ok",
           missing: list[str] | None = None) -> ToolCallRecord:
    ends = ends if ends is not None else [start + timedelta(minutes=5 * (i + 1)) for i in range(12)]
    series = [{"interval_end_utc": _iso(t), "rrp": 100.0, "price_status": "FIRM", "rrp_evidence_id": f"ev{i:04d}",
               "row_id": f"row{i}"} for i, t in enumerate(ends)]
    return ToolCallRecord(call_id="c", name="get_price_timeline", origin="model", raw_args={},
                          args={"region": region, "start_utc": _iso(start), "end_utc": _iso(end), "as_of_utc": as_of},
                          status=status, view={"excluded_not_yet_available_at_as_of": excluded},
                          data={"series": series} if status == "ok" else {}, missing=missing or [])


def _demand(ends: list[datetime]) -> ToolCallRecord:
    series = [{"interval_end_utc": _iso(t), "operational_demand_mw": 1500.0, "evidence_id": "ev9", "revision": "updated"}
              for t in ends]
    return ToolCallRecord(call_id="d", name="get_actual_demand", origin="model", raw_args={},
                          args={"region": "SA1", "start_utc": _iso(T0), "end_utc": _iso(T0 + timedelta(hours=1)),
                                "revision_policy": "latest_available", "as_of_utc": None},
                          status="ok", view={"excluded_not_yet_available_at_as_of": 0}, data={"series": series})


def test_an_early_chart_draws_only_successful_results_for_the_resolved_region_window_and_cutoff():
    inside = _price(start=T0 + timedelta(minutes=30), ends=[T0 + timedelta(minutes=35)])
    others = [_price(region="VIC1"), _price(as_of="2026-07-31T00:30:00Z"),
              _price(start=T0 - timedelta(minutes=5)),  # starts before the resolved window
              _price(end=T0 + timedelta(hours=2)), _price(status="unavailable"),
              ToolCallRecord(call_id="b", name="get_price_timeline", origin="model", raw_args="{bad", args=None,
                             status="blocked", blocked_reason="invalid arguments")]
    full = _price()
    assert early_chart_records([*others, inside, full], "SA1", WINDOW, None) == [inside, full]
    assert early_chart_records([full], "SA1", WINDOW, datetime(2026, 7, 31, 0, 30, tzinfo=UTC)) == []
    cut = _price(as_of="2026-07-31T00:30:00Z")
    assert early_chart_records([cut], "SA1", WINDOW, datetime(2026, 7, 31, 0, 30, tzinfo=UTC)) == [cut]


def test_the_notes_say_where_coverage_is_partial_and_what_was_not_drawn():
    gaps = _price(ends=[T0 + timedelta(minutes=5 * (i + 1)) for i in range(10)], excluded=2)
    half = _demand([T0 + timedelta(minutes=30)])
    notes = early_chart_notes([gaps, half], "SA1", WINDOW, None)
    assert ("Price: 10 of the 12 five-minute intervals of the requested window are drawn; 2 published after the "
            "cutoff are left out.") in notes
    assert "Actual demand: 1 of the 2 half-hours of the requested window are drawn." in notes
    assert early_chart_notes([_price(), _demand([T0 + timedelta(minutes=30), T0 + timedelta(hours=1)])],
                             "SA1", WINDOW, None) == []  # complete: nothing to say
    failed = _price(status="unavailable", missing=["Price timeline unavailable: no dispatch price rows."])
    assert early_chart_notes([failed], "SA1", WINDOW, None) == [
        "Price timeline: no data drawn; its last call returned unavailable (Price timeline unavailable: no dispatch "
        "price rows.)."]
    assert early_chart_notes([_price(region="VIC1")], "SA1", WINDOW, None) == [
        "Price timeline: retrieved for another region, window or cutoff than the request, so not drawn here."]


# -- the page ---------------------------------------------------------------------------------------------------------
class FailsAtSynthesis(FakeModel):
    def create(self, **kw: Any) -> dict[str, Any]:
        if ((kw.get("text") or {}).get("format") or {}).get("name") == "ModelReport":
            raise RuntimeError("SYNTHETIC transport failure at synthesis")
        return super().create(**kw)


def _page(monkeypatch: pytest.MonkeyPatch, fakes: list[FakeModel]) -> Any:
    """The app in Live mode, each investigation served by the next scripted fake (the callback passed through)."""
    from streamlit.testing.v1 import AppTest

    import nem_agent.service as service

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-key")  # presence only: the model is a scripted fake
    real = service.investigate
    queue = list(fakes)
    monkeypatch.setattr(service, "investigate",
                        lambda req, **kw: real(req, live_client=queue.pop(0), write_trace=False, **kw))
    at = AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"), default_timeout=180)
    at.run()
    at.sidebar.radio[0].set_value("live").run()
    return at


def _investigate(at: Any) -> Any:
    return next(b for b in at.button if b.label == "Investigate").click().run()


def _texts(at: Any) -> str:
    return "\n".join(str(getattr(e, "value", "")) for kind in ("markdown", "caption", "subheader", "success", "warning",
                                                                "info", "error") for e in at.get(kind))


def _charts(at: Any) -> int:
    return len(at.get("vega_lite_chart"))


def test_the_page_shows_the_stages_then_the_finished_result(ev, monkeypatch):
    at = _investigate(_page(monkeypatch, [_fake(ev)]))
    assert not at.exception
    status = at.get("status")
    assert len(status) == 1 and status[0].label.startswith("Live investigation ended after ")
    assert "answer written by" in status[0].label
    text = _texts(at)
    for step in ("Reading the question (routing call)", "Choosing and running tools (model turn 1)",
                 "Writing the answer (model)", "Checking the draft (independent validator)", "Final validation"):
        assert step in text
    assert EARLY_DATA_LABEL.split("**")[1] not in text  # the early charts went: the result below draws its own
    assert any("answer written" in s.value for s in at.success)  # the finished result, unchanged


def test_a_failure_keeps_the_early_charts_labelled_as_no_answer_and_clears_the_earlier_result(ev, monkeypatch):
    at = _page(monkeypatch, [_fake(ev), FailsAtSynthesis(_route(ev), [_required_turn(ev)], _good_report)])
    _investigate(at)
    assert any("answer written" in s.value for s in at.success) and _charts(at) == 2  # the first run, finished
    _investigate(at)
    assert at.exception and "SYNTHETIC transport failure at synthesis" in str(at.exception[0].value)
    status = at.get("status")[0]
    assert status.label.startswith("Live investigation failed after ") and "no answer was produced" in status.label
    text = _texts(at)
    assert EARLY_DATA_FAILED.split("**")[1] in text and _charts(at) == 2  # the data retrieved before the failure
    assert not at.success and "The fake model only restates tool values." not in text  # no answer, no model text
    assert "result" not in at.session_state  # the first run's result cannot reappear


def test_a_budget_stop_shows_its_outcome_in_the_panel(ev, monkeypatch):
    another_session_before(monkeypatch, 4)
    at = _investigate(_page(monkeypatch, [_fake(ev)]))
    assert not at.exception
    status = at.get("status")[0]
    assert "stopped at a budget limit before the model wrote an answer" in status.label
    assert any("stopped at a budget limit" in w.value for w in at.warning)
    assert not any("answer written" in s.value for s in at.success)


def test_replay_shows_no_progress_panel(real_store, monkeypatch):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"), default_timeout=180).run()
    _investigate(at)
    assert not at.exception and at.get("status") == [] and "REPLAY" in _texts(at)
