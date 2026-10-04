"""D31 Amendment 1 (docs/decisions.md): route contract v16, the request plan, and its deterministic compiler, offline.

One routing call returns a typed plan (operations with a stance, a kind and a subject, referring by id to their scope,
run and cutoff); code compiles it into the existing ``RequestResolution``. The path is opt-in (``NEM_AGENT_ROUTE_PLAN``)
and off by default, and a decision recorded under v12-v15 keeps its resolver whatever the switch says.

- **The default path:** with the switch off, Live sends contract v15 with prompts v16, byte for byte as before; every
  saved v12-v15 decision resolves identically with the switch off and on.
- **Admission:** incomplete, unparsable and structurally invalid plans, and plans that are sent back, offer no tools
  and execute nothing.
- **Scripted plans** (resolution level): incidental demand mentions, ambiguity, negation, background, shared scope,
  mixed operations and kinds, time roles, missing references and request overrides; the known unsupported cases
  (noon, midday, parts of the day, windows over the limits) are sent back, not claimed fixed.
- **The v15 diagnostic questions** with scripted correct plans, against the frozen gold (read, never changed).
- **Equivalence** (the real store, the saved end-to-end records replayed through the SYNTHETIC fake transport): the
  same reading given as a plan computes, verifies, validates and renders the same answer as under v15; the new metadata
  (the contract label, the plan record, the echo note, prompts v17) is listed apart.
- **The interpretation echo:** labelled controller metadata in the notes channel; serialised and displayed; withdrawn
  when the question does not run; fallback withholding and the interpretation status are unchanged.

These are design controls on scripted plans: they show what the compiler does with a given reading, independently of
how a hosted model extracts one. They are not evidence of extraction quality or of generalisation, and they make no
Live claim."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from nem_agent import config
from nem_agent.agent import plan as request_plan
from nem_agent.agent.live import LiveController, RouteDecision, checked_route
from nem_agent.agent.plan import (
    ECHO_LABEL,
    PLAN_INVALID_CLARIFICATION,
    PLAN_OPERATION_CLARIFICATION,
    PLAN_OPERATIONS_CLARIFICATION,
    PlanRouteDecision,
)
from nem_agent.agent.request import (
    HALF_HOUR_CLARIFICATION,
    MAXIMUM_CLARIFICATION,
    MAXIMUM_WINDOW_CLARIFICATION,
    InvestigateRequest,
)
from nem_agent.agent.structured import (
    CUTOFF_CLARIFICATION,
    DEMAND_FORECAST_TOOLS,
    FORECAST_DOMAIN_CLARIFICATION,
    FORECAST_LIMIT_CLARIFICATION,
    FORECAST_OPERATION_CLARIFICATION,
    FORECAST_SCOPE_CLARIFICATION,
    FORECAST_UNSUPPORTED_CLARIFICATION,
    PLAN_CUTOFF_CLARIFICATION,
    START_OR_END_CLARIFICATION,
    not_answered_note,
)
from nem_agent.display import plain_note
from nem_agent.evidence import EvidenceRegistry
from nem_agent.report import InvestigationReport, Versions
from nem_agent.selection import load_selection
from nem_agent.service import investigate, resolve_routed
from nem_agent.tools.args import strict_json_schema
from nem_agent.trace import Trace
from tests.provider.fake_model import FakeModel, msg

pytestmark = pytest.mark.synthetic

ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "artifacts" / "live"
E2E = LIVE / "LC-e2e-v13-run"
PROMPTS = ROOT / "src" / "nem_agent" / "prompts"
SEL = load_selection()
TOP = {"needs_clarification": False, "clarification_reason": None, "clarification": None, "out_of_scope": False}
# the v15 routing schema and prompt as at v2.0.0 (82c6ac7): the default path sends exactly these
V15_ROUTE_SCHEMA_SHA256 = "bff0a62bbbf02d8b7135026325a8015be97256e95a5a9dc34c5154ea51a92262"
V16_ROUTE_PROMPT_SHA256 = "0f470764ff3b3daab3b10dcea7b2f7745fe660145559db327b383796b91b8eec"


# ------------------------------------------------------------------------------------------------ helpers
def op(i: str, kind: str, subject: str, subject_text: str | None, operation_text: str | None, scope: str | None = None,
       run: str | None = None, cutoff: str | None = None, stance: str = "asked") -> dict[str, Any]:
    """A SYNTHETIC plan operation."""
    return {"id": i, "stance": stance, "kind": kind, "subject": subject, "subject_text": subject_text,
            "operation_text": operation_text, "scope_ref": scope, "run_ref": run, "cutoff_ref": cutoff}


def decision(intent: str | None, region: str | None, event_date: str | None, operations: list[dict[str, Any]],
             scopes: dict[str, tuple[str, str]] | None = None, runs: dict[str, tuple[str, str]] | None = None,
             cutoffs: dict[str, str] | None = None, cutoff_ref: str | None = None, **top: Any) -> dict[str, Any]:
    """A SYNTHETIC route contract v16 decision: scopes and runs as {id: (kind or selection, words)}."""
    return {"intent": intent, "region": region, "event_date": event_date, **TOP, **top, "plan": {
        "operations": operations,
        "scopes": [{"id": k, "kind": v[0], "text": v[1]} for k, v in (scopes or {}).items()],
        "runs": [{"id": k, "selection": v[0], "text": v[1]} for k, v in (runs or {}).items()],
        "cutoffs": [{"id": k, "text": v} for k, v in (cutoffs or {}).items()], "cutoff_ref": cutoff_ref}}


def resolved(q: str, d: dict[str, Any], **request: Any) -> Any:
    """The resolution of a question from a scripted v16 decision, as Live resolves it."""
    return resolve_routed(InvestigateRequest(question=q, mode="live", **request),
                          request_plan.checked_plan_route(PlanRouteDecision.model_validate(d)), SEL)


def bound(res: Any) -> dict[str, Any]:
    """What the controllers read from a resolution (``forecast_compare``, ``demand_max``, the Live context, the
    dispatcher): the fields compared for equivalence."""
    r = res.requests
    fr = r.forecast_run.forecast_request()

    def iso(w: Any) -> list[str] | None:
        return [t.isoformat() for t in w] if w else None
    return {"status": res.status, "reasons": res.reasons, "intent": res.intent, "region": res.region,
            "as_of": res.as_of.isoformat() if res.as_of else None, "window": iso(res.window), "target": iso(res.target),
            "event": res.event.event_id if res.event else None,
            "run": (fr.run, fr.issued_at.isoformat() if fr and fr.issued_at else None, iso(fr.half_hour)) if fr else None,
            "forecast": (r.forecast.status, r.forecast.operation, r.forecast.scope, iso(r.forecast.target),
                         iso(r.forecast.window), r.forecast.domain if r.forecast.status == "bound" else None,
                         r.forecast.unsupported if r.forecast.status == "bound" else None),
            "maximum": (r.maximum.status, r.maximum.measures, r.maximum.window_kind, iso(r.maximum.window)),
            "cutoff": (r.cutoff.status, r.cutoff.as_of.isoformat() if r.cutoff.as_of else None),
            "ineligible_tools": sorted(r.ineligible_tools),
            "notes": [n for n in r.notes if not n.startswith(ECHO_LABEL)]}


class PlanFake(FakeModel):
    """The SYNTHETIC fake transport, answering the v16 routing call with a scripted plan."""

    def __init__(self, plan: dict[str, Any] | None, *args: Any, raw: dict[str, Any] | None = None, **kw: Any) -> None:
        super().__init__({}, *args, **kw)
        self.plan, self.raw = plan, raw

    def create(self, **kw: Any) -> dict[str, Any]:
        if (kw.get("text") or {}).get("format", {}).get("name") == "PlanRouteDecision":
            self.requests.append(copy.deepcopy(kw))
            return self.raw if self.raw is not None else msg(json.dumps(self.plan))
        return super().create(**kw)


def _controller(fake: Any) -> LiveController:
    return LiveController(None, EvidenceRegistry(), Versions(code="test", data=None, corpus=None, prompt="test",
                                                             model=None, controller="live"), client=fake)


DRAFT = {"status": "answered", "headline": "SYNTHETIC.", "summary": ["SYNTHETIC."], "document_statements": [],
         "observation_evidence_ids": [], "possible_explanations": [], "published_findings": [], "citations": [],
         "uncertainties": [], "missing_evidence": [], "forecast_mae_evidence_id": None, "numeric_claims": []}


# ------------------------------------------------------------------------------------------------ the switch
@pytest.mark.parametrize("value, on", [(None, False), ("1", True), ("true", True), ("Yes", True), ("ON", True),
                                       ("0", False), ("", False), ("off", False), ("no", False), ("v16", False)])
def test_the_switch_is_opt_in_and_off_by_default(value, on, monkeypatch):
    if value is not None:
        monkeypatch.setenv("NEM_AGENT_ROUTE_PLAN", value)
    assert config.ROUTE_PLAN_DEFAULT is False
    assert request_plan.enabled() is on
    assert request_plan.prompt_version() == ("prompts/v17" if on else "prompts/v16")
    assert config.PROMPT_VERSION == "prompts/v16" and config.MAX_OUTPUT_TOKENS["route"] == 2_000


@pytest.mark.parametrize("value, policy", [(None, "V1"), ("V1", "V1"), ("v0", "V0"), ("V0", "V0"), ("V2", "V1"),
                                           ("", "V1")])
def test_the_stated_basis_policy_is_v1_unless_v0_is_chosen(value, policy, monkeypatch):
    if value is not None:
        monkeypatch.setenv("NEM_AGENT_PLAN_POLICY", value)
    assert request_plan.policy() == policy


def test_the_default_route_is_contract_v15_with_prompts_v16_unchanged():
    """With the switch off, the routing call is exactly the v2.0.0 one: the v15 schema and the v16 route prompt."""
    fake = FakeModel({"intent": "source_explanation", "region": None, "event_date": None, "as_of_text": None, **TOP,
                      "requested": None}, [], lambda kw: DRAFT)
    lc = _controller(fake)
    dec = lc.route("What does TOTALDEMAND mean?", Trace())
    assert isinstance(dec, RouteDecision) and dec.contract == "v15"
    (call,) = fake.requests
    fmt = call["text"]["format"]
    assert fmt["name"] == "RouteDecision"
    assert hashlib.sha256(json.dumps(fmt["schema"], sort_keys=True).encode()).hexdigest() == V15_ROUTE_SCHEMA_SHA256
    assert hashlib.sha256(call["instructions"].encode()).hexdigest() == V16_ROUTE_PROMPT_SHA256
    assert call["instructions"] == (PROMPTS / "v16" / "route.md").read_text()
    assert lc.prompt_version == "prompts/v16" and call["max_output_tokens"] == 2_000


def test_the_switch_sends_contract_v16_with_prompts_v17(monkeypatch):
    monkeypatch.setenv("NEM_AGENT_ROUTE_PLAN", "1")
    plan = decision("source_explanation", None, None, [])
    fake = PlanFake(plan, [], lambda kw: DRAFT)
    lc = _controller(fake)
    dec = lc.route("What does TOTALDEMAND mean?", Trace())
    assert isinstance(dec, PlanRouteDecision) and dec.contract == "v16"
    (call,) = fake.requests
    assert call["text"]["format"]["name"] == "PlanRouteDecision"
    assert call["instructions"] == (PROMPTS / "v17" / "route.md").read_text()
    assert lc.prompt_version == "prompts/v17" and call["max_output_tokens"] == 2_000  # the cap is unchanged
    for name in ("system", "synthesis"):  # prompts v17 change routing only
        assert (PROMPTS / "v17" / f"{name}.md").read_bytes() == (PROMPTS / "v16" / f"{name}.md").read_bytes()
    assert sorted(p.name for p in (PROMPTS / "v17").iterdir()) == ["route.md", "synthesis.md", "system.md"]


def test_the_v16_schema_is_strict_and_carries_the_plan_only():
    schema = strict_json_schema(PlanRouteDecision)

    def objects(node: Any) -> list[dict[str, Any]]:
        if isinstance(node, dict):
            return ([node] if node.get("type") == "object" else []) + [o for v in node.values() for o in objects(v)]
        return [o for v in node for o in objects(v)] if isinstance(node, list) else []
    assert all(o["required"] == list(o["properties"]) and o["additionalProperties"] is False for o in objects(schema))
    assert "plan" in schema["properties"] and not {"as_of_text", "requested"} & set(schema["properties"])
    assert set(schema["properties"]) - {"plan"} == set(strict_json_schema(RouteDecision)["properties"]) - {
        "as_of_text", "requested"}


def _saved_decisions() -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    out = []
    for p in sorted(LIVE.glob("*/*.json")):
        try:
            rec = json.loads(p.read_text())
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(rec, dict) and isinstance(rec.get("route"), dict) and rec.get("question"):
            out.append((f"{p.parent.name}/{p.stem}", rec["route"], rec))
    return out


def test_every_recorded_decision_keeps_its_resolver_whatever_the_switch(monkeypatch):
    """Every saved decision the current reader accepts (399 of 437: contracts v12, v13 and v15) resolves identically
    with the switch off and on: the contract a decision was given in decides its path, never the switch, and none of
    them reaches the plan compiler. The other 38 are the earliest L1-L3 records, in a shape no current reader accepts,
    with or without this change."""
    saved = _saved_decisions()
    assert len(saved) == 437
    readable = []
    for name, route, rec in saved:
        try:
            readable.append((name, checked_route(RouteDecision.model_validate(route)), rec))
        except ValidationError:
            assert name.split("/")[0] in ("L1", "L2", "L2-run1", "L2-run2", "L2-run3", "L2-run4", "L3", "L3-run1")
    assert len(readable) == 399
    for name, dec, rec in readable:
        route = rec["route"]
        assert dec.contract in ("v12", "v13", "v14", "v15"), name
        req = InvestigateRequest(question=rec["question"], mode="live", **(rec.get("request") or {}))
        monkeypatch.delenv("NEM_AGENT_ROUTE_PLAN", raising=False)
        off = resolve_routed(req, dec, SEL)
        monkeypatch.setenv("NEM_AGENT_ROUTE_PLAN", "1")
        on = resolve_routed(req, checked_route(RouteDecision.model_validate(route)), SEL)
        assert (off.status, off.reasons, off.routing) == (on.status, on.reasons, on.routing), name
        assert off.requests is None or (off.requests.plan is None and off.requests.contract != "v16"), name
        assert "plan" not in (off.routing.get("requests") or {}), name


# ------------------------------------------------------------------------------------------------ admission
Q_N04 = ("Leave the weather forecast out of this one. For Victoria, I want AEMO's operational demand forecast values "
         "for a single half-hour on 17 August 2026: the one ending at 18:30 AEST. What did they show?")


def _n04(**over: Any) -> dict[str, Any]:
    return decision("forecast_review", "VIC1", "2026-08-17", [
        op("o1", "forecast_value", "weather", "the weather forecast", "Leave the weather forecast out of this one",
           stance="declined"),
        op("o2", "forecast_value", "operational_demand", "AEMO's operational demand forecast values",
           "What did they show?", "s1")],
        scopes={"s1": ("half_hour", "a single half-hour on 17 August 2026: the one ending at 18:30 AEST")}, **over)


@pytest.mark.parametrize("breakage, problem", [
    (lambda d: d["plan"]["operations"].append(dict(d["plan"]["operations"][1])), "repeated ids"),
    (lambda d: d["plan"]["operations"][1].update(scope_ref="s9"), "o2.scope_ref"),
    (lambda d: d["plan"]["operations"][1].update(run_ref="s1"), "o2.run_ref"),  # a scope's id given as a run
    (lambda d: d["plan"]["operations"][1].update(cutoff_ref="c1"), "o2.cutoff_ref"),
    (lambda d: d["plan"].update(cutoff_ref="c1"), "cutoff_ref"),
])
def test_a_structurally_invalid_plan_is_sent_back_before_anything_is_read(breakage, problem):
    d = _n04()
    breakage(d)
    res = resolved(Q_N04, d)
    assert res.status == "needs_clarification" and res.reasons == [PLAN_INVALID_CLARIFICATION]
    assert any(p.startswith(problem) for p in res.requests.plan["problems"])
    assert res.requests.forecast.status == "absent" and res.requests.forecast_run.status == "absent"
    assert res.requests.cutoff.status == "absent" and not res.requests.notes


@pytest.mark.parametrize("raw", [
    {"id": "r", "status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
     "output": [{"type": "message", "content": [{"type": "output_text", "text": "{\"intent\": \"forecast_re"}]}],
     "usage": {"output_tokens": 2000}},
    msg("not json"),
    msg(json.dumps({**_n04(), "as_of_text": None})),  # a v15 field: the strict v16 schema forbids it
])
def test_an_incomplete_or_invalid_routing_response_is_no_decision(raw, monkeypatch):
    """Rejected before parsing or by the schema, with no prefix salvaged: the question is sent back (fail closed)."""
    monkeypatch.setenv("NEM_AGENT_ROUTE_PLAN", "1")
    fake = PlanFake(None, [], lambda kw: DRAFT, raw=raw)
    assert _controller(fake).route(Q_N04, Trace()) is None
    res = resolve_routed(InvestigateRequest(question=Q_N04, mode="live"), None, SEL)
    assert res.status == "needs_clarification" and res.reasons == ["The routing model returned invalid output."]


@pytest.mark.parametrize("plan, raw", [
    ({**_n04(), "plan": {**_n04()["plan"], "cutoff_ref": "c9"}}, None),  # invalid
    (None, msg("not json")),  # unparsable
    (decision("forecast_review", "QLD1", "2026-08-04", [  # sent back: "noon" cannot be read (known unsupported)
        op("o1", "forecast_comparison", "operational_demand", "AEMO's operational demand forecast for Queensland",
           "How did AEMO's operational demand forecast for Queensland compare with actual operational demand", "s1")],
        scopes={"s1": ("explicit", "between 06:00 and noon AEST on 4 August 2026")}), None),
])
def test_incomplete_invalid_and_sent_back_plans_offer_no_tools_and_execute_nothing(plan, raw, real_store, monkeypatch):
    monkeypatch.setenv("NEM_AGENT_ROUTE_PLAN", "1")
    q = ("How did AEMO's operational demand forecast for Queensland compare with actual operational demand between "
         "06:00 and noon AEST on 4 August 2026?") if plan and plan["region"] == "QLD1" else Q_N04
    fake = PlanFake(plan, [[("get_forecast_runs", {"region": "VIC1"})]], lambda kw: DRAFT, raw=raw)
    res = investigate(InvestigateRequest(question=q, mode="live"), live_client=fake, write_trace=False)
    assert res.report.status == "needs_clarification"
    assert len(fake.requests) == 1 and fake.issued == [] and res.records == []  # the routing call only
    assert not res.report.answer and not res.report.results and not res.report.observations
    assert not any(u.startswith(ECHO_LABEL) for u in res.report.uncertainties)


# ------------------------------------------------------------------------------------------------ scripted plans
Q_INCIDENTAL = ("Demand was high across Victoria that evening. What did the last forecast issued before the half-hour "
                "ending 18:30 AEST on 17 August 2026 say?")


def _incidental(subject: str, subject_text: str | None) -> dict[str, Any]:
    return decision("forecast_review", "VIC1", "2026-08-17", [
        op("o1", "forecast_value", subject, subject_text, "What did the last forecast issued before", "s1", "r1")],
        scopes={"s1": ("half_hour", "the half-hour ending 18:30 AEST on 17 August 2026")},
        runs={"r1": ("last_issued_before", "the last forecast issued before")})


def test_an_incidental_demand_mention_does_not_name_the_forecast(monkeypatch):
    """The question mentions demand, but its forecast is unnamed. The correct reading (not stated) is clarified; a
    reading that claims demand on the forecast's own words is clarified under V1 and accepted under V0."""
    assert resolved(Q_INCIDENTAL, _incidental("not_stated", None)).reasons == [FORECAST_DOMAIN_CLARIFICATION]
    claimed = _incidental("operational_demand", "the last forecast")
    res = resolved(Q_INCIDENTAL, claimed)
    assert res.reasons == [FORECAST_DOMAIN_CLARIFICATION]
    assert any("V1" in n for n in res.requests.plan["operations"]["o1"]["notes"])
    monkeypatch.setenv("NEM_AGENT_PLAN_POLICY", "V0")
    res = resolved(Q_INCIDENTAL, claimed)
    assert res.status == "ok" and res.requests.forecast.operation == "forecast_value"
    assert res.requests.plan["policy"] == "V0"


