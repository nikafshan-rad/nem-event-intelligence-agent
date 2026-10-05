"""The experimental confirmed-request workflow (``nem_agent.agent.confirm``, the app's opt-in workflow), offline.

Every routing decision is SYNTHETIC (a scripted transport stands in for the model; no network, no key), the data is the
real pinned store, and the ledger is a scratch one (tests/conftest.py). Covered:
- end to end, question to verified computed answer: a demand maximum, a forecast point, a period aggregate, an
  unavailable requested comparison, and a clarification settled one question at a time;
- the confirmed request is executed exactly as displayed (its resolution is built from its fields), with no model call
  after the interpretation; a correction is executed exactly as corrected;
- confirmation applies to one exact revision: a stale or edited revision is refused, and a revision runs once;
- an unfinished draft never reaches execution; invalid, incomplete, conflicting or unsupported requests run nothing;
- dependent fields are revalidated when an earlier answer changes, and fields already settled are not asked again;
- the default workflow is unchanged, and the app's experimental flow renders end to end (Streamlit AppTest).
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from nem_agent.agent import confirm as C
from nem_agent.service import execute_confirmed, interpret_request

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.synthetic


class Scripted:
    """SYNTHETIC routing model: returns the scripted decision and counts its calls."""

    def __init__(self, *decisions: dict[str, Any]) -> None:
        self.decisions, self.calls = list(decisions), 0

    def create(self, **kw: Any) -> dict[str, Any]:
        self.calls += 1
        assert kw["text"]["format"]["name"] == "PlanRouteDecision"  # contract v16, whatever the switch says
        d = self.decisions[min(self.calls, len(self.decisions)) - 1]
        return {"id": f"resp_{self.calls}", "status": "completed", "usage": {"input_tokens": 9000, "output_tokens": 700},
                "output": [{"type": "message", "role": "assistant",
                            "content": [{"type": "output_text", "text": json.dumps(d)}]}]}


def _op(i: str, kind: str, subject: str, subject_text: str | None, operation_text: str | None,
        scope: str | None = None, run: str | None = None, stance: str = "asked") -> dict[str, Any]:
    return {"id": i, "stance": stance, "kind": kind, "subject": subject, "subject_text": subject_text,
            "operation_text": operation_text, "scope_ref": scope, "run_ref": run, "cutoff_ref": None}


def _plan(intent: str | None, region: str | None, day: str | None, ops: list[dict[str, Any]],
          scopes: list[tuple[str, str, str]] | None = None, runs: list[tuple[str, str, str]] | None = None
          ) -> dict[str, Any]:
    return {"intent": intent, "region": region, "event_date": day, "needs_clarification": False,
            "clarification_reason": None, "clarification": None, "out_of_scope": False,
            "plan": {"operations": ops, "scopes": [{"id": i, "kind": k, "text": t} for i, k, t in scopes or []],
                     "runs": [{"id": i, "selection": s, "text": t} for i, s, t in runs or []], "cutoffs": [],
                     "cutoff_ref": None}}


Q_MAX = ("On 29 July 2026, Sydney time, at which five-minute interval was NSW dispatch total demand highest across the "
         "whole day, and what was the level?")
P_MAX = _plan("market_event_review", "NSW1", "2026-07-29", [
    _op("o1", "demand_maximum", "dispatch_total_demand", "dispatch total demand",
        "at which five-minute interval was NSW dispatch total demand highest", scope="s1")],
    scopes=[("s1", "whole_local_day", "across the whole day")])
Q_POINT = ("Taking South Australia's 7:30-8:00 am half-hour (Adelaide time, ACST) on 20 August 2026: what POE10, POE50 "
           "and POE90 operational demand values were in the final forecast run issued ahead of it, and what "
           "operational demand was actually measured?")
P_POINT = _plan("forecast_review", "SA1", "2026-08-20", [
    _op("o1", "forecast_comparison", "operational_demand", "POE10, POE50 and POE90 operational demand values",
        "what operational demand was actually measured", scope="s1", run="r1")],
    scopes=[("s1", "half_hour", "South Australia's 7:30-8:00 am half-hour (Adelaide time, ACST) on 20 August 2026")],
    runs=[("r1", "last_issued_before", "the final forecast run issued ahead of it")])
Q_AGG = "How accurate were the operational demand forecasts for NSW1 on 31 July 2026?"
P_AGG = _plan("forecast_review", "NSW1", "2026-07-31", [
    _op("o1", "forecast_comparison", "operational_demand", "operational demand forecasts",
        "How accurate were the operational demand forecasts", scope="s1")],
    scopes=[("s1", "whole_local_day", "on 31 July 2026")])
Q_OPEN = "What was the highest operational demand in Queensland?"
P_OPEN = _plan("market_event_review", "QLD1", None, [
    _op("o1", "demand_maximum", "operational_demand", "operational demand",
        "What was the highest operational demand in Queensland")])
Q_WEATHER = "What was the weather forecast for Adelaide on 31 July 2026?"
P_WEATHER = _plan("forecast_review", "SA1", "2026-07-31", [
    _op("o1", "forecast_value", "weather", "weather", "What was the weather forecast")])


@pytest.fixture(scope="module")
def sel(real_store):
    from nem_agent.service import _shared

    return _shared()[1]


def _start(q: str, plan: dict[str, Any]) -> tuple[dict[str, Any], Scripted]:
    fake = Scripted(plan)
    state = C.new_state()
    C.start(state, q, lambda text: interpret_request(text, live_client=fake, write_trace=False))
    return state, fake


def _run(state: dict[str, Any], sel: Any) -> Any:
    """Confirm the current revision and execute it as the app does: once."""
    d = C.draft_of(state)
    x = C.executable(d, sel)
    assert x is not None, C.issues(d, sel)
    rid = C.revision_id(x)
    assert C.confirm(state, rid, sel)
    pending = C.take_pending(state, sel)
    assert pending == x
    state["results"][rid] = execute_confirmed(pending, original=state["original"], write_trace=False)
    return x, state["results"][rid]


def _executed(res: Any) -> dict[str, Any]:
    return next(e for e in res.trace.as_dict()["events"] if e.get("name") == "confirmed_request")["confirmed"]


# ------------------------------------------------------------------------------------------------ end to end
def test_a_maximum_is_previewed_confirmed_and_computed(sel):
    state, fake = _start(Q_MAX, P_MAX)
    d = C.draft_of(state)
    rows = dict(C.preview(d, sel))
    assert rows["Operation"].startswith("Demand maximum") and "TOTALDEMAND" in rows["Measure / domain"]
    assert rows["Region"].startswith("NSW1") and "2026-07-28T14:00:00Z to 2026-07-29T14:00:00Z" in rows[
        "Interval / window"]
    assert rows["Needs clarification"] == "nothing" and rows["Request-field overrides"] == "none"
    x, res = _run(state, sel)
    (a,) = res.report.answer
    assert (a.kind, a.status, a.verification) == ("demand_maximum", "established", "verified")
    assert fake.calls == 1  # one routing call; none after confirmation
    assert _executed(res) == x.model_dump(mode="json")
    assert res.resolution.requests.maximum.window == (C.bounds(d, sel))


def test_a_forecast_point_runs_the_named_run_for_the_half_hour_shown(sel):
    state, fake = _start(Q_POINT, P_POINT)
    x, res = _run(state, sel)
    assert (x.operation, x.run, x.start_utc, x.end_utc) == ("single_interval_comparison", "last_issued_before",
                                                            "2026-08-19T22:00:00Z", "2026-08-19T22:30:00Z")
    (a,) = res.report.answer
    assert (a.kind, a.status, a.verification) == ("forecast_point", "established", "verified")
    fa = res.resolution.requests.forecast
    assert (fa.operation, [t.isoformat() for t in fa.target]) == ("single_interval_comparison", [
        "2026-08-19T22:00:00+00:00", "2026-08-19T22:30:00+00:00"])
    assert fake.calls == 1


def test_a_period_aggregate_is_computed_over_exactly_the_period_shown(sel):
    state, _ = _start(Q_AGG, P_AGG)
    d = C.draft_of(state)
    assert d.run == "latest_before_each" and d.sources["run"] == "rule (no run named)"  # shown, not silent
    assert "latest run issued before it" in dict(C.preview(d, sel))["Forecast run"]
    x, res = _run(state, sel)
    (a,) = res.report.answer
    assert (a.kind, a.verification) == ("forecast_aggregate", "verified") and a.status in ("established", "partial")
    assert (x.start_utc, x.end_utc, x.half_hours) == ("2026-07-30T14:00:00Z", "2026-07-31T14:00:00Z", 48)


def test_an_unavailable_requested_comparison_is_stated_and_nothing_stands_in(sel):
    state, _ = _start(Q_POINT, P_POINT)
    d = C.draft_of(state)
    assert C.choose(state, d.revision, "run", "issued_at", sel)  # a correction: a run issued at a stated time
    d = C.draft_of(state)
    assert C.issues(d, sel)[0].field == "issued_at"
    assert C.reply(state, "2026-08-19T03:17:00Z", sel)  # no run was issued then
    x, res = _run(state, sel)
    assert (x.run, x.issued_at_utc) == ("issued_at", "2026-08-19T03:17:00Z")
    (a,) = res.report.answer
    assert (a.kind, a.status) == ("forecast_point", "unavailable")
    assert _executed(res)["issued_at_utc"] == "2026-08-19T03:17:00Z"  # executed exactly as corrected


def test_a_clarification_asks_one_question_at_a_time_and_keeps_what_is_settled(sel):
    state, fake = _start(Q_OPEN, P_OPEN)
    d = C.draft_of(state)
    asked = []
    first = C.issues(d, sel)[0]
    asked.append(first.field)
    assert first.field == "date" and d.measure == "operational demand" and d.region == "QLD1"
    assert C.executable(d, sel) is None and C.take_pending(state, sel) is None  # nothing runs while a field is open
    assert C.reply(state, "29 July 2026", sel)  # read by the existing parser, no model call
    d = C.draft_of(state)
    nxt = C.issues(d, sel)[0]
    asked.append(nxt.field)
    assert nxt.field == "scope_kind" and {c.value for c in nxt.choices} >= {"day", "explicit"}
    assert C.choose(state, d.revision, "scope_kind", "day", sel)
    d = C.draft_of(state)
    assert C.issues(d, sel) == [] and asked == ["date", "scope_kind"]
    assert (d.sources["date"], d.sources["scope_kind"], d.sources["region"]) == ("you", "you", "interpretation")
    x, res = _run(state, sel)
    (a,) = res.report.answer
    assert (a.kind, a.verification) == ("demand_maximum", "verified") and x.measure == "operational demand"
    assert fake.calls == 1


# ------------------------------------------------------------------------------------------------ confirmation
def test_confirmation_applies_to_one_exact_revision_and_runs_once(sel):
    state, _ = _start(Q_POINT, P_POINT)
    d = C.draft_of(state)
    x = C.executable(d, sel)
    rid = C.revision_id(x)
    assert C.confirm(state, rid, sel)
    # an edit before it runs invalidates the confirmation: the confirmed revision no longer runs
    assert C.choose(state, d.revision, "half_hour_end", "08:30", sel)
    assert C.take_pending(state, sel) is None and state["confirmed"] is None
    assert not C.confirm(state, rid, sel)  # the stale revision cannot be confirmed again
    d2 = C.draft_of(state)
    assert not C.choose(state, d.revision, "half_hour_end", "09:00", sel)  # a choice from an old revision is ignored
    x2, _ = _run(state, sel)
    assert C.revision_id(x2) != rid and x2.end_utc == "2026-08-19T23:00:00Z" and d2.revision == x2.revision
    assert C.take_pending(state, sel) is None  # rerun: nothing runs twice
    assert C.confirm(state, C.revision_id(x2), sel) and C.take_pending(state, sel) is None  # already ran


def test_an_unfinished_or_invalid_draft_never_reaches_execution(sel):
    state, _ = _start(Q_OPEN, P_OPEN)
    d = C.draft_of(state)
    assert C.executable(d, sel) is None and C.take_pending(state, sel) is None
    with pytest.raises(TypeError):
        execute_confirmed(d, write_trace=False)
    bad = C.apply(C.apply(d, "date", "2026-07-29", sel), "period", ("17:15", "18:00"), sel)  # not on the grid
    assert C.issues(bad, sel)[0].field == "period" and C.executable(bad, sel) is None
    long = C.apply(C.apply(C.apply(d, "operation", "window_comparison", sel), "date", "2025-10-05", sel),
                   "scope_kind", "day", sel)
    long = C.apply(long, "region", "NSW1", sel)  # 5 October 2025 in Sydney has 23 hours; 4 October has 24
    assert C.issues(long, sel)[0].field == "run"
    early = C.apply(C.apply(long, "run", "issued_at", sel), "issued_at", "2025-10-06T00:00:00Z", sel)
    assert C.issues(early, sel)[0].field == "issued_at"  # issued after the period begins


def test_an_unsupported_request_runs_nothing_until_a_supported_one_is_chosen(sel):
    state, _ = _start(Q_WEATHER, P_WEATHER)
    d = C.draft_of(state)
    first = C.issues(d, sel)[0]
    assert first.field == "operation" and d.operation is None and "weather" in " ".join(d.blocked.values()).lower()
    assert C.executable(d, sel) is None
    assert {c.value for c in first.choices} == set(C.OPERATIONS)  # the user chooses; nothing is picked for them


class Truncated(Scripted):
    """SYNTHETIC routing response cut off at the output cap: its text is valid JSON up to the cut."""

    def create(self, **kw: Any) -> dict[str, Any]:
        resp = super().create(**kw)
        text = json.dumps(self.decisions[0])
        resp.update(status="incomplete", incomplete_details={"reason": "max_output_tokens"})
        resp["output"][0]["content"][0]["text"] = text[: len(text) // 2]
        return resp


def test_a_truncated_routing_response_is_not_salvaged(sel):
    fake = Truncated(P_MAX)
    state = C.new_state()
    C.start(state, Q_MAX, lambda text: interpret_request(text, live_client=fake, write_trace=False))
    d = C.draft_of(state)
    # the question parser could read a region, a date and a maximum here; none of it is used
    assert d.blocked == {"operation": C.INVALID_OUTPUT}
    assert (d.operation, d.region, d.date, d.measure, d.scope_kind) == (None, None, None, None, None)
    assert state["original"]["decision"] is None and C.executable(d, sel) is None


def test_a_failed_routing_call_leaves_the_session_unchanged(sel):
    state, _ = _start(Q_MAX, P_MAX)
    before = json.dumps(state, default=str)

    def failing(text: str) -> C.Interpretation:
        raise RuntimeError("scripted API failure")
    with pytest.raises(RuntimeError):
        C.start(state, "another question", failing)
    assert json.dumps(state, default=str) == before


def test_a_refused_question_runs_nothing(sel):
    plan = {**_plan(None, None, None, []), "out_of_scope": True, "clarification": "Out of scope."}
    state, _ = _start("Should I buy power futures tomorrow?", plan)
    d = C.draft_of(state)
    assert d.refused and C.issues(d, sel)[0].field == "refused" and C.executable(d, sel) is None


def test_two_distinct_operations_are_never_chosen_between(sel):
    q = ("For NSW1 on 31 July 2026, how high did operational demand peak over the whole day, and how accurate were "
         "the operational demand forecasts that day?")
    plan = _plan("forecast_review", "NSW1", "2026-07-31", [
        _op("o1", "demand_maximum", "operational_demand", "operational demand", "how high did operational demand peak",
            scope="s1"),
        _op("o2", "forecast_comparison", "operational_demand", "operational demand forecasts",
            "how accurate were the operational demand forecasts", scope="s2")],
        scopes=[("s1", "whole_local_day", "over the whole day"), ("s2", "whole_local_day", "that day")])
    state, _ = _start(q, plan)
    d = C.draft_of(state)
    assert d.operation is None and C.issues(d, sel)[0].field == "operation" and C.executable(d, sel) is None


def test_changing_an_earlier_answer_revalidates_what_depends_on_it(sel):
    state, _ = _start(Q_POINT, P_POINT)
    d = C.draft_of(state)
    moved = C.apply(d, "region", "NSW1", sel)  # the same local half-hour, now in Sydney time
    assert C.executable(moved, sel).start_utc == "2026-08-19T21:30:00Z"  # 07:30 AEST, not ACST
    to_window = C.apply(d, "operation", "window_comparison", sel)
    assert to_window.scope_kind is None and to_window.run is None  # no longer fit: asked again
    assert C.issues(to_window, sel)[0].field == "scope_kind" and to_window.region == "SA1"  # kept


def test_a_typed_reply_the_parsers_cannot_read_may_use_one_routing_call_that_fills_only_open_fields(sel):
    state, _ = _start(Q_OPEN, P_OPEN)
    d = C.draft_of(state)
    second = Scripted(_plan("market_event_review", "QLD1", "2026-07-29", [
        _op("o1", "demand_maximum", "operational_demand", "operational demand",
            "What was the highest operational demand in Queensland", scope="s1")],
        scopes=[("s1", "whole_local_day", "the day of the price spike")]))
    q2 = Q_OPEN + "\nthe day of the price spike"
    assert C.reply(state, "the day of the price spike", sel,
                   lambda text: interpret_request(text, live_client=second, write_trace=False))
    assert second.calls == 1 and len(state["interpretations"]) == 2
    n = C.draft_of(state)
    assert n.region == d.region and n.sources["region"] == "interpretation"  # settled fields kept
    assert state["interpretations"][1]["question"] == q2


def test_the_default_workflow_is_unchanged(monkeypatch):
    from nem_agent.agent.live import LiveController
    from nem_agent.evidence import EvidenceRegistry
    from nem_agent.report import Versions

    v = Versions(code="", data="", corpus="", prompt="", model=None, controller="live")
    monkeypatch.delenv("NEM_AGENT_ROUTE_PLAN", raising=False)
    assert LiveController(None, EvidenceRegistry(), v, client=Scripted()).request_plan is False
    assert LiveController(None, EvidenceRegistry(), v, client=Scripted(), plan=True).request_plan is True


# ------------------------------------------------------------------------------------------------ the app
def test_the_app_flow_question_preview_confirmation_answer(sel, monkeypatch):
    """The page on a seeded session: the preview and the confirm button, then the computed answer after the click;
    a rerun does not run the request again."""
    from streamlit.testing.v1 import AppTest

    state, _ = _start(Q_MAX, P_MAX)
    at = AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"), default_timeout=180)
    at.session_state["confirm_flow"] = state
    at.run()
    at.sidebar.toggle[0].set_value(True).run()
    assert not at.exception
    assert any("Request preview" in m.value for m in at.markdown)
    confirm = [b for b in at.button if b.label == "Confirm and run"]
    assert len(confirm) == 1
    confirm[0].click().run()
    assert not at.exception
    assert any("Computed answer" in m.value for m in at.markdown)
    st_state = at.session_state["confirm_flow"]
    assert len(st_state["results"]) == 1
    at.run()  # a rerun
    assert len(at.session_state["confirm_flow"]["results"]) == 1 and not at.exception


def test_the_app_without_a_key_builds_the_request_from_choices_only(sel, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    at = AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"), default_timeout=180)
    at.run()
    at.sidebar.toggle[0].set_value(True).run()
    at.chat_input[0].set_value("Forecast accuracy for Sydney?").run()
    assert not at.exception
    d = C.draft_of(at.session_state["confirm_flow"])
    assert d.operation is None and at.session_state["confirm_flow"]["original"] is None  # no model was asked
    assert any("What should be worked out" in m.value for m in at.markdown)
    next(b for b in at.button if b.label.startswith("Forecast accuracy over a period")).click().run()
    assert C.draft_of(at.session_state["confirm_flow"]).operation == "window_comparison"


def test_the_app_asks_the_next_question_with_choices(sel):
    from streamlit.testing.v1 import AppTest

    state, _ = _start(Q_OPEN, P_OPEN)
    at = AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"), default_timeout=180)
    at.session_state["confirm_flow"] = state
    at.run()
    at.sidebar.toggle[0].set_value(True).run()
    assert not at.exception and not [b for b in at.button if b.label == "Confirm and run"]
    assert any("Which date" in m.value for m in at.markdown)
    at.chat_input[0].set_value("29 July 2026").run()  # a typed answer, read by the existing date parser
    assert not at.exception
    d = C.draft_of(at.session_state["confirm_flow"])
    assert d.date == "2026-07-29" and d.sources["date"] == "you"
    assert any("Over which period" in m.value for m in at.markdown)  # the next question, one at a time
    day = next(b for b in at.button if b.label.startswith("The whole local day"))
    day.click().run()
    assert not at.exception and [b for b in at.button if b.label == "Confirm and run"]


# ------------------------------------------------------------------------------------------------ integration review
# Through the actual page: the routing model is SYNTHETIC (``service.interpret_request`` with a scripted transport),
# and every analytical tool call the dispatcher would make is counted.
Q_NOON = ("Based only on data published by noon Brisbane time on Sunday 5 October 2025, what was the highest "
          "operational demand in Queensland over that entire local day?")
P_NOON = _plan("market_event_review", "QLD1", "2025-10-05", [
    {**_op("o1", "demand_maximum", "operational_demand", "operational demand",
           "what was the highest operational demand in Queensland", scope="s1"), "cutoff_ref": "c1"}],
    scopes=[("s1", "whole_local_day", "over that entire local day")])
P_NOON["plan"]["cutoffs"] = [{"id": "c1", "text": "Based only on data published by noon Brisbane time on Sunday 5 "
                                                   "October 2025"}]
Q_TWO = ("For NSW1 on 31 July 2026, how high did operational demand peak over the whole day, and how accurate were the "
         "operational demand forecasts that day?")
P_TWO = _plan("forecast_review", "NSW1", "2026-07-31", [
    _op("o1", "demand_maximum", "operational_demand", "operational demand", "how high did operational demand peak",
        scope="s1"),
    _op("o2", "forecast_comparison", "operational_demand", "operational demand forecasts",
        "how accurate were the operational demand forecasts", scope="s2")],
    scopes=[("s1", "whole_local_day", "over the whole day"), ("s2", "whole_local_day", "that day")])
Q_LONG = ("How did the operational demand forecasts for VIC1 compare with actual demand from 06:00 AEST on 17 August "
          "2026 to 12:00 AEST on 18 August 2026?")
P_LONG = _plan("forecast_review", "VIC1", "2026-08-17", [
    _op("o1", "forecast_comparison", "operational_demand", "operational demand forecasts",
        "How did the operational demand forecasts for VIC1 compare with actual demand", scope="s1")],
    scopes=[("s1", "explicit", "from 06:00 AEST on 17 August 2026 to 12:00 AEST on 18 August 2026")])


@pytest.fixture
def tool_calls(monkeypatch):
    """Every analytical tool call made through the dispatcher, from any path."""
    from nem_agent.agent.dispatcher import Dispatcher

    calls: list[str] = []
    real = Dispatcher.call

    def spy(self: Any, name: str, raw_args: Any, **kw: Any) -> Any:
        calls.append(name)
        return real(self, name, raw_args, **kw)
    monkeypatch.setattr(Dispatcher, "call", spy)
    return calls


def _page(monkeypatch: pytest.MonkeyPatch, fake: Scripted | None) -> Any:
    """The app in the experimental workflow; with ``fake``, a key is present and the routing call is SYNTHETIC."""
    from streamlit.testing.v1 import AppTest

    import nem_agent.service as service

    if fake is None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    else:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-key")  # presence only: no request leaves the process
        real = service.interpret_request
        monkeypatch.setattr(service, "interpret_request",
                            lambda q, **kw: real(q, live_client=fake, write_trace=False))
    at = AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"), default_timeout=180)
    at.run()
    at.sidebar.toggle[0].set_value(True).run()
    return at


def _texts(at: Any) -> list[str]:
    return [e.value for kind in ("markdown", "caption", "info", "success", "warning", "error") for e in getattr(at, kind)]


def _parse(s: str) -> Any:
    from nem_agent.timeutil import parse_iso

    return parse_iso(s)


@pytest.mark.parametrize("q, plan, truncated, field", [
    (Q_MAX, P_MAX, True, "operation"),
    (Q_TWO, P_TWO, False, "operation"),
    (Q_NOON, P_NOON, False, "cutoff"),
    (Q_LONG, P_LONG, False, "operation"),
], ids=["truncated output", "two analyses", "unresolved active cutoff", "period over 24 hours"])
def test_through_the_page_nothing_reaches_the_tools_until_the_user_repairs_the_request(q, plan, truncated, field, sel,
                                                                                       tool_calls, monkeypatch):
    fake = Truncated(plan) if truncated else Scripted(plan)
    at = _page(monkeypatch, fake)
    at.chat_input[0].set_value(q).run()
    assert not at.exception and fake.calls == 1
    state = at.session_state["confirm_flow"]
    d = C.draft_of(state)
    assert C.issues(d, sel)[0].field == field and C.executable(d, sel) is None
    assert not [b for b in at.button if b.label == "Confirm and run"]
    state["pending"] = state["confirmed"] = "forged"  # a forged confirmation of the open draft
    at.session_state["confirm_flow"] = state
    at.run()
    assert not at.exception and tool_calls == [] and at.session_state["confirm_flow"]["results"] == {}
    assert dict(C.preview(d, sel))["Needs clarification"] != "nothing"


def test_through_the_page_an_unreadable_cutoff_is_repaired_only_by_the_users_answer(sel, tool_calls, monkeypatch):
    at = _page(monkeypatch, Scripted(P_NOON))
    at.chat_input[0].set_value(Q_NOON).run()
    d = C.draft_of(at.session_state["confirm_flow"])
    assert "stated but not pinned down" in dict(C.preview(d, sel))["Cutoff"]
    at.chat_input[0].set_value("2025-10-05T02:00:00Z").run()  # the user states it
    d = C.draft_of(at.session_state["confirm_flow"])
    assert (d.cutoff, d.cutoff_utc, d.sources["cutoff"]) == ("set", "2025-10-05T02:00:00Z", "you")
    next(b for b in at.button if b.label == "Confirm and run").click().run()
    assert not at.exception and tool_calls
    (res,) = at.session_state["confirm_flow"]["results"].values()
    assert res.resolution.as_of.isoformat() == "2025-10-05T02:00:00+00:00"  # executed with the cutoff given


def test_a_forecast_period_longer_than_24_hours_is_never_cut_short(sel):
    ev = next(e for e in sel.events
              if (_parse(e.window_end_utc) - _parse(e.window_start_utc)).total_seconds() > 24 * 3600)
    day = _parse(ev.peak_interval_end_utc).astimezone(C.region_zone(ev.region)).date().isoformat()
    d = C.Draft(question="SYNTHETIC", origin="structured")
    for f, v in (("operation", "window_comparison"), ("region", ev.region), ("date", day), ("scope_kind", "event")):
        d = C.apply(d, f, v, sel)
    first = C.issues(d, sel)[0]
    assert first.field == "scope_kind" and "24-hour limit" in first.message and C.executable(d, sel) is None
    assert "event" not in {c.value for c in first.choices}  # the event window is not offered again


def test_through_the_page_an_edit_invalidates_confirmation_and_reruns_never_repeat_a_run(sel, tool_calls, monkeypatch):
    at = _page(monkeypatch, Scripted(P_POINT))
    at.chat_input[0].set_value(Q_POINT).run()
    next(b for b in at.button if b.label == "Confirm and run").click().run()
    n = len(tool_calls)
    assert n > 0 and len(at.session_state["confirm_flow"]["results"]) == 1
    at.run()
    at.run()
    assert len(tool_calls) == n  # reruns run nothing again
    next(t for t in at.text_input if t.label.startswith("Half-hour end")).set_value("08:30")
    next(b for b in at.button if b.label == "Apply changes").click().run()
    state = at.session_state["confirm_flow"]
    assert not at.exception and state["confirmed"] is None and len(tool_calls) == n  # cleared; nothing ran
    assert C.executable(C.draft_of(state), sel).end_utc == "2026-08-19T23:00:00Z"  # dependent bounds recomputed
    assert any("the request has changed since" in t for t in _texts(at))  # the earlier result is labelled stale
    next(b for b in at.button if b.label == "Confirm and run").click().run()
    assert len(tool_calls) > n and len(at.session_state["confirm_flow"]["results"]) == 2


def test_separate_sessions_never_share_a_draft(sel, monkeypatch):
    a = _page(monkeypatch, Scripted(P_POINT))
    a.chat_input[0].set_value(Q_POINT).run()
    assert C.draft_of(a.session_state["confirm_flow"]) is not None
    b = _page(monkeypatch, Scripted(P_MAX))
    assert C.draft_of(b.session_state["confirm_flow"]) is None and b.session_state["confirm_flow"]["history"] == []
    assert C.draft_of(a.session_state["confirm_flow"]).question == Q_POINT


def test_an_unavailable_comparison_under_a_publication_cutoff_takes_no_neighbouring_run(sel, real_store):
    state, _ = _start(Q_POINT, P_POINT)
    cut = "2026-08-19T21:10:00Z"  # before the last run ahead of the half-hour (issued 21:57:01Z) was public
    assert C.choose(state, C.draft_of(state).revision, "cutoff", cut, sel)
    x, res = _run(state, sel)
    assert (x.run, x.cutoff_utc) == ("last_issued_before", cut)
    (a,) = res.report.answer
    assert (a.kind, a.status, a.verification, a.source_row_ids) == ("forecast_point", "unavailable", "verified", ())
    assert "not provably public by the as-of cutoff" in a.statement and "No other forecast run" in a.statement
    assert res.resolution.forecast_run["run_id"] is None
    earlier = {r["run_id"] for r in real_store.query(
        "SELECT DISTINCT run_id FROM opdemand_forecast WHERE region=? AND target_end_utc=? AND available_at_utc<=?",
        ["SA1", _parse("2026-08-19T22:30:00Z"), _parse(cut)])}
    assert earlier  # runs that were public by the cutoff hold the half-hour, and none stands in
    shown = json.dumps(res.report.model_dump(mode="json"))
    assert not any(r in shown for r in earlier)


def test_the_page_labels_the_narrative_and_the_interpretation_status_honestly(sel, monkeypatch):
    at = _page(monkeypatch, Scripted(P_MAX))
    at.chat_input[0].set_value(Q_MAX).run()
    assert C.INTERPRETATION_LABEL in _texts(at)
    next(b for b in at.button if b.label == "Confirm and run").click().run()
    shown = " ".join(_texts(at))
    assert "it does not validate the routing model's reading" in shown
    assert "model-written interpretation: none in this workflow" in shown
    assert "REPLAY — scripted controller over real data, no LLM" in shown
    assert "answer written by" not in shown and "passed on the first draft" not in shown
    (res,) = at.session_state["confirm_flow"]["results"].values()
    assert res.report.mode == "replay" and res.report.generator.startswith("scripted")


def test_without_a_key_the_page_says_guided_structured_input_not_extraction(sel, monkeypatch):
    at = _page(monkeypatch, None)
    at.chat_input[0].set_value("What was the highest operational demand in Queensland on 29 July 2026?").run()
    shown = _texts(at)
    assert any("guided structured input" in t for t in shown) and C.STRUCTURED_LABEL in shown
    assert C.INTERPRETATION_LABEL not in shown
    d = C.draft_of(at.session_state["confirm_flow"])
    assert d.origin == "structured" and (d.operation, d.region, d.date) == (None, None, None)  # nothing was read
    t_state = C.new_state()  # a truncated routing response is labelled the same way
    C.start(t_state, Q_MAX, lambda q: interpret_request(q, live_client=Truncated(P_MAX), write_trace=False))
    assert C.preview_label(C.draft_of(t_state)) == C.STRUCTURED_LABEL
    state, _ = _start(Q_MAX, P_MAX)
    assert C.preview_label(C.draft_of(state)) == C.INTERPRETATION_LABEL


# ------------------------------------------------------------------------------------------------ a maximum alone
def _confirmed_maximum(sel: Any, region: str, day: str, measure: str, scope: str) -> dict[str, Any]:
    """A session holding a complete maximum request, built from structured choices (no model)."""
    d = C.Draft(question=f"When was {measure} highest in {region} on {day}?", origin="structured")
    for f, v in (("operation", "demand_maximum"), ("measure", measure), ("region", region), ("date", day),
                 ("scope_kind", scope)):
        d = C.apply(d, f, v, sel)
    state = C.new_state()
    state["draft"] = d.model_dump()
    return state


UNREQUESTED = re.compile(r"mean absolute error|\bmae\b|largest|forecast run|poe50|poe10|poe90|dispatch price|"
                         r"\$/mwh|market notice", re.I)


def test_the_confirmed_qld1_maximum_runs_only_its_own_calculation(sel, tool_calls):
    """Regression (the demo run of 2026-10-05, revision 5df77825cea9): the confirmed QLD1 operational-demand maximum for
    the whole local day of 29 July 2026 also ran the forecast-review plan (forecast runs, two forecast comparisons and
    two document searches) and headlined an unrequested forecast MAE. Only the requested maximum runs now, and the
    report carries nothing else."""
    state = _confirmed_maximum(sel, "QLD1", "2026-07-29", "operational demand", "day")
    x, res = _run(state, sel)
    assert (x.operation, x.measure, x.region, x.scope_kind, x.start_utc, x.end_utc) == (
        "demand_maximum", "operational demand", "QLD1", "day", "2026-07-28T14:00:00Z", "2026-07-29T14:00:00Z")
    assert tool_calls == ["get_actual_demand"] and [r.name for r in res.records] == ["get_actual_demand"]
    (a,) = res.report.answer
    assert (a.kind, a.status, a.verification) == ("demand_maximum", "established", "verified")
    assert "7548 MW" in a.statement and "18:30 AEST" in a.statement
    rep = res.report
    assert rep.summary == [] and rep.forecast_comparison is None and rep.possible_explanations == []
    assert rep.citations == [] and rep.published_findings == []
    assert not UNREQUESTED.search(json.dumps(rep.model_dump(mode="json")))
    assert rep.status == "answered" and rep.uncertainties == [C.scope_note(x)]  # its tool ran, its result verified
    assert rep.validation.get("final_passed", rep.validation.get("passed"))


@pytest.mark.parametrize("measure, tool", [("operational demand", "get_actual_demand"),
                                           ("total demand", "get_price_timeline")])
def test_every_confirmed_maximum_runs_only_its_measures_tool(measure, tool, sel, tool_calls):
    ev = sel.events[0]
    day = datetime.fromisoformat(ev.peak_interval_end_utc.replace("Z", "+00:00")).astimezone(
        C.region_zone(ev.region)).date().isoformat()
    for scope in ("day", "event"):  # a whole day (forecast review) and an event window (event review)
        tool_calls.clear()
        _, res = _run(_confirmed_maximum(sel, ev.region, day, measure, scope), sel)
        assert tool_calls == [tool], (scope, tool_calls)
        (a,) = res.report.answer
        assert (a.kind, a.verification) == ("demand_maximum", "verified") and not res.report.summary
        assert not UNREQUESTED.search(json.dumps(res.report.model_dump(mode="json"))), scope


def test_the_page_shows_the_verified_requested_result_first_and_no_unrequested_metric(sel, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    at = AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"), default_timeout=180)
    at.session_state["confirm_flow"] = _confirmed_maximum(sel, "QLD1", "2026-07-29", "operational demand", "day")
    at.run()
    at.sidebar.toggle[0].set_value(True).run()
    next(b for b in at.button if b.label == "Confirm and run").click().run()
    assert not at.exception
    shown = [m.value for m in at.markdown]
    first = next(i for i, m in enumerate(shown) if m == "### Computed answer")
    head = next(i for i, m in enumerate(shown) if m.startswith("**Report headline**"))
    assert first < head and "7548 MW" in shown[first + 1]
    assert not UNREQUESTED.search(" ".join(_texts(at)))


# ------------------------------------------------------------------------------------------------ the confirmed request decides the tools
def _confirmed(sel: Any, steps: list[tuple[str, Any]]) -> dict[str, Any]:
    d = C.Draft(question="SYNTHETIC confirmed request", origin="structured")
    for f, v in steps:
        d = C.apply(d, f, v, sel)
    state = C.new_state()
    state["draft"] = d.model_dump()
    return state


POINT = [("operation", "single_interval_comparison"), ("region", "SA1"), ("date", "2026-08-20"),
         ("half_hour_end", "08:00"), ("run", "last_issued_before")]
AGGREGATE = [("operation", "window_comparison"), ("region", "NSW1"), ("date", "2026-07-31"), ("scope_kind", "day"),
             ("run", "latest_before_each")]
MAXIMUM = [("operation", "demand_maximum"), ("measure", "operational demand"), ("region", "QLD1"),
           ("date", "2026-07-29"), ("scope_kind", "day")]
CONFIRMED = {
    "point, last run before": (POINT, "compare_forecast_actual",
                               {"target_start_utc": "2026-08-19T22:00:00Z", "target_end_utc": "2026-08-19T22:30:00Z",
                                "run_selector": "run_id", "as_of_utc": None}),
    "point, run issued at": (POINT[:4] + [("run", "issued_at"), ("issued_at", "2026-08-19T21:57:01Z")],
                             "compare_forecast_actual",
                             {"target_start_utc": "2026-08-19T22:00:00Z", "target_end_utc": "2026-08-19T22:30:00Z",
                              "run_selector": "run_id", "as_of_utc": None}),
    "aggregate, latest before each": (AGGREGATE, "compare_forecast_actual",
                                      {"target_start_utc": "2026-07-30T14:00:00Z",
                                       "target_end_utc": "2026-07-31T14:00:00Z", "run_selector": "latest_before_target",
                                       "as_of_utc": None}),
    "aggregate, under a cutoff": (AGGREGATE + [("cutoff", "2026-07-31T02:00:00Z")], "compare_forecast_actual",
                                  {"target_start_utc": "2026-07-30T14:00:00Z", "target_end_utc": "2026-07-31T14:00:00Z",
                                   "run_selector": "latest_available_as_of", "as_of_utc": "2026-07-31T02:00:00Z"}),
    "maximum": (MAXIMUM, "get_actual_demand",
                {"start_utc": "2026-07-28T14:00:00Z", "end_utc": "2026-07-29T14:00:00Z", "as_of_utc": None}),
}


@pytest.mark.parametrize("name", list(CONFIRMED))
def test_the_confirmed_request_decides_exactly_which_tool_runs_and_how(name, sel, tool_calls):
    steps, tool, want = CONFIRMED[name]
    x, res = _run(_confirmed(sel, steps), sel)
    assert tool_calls == [tool], tool_calls  # one call: no supplementary comparison, run listing or document search
    (rec,) = res.records
    assert {k: (rec.args or {}).get(k) for k in want} == want  # exactly the confirmed target or window, policy, cutoff
    if want.get("run_selector") == "run_id":  # the run the request names, chosen by issue time, is the one compared
        assert rec.args["run_id"] == res.resolution.forecast_run["run_id"] is not None
    (a,) = res.report.answer
    assert a.verification == "verified" and a.status in ("established", "not_established", "partial")
    rep = res.report
    assert rep.summary == [] and rep.citations == [] and rep.forecast_comparison is None
    assert rep.uncertainties[0] == C.scope_note(x)
    # "answered" exactly when the one result is verified and established: a partial result keeps its caveat
    assert rep.status == ("answered" if a.status == "established" else "answered_with_caveats")
    assert not any("required tool not executed" in m for m in rep.missing_evidence)
    assert rep.validation.get("final_passed", rep.validation.get("passed")) and not rep.validation["fallback_applied"]


@pytest.mark.parametrize("name", ["point, last run before", "aggregate, latest before each", "maximum"])
def test_the_requested_verified_result_is_unchanged_from_the_full_plan(name, sel):
    """The same confirmed request run through the full scripted plan (as before this correction) gives the same
    verified result: only the unrequested extras are gone."""
    from nem_agent.agent.dispatcher import Dispatcher
    from nem_agent.agent.replay import ReplayController
    from nem_agent.evidence import EvidenceRegistry
    from nem_agent.report import Versions
    from nem_agent.service import _shared
    from nem_agent.trace import Trace

    steps, _, _ = CONFIRMED[name]
    x, now = _run(_confirmed(sel, steps), sel)
    store = _shared()[0]
    res = C.to_resolution(x, sel)
    reg = EvidenceRegistry()
    disp = Dispatcher(store, sel, Trace(), reg, res.intent, res.as_of, res.requests.ineligible_tools)
    full = ReplayController(disp, reg, Versions(code="t", data=store.data_version, corpus=None, prompt="p", model=None,
                                                controller="replay")).run(res)
    assert len(disp.records) > 1  # the full plan ran extras
    key = [(a.kind, a.status, a.verification, a.statement, a.source_row_ids) for a in full.answer]
    assert [(a.kind, a.status, a.verification, a.statement, a.source_row_ids) for a in now.report.answer] == key


def test_unavailable_comparisons_stay_unavailable_and_nothing_stands_in(sel, tool_calls):
    # a point whose named run was not public by the cutoff: the run lookup finds none, so no comparison call is made
    x, res = _run(_confirmed(sel, POINT + [("cutoff", "2026-08-19T21:10:00Z")]), sel)
    (a,) = res.report.answer
    assert (a.status, tool_calls, res.resolution.forecast_run["run_id"]) == ("unavailable", [], None)
    assert "No other forecast run or half-hour is given in its place." in a.statement
    # a period with no forecast held (October 2025): one call for exactly that period, and no other window or run
    tool_calls.clear()
    x, res = _run(_confirmed(sel, [("operation", "window_comparison"), ("region", "NSW1"), ("date", "2025-10-05"),
                                   ("scope_kind", "day"), ("run", "latest_before_each")]), sel)
    (a,) = res.report.answer
    assert a.status == "unavailable" and tool_calls == ["compare_forecast_actual"]
    assert (res.records[0].args["target_start_utc"], res.records[0].args["target_end_utc"]) == (x.start_utc,
                                                                                                x.end_utc)
    assert "No other window or run selection is given in its place." in a.statement


def test_the_page_shows_a_confirmed_comparison_first_and_nothing_else(sel, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    at = AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"), default_timeout=180)
    at.session_state["confirm_flow"] = _confirmed(sel, AGGREGATE)
    at.run()
    at.sidebar.toggle[0].set_value(True).run()
    next(b for b in at.button if b.label == "Confirm and run").click().run()
    assert not at.exception
    shown = [m.value for m in at.markdown]
    first = next(i for i, m in enumerate(shown) if m == "### Computed answer")
    head = next(i for i, m in enumerate(shown) if m.startswith("**Report headline**"))
    assert first < head and "mean absolute error" in shown[first + 1]
    assert not any(m.startswith("**Narrative**") for m in shown)  # no scripted narrative beside it


# ------------------------------------------------------------------------------------------------ the confirmed status
STATUS_NOTE = 'The status is "answered with caveats", not "answered": '
SA1_PERIOD = [("operation", "window_comparison"), ("region", "SA1"), ("date", "2026-08-20"),
              ("period", ("07:00", "09:00")), ("run", "latest_before_each")]
NSW1_EVENING = [("operation", "window_comparison"), ("region", "NSW1"), ("date", "2026-07-31"),
                ("period", ("17:00", "21:00")), ("run", "latest_before_each")]
VIC1_EVENING = [("operation", "window_comparison"), ("region", "VIC1"), ("date", "2026-08-17"),
                ("period", ("17:00", "19:00")), ("run", "latest_before_each")]
QLD1_UNHELD = [("operation", "demand_maximum"), ("measure", "operational demand"), ("region", "QLD1"),
               ("date", "2025-01-15"), ("scope_kind", "day")]
POINT_UNDER_CUTOFF = POINT + [("cutoff", "2026-08-19T21:10:00Z")]  # its named run was not public by then
COMPLETE = {
    "maximum": (MAXIMUM, "get_actual_demand", ("7548 MW", "18:30 AEST")),
    "point": (POINT, "compare_forecast_actual", ("a POE50 of 1594 MW", "was 1567 MW", "an error of +27 MW")),
    "aggregate": (SA1_PERIOD, "compare_forecast_actual",
                  ("a mean absolute error of 29.75 MW", "a mean error of -18.75 MW", "over the 4 half-hours")),
}


def _note(rep: Any) -> str:
    (note,) = [u for u in rep.uncertainties if u.startswith(STATUS_NOTE)]
    return note


def _clean(rep: Any) -> bool:
    v = rep.validation
    return bool(v["final_passed"]) and not v["fallback_applied"] and v["initial"]["violations"] == []


@pytest.mark.parametrize("name", list(COMPLETE))
def test_a_complete_confirmed_result_is_answered(name, sel, tool_calls):
    """The operation's own tool ran successfully, once, and its one result is verified and established: the report is
    "answered", the validator holds it to the confirmed requirement and raises nothing, and the values are unchanged."""
    steps, tool, values = COMPLETE[name]
    x, res = _run(_confirmed(sel, steps), sel)
    assert tool_calls == [tool] and [(r.name, r.status) for r in res.records] == [(tool, "ok")]
    (a,) = res.report.answer
    assert (a.status, a.verification) == ("established", "verified")
    assert all(v in a.statement for v in values), a.statement
    (r,) = res.report.results
    assert (r.result.identity.kind, r.server_verification.outcome) == (C.RESULT_KIND[x.operation], "verified")
    rep = res.report
    assert rep.status == "answered" and rep.uncertainties == [C.scope_note(x)] and _clean(rep)


KEPT = {
    "partial aggregate": (NSW1_EVENING, [("compare_forecast_actual", "ok")], "partial",
                          "the result is partial."),
    "unavailable aggregate": (VIC1_EVENING, [("compare_forecast_actual", "unavailable")], "unavailable",
                              "comparison was unavailable; the result is unavailable."),
    "unavailable maximum": (QLD1_UNHELD, [("get_actual_demand", "unavailable")], "unavailable",
                            "data was unavailable; the result is unavailable."),
}


@pytest.mark.parametrize("name", list(KEPT))
def test_partial_and_unavailable_confirmed_results_keep_their_status(name, sel):
    """A partial or unavailable result is reported as it is, and the report says why it is not "answered"."""
    steps, calls, status, why = KEPT[name]
    _x, res = _run(_confirmed(sel, steps), sel)
    assert [(r.name, r.status) for r in res.records] == calls
    (a,) = res.report.answer
    assert (a.status, a.verification) == (status, "verified")  # the result's own status is kept
    rep = res.report
    assert rep.status == "answered_with_caveats" and _note(rep).endswith(why) and _clean(rep)


def test_a_point_whose_run_was_not_public_makes_no_call_and_is_not_answered(sel, tool_calls):
    """The unavailable-point path: the run the request names was not public by the confirmed cutoff, so no comparison
    call is made. None is forced to meet the requirement, no other run stands in, and the report is not "answered"."""
    _x, res = _run(_confirmed(sel, POINT_UNDER_CUTOFF), sel)
    assert tool_calls == [] and res.records == [] and res.resolution.forecast_run["run_id"] is None
    (a,) = res.report.answer
    assert (a.status, a.verification) == ("unavailable", "verified")
    rep = res.report
    assert rep.status == "answered_with_caveats" and _clean(rep)
    assert _note(rep) == (STATUS_NOTE + "the forecast-versus-actual comparison did not run, because the run the "
                          "question asks for is not provably public by the as-of cutoff; no other run is substituted; "
                          "the result is unavailable.")


def test_an_unverified_confirmed_result_is_not_answered(sel, monkeypatch):
    """A result that fails runtime verification is not admitted: the tool ran successfully, but that is not enough."""
    from nem_agent import results

    monkeypatch.setattr(results, "_rederive", lambda *a, **k: ("failed", ["SYNTHETIC: the re-derived result differs"]))
    _x, res = _run(_confirmed(sel, MAXIMUM), sel)
    assert [(r.name, r.status) for r in res.records] == [("get_actual_demand", "ok")]
    (r,) = res.report.results
    assert (r.result.status, r.server_verification.outcome) == ("established", "failed")
    rep = res.report
    assert rep.status == "answered_with_caveats" and _note(rep).endswith("the result is not verified (failed).")


def _forced(res: Any, x: Any, records: Any = None, requirement: Any = "derived") -> Any:
    """The report validated again as the service validates it, with its status forced to "answered"."""
    from nem_agent.trace import Trace
    from nem_agent.validation import validate_and_finalize

    forced = res.report.model_copy(update={"status": "answered", "validation": {}})
    kw = {} if requirement is None else {"confirmed": C.requirement(x) if requirement == "derived" else requirement}
    return validate_and_finalize(forced, res.registry, res.records if records is None else records, res.resolution,
                                 Trace(), **kw)


def _overclaims(out: Any) -> list[str]:
    return [v["detail"] for v in out.validation["initial"]["violations"]
            if v["code"] == "STATUS_OVERCLAIMS" and v["severity"] == "critical"]


TOOL_FAILED = "the confirmed operation's tool did not run successfully: "
NOT_ONE_VERIFIED = "the confirmed result is not one verified, established "
FORCED = {
    "missing tool": (MAXIMUM, "none", [TOOL_FAILED + "['get_actual_demand']"]),
    "failed tool": (MAXIMUM, "error", [TOOL_FAILED + "['get_actual_demand']"]),
    "unavailable tool": (QLD1_UNHELD, None, [TOOL_FAILED + "['get_actual_demand']",
                                             NOT_ONE_VERIFIED + "demand_maximum result"]),
    "partial result": (NSW1_EVENING, None, [NOT_ONE_VERIFIED + "forecast_aggregate result"]),
    "unavailable point, no call": (POINT_UNDER_CUTOFF, None, [TOOL_FAILED + "['compare_forecast_actual']",
                                                              NOT_ONE_VERIFIED + "forecast_point result"]),
}


@pytest.mark.parametrize("name", list(FORCED))
def test_the_validator_rejects_a_forced_answered_status(name, sel):
    """Forced to "answered", a confirmed report whose tool is missing or did not succeed, or whose result is not one
    verified and established result, fails with STATUS_OVERCLAIMS, and the fallback lowers the status."""
    import dataclasses

    steps, records, want = FORCED[name]
    x, res = _run(_confirmed(sel, steps), sel)
    recs = [] if records == "none" else [dataclasses.replace(r, status=records) for r in res.records] if records \
        else None
    out = _forced(res, x, recs)
    got = _overclaims(out)
    assert [g[:len(w)] for g, w in zip(got, want, strict=True)] == want, got
    assert out.status != "answered" and out.validation["fallback_applied"]


def test_the_validator_rejects_a_forced_answered_status_on_an_unverified_result(sel, monkeypatch):
    from nem_agent import results

    monkeypatch.setattr(results, "_rederive", lambda *a, **k: ("failed", ["SYNTHETIC: the re-derived result differs"]))
    x, res = _run(_confirmed(sel, MAXIMUM), sel)
    out = _forced(res, x)
    assert _overclaims(out) == [NOT_ONE_VERIFIED + "demand_maximum result: [('demand_maximum', 'established', "
                                "'failed')]"]
    assert out.status != "answered"


def test_the_validator_accepts_answered_only_for_the_confirmed_result_kind(sel):
    """The requirement checks the result's kind: an established maximum does not meet an aggregate's requirement."""
    from nem_agent.validation import ConfirmedRequirement

    x, res = _run(_confirmed(sel, MAXIMUM), sel)
    assert _overclaims(_forced(res, x)) == []  # its own requirement: met
    other = ConfirmedRequirement("window_comparison", ("compare_forecast_actual",), "forecast_aggregate")
    got = _overclaims(_forced(res, x, requirement=other))
    assert got[0] == TOOL_FAILED + "['compare_forecast_actual']" and got[1].startswith(NOT_ONE_VERIFIED + "forecast_")


def test_without_a_requirement_the_default_validation_is_unchanged(sel):
    """Every other caller passes no requirement: an "answered" report is held to the intent's full playbook, as
    before (the confirmed maximum runs one of its tools, so the rest are reported as not run)."""
    from nem_agent.agent.playbook import PLAYBOOKS

    x, res = _run(_confirmed(sel, MAXIMUM), sel)
    out = _forced(res, x, requirement=None)
    miss = [t for t in PLAYBOOKS[res.resolution.intent].required if t != "get_actual_demand"]
    assert miss and _overclaims(out) == [f"required tools not run: {miss}"]


DERIVED = {
    "operational-demand maximum": (MAXIMUM, "get_actual_demand", "demand_maximum"),
    "total-demand maximum": ([*MAXIMUM[:1], ("measure", "total demand"), *MAXIMUM[2:]], "get_price_timeline",
                             "demand_maximum"),
    "point": (POINT, "compare_forecast_actual", "forecast_point"),
    "aggregate": (AGGREGATE, "compare_forecast_actual", "forecast_aggregate"),
}


@pytest.mark.parametrize("name", list(DERIVED))
def test_the_requirement_is_derived_by_code_from_the_confirmed_operation(name, sel):
    """The requirement is computed from the confirmed operation and measure alone (no model or user input is read),
    and is exactly the one tool the dispatcher allows."""
    steps, tool, kind = DERIVED[name]
    x = C.executable(C.draft_of(_confirmed(sel, steps)), sel)
    req = C.requirement(x)
    assert (req.operation, req.tools, req.result_kind) == (x.operation, (tool,), kind)
    assert C.confirmed_playbook(x).required == req.tools and C.confirmed_playbook(x).max_calls_per_required_tool == 1


def test_an_empty_or_hand_made_requirement_cannot_bypass_the_status_check(sel):
    from nem_agent.validation import ConfirmedRequirement

    for tools, kind in (((), "demand_maximum"), (("",), "demand_maximum"), (("get_actual_demand",), "")):
        with pytest.raises(ValueError, match="empty one would bypass"):
            ConfirmedRequirement("demand_maximum", tools, kind)
    x, res = _run(_confirmed(sel, MAXIMUM), sel)
    with pytest.raises(TypeError, match="derived from the confirmed operation"):
        _forced(res, x, requirement=("get_actual_demand",))


# ------------------------------------------------------------------------------------------------ open requirements, now
TEXT_KINDS = ("markdown", "caption", "info", "success", "warning", "error", "json")
HISTORY = "Diagnostics: how the routing model read the question (historical)"  # app/confirm_flow.py


def _rows(at: Any) -> dict[str, str]:
    """The request preview on the page, as field -> value."""
    (table,) = at.table
    return dict(zip(table.value["field"], table.value["value"], strict=True))


def _history(at: Any) -> Any:
    return next(x for x in at.expander if x.label == HISTORY)


def _shown_now(at: Any) -> list[str]:
    """Every text on the page outside the diagnostics, with the preview's values: what reads as current."""
    inside = [e for x in at.expander if x.label.startswith("Diagnostics") for k in TEXT_KINDS for e in getattr(x, k)]
    return [*_rows(at).values(), *(str(e.value) for k in TEXT_KINDS for e in getattr(at, k)
                                   if not any(e is i for i in inside))]


