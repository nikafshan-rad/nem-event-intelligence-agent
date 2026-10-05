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
