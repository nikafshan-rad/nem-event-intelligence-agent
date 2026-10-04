"""Route contract v16 (D31, Amendment 1): one routing call returns a typed request plan, and a deterministic compiler
turns it into the existing ``structured.RequestResolution``. Opt-in and off by default (``NEM_AGENT_ROUTE_PLAN``): the
default Live path keeps route contract v15 and prompts v16, and a decision recorded under v12-v15 keeps its resolver
(``structured``) whatever the switch says; the contract a decision was given in decides its path.

**The model says what is meant:** each operation's stance (asked, declined or background), kind and subject, with the
question's own words for each, and the scope, run and cutoff it refers to, by id. **Code decides the rest:** admission
(failing closed), locating the quoted words (provenance only), the plan's consistency, one primary operation, the
stated-basis policy, every time conversion (the existing readers, unchanged), the supported limits and the tools a
resolved request may use. Calculation, verification, validation and rendering are the existing ones.

**Not semantic verification.** A subject accepted under V0 or V1 is the model's reading, with words that are in the
question (under V1, words holding the frozen demand vocabulary): a plausible misreading whose words name demand passes
both. An asked run or maximum that the plan leaves out is not detected unless its words hold a time no plan entity
accounts for. The question parser's as-of detection is an omission backstop only, never a reading in the plan's place.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .. import config
from ..timeutil import half_hour_end_for, iso_utc, local_day_window, parse_iso
from .request import AS_OF_Q_RE, InvestigateRequest, extract_as_of, extract_dates, half_hour_after_cutoff
from .structured import (
    _DEMAND_WORD_RE,
    _EVENT_WORD_RE,
    _MEASURE_OF,
    _MEASURE_WORDS,
    _POE_RE,
    _QUOTED_RE,
    _RELATIVE_NARROW_RE,
    DEMAND_FORECAST_TOOLS,
    PERIOD_SCOPES,
    SINGLE_SCOPES,
    CutoffRequest,
    ForecastAnalysis,
    MaxRequest,
    RequestResolution,
    Routed,
    RunRequest,
    Source,
    Span,
    _cutoff_words_end,
    _day_of,
    _day_span_ok,
    _first_instant,
    _instants_in,
    _masked,
    _narrows,
    _on_grid,
    _restatements,
    _span,
    _time_expressions,
    half_hour_from_text,
    issue_time_from_text,
    not_answered_note,
    question_as_of,
    request_field_notes,
    span,
    window_from_text,
)

CONTRACT: Literal["v16"] = "v16"
Policy = Literal["V0", "V1"]


def enabled() -> bool:
    """Whether Live routing uses the request plan: ``NEM_AGENT_ROUTE_PLAN`` (1, true, yes or on), else the default
    (off). It decides only which contract a new routing call is given."""
    v = os.environ.get("NEM_AGENT_ROUTE_PLAN")
    return config.ROUTE_PLAN_DEFAULT if v is None else v.strip().lower() in ("1", "true", "yes", "on")


def policy() -> Policy:
    """The stated-basis policy: ``NEM_AGENT_PLAN_POLICY`` (V0 or V1), else the default (V1). Any other value reads as
    V1, the conservative policy."""
    v = os.environ.get("NEM_AGENT_PLAN_POLICY", config.PLAN_POLICY_DEFAULT).strip().upper()
    return "V0" if v == "V0" else "V1"


def prompt_version() -> str:
    """The prompts Live reads: v17 with the request plan, else the default (v16)."""
    return config.PLAN_PROMPT_VERSION if enabled() else config.PROMPT_VERSION


# ------------------------------------------------------------------------------------------------ the routed schema
# Model-facing schemas carry no docstring: it would enter the schema.
class _P(BaseModel):
    model_config = ConfigDict(extra="forbid")


_WORDS = ("copied verbatim from the question: one continuous piece, with enough words that it occurs only once; the "
          "words for different things are copied separately")


class PlanScope(_P):
    id: str = Field(description="this scope's id, unique in the plan (for example 's1')")
    kind: Literal["half_hour", "event_peak_half_hour", "whole_local_day", "event", "explicit"] = Field(
        description="half_hour = one stated half-hour; event_peak_half_hour = a price event's peak half-hour; "
                    "whole_local_day = one whole local calendar day; event = a price event's window; explicit = a "
                    "stated start and end")
    text: str = Field(description="the question's words naming the half-hour or period, with its clock times, date and "
                                  "time zone where they are written there; " + _WORDS)


class PlanRun(_P):
    id: str = Field(description="this run's id, unique in the plan (for example 'r1')")
    selection: Literal["last_issued_before", "issued_at", "as_of_availability", "unclear"] = Field(
        description="the one forecast run asked for: last_issued_before = the last run issued before the target "
                    "half-hour starts; issued_at = the run issued at a stated time; as_of_availability = the newest run "
                    "public by the cutoff; unclear = one specific run is asked for, but which cannot be told")
    text: str = Field(description="the question's words asking for this run (for issued_at, with the issue time as "
                                  "written); " + _WORDS)


class PlanCutoff(_P):
    id: str = Field(description="this cutoff's id, unique in the plan (for example 'c1')")
    text: str = Field(description="the question's words stating an as-of cutoff (what was public, published, available "
                                  "or known by a time), with the time, date and time zone written there; " + _WORDS)


class PlanOperation(_P):
    id: str = Field(description="this operation's id, unique in the plan (for example 'o1')")
    stance: Literal["asked", "declined", "background"] = Field(
        description="asked = the question asks for it; declined = the question says it does not want it; background = "
                    "mentioned as context, including a quoted statement, and not asked for")
    kind: Literal["forecast_value", "forecast_comparison", "demand_maximum", "not_stated"] = Field(
        description="forecast_value = what a forecast said (its values, or which run), not compared with actual values; "
                    "forecast_comparison = a forecast compared with the actual values, for one half-hour or a period "
                    "(also when both values are asked for); demand_maximum = when, or at what level, a demand measure "
                    "was highest over a window; not_stated = which of these cannot be told")
    subject: Literal["operational_demand", "dispatch_total_demand", "demand_unspecified", "weather", "price", "other",
                     "not_stated"] = Field(
        description="what is forecast or measured: operational_demand = operational demand (for a forecast: AEMO's "
                    "demand forecasts); dispatch_total_demand = dispatch total demand (TOTALDEMAND); demand_unspecified "
                    "= demand, without saying which measure; weather (including temperature), price or other = another "
                    "kind; not_stated = the question does not say what is forecast or measured")
    subject_text: str | None = Field(description="the question's words stating the subject; null when it is not "
                                                 "stated; " + _WORDS)
    operation_text: str | None = Field(description="the question's words asking for, declining or mentioning this "
                                                   "operation; " + _WORDS)
    scope_ref: str | None = Field(description="the id of this operation's half-hour or period in scopes; null when the "
                                              "question gives none for it")
    run_ref: str | None = Field(description="the id of the one forecast run this operation asks for in runs; null when "
                                            "no specific run is asked for")
    cutoff_ref: str | None = Field(description="the id of the as-of cutoff that limits this operation in cutoffs; null "
                                               "when none does")


class RequestPlan(_P):
    operations: list[PlanOperation] = Field(
        description="every forecast or demand-peak operation the question asks for, declines or mentions as "
                    "background; empty when there is none")
    scopes: list[PlanScope] = Field(description="every half-hour or period an operation refers to; operations that "
                                                "share one refer to the same id")
    runs: list[PlanRun] = Field(description="every specific forecast run an operation asks for")
    cutoffs: list[PlanCutoff] = Field(description="every as-of cutoff the question states")
    cutoff_ref: str | None = Field(description="the id of an as-of cutoff that limits the whole question when no "
                                               "operation holds it (for example a market event review asked as of a "
                                               "time); else null")


class PlanRouteDecision(_P):
    intent: Literal["market_event_review", "forecast_review", "source_explanation"] | None
    region: Literal["NSW1", "QLD1", "SA1", "TAS1", "VIC1"] | None
    event_date: str | None = Field(description="YYYY-MM-DD in the region's local time")
    needs_clarification: bool
    clarification_reason: Literal["several_regions", "several_dates", "missing_region_or_date",
                                  "unclear_question"] | None = Field(
        description="why clarification is needed; null when needs_clarification is false")
    clarification: str | None
    out_of_scope: bool
    plan: RequestPlan

    @property
    def contract(self) -> str:
        return CONTRACT

    def routed(self) -> Routed:
        """What the resolver reads from this decision: the plan, compiled by ``compile_plan``."""
        return Routed(None, None, CONTRACT, plan=self.plan)


def checked_plan_route(dec: PlanRouteDecision) -> PlanRouteDecision:
    """A routing decision with an unparsable event date sent back (as ``live.checked_route``)."""
    if dec.event_date:
        try:
            date.fromisoformat(dec.event_date)
        except ValueError:
            return dec.model_copy(update={"event_date": None, "needs_clarification": True,
                                          "clarification_reason": "missing_region_or_date",
                                          "clarification": "The event date could not be parsed."})
    return dec


# ------------------------------------------------------------------------------------------------ clarifications
# the field only: no time, number or quotation for the answer checks to read
PLAN_INVALID_CLARIFICATION = "The routing model returned an invalid request plan."
PLAN_OPERATIONS_CLARIFICATION = (
    "The question asks for more than one analysis (for example a forecast and a demand peak, or two different "
    "forecasts or periods). This assistant answers one at a time and does not choose between them, so nothing is run. "
    "Ask about one of them.")
PLAN_OPERATION_CLARIFICATION = (
    "What should be worked out: what a forecast said, how a forecast compared with actual demand, or when and how high "
    "a demand measure peaked? It cannot be told from the question, so nothing is run in its place.")
# the interpretation echo: controller metadata in the notes channel, never the model's interpretation
ECHO_LABEL = ("Controller reading of the request (metadata generated by code from the routing plan; not the model's "
              "interpretation, not a validation result and not a confirmation by the user): ")


# ------------------------------------------------------------------------------------------------ admission
def admit(plan: RequestPlan) -> list[str]:
    """Structural problems that make a plan invalid (failing closed): a repeated id, or a reference to an entity the
    plan does not hold or holds as another type."""
    problems: list[str] = []
    ids = [o.id for o in plan.operations] + [s.id for s in plan.scopes] + [r.id for r in plan.runs] + \
        [c.id for c in plan.cutoffs]
    repeated = sorted({i for i in ids if ids.count(i) > 1})
    if repeated:
        problems.append(f"repeated ids: {', '.join(repeated)}")
    pools = {"scope_ref": {s.id for s in plan.scopes}, "run_ref": {r.id for r in plan.runs},
             "cutoff_ref": {c.id for c in plan.cutoffs}}
    for o in plan.operations:
        for ref, pool in pools.items():
            v = getattr(o, ref)
            if v is not None and v not in pool:
                problems.append(f"{o.id}.{ref}: '{v}' is not a {ref.removesuffix('_ref')} of the plan")
    if plan.cutoff_ref is not None and plan.cutoff_ref not in pools["cutoff_ref"]:
        problems.append(f"cutoff_ref: '{plan.cutoff_ref}' is not a cutoff of the plan")
    return problems


# ------------------------------------------------------------------------------------------------ reading the plan
def _inside(occ: tuple[int, int], regions: Sequence[tuple[int, int]]) -> bool:
    return any(a <= occ[0] and occ[1] <= b for a, b in regions)


def _only_inside(sp: Span, regions: Sequence[tuple[int, int]]) -> bool:
    """Every occurrence of the words lies in the regions (quoted background, declined or background material)."""
    return bool(sp.occurrences) and all(_inside(o, regions) for o in sp.occurrences)


def _touches(sp: Span, regions: Sequence[tuple[int, int]]) -> bool:
    return any(a < y and x < b for a, b in sp.occurrences for x, y in regions)


def _regions(spans: Sequence[Span]) -> list[tuple[int, int]]:
    return [o for sp in spans for o in sp.occurrences]


@dataclass
class _Scope:
    """An operation's half-hour or period as code read it from the scope's words."""
    kind: str | None = None
    bounds: tuple[datetime, datetime] | None = None
    source: Source | None = None
    span: Span | None = None
    missing: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    stated: tuple[str, tuple[datetime, datetime]] | None = None  # the plan's reading, under a request window


@dataclass
class _Op:
    """An asked operation as classified: supported (a demand forecast, or a measure's maximum), unsupported (a forecast
    of another kind: named as not answered) or unresolved (sent back, with what is missing)."""
    op: Any
    family: Literal["forecast", "maximum", "unknown"]
    status: Literal["supported", "unsupported", "unresolved"] = "unresolved"
    subject: str | None = None
    subject_source: Source | None = None
    other_kind: str | None = None
    missing: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    spans: list[Span] = field(default_factory=list)
    scope: _Scope = field(default_factory=_Scope)
    run: RunRequest = field(default_factory=RunRequest)


def _basis(text: str | None, q: str, quoted: list[tuple[int, int]]) -> tuple[Span | None, str | None]:
    """The subject's stated words (V0): given, in the question, and not only inside quotation marks."""
    if not text:
        return None, "the subject's words are not given"
    sp = span("subject", text, q)
    if sp is None:
        return None, "the subject's words are not in the question"
    if _only_inside(sp, quoted):
        return sp, "the subject's words are only in quotation marks"
    return sp, None