def test_v1_is_not_semantic_verification(monkeypatch):
    """A limitation, shown: a reading that takes its subject from the incidental mention ('Demand') holds the
    vocabulary, so V1 accepts it. Located words and vocabulary are provenance, not meaning."""
    res = resolved(Q_INCIDENTAL, _incidental("operational_demand", "Demand"))
    assert res.status == "ok" and res.requests.forecast.domain == "operational_demand"


Q_D08 = "As of 2026-07-30T14:35:00Z, what did the latest issued forecast say for the SA1 peak half-hour on 2026-07-31?"
Q_N03 = ("I'm reviewing how 10 August 2026 played out in New South Wales. How far off were the forecasts on the day, "
         "compared with what actually happened?")


def _d08(subject: str, subject_text: str | None) -> dict[str, Any]:
    return decision("forecast_review", "SA1", "2026-07-31", [
        op("o1", "forecast_value", subject, subject_text, "what did the latest issued forecast say", "s1", "r1", "c1")],
        scopes={"s1": ("event_peak_half_hour", "the SA1 peak half-hour on 2026-07-31")},
        runs={"r1": ("as_of_availability", "the latest issued forecast")}, cutoffs={"c1": "As of 2026-07-30T14:35:00Z"})


def _n03(subject: str, subject_text: str | None) -> dict[str, Any]:
    return decision("forecast_review", "NSW1", "2026-08-10", [
        op("o1", "forecast_comparison", subject, subject_text, "How far off were the forecasts", "s1")],
        scopes={"s1": ("whole_local_day", "on the day")})