def _open_maximum_settled(monkeypatch: pytest.MonkeyPatch, sel: Any) -> tuple[Any, Scripted, str, list[str]]:
    """The walkthrough of 2026-10-05, offline: an open QLD1 maximum, settled by the user's replies, step by step. Returns
    the page, the scripted model, the routing model's original note and what "Needs clarification" said at each
    step."""
    fake = Scripted(P_OPEN)
    at = _page(monkeypatch, fake)
    at.chat_input[0].set_value(Q_OPEN).run()
    (note,) = at.session_state["confirm_flow"]["original"]["reasons"]
    steps = [_rows(at)["Needs clarification"]]
    at.chat_input[0].set_value("29 July 2026").run()  # read by the date parser
    steps.append(_rows(at)["Needs clarification"])
    next(b for b in at.button if b.label == "The whole local day (2026-07-29)").click().run()
    steps.append(_rows(at)["Needs clarification"])
    return at, fake, note, steps


def test_through_the_page_open_requirements_follow_the_draft_and_the_first_reading_is_history(sel, tool_calls,
                                                                                             monkeypatch):
    """Missing date -> supplied date -> whole local day -> confirmation. At every step the preview shows what is still
    needed now. The routing model's note that the window is unresolved and no maximum can be given stays in the
    diagnostics, labelled historical, and is never shown as a current requirement, before or after the run."""
    at, fake, note, steps = _open_maximum_settled(monkeypatch, sel)
    assert "no maximum is given" in note
    assert steps == ["Which date (the region's local date)?",
                     "The window of the demand peak is not pinned down. Over which period?", "nothing"]
    assert "Interpretation notes" not in _rows(at) and not any(note in t for t in _shown_now(at))
    history = _history(at)
    assert any(note in m.value for m in history.markdown)  # kept, as recorded then
    assert any("not current warnings" in c.value for c in history.caption)
    next(b for b in at.button if b.label == "Confirm and run").click().run()
    assert not at.exception and fake.calls == 1 and tool_calls == ["get_actual_demand"]  # replies made no model call
    (res,) = at.session_state["confirm_flow"]["results"].values()
    (a,) = res.report.answer
    assert "7548 MW" in a.statement and "18:30 AEST" in a.statement and res.report.status == "answered"
    assert _rows(at)["Needs clarification"] == "nothing" and not any(note in t for t in _shown_now(at))
    assert any("Original interpretation** (historical" in m.value for x in at.expander for m in x.markdown)