def _classify(o: Any, q: str, quoted: list[tuple[int, int]], pol: Policy) -> _Op:
    family: Literal["forecast", "maximum", "unknown"] = (
        "forecast" if o.kind in ("forecast_value", "forecast_comparison") else
        "maximum" if o.kind == "demand_maximum" else "unknown")
    rd = _Op(o, family)

    def unresolved(missing: str, note: str) -> _Op:
        rd.status, rd.missing = "unresolved", [missing]
        rd.notes.append(f"{o.id}: {note}")
        return rd
    if family == "unknown":
        return unresolved("operation", "which operation is asked for is not stated")
    op_sp = span("operation", o.operation_text, q) if o.operation_text else None
    if op_sp is None:
        return unresolved("operation", "the operation's words are not in the question")
    if _only_inside(op_sp, quoted):  # the quotation-mark check (decision 4): quoted words are background
        return unresolved("operation", "the operation's words are only in quotation marks")
    rd.spans.append(op_sp)
    if family == "forecast":
        if o.subject in ("weather", "price", "other", "dispatch_total_demand"):
            rd.status, rd.other_kind = "unsupported", o.subject if o.subject in ("weather", "price") else "other"
            return rd
        if o.subject == "not_stated":
            return unresolved("domain", "what is forecast is not stated")
        sp, why = _basis(o.subject_text, q, quoted)
        if why:
            return unresolved("domain", why)
        assert sp is not None
        if pol == "V1" and not (_DEMAND_WORD_RE.search(sp.text) or _POE_RE.search(sp.text)):
            return unresolved("domain", f"V1: the subject's words '{sp.text}' hold no demand word and no POE level")
        rd.status, rd.subject, rd.spans = "supported", "operational_demand", [*rd.spans, sp]
        rd.subject_source = Source("route_model", sp.text, f"the model's stated subject ({pol})")
        return rd
    if o.subject not in _MEASURE_OF:
        return unresolved("measure", "which demand measure is not stated")
    sp, why = _basis(o.subject_text, q, quoted)
    if why:
        return unresolved("measure", why)
    assert sp is not None
    want = _MEASURE_OF[o.subject]
    named = [m for m, rx in _MEASURE_WORDS.items() if rx.search(sp.text)]
    if pol == "V1" and named != [want]:
        return unresolved("measure", f"V1: the words '{sp.text}' name {' and '.join(named) or 'no measure'}, the "
                                     f"reading {want}")
    rd.status, rd.subject, rd.spans = "supported", want, [*rd.spans, sp]
    rd.subject_source = Source("route_model", sp.text, f"the model's stated subject ({pol})")
    return rd