@pytest.mark.parametrize("q, make", [(Q_D08, _d08), (Q_N03, _n03)], ids=["D08", "N03"])
def test_an_unnamed_forecast_is_clarified_never_assumed_to_be_demand(q, make, monkeypatch):
    """Ambiguity (v15 D08 and N03): the correct reading is clarified; the misreading v15 accepted for D08 (and
    stopped for N03 only incidentally) is clarified under V1, and accepted under V0, which trusts the stated basis."""
    assert resolved(q, make("not_stated", None)).reasons == [FORECAST_DOMAIN_CLARIFICATION]
    words = "the latest issued forecast" if q == Q_D08 else "the forecasts"
    assert resolved(q, make("operational_demand", words)).reasons == [FORECAST_DOMAIN_CLARIFICATION]
    monkeypatch.setenv("NEM_AGENT_PLAN_POLICY", "V0")
    assert resolved(q, make("operational_demand", words)).status == "ok"


def test_a_declined_forecast_is_neither_answered_nor_named_as_unanswered():
    """Negation (v15 N04's resolver defect): the declined weather forecast is not executed and not named as not
    answered; the requested demand forecast value binds as the gold says."""
    res = resolved(Q_N04, _n04())
    b = bound(res)
    assert res.status == "ok" and b["forecast"][:5] == ("bound", "forecast_value", "half_hour",
                                                        ["2026-08-17T08:00:00+00:00", "2026-08-17T08:30:00+00:00"],
                                                        None)
    assert b["notes"] == [] and res.requests.forecast.unsupported == []
    assert res.requests.plan["declined"] == ["o1"] and res.requests.plan["not_answered"] == []


Q_N05 = ("I don't need AEMO's operational demand forecast for this. What did the weather forecasters expect for Hobart "
         "on 2 August 2026, particularly wind and rain?")


@pytest.mark.parametrize("intent", ["forecast_review", "market_event_review"])
def test_a_declined_demand_forecast_and_an_asked_weather_forecast(intent):
    d = decision(intent, "TAS1", "2026-08-02", [
        op("o1", "forecast_value", "operational_demand", "AEMO's operational demand forecast",
           "I don't need AEMO's operational demand forecast for this", stance="declined"),
        op("o2", "forecast_value", "weather", "wind and rain", "What did the weather forecasters expect", "s1")],
        scopes={"s1": ("whole_local_day", "for Hobart on 2 August 2026")})
    res = resolved(Q_N05, d)
    if intent == "forecast_review":
        assert res.reasons == [FORECAST_UNSUPPORTED_CLARIFICATION]
    else:  # an event review: the demand-forecast tools serve none, and the weather forecast is named as not answered
        assert res.status == "ok" and set(res.requests.ineligible_tools) == set(DEMAND_FORECAST_TOOLS)
        assert res.requests.notes == [not_answered_note(["weather"])]


Q_N06 = ("For context, someone in our operations team told me \"AEMO's demand forecast for South Australia came in well "
         "below the actuals.\" What minimum temperature had been forecast for Adelaide on 14 August 2026?")


def test_quoted_background_is_not_a_request():
    d = decision("forecast_review", "SA1", "2026-08-14", [
        op("o1", "forecast_comparison", "operational_demand", "AEMO's demand forecast for South Australia",
           "came in well below the actuals", stance="background"),
        op("o2", "forecast_value", "weather", "minimum temperature", "What minimum temperature had been forecast", "s1")],
        scopes={"s1": ("whole_local_day", "for Adelaide on 14 August 2026")})
    assert resolved(Q_N06, d).reasons == [FORECAST_UNSUPPORTED_CLARIFICATION]


def test_the_quotation_mark_check_rejects_a_quoted_request_conservatively():
    """Decision 4: words only inside quotation marks are background, so a question that quotes its own request is
    sent back. This is conservative, and documented: such a question is not answered."""
    q = "Show me \"the highest operational demand in Queensland\" on 29 July 2026."
    d = decision("market_event_review", "QLD1", "2026-07-29", [
        op("o1", "demand_maximum", "operational_demand", "operational demand",
           "the highest operational demand in Queensland", "s1")], scopes={"s1": ("whole_local_day", "on 29 July 2026")})
    res = resolved(q, d)
    assert res.status == "needs_clarification" and res.reasons == [PLAN_OPERATION_CLARIFICATION]
    assert any("quotation marks" in n for n in res.requests.plan["operations"]["o1"]["notes"])


def test_a_cutoff_of_background_material_only_is_not_active():
    """Decision 3: a cutoff that only a background operation refers to holds its words (and their time) but does not
    constrain; the parser's as-of words inside quotation marks are not an omission."""
    q = ("An analyst wrote \"as of 14:00 AEST the forecast looked high\". What was the highest operational demand in "
         "Queensland on 29 July 2026?")
    d = decision("market_event_review", "QLD1", "2026-07-29", [
        op("o1", "forecast_value", "not_stated", None, "the forecast looked high", cutoff="c1", stance="background"),
        op("o2", "demand_maximum", "operational_demand", "operational demand",
           "What was the highest operational demand in Queensland", "s1")],
        scopes={"s1": ("whole_local_day", "on 29 July 2026")}, cutoffs={"c1": "as of 14:00 AEST"})
    res = resolved(q, d)
    assert res.status == "ok" and res.as_of is None and res.requests.cutoff.status == "absent"
    assert res.requests.maximum.status == "bound" and res.requests.maximum.window_kind == "day"