def test_through_the_page_an_edit_that_reopens_a_requirement_shows_it(sel, tool_calls, monkeypatch):
    """Revising a complete, confirmed request so that it needs something again: the preview names what is needed now,
    nothing can be confirmed or run, and the answer updates the requirements again. The old note stays history."""
    at, fake, note, _ = _open_maximum_settled(monkeypatch, sel)
    next(b for b in at.button if b.label == "Confirm and run").click().run()
    n = len(tool_calls)
    next(s for s in at.selectbox if s.label == "Operation").set_value("single_interval_comparison")
    next(b for b in at.button if b.label == "Apply changes").click().run()
    assert not at.exception
    assert _rows(at)["Needs clarification"] == "Which half-hour? Give the time it ends, in the region's local time."
    assert not [b for b in at.button if b.label == "Confirm and run"] and len(tool_calls) == n  # nothing runs
    assert any("the request has changed since" in t for t in _texts(at))  # the earlier result is labelled stale
    at.chat_input[0].set_value("18:30").run()  # the reply settles it: the requirements move on
    now = _rows(at)["Needs clarification"]
    assert now != "nothing" and "Which half-hour?" not in now
    assert C.issues(C.draft_of(at.session_state["confirm_flow"]), sel)[0].field == "run"
    assert fake.calls == 1 and len(tool_calls) == n and not any(note in t for t in _shown_now(at))