def _read_scope(q: str, region: str | None, day: date | None, event: Any, s: Any, family: str,
                as_of: datetime | None, quoted: list[tuple[int, int]]) -> _Scope:
    """The operation's half-hour or period, from its scope's words, by the existing readers (D26, D28)."""
    miss = "scope" if family == "forecast" else "window"
    if s is None:
        return _Scope(missing=[miss], notes=["scope: the operation refers to no scope"])
    sp = span("scope", s.text, q)
    if sp is None:
        return _Scope(missing=[miss], notes=[f"scope: the words of {s.id} are not in the question"])
    if _only_inside(sp, quoted):
        return _Scope(span=sp, missing=[miss], notes=[f"scope: the words of {s.id} are only in quotation marks"])
    text = sp.text
    if family == "maximum" and s.kind not in ("whole_local_day", "event", "explicit"):
        return _Scope(span=sp, missing=["window"], notes=["scope: a maximum is taken over a whole local day, an "
                                                          "event's window or a stated start and end"])
    if s.kind == "half_hour":
        hh, missing, conv = half_hour_from_text(text, q, region)
        if hh is None and missing == ["date"] and as_of is not None and not extract_dates(q):
            words: list[tuple[int, int]] = []
            dated = half_hour_after_cutoff(q, as_of, words)  # a clock-only half-hour dated by the cutoff (I-10)
            if dated is not None and _touches(sp, words):
                hh, missing = dated, []
                conv = f"'{text}': a clock-only half-hour dated by the as-of cutoff {iso_utc(as_of)} (I-10)"
        if hh is None:
            return _Scope(span=sp, missing=missing or ["half_hour"],
                          notes=[f"scope: '{text}' does not give a half-hour that code can read"])
        return _Scope("half_hour", hh, Source("route_model", text, conv), sp)
    if s.kind == "event_peak_half_hour":
        if event is None:
            return _Scope(span=sp, missing=["event"], notes=["scope: a peak half-hour is named, but no price event is "
                                                             "held for it"])
        end = half_hour_end_for(parse_iso(event.peak_interval_end_utc))
        return _Scope(s.kind, (end - timedelta(minutes=30), end),
                      Source("route_model", text, f"the peak half-hour of {event.event_id}"), sp)
    if s.kind == "whole_local_day":
        d = _day_of(text, q)
        if d is None or region is None:
            return _Scope(span=sp, missing=["date"], notes=[f"scope: the day of '{text}' is not pinned down"])
        if not _day_span_ok(text) or (day is not None and d != day):
            return _Scope(span=sp, missing=[miss], notes=[f"scope: '{text}' is not one whole local day by itself"])
        return _Scope(s.kind, local_day_window(d, region), Source("route_model", text, f"whole local day {d} in {region}"),
                      sp)
    if s.kind == "event":
        if event is None:
            return _Scope(span=sp, missing=["event"], notes=["scope: an event is named, but no price event is held"])
        if not _EVENT_WORD_RE.search(text) or _RELATIVE_NARROW_RE.search(text):
            return _Scope(span=sp, missing=[miss], notes=[f"scope: '{text}' names no event window by itself"])
        return _Scope("event", (parse_iso(event.window_start_utc), parse_iso(event.window_end_utc)),
                      Source("route_model", text, f"the window of {event.event_id}"), sp)
    w, conv = window_from_text(text, q, region)
    if w is None:
        return _Scope(span=sp, missing=[miss], notes=[f"scope: '{text}' gives no start and end that code can read"])
    return _Scope("explicit", w, Source("route_model", text, conv), sp)