def test_a_declined_operation_holds_its_time_without_creating_a_request():
    """A contextual time held by declined material: no omission, no constraint, no request."""
    q = ("Ignoring the 18:00 ACST weather update, how accurate were the operational demand forecasts for SA1 on 31 July "
         "2026?")
    d = decision("forecast_review", "SA1", "2026-07-31", [
        op("o1", "forecast_value", "weather", "weather update", "Ignoring the 18:00 ACST weather update",
           stance="declined"),
        op("o2", "forecast_comparison", "operational_demand", "the operational demand forecasts",
           "how accurate were the operational demand forecasts", "s1")], scopes={"s1": ("whole_local_day",
                                                                                      "on 31 July 2026")})
    res = resolved(q, d)
    assert res.status == "ok" and res.requests.forecast.operation == "window_comparison"
    loose = d | {"plan": {**d["plan"], "operations": d["plan"]["operations"][1:]}}  # without it, 18:00 is unheld
    assert resolved(q, loose).reasons == [FORECAST_SCOPE_CLARIFICATION]


Q_D07 = ("For South Australia's half-hour closing 2026-07-29T08:00:00Z, what POE50 operational demand did AEMO's newest "
         "forecast run show as of 2026-07-29T05:00:00Z, and what temperature was then expected for Adelaide at that "
         "time?")


def _d07() -> dict[str, Any]:
    return decision("forecast_review", "SA1", "2026-07-29", [
        op("o1", "forecast_value", "operational_demand", "POE50 operational demand",
           "what POE50 operational demand did AEMO's newest forecast run show", "s1", "r1", "c1"),
        op("o2", "forecast_value", "weather", "temperature",
           "what temperature was then expected for Adelaide at that time", "s1", None, "c1")],
        scopes={"s1": ("half_hour", "South Australia's half-hour closing 2026-07-29T08:00:00Z")},
        runs={"r1": ("as_of_availability", "AEMO's newest forecast run")}, cutoffs={"c1": "as of 2026-07-29T05:00:00Z"})


def test_a_shared_scope_and_cutoff_serve_the_asked_request_and_another_kind_is_named():
    """Shared scope and mixed kinds (v15 D07: rejected by clause containment, the half-hour stated before the demand
    clause): both operations refer to the same half-hour and cutoff; the demand forecast binds, the temperature
    forecast is named as not answered."""
    res = resolved(Q_D07, _d07())
    b = bound(res)
    assert res.status == "ok"
    assert b["forecast"][:4] == ("bound", "forecast_value", "half_hour",
                                 ["2026-07-29T07:30:00+00:00", "2026-07-29T08:00:00+00:00"])
    assert b["cutoff"] == ("bound", "2026-07-29T05:00:00+00:00") and res.requests.forecast_run.status == \
        "as_of_availability"
    assert b["notes"] == [not_answered_note(["weather"])]


Q_MIXED = ("For SA1 on 31 July 2026, how did the operational demand forecasts compare with actual demand, and when was "
           "operational demand highest?")


def test_distinct_asked_operations_are_clarified_never_chosen_between():
    """Decision 1: a forecast comparison and a demand maximum asked together; two maxima of two measures."""
    d = decision("forecast_review", "SA1", "2026-07-31", [
        op("o1", "forecast_comparison", "operational_demand", "the operational demand forecasts",
           "how did the operational demand forecasts compare with actual demand", "s1"),
        op("o2", "demand_maximum", "operational_demand", "operational demand", "when was operational demand highest",
           "s1")], scopes={"s1": ("whole_local_day", "on 31 July 2026")})
    res = resolved(Q_MIXED, d)
    assert res.reasons == [PLAN_OPERATIONS_CLARIFICATION] and res.requests.plan["primary"] is None
    assert res.requests.forecast.status == "absent" and res.requests.maximum.status == "absent"
    q = "On 29 July 2026, when were Queensland's dispatch total demand and operational demand each at their highest?"
    two = decision("market_event_review", "QLD1", "2026-07-29", [
        op("o1", "demand_maximum", "dispatch_total_demand", "dispatch total demand", "each at their highest", "s1"),
        op("o2", "demand_maximum", "operational_demand", "operational demand", "each at their highest", "s1")],
        scopes={"s1": ("whole_local_day", "On 29 July 2026")})
    assert resolved(q, two).reasons == [PLAN_OPERATIONS_CLARIFICATION]


_NO_RUN = {"selection": "none", "selection_text": None, "half_hour_text": None}
_NO_MAX = {"kind": "none", "measure": None, "measure_text": None, "peak_text": None, "window": None, "window_text": None}


def _v15(intent: str, region: str, event_date: str, forecast: dict[str, Any] | None = None,
         maximum: dict[str, Any] | None = None, run: dict[str, Any] | None = None) -> RouteDecision:
    """A SYNTHETIC v15 decision with the same reading, for the changed outcomes."""
    return checked_route(RouteDecision.model_validate({
        "intent": intent, "region": region, "event_date": event_date, "as_of_text": None, **TOP,
        "requested": {"forecast_run": run or _NO_RUN, "maximum": maximum or _NO_MAX, "forecast": forecast}}))


def test_changed_outcomes_against_v15_for_the_same_question():
    """Recorded in D31 Amendment 1's implementation entry: what v15 does with the same question and the reading its
    single fields can hold, and what the plan does. v15 binds one request silently; the plan sends the question back."""
    live = InvestigateRequest(question=Q_MIXED, mode="live")
    old = resolve_routed(live, _v15("forecast_review", "SA1", "2026-07-31", forecast={
        "operation": "window_comparison", "operation_text": "how did the operational demand forecasts compare with "
        "actual demand", "scope": "whole_local_day", "scope_text": "on 31 July 2026", "domain": "operational_demand",
        "request_text": "how did the operational demand forecasts compare with actual demand", "unsupported_text": None},
        maximum={"kind": "maximum", "measure": "operational_demand", "measure_text": "operational demand highest",
                 "peak_text": "highest", "window": "whole_local_day", "window_text": "on 31 July 2026"}), SEL)
    assert old.status == "ok" and old.requests.maximum.status == "bound" and old.requests.forecast.status == "absent"
    assert old.requests.notes == [not_answered_note([])]  # the comparison asked for: noted as an unnamed forecast
    q = "On 29 July 2026, when were Queensland's dispatch total demand and operational demand each at their highest?"
    old = resolve_routed(InvestigateRequest(question=q, mode="live"), _v15("market_event_review", "QLD1", "2026-07-29",
        maximum={"kind": "maximum", "measure": "dispatch_total_demand", "measure_text": "dispatch total demand",
                 "peak_text": "highest", "window": "whole_local_day", "window_text": "On 29 July 2026"}), SEL)
    assert old.status == "ok" and old.requests.maximum.measures == ["total demand"]  # one of the two asked
    old = resolve_routed(InvestigateRequest(question=Q_CUTOFF, mode="live"), _v15("forecast_review", "VIC1",
        "2026-08-17", forecast={"operation": "forecast_value", "operation_text": "what did the last operational demand "
        "forecast issued before", "scope": "half_hour", "scope_text": "the half-hour ending 18:30 AEST that day",
        "domain": "operational_demand", "request_text": "what did the last operational demand forecast issued before "
        "the half-hour ending 18:30 AEST that day give for Victoria", "unsupported_text": None},
        run={"selection": "last_issued_before", "selection_text": "the last operational demand forecast issued before",
             "half_hour_text": "the half-hour ending 18:30 AEST that day"}), SEL)
    assert old.status == "ok" and old.as_of is not None  # the parser's as-of words, applied to the whole question
    assert resolved(Q_CUTOFF, _cutoff_plan(None, with_cutoff=False)).reasons == [PLAN_CUTOFF_CLARIFICATION]


Q_R02 = ("Taking South Australia's 7:30-8:00 am half-hour (Adelaide time, ACST) on 20 August 2026: what POE10, POE50 "
         "and POE90 operational demand values were in the final forecast run issued ahead of it, and what operational "
         "demand was actually measured?")


def _r02(second_run: str = "r1", run: tuple[str, str] | None = ("last_issued_before",
                                                                  "the final forecast run issued ahead of it"),
         scope: tuple[str, str] = ("half_hour", "South Australia's 7:30-8:00 am half-hour (Adelaide time, ACST) on 20 "
                                                "August 2026")) -> dict[str, Any]:
    runs = {"r1": run, "r2": ("issued_at", "the final forecast run issued ahead of it")} if run else {}
    return decision("forecast_review", "SA1", "2026-08-20", [
        op("o1", "forecast_value", "operational_demand", "POE10, POE50 and POE90 operational demand values",
           "what POE10, POE50 and POE90 operational demand values were in the final forecast run", "s1",
           "r1" if run else None),
        op("o2", "forecast_comparison", "operational_demand", "POE10, POE50 and POE90 operational demand values",
           "what operational demand was actually measured", "s1", second_run if run else None)],
        scopes={"s1": scope}, runs=runs)