def _read_run(q: str, region: str | None, r: Any, scope: _Scope, quoted: list[tuple[int, int]]) -> RunRequest:
    """The forecast run an operation asks for (D26's rules, by its own words): a run named by its issue time; the last
    run issued before the operation's half-hour; or the newest run public by the cutoff. The cutoff filters
    availability and never replaces the selection."""
    out = RunRequest(detected_by=["route_model"])
    if r is None:
        return RunRequest()
    sp = span("run_selection", r.text, q)
    if sp is None or _only_inside(sp, quoted) or r.selection == "unclear":
        out.status, out.missing = "unresolved", ["run_rule"]
        return out
    out.spans = [sp]
    src = Source("route_model", sp.text)
    if r.selection == "as_of_availability":
        out.status, out.provenance["selection"] = "as_of_availability", src
        return out
    out.selection, out.provenance["selection"] = r.selection, src
    single = scope.kind in SINGLE_SCOPES and scope.bounds is not None and scope.source is not None
    if r.selection == "issued_at":
        t, conv = issue_time_from_text(sp.text, q, region)
        if t is None:
            out.status, out.missing = "unresolved", ["issue_time"]
            return out
        out.issued_at, out.provenance["issued_at"] = t, Source("route_model", sp.text, conv)
    elif scope.kind != "half_hour" or not single:
        # the last run before a half-hour needs that half-hour (an operation's own half-hour, read by code)
        out.status = "unresolved"
        out.missing = scope.missing if scope.missing in (["start_or_end"], ["time_zone"]) else ["half_hour"]
        return out
    if single:
        assert scope.bounds is not None and scope.source is not None
        out.half_hour, out.provenance["half_hour"] = scope.bounds, scope.source
        if scope.span is not None:
            out.spans.append(Span("run_half_hour", scope.span.text, scope.span.occurrences))
    out.status = "bound"
    return out


def _same_reading(a: _Op, b: _Op, cutoff_at: dict[str, datetime | None]) -> bool:
    """Identical subject, scope, run and cutoff, as code read them."""
    ra, rb = a.run, b.run
    return (a.subject == b.subject and a.scope.kind == b.scope.kind and a.scope.bounds == b.scope.bounds and
            a.scope.bounds is not None and (ra.status, ra.selection, ra.issued_at, ra.half_hour) ==
            (rb.status, rb.selection, rb.issued_at, rb.half_hour) and
            cutoff_at.get(a.op.cutoff_ref or "") == cutoff_at.get(b.op.cutoff_ref or ""))


def _consolidate(ops: list[_Op], cutoff_at: dict[str, datetime | None]) -> tuple[_Op | None, list[_Op]]:
    """One primary from several asked operations (decision 1), or None. Identical duplicates are one operation; a
    forecast value and a comparison are one comparison only when their subject, scope, run and cutoff are identical
    and the comparison contains the requested values: one half-hour compared under a named run, whose result carries
    POE50, POE10, POE90 and the actual. Anything else is not chosen between, nor merged."""
    if len({o.family for o in ops}) != 1 or not all(_same_reading(ops[0], o, cutoff_at) for o in ops[1:]):
        return None, []
    kinds = {o.op.kind for o in ops}
    if len(kinds) == 1:  # identical duplicates (a forecast operation's or a demand maximum's)
        return ops[0], ops[1:]
    first = ops[0]
    if first.family == "forecast" and first.scope.kind in SINGLE_SCOPES and first.run.status == "bound" and \
            first.run.selection in ("last_issued_before", "issued_at"):
        primary = next(o for o in ops if o.op.kind == "forecast_comparison")
        return primary, [o for o in ops if o is not primary]
    return None, []


# ------------------------------------------------------------------------------------------------ the compiler
@dataclass
class Compiled:
    """The request resolution compiled from a plan, the target half-hour it pins (a forecast review's), the
    plan-level clarifications, and whether the plan was refused as invalid."""
    requests: RequestResolution
    target: tuple[datetime, datetime] | None = None
    reasons: list[str] = field(default_factory=list)
    invalid: bool = False


@dataclass
class _Ctx:
    """What every step of the compilation reads."""
    q: str
    given: InvestigateRequest
    intent: str | None
    region: str | None
    day: date | None
    plan: RequestPlan
    quoted: list[tuple[int, int]]
    inactive: list[tuple[int, int]]  # the words of declined and background material
    cutoff_spans: dict[str, Span]
    cutoff_at: dict[str, datetime | None]
    refs_active: set[str]
    parser_span: Span | None
    kinds: list[str] = field(default_factory=list)  # the other kinds of forecast asked for: not answered


_NOT_DEMAND = "the forecast asked about is not a resolved operational-demand request (D29)"


def compile_plan(q: str, req: InvestigateRequest, given: InvestigateRequest, intent: str | None, region: str | None,
                 day: date | None, event: Any, plan: RequestPlan, pol: Policy | None = None) -> Compiled:
    """The existing ``RequestResolution`` from a v16 request plan (D31 Amendment 1). ``req``: the effective request
    (with the routing model's region and date); ``given``: the user's own request, whose fields are authoritative.
    Every decision is recorded in ``requests.plan`` for the trace."""
    pol = pol or policy()
    rr = RequestResolution(routed="reported", contract=CONTRACT)
    record: dict[str, Any] = {"policy": pol, "asked": [], "declined": [], "background": [], "primary": None,
                              "consolidated": [], "not_answered": [], "operations": {}, "problems": [], "echo": None}
    rr.plan = record
    out = Compiled(rr)
    problems = admit(plan)
    if problems:  # failing closed: nothing in an invalid plan is read
        record["problems"], out.invalid = problems, True
        return out
    for o in plan.operations:
        record[o.stance].append(o.id)
    scopes, runs, cutoffs = ({x.id: x for x in xs} for xs in (plan.scopes, plan.runs, plan.cutoffs))
    asked = [o for o in plan.operations if o.stance == "asked"]
    inactive = [o for o in plan.operations if o.stance != "asked"]
    refs_active = {o.cutoff_ref for o in asked if o.cutoff_ref} | ({plan.cutoff_ref} if plan.cutoff_ref else set())
    inactive_words = [sp for o in inactive for sp in (
        span("operation", o.operation_text, q), span("subject", o.subject_text, q),
        span("scope", scopes[o.scope_ref].text, q) if o.scope_ref else None,
        span("run", runs[o.run_ref].text, q) if o.run_ref else None,
        span("cutoff", cutoffs[o.cutoff_ref].text, q) if o.cutoff_ref else None) if sp is not None]
    m = AS_OF_Q_RE.search(q)
    end = _cutoff_words_end(q, m.end()) if m else 0
    ctx = _Ctx(q, given, intent, region, day, plan, [m.span() for m in _QUOTED_RE.finditer(q)],
               _regions(inactive_words), {}, {}, refs_active,
               Span("cutoff", q[m.start():end], ((m.start(), end),), "question") if m else None)
    _compile_cutoff(ctx, rr.cutoff, {o.cutoff_ref for o in inactive if o.cutoff_ref} - refs_active)
    co = rr.cutoff

    # -- the asked operations: classified, then each one's scope and run read by code
    ops = [_classify(o, q, ctx.quoted, pol) for o in asked]
    for rd in ops:
        if rd.status != "unsupported" and rd.family != "unknown":
            rd.scope = _read_scope(q, region, day, event, scopes.get(rd.op.scope_ref or ""), rd.family, co.as_of,
                                   ctx.quoted)
            if rd.family == "forecast":
                rd.run = _read_run(q, region, runs.get(rd.op.run_ref or ""), rd.scope, ctx.quoted)
        record["operations"][rd.op.id] = {"family": rd.family, "status": rd.status, "missing": rd.missing,
                                          "notes": rd.notes + rd.scope.notes}
    supported = [rd for rd in ops if rd.status == "supported"]
    unresolved = [rd for rd in ops if rd.status == "unresolved"]
    ctx.kinds = record["not_answered"] = sorted({str(rd.other_kind) for rd in ops if rd.status == "unsupported"})
    if intent not in ("market_event_review", "forecast_review"):
        # a document question: its operations are not read (as under v15); the plan's cutoff_ref is its cutoff
        _cutoff_of_what_runs(ctx, co, {plan.cutoff_ref} - {None})
        return out
    if any(rd.run.status == "as_of_availability" for rd in supported) and co.as_of is None and \
            co.status not in ("conflict", "unresolved"):
        co.status, co.missing = "unresolved", ["cutoff"]  # the newest run public by a cutoff, with no cutoff
    # -- one primary operation (decision 1)
    primary: _Op | None = None
    merged: list[_Op] = []
    if len(supported) + len(unresolved) > 1:
        if not unresolved:
            primary, merged = _consolidate(supported, ctx.cutoff_at)
            record["consolidated"] = [rd.op.id for rd in merged]
        if primary is None:
            out.reasons.append(PLAN_OPERATIONS_CLARIFICATION)
            record["problems"].append("several asked operations that are not one operation")
            return out
    elif supported:
        primary = supported[0]
    elif unresolved:
        _unresolved_primary(out, unresolved[0], ctx)
        return out
    if intent == "market_event_review" and ctx.kinds and not (primary is not None and primary.family == "forecast"):
        rr.ineligible_tools = {t: _NOT_DEMAND for t in DEMAND_FORECAST_TOOLS}
    if primary is None:
        if intent == "forecast_review":  # a forecast review must say what is asked of the forecasts
            rr.forecast = ForecastAnalysis(status="unresolved", detected_by=["intent", "route_model"],
                                           missing=["domain_unsupported"] if ctx.kinds else ["operation"],
                                           unsupported=ctx.kinds, domain=ctx.kinds[0] if len(ctx.kinds) == 1 else None)
        else:  # an event review runs without a plan operation: only the plan's cutoff_ref limits it
            if ctx.kinds:
                rr.notes.append(not_answered_note(ctx.kinds))
            _cutoff_of_what_runs(ctx, co, {plan.cutoff_ref} - {None})
        return out
    record["primary"] = primary.op.id
    _cutoff_of_what_runs(ctx, co, ({o.op.cutoff_ref for o in [primary, *merged]} | {plan.cutoff_ref}) - {None})
    _compile_primary(out, primary, ctx)
    record["echo"] = echo(rr, region)
    if record["echo"]:
        rr.notes.append(record["echo"])
    return out