def test_a_value_and_a_comparison_are_one_comparison_only_when_it_contains_the_values():
    """Decision 1: identical subject, scope, run and cutoff, one half-hour under a named run (its point result carries
    POE50, POE10, POE90 and the actual): one comparison. A different run, no named run, or a period: clarified."""
    res = resolved(Q_R02, _r02())
    assert res.status == "ok" and res.requests.forecast.operation == "single_interval_comparison"
    assert res.requests.plan["primary"] == "o2" and res.requests.plan["consolidated"] == ["o1"]
    assert resolved(Q_R02, _r02(second_run="r2")).reasons == [PLAN_OPERATIONS_CLARIFICATION]  # another run (unread)
    assert resolved(Q_R02, _r02(run=None)).reasons == [PLAN_OPERATIONS_CLARIFICATION]  # no named run: no values
    q = "What did the operational demand forecasts say for NSW1 on 31 July 2026, and how accurate were they?"
    period = decision("forecast_review", "NSW1", "2026-07-31", [
        op("o1", "forecast_value", "operational_demand", "the operational demand forecasts",
           "What did the operational demand forecasts say", "s1"),
        op("o2", "forecast_comparison", "operational_demand", "the operational demand forecasts",
           "how accurate were they", "s1")], scopes={"s1": ("whole_local_day", "for NSW1 on 31 July 2026")})
    assert resolved(q, period).reasons == [PLAN_OPERATIONS_CLARIFICATION]  # an aggregate does not hold every value
    duplicate = copy.deepcopy(period)
    duplicate["plan"]["operations"][0]["kind"] = "forecast_comparison"
    res = resolved(q, duplicate)  # identical duplicates are one operation
    assert res.status == "ok" and res.requests.forecast.operation == "window_comparison"


Q_D01 = ("Take the forecast run issued at 2026-07-30T18:56:59Z. For Tasmania's half-hour ending at 8:00 am AEST, 31 July "
         "2026, which POE10, POE50 and POE90 operational demand values did it give, and how much operational demand "
         "was actually recorded in that half-hour?")


def test_target_issue_time_and_cutoff_are_distinct_roles():
    """Time roles: a run named by its issue time, the target half-hour and a cutoff are each read from their own
    words; none is required to equal another, and the cutoff does not replace the run's selection."""
    q = "As of 2026-07-30T20:00:00Z: " + Q_D01
    d = decision("forecast_review", "TAS1", "2026-07-31", [
        op("o1", "forecast_comparison", "operational_demand", "POE10, POE50 and POE90 operational demand values",
           "how much operational demand was actually recorded in that half-hour", "s1", "r1", "c1")],
        scopes={"s1": ("half_hour", "Tasmania's half-hour ending at 8:00 am AEST, 31 July 2026")},
        runs={"r1": ("issued_at", "the forecast run issued at 2026-07-30T18:56:59Z")},
        cutoffs={"c1": "As of 2026-07-30T20:00:00Z"})
    b = bound(resolved(q, d))
    assert b["status"] == "ok" and b["run"] == ("issued_at", "2026-07-30T18:56:59+00:00",
                                                ["2026-07-30T21:30:00+00:00", "2026-07-30T22:00:00+00:00"])
    assert b["cutoff"] == ("bound", "2026-07-30T20:00:00+00:00")
    assert b["forecast"][1] == "single_interval_comparison"


Q_D05 = ("As of 2026-08-19T20:00:00Z, looking only at runs already public, what was the newest Victorian operational "
         "demand forecast for the 23:00 to 23:30 UTC half-hour, at POE10, POE50 and POE90?")


def test_a_clock_only_half_hour_is_dated_by_the_cutoff_only_as_under_i10():
    d = decision("forecast_review", "VIC1", None, [
        op("o1", "forecast_value", "operational_demand", "Victorian operational demand forecast",
           "what was the newest Victorian operational demand forecast", "s1", "r1", "c1")],
        scopes={"s1": ("half_hour", "the 23:00 to 23:30 UTC half-hour")},
        runs={"r1": ("as_of_availability", "looking only at runs already public")},
        cutoffs={"c1": "As of 2026-08-19T20:00:00Z"})
    b = bound(resolved(Q_D05, d))
    assert b["status"] == "ok" and b["forecast"][3] == ["2026-08-19T23:00:00+00:00", "2026-08-19T23:30:00+00:00"]
    assert b["cutoff"] == ("bound", "2026-08-19T20:00:00+00:00")
    late = Q_D05.replace("20:00:00Z", "23:10:00Z")  # the half-hour starts before the cutoff: not safe to date
    later = copy.deepcopy(d)
    later["plan"]["cutoffs"][0]["text"] = "As of 2026-08-19T23:10:00Z"
    assert resolved(late, later).status == "needs_clarification"


def test_a_bracket_restating_a_held_time_is_held_and_another_time_is_not():
    q = ("For Tasmania's half-hour ending 2026-07-30T22:00:00Z (8:00 am AEST on 31 July), what did the last operational "
         "demand forecast issued before it give?")
    d = decision("forecast_review", "TAS1", "2026-07-31", [
        op("o1", "forecast_value", "operational_demand", "operational demand forecast",
           "what did the last operational demand forecast issued before it give", "s1", "r1")],
        scopes={"s1": ("half_hour", "Tasmania's half-hour ending 2026-07-30T22:00:00Z")},
        runs={"r1": ("last_issued_before", "the last operational demand forecast issued before it")})
    assert resolved(q, d).status == "ok"
    other = q.replace("(8:00 am AEST", "(9:00 am AEST")  # a bracket stating another instant holds nothing
    assert resolved(other, d).reasons == [FORECAST_SCOPE_CLARIFICATION]


def test_the_same_words_read_as_cutoff_and_scope_are_a_conflict():
    q = "What did the operational demand forecast available by 18:00 AEST on 17 August 2026 give for Victoria?"
    d = decision("forecast_review", "VIC1", "2026-08-17", [
        op("o1", "forecast_value", "operational_demand", "operational demand forecast",
           "What did the operational demand forecast available by 18:00 AEST on 17 August 2026 give", "s1",
           cutoff="c1")], scopes={"s1": ("half_hour", "18:00 AEST on 17 August 2026")},
        cutoffs={"c1": "available by 18:00 AEST on 17 August 2026"})
    res = resolved(q, d)
    assert res.status == "needs_clarification" and res.requests.cutoff.status == "conflict"


def test_two_readings_of_the_same_cutoff_words_must_agree():
    """Same role, same words: the plan's cutoff words and the parser's as-of words overlap, and read as different
    instants (the plan's words reach 17:00 first, the parser's read 18:00). Neither is chosen: sent back."""
    q = ("Using what was public at 17:00 AEST, as of 18:00 AEST on 17 August 2026, what did the newest operational "
         "demand forecast give for Victoria's half-hour ending 19:00 AEST that day?")
    d = decision("forecast_review", "VIC1", "2026-08-17", [
        op("o1", "forecast_value", "operational_demand", "operational demand forecast",
           "what did the newest operational demand forecast give", "s1", "r1", "c1")],
        scopes={"s1": ("half_hour", "Victoria's half-hour ending 19:00 AEST that day")},
        runs={"r1": ("as_of_availability", "the newest operational demand forecast")},
        cutoffs={"c1": "public at 17:00 AEST, as of 18:00 AEST on 17 August 2026"})
    res = resolved(q, d)
    assert res.status == "needs_clarification" and res.requests.cutoff.status == "conflict"
    assert res.requests.cutoff.conflicts == ["cutoff: 2026-08-17T08:00:00Z (question parser) or 2026-08-17T07:00:00Z "
                                             "(the plan)"]
    agree = copy.deepcopy(d)  # the same words read alike: bound
    agree["plan"]["cutoffs"][0]["text"] = "as of 18:00 AEST on 17 August 2026"
    res = resolved(q.replace("Using what was public at 17:00 AEST, ", ""), agree)
    assert res.status == "ok" and res.as_of is not None and res.as_of.isoformat() == "2026-08-17T08:00:00+00:00"


def test_an_event_review_keeps_d29s_tool_eligibility():
    """An event review keeps its handling: a resolved demand forecast keeps the demand-forecast tools (its run binds;
    no forecast request is resolved for an event review, as under v15); a forecast of another kind asked beside a
    demand maximum makes them ineligible, and is named as not answered."""
    q = ("During the SA1 price spike on 31 July 2026, what did the last operational demand forecast issued before the "
         "half-hour ending 18:30 ACST give?")
    d = decision("market_event_review", "SA1", "2026-07-31", [
        op("o1", "forecast_value", "operational_demand", "operational demand forecast",
           "what did the last operational demand forecast issued before", "s1", "r1")],
        scopes={"s1": ("half_hour", "the half-hour ending 18:30 ACST")},
        runs={"r1": ("last_issued_before", "the last operational demand forecast issued before")})
    res = resolved(q, d)
    assert res.status == "ok" and not res.requests.ineligible_tools and not res.requests.notes[:-1]
    assert res.requests.forecast_run.status == "bound" and res.requests.forecast.status == "absent"
    q2 = "During the SA1 price spike on 31 July 2026, how high did operational demand go, and what was the weather forecast?"
    d2 = decision("market_event_review", "SA1", "2026-07-31", [
        op("o1", "demand_maximum", "operational_demand", "operational demand", "how high did operational demand go",
           "s1"),
        op("o2", "forecast_value", "weather", "the weather forecast", "what was the weather forecast")],
        scopes={"s1": ("event", "During the SA1 price spike on 31 July 2026")})
    res = resolved(q2, d2)
    assert res.status == "ok" and set(res.requests.ineligible_tools) == set(DEMAND_FORECAST_TOOLS)
    assert [n for n in res.requests.notes if not n.startswith(ECHO_LABEL)] == [not_answered_note(["weather"])]
    assert res.requests.maximum.status == "bound" and res.requests.maximum.window_kind == "event"