def _compile_cutoff(ctx: _Ctx, co: CutoffRequest, refs_inactive: set[str]) -> None:
    """The cutoff (decision 3): a cutoff an asked operation (or the plan's ``cutoff_ref``) refers to is never dropped,
    and one that cannot be read is sent back; a cutoff nothing refers to is sent back, not applied globally; one that
    only declined or background material refers to does not constrain; the request field stays authoritative. The
    question parser's as-of words are an omission backstop (decision 5): words no plan cutoff holds are sent back, and
    where a plan cutoff holds them, the two readings of the same role must agree."""
    q, region = ctx.q, ctx.region
    for c in ctx.plan.cutoffs:
        sp = span("cutoff", c.text, q)
        if sp is None or (c.id in ctx.refs_active and _only_inside(sp, ctx.quoted)):
            ctx.cutoff_at[c.id] = None
            co.notes.append(f"cutoff: the words of {c.id} are not in the question, or only in quotation marks")
            continue
        ctx.cutoff_spans[c.id] = sp
        ctx.cutoff_at[c.id], conv = _first_instant(sp.text, q, region)
        if c.id in ctx.refs_active:
            co.spans.append(sp)
            if ctx.cutoff_at[c.id] is not None:
                co.provenance.setdefault("as_of", Source("route_model", sp.text, conv))
    unreferenced = [c.id for c in ctx.plan.cutoffs if c.id not in ctx.refs_active | refs_inactive and not (
        c.id in ctx.cutoff_spans and _only_inside(ctx.cutoff_spans[c.id], [*ctx.quoted, *ctx.inactive]))]
    if ctx.refs_active:
        co.detected_by.append("route_model")
    if ctx.given.as_of_utc:
        co.detected_by.insert(0, "request")
        co.status, co.as_of = "bound", parse_iso(ctx.given.as_of_utc)
        co.provenance = {"as_of": Source("request", "as_of_utc")}
        stated = next((c for c in [*sorted(ctx.refs_active), *unreferenced] if c in ctx.cutoff_spans), None)
        if stated is not None:  # the question's own cutoff words, as the plan quotes them: compared, never applied
            co.stated, co.stated_words = ctx.cutoff_at[stated], ctx.cutoff_spans[stated].text
        return
    active = {cid: ctx.cutoff_at.get(cid) for cid in ctx.refs_active}
    read = sorted({t for t in active.values() if t is not None})
    ps = ctx.parser_span
    held_by_plan = ps is not None and _touches(ps, _regions(list(ctx.cutoff_spans.values())))
    same_words = ps is not None and any(_touches(ps, list(ctx.cutoff_spans[c].occurrences))
                                        for c in ctx.refs_active if c in ctx.cutoff_spans)
    pt = (extract_as_of(q, region, ctx.day) or question_as_of(q, region)[0]) if same_words else None
    if read and read[-1] - read[0] > timedelta(seconds=59):
        co.status, co.conflicts = "conflict", ["cutoff: the plan's cutoffs name different times"]
    elif pt is not None and any(abs(pt - t) > timedelta(seconds=59) for t in read):
        co.status = "conflict"
        co.conflicts = [f"cutoff: {iso_utc(pt)} (question parser) or {', '.join(map(iso_utc, read))} (the plan)"]
    elif any(t is None for t in active.values()):
        co.status, co.missing = "unresolved", ["cutoff"]  # detected but not pinned down: never dropped (D26)
    elif unreferenced or (ps is not None and not held_by_plan and not _only_inside(ps, [*ctx.quoted, *ctx.inactive])):
        co.status, co.missing = "unresolved", ["cutoff_reference"]
        co.notes += [f"cutoff: {c} is referred to by no operation" for c in unreferenced]
        if ps is not None and not held_by_plan:
            co.notes.append(f"cutoff: the question parser reads as-of words ('{ps.text}') that no plan cutoff holds")
    elif read:
        co.status, co.as_of = "bound", read[0]


def _cutoff_of_what_runs(ctx: _Ctx, co: CutoffRequest, running: set[Any]) -> None:
    """Decision 3, for the request that runs: a cutoff that only an asked operation which does not run refers to (a
    forecast of another kind, named as not answered, or an operation a document question does not read) is not the
    running request's. Unless it names the same time as a cutoff the running request refers to, it is sent back:
    never applied to the running request in the plan's place, and never dropped. A request cutoff stands."""
    if ctx.given.as_of_utc or co.status in ("conflict", "unresolved"):
        return
    own = {ctx.cutoff_at.get(c) for c in running}
    stray = sorted(c for c in ctx.refs_active - running if ctx.cutoff_at.get(c) not in own or not running)
    if stray:
        co.status, co.as_of, co.missing = "unresolved", None, ["cutoff_reference"]
        co.notes += [f"cutoff: {c} limits only an operation that does not run; which request it limits is not shown"
                     for c in stray]


def _unresolved_primary(out: Compiled, rd: _Op, ctx: _Ctx) -> None:
    """One asked operation, not resolved: sent back with what is missing (an event review's unnamed forecast keeps
    D29's handling: the demand-forecast tools serve none, and the forecast is named as not answered)."""
    rr = out.requests
    assert rr.plan is not None
    rr.plan["primary"] = rd.op.id
    if rd.family == "unknown" or (rd.family == "maximum" and rd.missing != ["measure"]):
        out.reasons.append(PLAN_OPERATION_CLARIFICATION)
    elif rd.family == "maximum":
        rr.maximum = MaxRequest(status="unresolved", missing=["measure"], detected_by=["route_model"], spans=rd.spans,
                                unused=list(rd.notes))
    elif ctx.intent == "forecast_review":
        rr.forecast = ForecastAnalysis(status="unresolved", missing=rd.missing, detected_by=["intent", "route_model"],
                                       unsupported=ctx.kinds, notes=list(rd.notes))
    else:
        rr.ineligible_tools = {t: _NOT_DEMAND for t in DEMAND_FORECAST_TOOLS}
        rr.notes.append(not_answered_note([]))


def _held_regions(ctx: _Ctx, rd: _Op, scope: _Scope, co: CutoffRequest) -> list[tuple[int, int]]:
    """Where the question's times may be: the words of every scope and run an operation refers to, of every operation
    (any stance) and of every cutoff (the plan's and the parser's: a cutoff's time is the cutoff's, whether or not the
    cutoff is sent back for its reference), quoted background, and a bracket restating one of them."""
    q, plan = ctx.q, ctx.plan
    referenced = {x for o in plan.operations for x in (o.scope_ref, o.run_ref)}
    texts = [x.text for xs in (plan.scopes, plan.runs) for x in xs if x.id in referenced]
    texts += [t for o in plan.operations for t in (o.operation_text, o.subject_text) if t]
    held = [sp for sp in (span("held", t, q) for t in texts) if sp is not None]
    held += [*ctx.cutoff_spans.values(), *([ctx.parser_span] if ctx.parser_span is not None else [])]
    cutoff_texts = {sp.text for sp in ctx.cutoff_spans.values()}
    run_texts = {sp.text for sp in rd.run.spans if sp.role == "run_selection"}

    def instants(sp: Span) -> set[datetime]:
        out = _instants_in(sp.text, q, ctx.region)
        if scope.bounds and scope.span is not None and sp.text == scope.span.text:
            out |= set(scope.bounds)
        if sp.text in cutoff_texts and co.as_of is not None:
            out.add(co.as_of)
        if sp.text in run_texts and rd.run.issued_at is not None:
            out.add(rd.run.issued_at)
        return out
    located = [(sp.located, instants(sp)) for sp in held if sp.located is not None]
    return [*_regions(held), *ctx.quoted, *_restatements(q, [(a, i) for a, i in located if a is not None], ctx.region)]