def test_an_unparsable_event_date_is_sent_back():
    d = _n04()
    d["event_date"] = "17/08/2026"
    dec = request_plan.checked_plan_route(PlanRouteDecision.model_validate(d))
    assert dec.needs_clarification and dec.event_date is None and dec.contract == "v16"


# -- missing references and the cutoff backstop
def test_missing_references_are_clarified():
    no_scope = _n04()
    no_scope["plan"]["operations"][1]["scope_ref"] = None
    assert resolved(Q_N04, no_scope).reasons == [FORECAST_SCOPE_CLARIFICATION]
    q = "When was Queensland's operational demand highest on 29 July 2026?"
    mx = decision("market_event_review", "QLD1", "2026-07-29", [
        op("o1", "demand_maximum", "operational_demand", "operational demand",
           "When was Queensland's operational demand highest")])
    assert resolved(q, mx).reasons == [MAXIMUM_WINDOW_CLARIFICATION]
    unspecified = copy.deepcopy(mx)
    unspecified["plan"]["operations"][0]["subject"] = "demand_unspecified"
    assert resolved(q, unspecified).reasons == [MAXIMUM_CLARIFICATION]
    kindless = decision("forecast_review", "VIC1", "2026-08-17", [
        op("o1", "not_stated", "operational_demand", "AEMO's operational demand forecast values", "What did they show?",
           "s1")], scopes={"s1": ("half_hour", "a single half-hour on 17 August 2026: the one ending at 18:30 AEST")})
    assert resolved(Q_N04, kindless).reasons == [PLAN_OPERATION_CLARIFICATION]
    q2 = "How accurate were the operational demand forecasts for NSW1 on 31 July 2026?"
    nothing = decision("forecast_review", "NSW1", "2026-07-31", [])
    assert resolved(q2, nothing).reasons == [FORECAST_OPERATION_CLARIFICATION]  # a forecast review asks for something


def test_the_last_run_before_a_half_hour_needs_that_half_hour():
    q = "What did the last operational demand forecast issued before the start give for NSW1 on 31 July 2026?"
    d = decision("forecast_review", "NSW1", "2026-07-31", [
        op("o1", "forecast_value", "operational_demand", "operational demand forecast",
           "What did the last operational demand forecast issued before the start give", "s1", "r1")],
        scopes={"s1": ("whole_local_day", "for NSW1 on 31 July 2026")},
        runs={"r1": ("last_issued_before", "the last operational demand forecast issued before the start")})
    assert resolved(q, d).reasons == [HALF_HOUR_CLARIFICATION]
    q2 = "What did the last operational demand forecast issued before the 18:30 AEST half-hour on 17 August 2026 give?"
    d2 = decision("forecast_review", "VIC1", "2026-08-17", [
        op("o1", "forecast_value", "operational_demand", "operational demand forecast",
           "What did the last operational demand forecast issued before", "s1", "r1")],
        scopes={"s1": ("half_hour", "the 18:30 AEST half-hour on 17 August 2026")},
        runs={"r1": ("last_issued_before", "the last operational demand forecast issued before")})
    assert resolved(q2, d2).reasons == [START_OR_END_CLARIFICATION]  # is 18:30 its start or its end?


Q_CUTOFF = ("As of 14:00 AEST on 17 August 2026, what did the last operational demand forecast issued before the "
            "half-hour ending 18:30 AEST that day give for Victoria?")


def _cutoff_plan(cutoff_ref: str | None, stance: str = "asked", plan_ref: str | None = None,
                 with_cutoff: bool = True) -> dict[str, Any]:
    ops = [op("o1", "forecast_value", "operational_demand", "operational demand forecast",
              "what did the last operational demand forecast issued before", "s1", "r1", cutoff_ref)]
    if stance != "asked":
        ops.append(op("o2", "forecast_value", "not_stated", None, "As of 14:00 AEST on 17 August 2026", cutoff="c1",
                      stance=stance))
    return decision("forecast_review", "VIC1", "2026-08-17", ops,
                    scopes={"s1": ("half_hour", "the half-hour ending 18:30 AEST that day")},
                    runs={"r1": ("last_issued_before", "the last operational demand forecast issued before")},
                    cutoffs={"c1": "As of 14:00 AEST on 17 August 2026"} if with_cutoff else None, cutoff_ref=plan_ref)


def test_an_attached_cutoff_is_applied_and_never_dropped():
    res = resolved(Q_CUTOFF, _cutoff_plan("c1"))
    assert res.status == "ok" and res.as_of is not None and res.as_of.isoformat() == "2026-08-17T04:00:00+00:00"
    assert res.requests.forecast_run.selection == "last_issued_before"  # the cutoff filters; it does not select
    via_plan = resolved(Q_CUTOFF, _cutoff_plan(None, plan_ref="c1"))  # the plan's cutoff_ref: the whole question's
    assert via_plan.status == "ok" and via_plan.as_of == res.as_of


def test_an_unreferenced_cutoff_and_as_of_words_left_out_are_clarified_not_applied_globally():
    unreferenced = resolved(Q_CUTOFF, _cutoff_plan(None))
    assert unreferenced.reasons == [PLAN_CUTOFF_CLARIFICATION] and unreferenced.as_of is None
    left_out = resolved(Q_CUTOFF, _cutoff_plan(None, with_cutoff=False))  # the parser's omission backstop
    assert left_out.reasons == [PLAN_CUTOFF_CLARIFICATION] and left_out.as_of is None
    assert any("question parser" in n for n in left_out.requests.cutoff.notes)


@pytest.mark.parametrize("stance", ["declined", "background"])
def test_a_cutoff_of_declined_or_background_material_is_not_a_constraint(stance):
    res = resolved(Q_CUTOFF, _cutoff_plan(None, stance=stance))
    assert res.status == "ok" and res.as_of is None and res.requests.cutoff.status == "absent"


def test_an_event_review_asked_as_of_a_time_refers_to_its_cutoff_from_the_plan():
    q = "Using only what was known as of 14:00 ACST on 31 July 2026, what happened to SA1 prices?"
    d = decision("market_event_review", "SA1", "2026-07-31", [], cutoffs={"c1": "known as of 14:00 ACST on 31 July "
                                                                                 "2026"}, cutoff_ref="c1")
    res = resolved(q, d)
    assert res.status == "ok" and res.as_of is not None and res.as_of.isoformat() == "2026-07-31T04:30:00+00:00"
    assert not res.requests.notes  # nothing bound to state: no echo for an event review without an operation


# -- request overrides
Q_F07 = ("Based only on data published by noon Brisbane time on Sunday 5 October 2025, what was the highest operational "
         "demand in Queensland over that entire local day, and at what time?")


def _f07(cutoff: bool = True) -> dict[str, Any]:
    return decision("forecast_review", "QLD1", "2025-10-05", [
        op("o1", "demand_maximum", "operational_demand", "operational demand",
           "what was the highest operational demand in Queensland", "s1", None, "c1" if cutoff else None)],
        scopes={"s1": ("whole_local_day", "over that entire local day")},
        cutoffs={"c1": "Based only on data published by noon Brisbane time on Sunday 5 October 2025"})


def test_f07s_request_cutoff_overrides_an_unreadable_question_cutoff_with_the_discrepancy_recorded():
    """F07's established override: the request field applies; the question's own cutoff ('noon', which code cannot
    read) is recorded as not compared. Without the field (F07N) the cutoff is sent back: noon stays unsupported."""
    res = resolved(Q_F07, _f07(), as_of_utc="2025-10-05T02:00:00Z")
    assert res.status == "ok" and res.as_of is not None and res.as_of.isoformat() == "2025-10-05T02:00:00+00:00"
    (note,) = [n for n in res.requests.notes if not n.startswith(ECHO_LABEL)]
    assert note.startswith("The as-of cutoff given with the request, 2025-10-05T02:00:00Z, is applied.")
    assert "could not be compared with it" in note
    f07n = resolved(Q_F07, _f07())
    assert f07n.reasons == [CUTOFF_CLARIFICATION] and f07n.as_of is None
    assert resolved(Q_F07, _f07(cutoff=False)).reasons == [PLAN_CUTOFF_CLARIFICATION]  # unreferenced: not applied


def test_a_request_window_is_authoritative_and_the_question_window_is_noted():
    q = "When was Queensland's operational demand highest on 29 July 2026?"
    d = decision("market_event_review", "QLD1", "2026-07-29", [
        op("o1", "demand_maximum", "operational_demand", "operational demand",
           "When was Queensland's operational demand highest", "s1")], scopes={"s1": ("whole_local_day",
                                                                                     "on 29 July 2026")})
    res = resolved(q, d, window_start_utc="2026-07-29T06:00:00Z", window_end_utc="2026-07-29T09:00:00Z")
    mx = res.requests.maximum
    assert res.status == "ok" and mx.window_kind == "explicit" and mx.provenance["window"].source == "request"
    (note,) = [n for n in res.requests.notes if not n.startswith(ECHO_LABEL)]
    assert note.startswith("The maximum is taken over the window given with the request")


def test_a_request_cutoff_differing_from_the_question_is_applied_and_noted():
    res = resolved(Q_CUTOFF, _cutoff_plan("c1"), as_of_utc="2026-08-17T05:00:00Z")
    assert res.status == "ok" and res.as_of is not None and res.as_of.isoformat() == "2026-08-17T05:00:00+00:00"
    assert any("which differs" in n for n in res.requests.notes)


# -- known unsupported cases: sent back, not claimed fixed
KNOWN_UNSUPPORTED = {
    "noon": ("How did AEMO's operational demand forecast for Queensland compare with actual operational demand between "
             "06:00 and noon AEST on 4 August 2026?", ("explicit", "between 06:00 and noon AEST on 4 August 2026")),
    "midday": ("How did AEMO's operational demand forecast for Queensland compare with actual operational demand from "
               "06:00 until midday AEST on 4 August 2026?", ("explicit", "from 06:00 until midday AEST on 4 August 2026")),
    "part of the day": ("How did AEMO's operational demand forecast for Queensland compare with actual operational "
                        "demand in the evening of 4 August 2026?", ("whole_local_day", "in the evening of 4 August 2026")),
    "over the limit": ("How did AEMO's operational demand forecast for Queensland compare with actual operational "
                       "demand from 2026-08-03T00:00:00Z to 2026-08-04T06:00:00Z?",
                       ("explicit", "from 2026-08-03T00:00:00Z to 2026-08-04T06:00:00Z")),
}


@pytest.mark.parametrize("name", sorted(KNOWN_UNSUPPORTED))
def test_known_unsupported_time_expressions_are_sent_back(name):
    q, scope = KNOWN_UNSUPPORTED[name]
    d = decision("forecast_review", "QLD1", "2026-08-04", [
        op("o1", "forecast_comparison", "operational_demand", "AEMO's operational demand forecast for Queensland",
           "How did AEMO's operational demand forecast for Queensland compare with actual operational demand", "s1")],
        scopes={"s1": scope})
    res = resolved(q, d)
    assert res.status == "needs_clarification"
    assert res.reasons == [FORECAST_LIMIT_CLARIFICATION if name == "over the limit" else FORECAST_SCOPE_CLARIFICATION]


# ------------------------------------------------------------------------------------------------ v15 diagnostic
V15 = {c["config"]: c for c in json.loads((ROOT / "eval" / "livecheck_route_v15" / "cases.json").read_text())["cases"]}
GOLD = {c["config"]: c for c in json.loads((ROOT / "eval" / "livecheck_route_v15" / "GOLD_AMENDED.json").read_text())[
    "cases"]}
F = "forecast_value"
C = "forecast_comparison"
# scripted correct readings of the 17 v15 diagnostic questions (the frozen gold is read, never changed)
CORRECT: dict[str, dict[str, Any]] = {
    "D01": decision("forecast_review", "TAS1", "2026-07-31", [
        op("o1", F, "operational_demand", "POE10, POE50 and POE90 operational demand values",
           "which POE10, POE50 and POE90 operational demand values did it give", "s1", "r1"),
        op("o2", C, "operational_demand", "POE10, POE50 and POE90 operational demand values",
           "how much operational demand was actually recorded in that half-hour", "s1", "r1")],
        scopes={"s1": ("half_hour", "Tasmania's half-hour ending at 8:00 am AEST, 31 July 2026")},
        runs={"r1": ("issued_at", "the forecast run issued at 2026-07-30T18:56:59Z")}),
    "D02": _r02(),
    "D03": decision("forecast_review", "NSW1", "2026-07-31", [
        op("o1", C, "operational_demand", "the operational demand forecasts",
           "How accurate were the operational demand forecasts", "s1")],
        scopes={"s1": ("whole_local_day", "for NSW1 on 31 July 2026")}),
    "D04": decision("forecast_review", "SA1", "2026-07-31", [
        op("o1", C, "operational_demand", "the operational demand forecasts",
           "How did the operational demand forecasts compare with actual demand", "s1")],
        scopes={"s1": ("explicit", "between 18:00 and 21:00 ACST on 31 July 2026")}),
    "D05": decision("forecast_review", "VIC1", None, [
        op("o1", F, "operational_demand", "Victorian operational demand forecast",
           "what was the newest Victorian operational demand forecast", "s1", "r1", "c1")],
        scopes={"s1": ("half_hour", "the 23:00 to 23:30 UTC half-hour")},
        runs={"r1": ("as_of_availability", "looking only at runs already public")},
        cutoffs={"c1": "As of 2026-08-19T20:00:00Z"}),
    "D06": decision("forecast_review", "VIC1", "2026-08-20", [
        op("o1", F, "operational_demand", "Victorian operational demand",
           "what did the latest available AEMO forecast expect", "s1", "r1", "c1"),
        op("o2", F, "weather", "cold weather", "was cold weather expected to push demand up that morning", "s1", None,
           "c1")],
        scopes={"s1": ("half_hour", "the half-hour ending 2026-08-19T23:30:00Z")},
        runs={"r1": ("as_of_availability", "the latest available AEMO forecast")},
        cutoffs={"c1": "As of 2026-08-19T21:00:00Z"}),
    "D07": _d07(),
    "D08": _d08("not_stated", None),
    "D09": decision("forecast_review", "SA1", "2026-07-31", [
        op("o1", F, "weather", "the weather forecast", "What was the weather forecast", "s1")],
        scopes={"s1": ("whole_local_day", "for Adelaide on 31 July 2026")}),
    "D10": _f07(),
    "N01": decision("forecast_review", "QLD1", "2026-08-13", [
        op("o1", F, "weather", "maximum temperature", "What maximum temperature was forecast", "s1")],
        scopes={"s1": ("whole_local_day", "for the city on 13 August 2026")}),
    "N02": decision("forecast_review", "SA1", "2026-07-29", [
        op("o1", F, "price", "predispatch price forecasts", "Could you pull AEMO's predispatch price forecasts")]),
    "N03": _n03("not_stated", None),
    "N04": _n04(),
    "N05": decision("forecast_review", "TAS1", "2026-08-02", [
        op("o1", F, "operational_demand", "AEMO's operational demand forecast",
           "I don't need AEMO's operational demand forecast for this", stance="declined"),
        op("o2", F, "weather", "wind and rain", "What did the weather forecasters expect", "s1")],
        scopes={"s1": ("whole_local_day", "for Hobart on 2 August 2026")}),
    "N06": decision("forecast_review", "SA1", "2026-08-14", [
        op("o1", C, "operational_demand", "AEMO's demand forecast for South Australia",
           "came in well below the actuals", stance="background"),
        op("o2", F, "weather", "minimum temperature", "What minimum temperature had been forecast", "s1")],
        scopes={"s1": ("whole_local_day", "for Adelaide on 14 August 2026")}),
    "N07": decision("forecast_review", "QLD1", "2026-08-04", [
        op("o1", F, "weather", "a cold, drizzly morning", "the Bureau was calling for a cold, drizzly morning",
           stance="background"),
        op("o2", C, "operational_demand", "AEMO's operational demand forecast for Queensland",
           "How did AEMO's operational demand forecast for Queensland compare with actual operational demand", "s1")],
        scopes={"s1": ("explicit", "between 06:00 and noon AEST on 4 August 2026")}),
}
CLARIFY = {"clarify_which_forecast": FORECAST_DOMAIN_CLARIFICATION,
           "clarify_unsupported": FORECAST_UNSUPPORTED_CLARIFICATION}
# what each correct reading met in the v15 diagnostic (REPORT.md, sections 2 and 7), and what the compiler gives it
V15_CODE_LOST = {"D01": "clause containment", "D02": "clause containment", "D03": "clause containment",
                 "D07": "clause containment (shared scope)", "N07": "clause containment, and noon",
                 "N04": "the declined weather forecast named as unanswered"}


@pytest.mark.parametrize("cid", sorted(CORRECT))
def test_v15_diagnostic_questions_with_correct_plans_against_the_gold(cid):
    """Each v15 diagnostic question with a scripted correct plan, against the frozen amended gold: 16 of 17 give the
    gold outcome. N07 is sent back, since 'noon' cannot be read: a known unsupported case, not claimed fixed. These
    are scripted readings: no claim about how a hosted model reads these questions."""
    case, gold = V15[cid], GOLD[cid]
    res = resolved(case["question"], CORRECT[cid], **case["request"])
    if cid == "N07":
        assert res.reasons == [FORECAST_SCOPE_CLARIFICATION] and gold["outcome"] == "resolved"
        return
    if gold["outcome"] in CLARIFY:
        assert res.reasons == [CLARIFY[gold["outcome"]]]
        return
    assert gold["outcome"] == "resolved" and res.status == "ok", res.reasons
    r = res.requests
    assert (res.as_of.isoformat().replace("+00:00", "Z") if res.as_of else None) == gold["cutoff_utc"]
    if gold["maximum"]:
        mx = gold["maximum"]
        assert r.maximum.status == "bound" and r.maximum.measures == [{"operational_demand": "operational demand"}[
            mx["measure"]]]
        assert [t.isoformat().replace("+00:00", "Z") for t in r.maximum.window] == [mx["start_utc"], mx["end_utc"]]
        return
    fa = r.forecast
    assert (fa.status, fa.operation, fa.domain) == ("bound", gold["operation"], gold["domain"])
    assert fa.scope in gold["scope"]["kinds"]
    assert [t.isoformat().replace("+00:00", "Z") for t in fa.bounds] == [gold["scope"]["start_utc"],
                                                                          gold["scope"]["end_utc"]]
    rule = gold["run"]["rule"]
    run = r.forecast_run
    assert (run.status if run.status == "as_of_availability" else run.selection or "none") == rule
    if rule == "issued_at":
        assert run.issued_at is not None and run.issued_at.isoformat().replace("+00:00", "Z") == gold["run"][
            "issued_at_utc"]
    kinds = {p["kind"] for p in gold.get("unsupported_parts") or []}
    assert set(fa.unsupported) == kinds
    if cid in V15_CODE_LOST:  # a correct reading the v15 resolver lost now binds, as the gold says
        assert not res.reasons