def _compile_primary(out: Compiled, rd: _Op, ctx: _Ctx) -> None:
    """The primary operation as the existing request it is: a demand maximum (D24-D26), or a forecast request (D28)
    with its run (D26); an event review's forecast decides its tools only, as under v15."""
    rr, co, q, given = out.requests, out.requests.cutoff, ctx.q, ctx.given
    scope = rd.scope
    if given.window_start_utc and given.window_end_utc:  # the request's window is authoritative
        stated = (str(scope.kind), scope.bounds) if scope.kind and scope.bounds else None
        scope = _Scope("explicit", (parse_iso(given.window_start_utc), parse_iso(given.window_end_utc)),
                       Source("request", "window_start_utc, window_end_utc"), scope.span, [], list(scope.notes), stated)
    # the active cutoff's words read as the scope's too: two roles for the same words (D26; a request cutoff stands)
    if scope.span is not None and not given.as_of_utc and any(
            _touches(scope.span, list(ctx.cutoff_spans[c].occurrences)) for c in ctx.refs_active if c in ctx.cutoff_spans):
        co.status, co.as_of = "conflict", None
        co.conflicts = [f"cutoff: the words '{scope.span.text}' are read as the cutoff and as the half-hour or period "
                        "asked about"]
    # every time the question names must be held (D26, D28): a time none holds may be the one asked about, or narrow
    # the period; and no other words may narrow a period read from the plan
    regions = _held_regions(ctx, rd, scope, co)
    loose = [q[a:b] for a, b in _time_expressions(q)
             if not any(x <= a and b - (q[b - 1] == ".") <= y for x, y in regions)]  # "3:57 pm." ends a sentence
    own = [*ctx.cutoff_spans.values(), *([ctx.parser_span] if ctx.parser_span is not None else []), *rd.run.spans,
           *([scope.span] if scope.span is not None else [])]  # other roles' words, and the scope's own
    masks = [Span("masked", "", (r,)) for r in [*ctx.quoted, *ctx.inactive, *_regions(own)]]
    narrowing = scope.kind in PERIOD_SCOPES and scope.source is not None and scope.source.source == "route_model" and \
        _narrows(_masked(q, masks))
    notes = list(scope.notes)
    if loose:
        notes.append(f"scope: the question names {', '.join(repr(t) for t in loose)}, which no plan entity's words hold")
    if narrowing:
        notes.append("scope: other words narrow the period")
    missing = scope.missing or (["unheld"] if loose or narrowing else [])
    if rd.family == "maximum":
        mx = rr.maximum = MaxRequest(detected_by=["route_model"], measures=[str(rd.subject)], unused=notes,
                                     spans=[*rd.spans, *([scope.span] if scope.span is not None else [])])
        if rd.subject_source is not None:
            mx.provenance["measure"] = rd.subject_source
        if scope.stated is not None:
            mx.stated = ({"whole_local_day": "day"}.get(scope.stated[0], scope.stated[0]), scope.stated[1])
        if missing:
            mx.status = "unresolved"
            mx.missing = ["event"] if "event" in missing else ["date"] if missing == ["date"] else ["window"]
        else:
            assert scope.bounds is not None and scope.source is not None
            mx.status, mx.window, mx.provenance["window"] = "bound", scope.bounds, scope.source
            mx.window_kind = {"whole_local_day": "day"}.get(str(scope.kind), str(scope.kind))
        rr.notes = request_field_notes(q, given, ctx.region, ctx.day, mx, co)
        if ctx.kinds:
            rr.notes.append(not_answered_note(ctx.kinds))
        return
    # a forecast operation: its run (a run not bound is sent back first, as under v15), then its request (D28)
    rr.forecast_run = rd.run
    rr.notes = request_field_notes(q, given, ctx.region, ctx.day, rr.maximum, co)
    if ctx.intent != "forecast_review":  # an event review keeps its handling: the operation decides its tools only
        if ctx.kinds:
            rr.notes.append(not_answered_note(ctx.kinds))
        return
    if rd.run.status == "bound" and rd.run.half_hour is not None:
        out.target = rd.run.half_hour
    if rd.run.status in ("unresolved", "conflict"):
        return
    fa = rr.forecast = ForecastAnalysis(detected_by=["intent", "route_model"], domain="operational_demand",
                                        unsupported=ctx.kinds, notes=notes, spans=list(rd.spans))
    if rd.subject_source is not None:
        fa.provenance["domain"] = rd.subject_source
    fa.provenance["operation"] = Source("route_model", rd.spans[0].text)
    if missing:
        fa.status, fa.missing = "unresolved", ["scope"]
        return
    assert scope.bounds is not None and scope.source is not None
    if not _on_grid(scope.bounds) or \
            scope.bounds[1] - scope.bounds[0] > timedelta(hours=config.MAX_FORECAST_TARGET_HOURS):
        fa.status, fa.missing = "unresolved", ["window_limit"]
        fa.notes.append(f"scope: {_span(scope.bounds)} is not whole half-hours within "
                        f"{config.MAX_FORECAST_TARGET_HOURS} hours")
        return
    single = scope.kind in SINGLE_SCOPES
    fa.operation = "forecast_value" if rd.op.kind == "forecast_value" else \
        "single_interval_comparison" if single else "window_comparison"
    fa.status, fa.scope = "bound", scope.kind
    fa.target, fa.window = (scope.bounds, None) if single else (None, scope.bounds)
    fa.provenance["scope"] = scope.source
    if scope.span is not None:
        fa.spans.append(scope.span)
    out.target = fa.target or out.target
    if ctx.kinds:  # another kind of forecast asked for too: said not to be answered (D29)
        rr.notes.append(not_answered_note(ctx.kinds))


# ------------------------------------------------------------------------------------------------ the echo
_OPERATION_WORDS = {
    "forecast_value": "what AEMO's operational demand forecast gave",
    "single_interval_comparison": "AEMO's operational demand forecast compared with actual operational demand",
    "window_comparison": "AEMO's operational demand forecasts compared with actual operational demand"}
_WINDOW_WORDS = {"day": "the whole local day", "event": "the price event's window", "explicit": "the window"}


def echo(rr: RequestResolution, region: str | None) -> str | None:
    """The interpretation echo: the bound reading, stated by code (controller metadata, labelled as such), or None when
    nothing is bound. It is not the model's interpretation, a validation result or a confirmation by the user."""
    fa, mx, run, co = rr.forecast, rr.maximum, rr.forecast_run, rr.cutoff
    where = f" in {region}" if region else ""
    if fa.status == "bound" and fa.operation in _OPERATION_WORDS:
        b = fa.target or fa.window
        assert b is not None and fa.operation is not None
        what = f"{_OPERATION_WORDS[fa.operation]}{where}, for the {'half-hour' if fa.target else 'period'} {_span(b)}"
    elif mx.status == "bound" and mx.window is not None:
        window = _WINDOW_WORDS.get(str(mx.window_kind), "the window")
        what = f"the highest {' and '.join(mx.measures)}{where}, over {window} {_span(mx.window)}"
    else:
        return None
    parts = [what]
    if run.status == "bound":
        parts.append("run: the last issued before that half-hour began" if run.selection == "last_issued_before" else
                     f"run: the one issued at {iso_utc(run.issued_at)}" if run.issued_at else "run: as named")
    elif run.status == "as_of_availability":
        parts.append("run: the newest public by the as-of cutoff")
    if co.status == "bound" and co.as_of is not None:
        src = co.provenance.get("as_of")
        parts.append(f"as-of cutoff: {iso_utc(co.as_of)}" +
                     (" (given with the request)" if src is not None and src.source == "request" else ""))
    return ECHO_LABEL + "; ".join(parts) + "."


def withdraw_echo(res: Any) -> Any:
    """A resolution that does not run (sent back or refused) states no reading: its echo is withdrawn from the notes
    and the plan record (``request.Resolution``; returned for chaining)."""
    rr = res.requests
    said = rr.plan.get("echo") if rr is not None and rr.plan else None
    if said and res.status != "ok":
        rr.notes = [n for n in rr.notes if n != said]
        rr.plan = {**rr.plan, "echo": None}
        res.routing["requests"] = rr.as_dict()
    return res