# ------------------------------------------------------------------------------------------------ equivalence
SAVED_PLANS = {
    "R02": _r02(),
    "D01": decision("market_event_review", "NSW1", "2026-07-29", [
        op("o1", "demand_maximum", "dispatch_total_demand", "NSW dispatch total demand",
           "at which five-minute interval was NSW dispatch total demand highest", "s1")],
        scopes={"s1": ("whole_local_day", "across the whole day")}),
    "D02": decision("market_event_review", "QLD1", "2026-07-29", [
        op("o1", "demand_maximum", "operational_demand", "operational demand",
           "had Queensland's highest operational demand", "s1")],
        scopes={"s1": ("whole_local_day", "on 29 July 2026 (Brisbane time)")}),
    "F02": decision("market_event_review", "SA1", "2026-07-29", [
        op("o1", "demand_maximum", "dispatch_total_demand", "dispatch total demand",
           "the day's top dispatch total demand", "s1")],
        scopes={"s1": ("whole_local_day",
                       "over the full local day of 29 July 2026 (midnight to midnight, Adelaide time)")}),
    "F06": decision("market_event_review", "VIC1", "2026-08-20", [
        op("o1", "demand_maximum", "dispatch_total_demand", "dispatch total demand (TOTALDEMAND)",
           "how high did VIC1 dispatch total demand (TOTALDEMAND) go", "s1")],
        scopes={"s1": ("event", "the Victorian high-price event of 20 August 2026")}),
    "F07": _f07(),
    "F07N": _f07(),
    "F08": decision("market_event_review", "TAS1", "2026-07-31", [
        op("o1", "demand_maximum", "demand_unspecified", "demand", "how far did demand climb", "s1")],
        scopes={"s1": ("event", "Tasmania's 31 July 2026 high-price episode")}),
}


def _record(cid: str) -> dict[str, Any]:
    return json.loads((E2E / f"{cid}.json").read_text())


@pytest.mark.parametrize("cid", sorted(SAVED_PLANS))
def test_the_same_reading_as_a_plan_resolves_to_the_same_bound_request(cid):
    """Resolution level, every saved end-to-end record: the reading of the saved (v13) decision, given as a plan,
    binds the same request. One recorded difference, not read by any controller: F07's v13 decision also read its
    cutoff words as a run ('as of availability'); a plan's maximum has no run."""
    rec = _record(cid)
    req = InvestigateRequest(question=rec["question"], mode="live", **rec["request"])
    v15 = bound(resolve_routed(req, checked_route(RouteDecision.model_validate(rec["route"])), SEL))
    v16 = bound(resolve_routed(req, PlanRouteDecision.model_validate(SAVED_PLANS[cid]), SEL))
    assert v16 == v15


def _saved_fake(cid: str, plan: dict[str, Any] | None) -> FakeModel:
    """The saved record's model tool calls and drafts (SYNTHETIC replay), its route given as the saved v13 decision
    (plan None) or as a plan."""
    rec = _record(cid)
    trace = json.loads((E2E / "traces" / f"{rec['trace_id']}.json").read_text())["events"]
    draft = rec["drafts"]["synthesis:draft"]
    patch = next((e.get("patch") for e in trace if e["name"] == "repair:scoped"), None)
    repaired = rec["drafts"].get("repair:draft")

    def repair(kw: dict) -> dict:
        return copy.deepcopy(patch if kw["text"]["format"]["name"] == "RepairPatch" else repaired)
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if t["origin"] == "model" and t["status"] != "blocked"]
    def report(kw: dict) -> dict:
        return copy.deepcopy(draft)
    rep = repair if (patch or repaired) else None
    return FakeModel(rec["route"], [calls], report, rep) if plan is None else PlanFake(plan, [calls], report, rep)


def _comparable(res: Any) -> dict[str, Any]:
    """The report without what differs by design: the trace id, the prompt version (v17 with the plan), the echo note
    (controller metadata, labelled), and what the SYNTHETIC transport makes up for each run (its response and call ids,
    numbered from a counter shared by the whole session, and the elapsed time)."""
    rep = json.loads(res.report.model_dump_json())
    rep.pop("trace_id")
    rep["versions"].pop("prompt")
    rep["source_manifest"]["usage"].pop("elapsed_s", None)
    rep["uncertainties"] = [u for u in rep["uncertainties"] if not u.startswith(ECHO_LABEL)]
    seen: dict[str, str] = {}

    def ids(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: ids(v) for k, v in node.items()}
        if isinstance(node, list):
            return [ids(v) for v in node]
        if isinstance(node, str) and re.fullmatch(r"(?:call|resp|fc)_\d+", node):
            return seen.setdefault(node, f"{node.split('_')[0]}#{len(seen)}")
        return node
    return dict(ids(rep))


@pytest.mark.parametrize("cid", ["R02", "D01", "D02", "F02", "F06", "F07"])
def test_equivalent_bound_resolutions_compute_verify_validate_and_render_the_same(cid, real_store, monkeypatch):
    """Through the real store, run, verifier, validators and renderer: the same answer (computed results, verification,
    the interpretation status, any fallback) as the saved decision gives. R02's fallback stays a fallback, its
    misleading aggregate sentence stays rejected; the maxima render byte for byte."""
    rec = _record(cid)
    old = investigate(InvestigateRequest(question=rec["question"], mode="live", **rec["request"]),
                      live_client=_saved_fake(cid, None), write_trace=False)
    monkeypatch.setenv("NEM_AGENT_ROUTE_PLAN", "1")
    new = investigate(InvestigateRequest(question=rec["question"], mode="live", **rec["request"]),
                      live_client=_saved_fake(cid, SAVED_PLANS[cid]), write_trace=False)
    assert _comparable(new) == _comparable(old)
    assert [r.name for r in new.records] == [r.name for r in old.records]
    assert new.resolution.forecast_primary == old.resolution.forecast_primary
    assert (new.report.versions.prompt, old.report.versions.prompt) == ("prompts/v17", "prompts/v16")
    # the intentional new metadata: the contract label, the plan record and the echo note
    assert new.resolution.requests.contract == "v16" and new.resolution.requests.plan["primary"]
    assert "plan" in new.resolution.routing["requests"] and "plan" not in old.resolution.routing["requests"]
    echoes = [u for u in new.report.uncertainties if u.startswith(ECHO_LABEL)]
    assert echoes == [new.resolution.requests.plan["echo"]]


# ------------------------------------------------------------------------------------------------ the echo
def test_the_echo_is_labelled_controller_metadata_and_survives_serialisation_and_display(real_store, monkeypatch):
    """R02: the echo is in the notes channel (the report's uncertainties), labelled as controller-generated metadata;
    it round-trips through the report's JSON, is not rewritten by the plain-display rules, and needs no escaping in
    the page. The model's interpretation is still withheld (a fallback) and its status is unchanged."""
    monkeypatch.setenv("NEM_AGENT_ROUTE_PLAN", "1")
    rec = _record("R02")
    res = investigate(InvestigateRequest(question=rec["question"], mode="live"), live_client=_saved_fake(
        "R02", SAVED_PLANS["R02"]), write_trace=False)
    (said,) = [u for u in res.report.uncertainties if u.startswith(ECHO_LABEL)]
    assert said == (ECHO_LABEL + "AEMO's operational demand forecast compared with actual operational demand in SA1, "
                    "for the half-hour (2026-08-19T22:00:00Z, 2026-08-19T22:30:00Z]; run: the last issued before that "
                    "half-hour began.")
    for words in ("metadata generated by code", "not the model's interpretation", "not a validation result",
                  "not a confirmation by the user"):
        assert words in said
    again = InvestigationReport.model_validate_json(res.report.model_dump_json())
    assert said in again.uncertainties and json.loads(res.report.model_dump_json())["uncertainties"][0] == said
    assert plain_note(said) == said and "$" not in said  # shown as written (the page escapes '$' only)
    v = res.report.validation
    assert v["fallback_applied"] and v["interpretation"].startswith("withheld")
    assert said not in json.dumps(res.report.summary) and said not in res.report.headline


def test_no_echo_for_a_question_that_does_not_run():
    """F07N (sent back for its cutoff) and a refused question state no reading: the echo is withdrawn."""
    f07n = resolved(Q_F07, _f07())
    assert f07n.status == "needs_clarification" and f07n.requests.plan["echo"] is None
    assert not any(n.startswith(ECHO_LABEL) for n in f07n.requests.notes)
    refused = resolved(Q_N04, _n04(out_of_scope=True))
    assert refused.status == "refused" and refused.requests.plan["echo"] is None
    assert not any(n.startswith(ECHO_LABEL) for n in json.dumps(refused.routing).split("\""))
    ok = resolved(Q_N04, _n04())
    assert ok.status == "ok" and ok.requests.notes == [ok.requests.plan["echo"]]
