"""Typed analytical results (D24): what the code computed, as a versioned contract, admitted only by verification.

The first and only kind is ``demand_maximum`` (I-17): a demand measure's maximum over the window a question asks
about, computed by ``agent.demand_max`` from the controller's own tool call.

- **The contract** (``AnalyticalResult``, ``analytical_result/1``) is public and serialised in the report's additive
  ``results`` field. It carries no "verified" or "trusted" field: a type, or a field, establishes nothing.
- **Identity.** ``result_id`` hashes the request (its question and explicit fields, not the mode), the kind, measure,
  region, window, cutoff, calculation version and the pinned data version; ``computation_id`` hashes the same without
  the request. The evidence IDs and the tool-call ID are in-run references (``Transient``), outside the identity.
- **Status.** ``established`` (every interval of the window held: the maximum and each tied interval);
  ``not_established`` (not every interval held: no maximum; the highest value held is carried apart, and it is not a
  maximum); ``unavailable`` (no value at all: only the reason).
- **Admission.** Only ``ResultRegistry`` creates a ``VerifiedResult``, and only when the runtime verifier says
  ``verified``:
  - **in the run** (``verify_in_run``), the result is re-derived from the pinned store with the same tool code and
    compared, and its in-run evidence references are checked against the run's evidence registry;
  - **on load** (``verify_loaded``), JSON is parsed, its identifiers and digest recomputed, and the result re-derived
    from the pinned store. The producing server's statement (``ReportedResult.server_verification``) is not trusted.
  - ``failed`` means the content does not match; ``unverifiable`` means it cannot be checked (no store, another pinned
    data version, an unknown calculation version, or a run-time policy block that cannot be re-derived). Neither is
    admitted, and neither is ever treated as verified.
- **Where verification happens.** Server-side, inside ``service.investigate``, where the pinned store is: API clients
  receive each result with the server's statement at response time and need no store. A saved or exported record is
  data: whoever reads it back and needs a verified result calls ``verify_loaded`` with the pinned store.

Nothing here renders, validates or changes an answer: the validator, the controller's sentence and the fallback still
read the binding dict, which ``agent.demand_max.binding_from_result`` derives from the result exactly as before.

**D27** adds the forecast-comparison results (``ForecastResult``, ``forecast_result/1``: kinds ``forecast_point`` and
``forecast_aggregate``, computed by ``agent.forecast_compare``) beside the demand maxima, which are unchanged. A report's
``results`` holds either, told apart by ``schema_version``; the same registry admits both, only when verified.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

if TYPE_CHECKING:
    from .evidence import EvidenceRegistry
    from .selection import Selection
    from .store import Store

RESULT_SCHEMA: Literal["analytical_result/1"] = "analytical_result/1"


class _R(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResultIdentity(_R):
    request_digest: str = Field(description="SHA-256 of the investigation request: question and explicit fields")
    kind: Literal["demand_maximum"]
    measure: str = Field(description="'total demand' (dispatch TOTALDEMAND, 5-minute) or 'operational demand'")
    region: str | None
    window_utc: tuple[str, str] | None = Field(description="(start, end] of the requested window, or None")
    window_kind: str | None
    cutoff_utc: str | None = Field(description="the request's as-of cutoff, or None")
    calculation_version: str
    data_version: str = Field(description="the pinned data snapshot the result was computed from")


class Coverage(_R):
    interval_minutes: int
    intervals_in_window: int
    intervals_held: int
    complete: bool
    excluded_by_as_of: int


class Limitation(_R):
    code: str
    text: str


class Transient(_R):
    """In-run references: meaningful only inside the investigation that produced the result; never its identity."""
    evidence_ids: tuple[str, ...]
    tool_call_id: str | None


class AnalyticalResult(_R):
    schema_version: Literal["analytical_result/1"] = RESULT_SCHEMA
    result_id: str
    computation_id: str
    identity: ResultIdentity
    status: Literal["established", "not_established", "unavailable"]
    reason: str | None = None
    metric: str
    unit: str | None = None
    maximum: float | None = Field(None, description="established only")
    interval_ends_utc: tuple[str, ...] = Field((), description="the maximum's interval ends, every tie; established only")
    highest_held: float | None = Field(None, description="not_established only: the highest value held, NOT a maximum")
    highest_held_interval_ends_utc: tuple[str, ...] = ()
    coverage: Coverage | None = None
    source_row_ids: tuple[str, ...] = Field((), description="durable source rows of the interval(s) reported")
    limitations: tuple[Limitation, ...] = ()
    transient: Transient
    digest: str = Field(description="SHA-256 of the content (not a signature: it detects edits, not forgery)")


# -- forecast comparisons (D27) ----------------------------------------------------------------------------------------
FORECAST_SCHEMA: Literal["forecast_result/1"] = "forecast_result/1"
ERROR_CONVENTION = ("error_mw = POE50 forecast minus actual (positive: the forecast was above the actual); error_pct = "
                    "error_mw / actual x 100 (none when the actual is 0); MAE = the mean of |error_mw| over the listed "
                    "pairs; mean error = the mean of error_mw over them")


class ForecastIdentity(_R):
    request_digest: str = Field(description="SHA-256 of the investigation request: question and explicit fields")
    kind: Literal["forecast_point", "forecast_aggregate"]
    measure: Literal["operational demand"] = Field(
        description="operational demand: AEMO's POE50 forecast against the actual, half-hourly, in MW")
    region: str
    target_utc: tuple[str, str] | None = Field(description="forecast_point: the half-hour asked about, (start, end]")
    window_utc: tuple[str, str] | None = Field(description="forecast_aggregate: the aggregation window, (start, end]")
    run_selection: Literal["last_issued_before", "issued_at", "run_id", "latest_before_target", "min_lead_hours",
                           "latest_available_as_of"] = Field(
        description="how runs are chosen: for a point, by issue time; for an aggregate, the comparison tool's selector")
    named_issued_at_utc: str | None = Field(None, description="issued_at: the issue time the request names")
    named_run_id: str | None = Field(None, description="run_id: the run the request names")
    min_lead_hours: float | None = None
    actual_revision_policy: Literal["latest_available", "initial", "updated"]
    cutoff_utc: str | None = Field(description="the request's as-of cutoff, or None")
    calculation_version: str
    data_version: str = Field(description="the pinned data snapshot the result was computed from")


class ForecastPair(_R):
    target_end_utc: str
    run_id: str = Field(description="the run that forecast this half-hour (an aggregate's runs may differ by target)")
    run_issued_at_utc: str
    run_published_at_utc: str | None
    run_available_at_utc: str
    lead_hours: float
    poe50_mw: float
    poe10_mw: float | None = Field(description="AEMO-published band context, not compared")
    poe90_mw: float | None = Field(description="AEMO-published band context, not compared")
    forecast_row_id: str
    actual_mw: float
    actual_revision: str
    actual_row_id: str
    error_mw: float = Field(description="POE50 minus actual: positive when the forecast was above the actual")
    abs_error_mw: float
    error_pct: float | None = Field(description="error_mw / actual x 100; None when the actual is 0")


class ExcludedTarget(_R):
    target_end_utc: str
    reason: Literal["no_forecast_for_selection", "no_actual", "not_public_by_cutoff", "no_data_held", "run_not_held",
                    "tied_runs", "run_not_public_by_cutoff"]
    detail: str


class ForecastResult(_R):
    schema_version: Literal["forecast_result/1"] = FORECAST_SCHEMA
    result_id: str
    computation_id: str
    identity: ForecastIdentity
    status: Literal["established", "partial", "unavailable"]
    reason: str | None = None
    unit: Literal["MW"] = "MW"
    error_convention: str = ERROR_CONVENTION
    pairs: tuple[ForecastPair, ...] = Field((), description="every forecast/actual pair the result is computed from")
    excluded: tuple[ExcludedTarget, ...] = Field((), description="every half-hour without a pair, with its reason")
    targets_expected: int = Field(description="half-hours in the target or window")
    mae_mw: float | None = Field(None, description="forecast_aggregate: the mean of |error_mw| over the pairs")
    mean_error_mw: float | None = Field(None, description="forecast_aggregate: the mean of error_mw over the pairs")
    source_row_ids: tuple[str, ...] = Field((), description="each pair's forecast and actual rows")
    limitations: tuple[Limitation, ...] = ()
    transient: Transient
    digest: str = Field(description="SHA-256 of the content (not a signature: it detects edits, not forgery)")


AnyResult = AnalyticalResult | ForecastResult
ResultT = Annotated[AnalyticalResult | ForecastResult, Field(discriminator="schema_version")]


class Verification(_R):
    outcome: Literal["verified", "failed", "unverifiable"]
    basis: Literal["in_run", "on_load"]
    data_version: str | None = Field(description="the pinned store's data version checked against, if any")
    reasons: tuple[str, ...] = ()


class ReportedResult(_R):
    """A result as a report carries it, with the producing server's verification statement at response time. The
    statement is information for API clients; it is not trusted when the JSON is read back (``verify_loaded``)."""
    result: ResultT
    server_verification: Verification


# -- identity and digest ----------------------------------------------------------------------------------------------
def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _sha(obj: Any) -> str:
    return hashlib.sha256(_canonical(obj).encode()).hexdigest()


def request_digest(request: Any) -> str:
    """The request's identity: its question and explicit fields, not the mode (Live and Replay ask the same)."""
    return _sha(request.model_dump(mode="json", exclude={"mode"}))


def _ids(identity: ResultIdentity | ForecastIdentity) -> tuple[str, str]:
    d = identity.model_dump(mode="json")
    return _sha(d), _sha({k: v for k, v in d.items() if k != "request_digest"})


def _content(r: AnyResult | dict[str, Any]) -> dict[str, Any]:
    d = r.model_dump(mode="json") if isinstance(r, AnalyticalResult | ForecastResult) else dict(r)
    return {k: v for k, v in d.items() if k != "digest"}


def make_result(identity: ResultIdentity, **content: Any) -> AnalyticalResult:
    """A result with its identifiers and digest computed from its identity and content."""
    rid, cid = _ids(identity)
    draft = AnalyticalResult(result_id=rid, computation_id=cid, identity=identity, digest="", **content)
    return draft.model_copy(update={"digest": _sha(_content(draft))})


def make_forecast_result(identity: ForecastIdentity, **content: Any) -> ForecastResult:
    """A forecast-comparison result (D27) with its identifiers and digest computed from its identity and content."""
    rid, cid = _ids(identity)
    draft = ForecastResult(result_id=rid, computation_id=cid, identity=identity, digest="", **content)
    return draft.model_copy(update={"digest": _sha(_content(draft))})


def _integrity(r: AnyResult) -> list[str]:
    """What is inconsistent within the result itself: its identifiers, digest and status fields."""
    if isinstance(r, ForecastResult):
        from .agent import forecast_compare

        return _id_integrity(r) + forecast_compare.integrity(r)
    out = []
    rid, cid = _ids(r.identity)
    if r.result_id != rid:
        out.append("result_id does not match its identity")
    if r.computation_id != cid:
        out.append("computation_id does not match its identity")
    if r.digest != _sha(_content(r)):
        out.append("digest does not match its content")
    if r.status == "established" and (r.maximum is None or not r.interval_ends_utc or r.highest_held is not None
                                      or r.coverage is None or not r.coverage.complete):
        out.append("an established result needs a maximum, its interval ends and complete coverage, and nothing else")
    if r.status == "not_established" and (r.maximum is not None or r.interval_ends_utc or r.highest_held is None
                                          or r.coverage is None or r.coverage.complete):
        out.append("a result not established carries no maximum, only the highest value held, with incomplete coverage")
    if r.status == "unavailable" and (r.maximum is not None or r.highest_held is not None or not r.reason):
        out.append("an unavailable result carries no value, only its reason")
    return out


def _id_integrity(r: AnyResult) -> list[str]:
    rid, cid = _ids(r.identity)
    return [m for m, bad in (("result_id does not match its identity", r.result_id != rid),
                             ("computation_id does not match its identity", r.computation_id != cid),
                             ("digest does not match its content", r.digest != _sha(_content(r)))) if bad]


# -- verification ---------------------------------------------------------------------------------------------------
def _known(r: AnyResult) -> str | None:
    from .agent import demand_max, forecast_compare

    if isinstance(r, ForecastResult):
        if r.identity.calculation_version == forecast_compare.CALCULATION_VERSION:
            return None
        return f"calculation {r.identity.kind} {r.identity.calculation_version} is not known to this server"

    if r.identity.kind == "demand_maximum" and r.identity.calculation_version == demand_max.CALCULATION_VERSION:
        return None
    return f"calculation {r.identity.kind} {r.identity.calculation_version} is not known to this server"


def _rederive(r: AnyResult, store: Store,
              selection: Selection) -> tuple[Literal["verified", "failed", "unverifiable"], list[str]]:
    """(outcome, reasons) of re-deriving ``r`` from the pinned store and comparing everything but in-run references."""
    from .agent import demand_max, forecast_compare

    mod: Any = forecast_compare if isinstance(r, ForecastResult) else demand_max
    if why := mod.not_rederivable(r):
        return "unverifiable", [why]
    try:
        again = mod.rederive(r.identity, store, selection)
    except Exception as exc:  # the check could not run: never treated as verified, nor as a mismatch
        return "unverifiable", [f"re-derivation from the pinned store could not run ({type(exc).__name__})"]
    a, b = _content(r), _content(again)
    a.pop("transient"), b.pop("transient")
    diff = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    return ("verified", []) if not diff else ("failed", [f"re-derived from the pinned store, {', '.join(diff)} differ"])


def verify_in_run(r: AnyResult, *, store: Store, selection: Selection,
                  evidence: EvidenceRegistry) -> Verification:
    """A result computed in this run: consistent, re-derivable from the pinned store, and its in-run evidence the run's."""
    reasons = _integrity(r)
    if not reasons and (why := _known(r)):
        return Verification(outcome="unverifiable", basis="in_run", data_version=store.data_version, reasons=(why,))
    if not reasons and r.identity.data_version != store.data_version:
        return Verification(outcome="unverifiable", basis="in_run", data_version=store.data_version,
                            reasons=(f"pinned data {r.identity.data_version} is not the store's {store.data_version}",))
    if not reasons:
        outcome, more = _rederive(r, store, selection)
        if outcome != "verified":
            return Verification(outcome=outcome, basis="in_run", data_version=store.data_version, reasons=tuple(more))
        if isinstance(r, ForecastResult):
            from .agent import forecast_compare

            reasons += forecast_compare.in_run_problems(r, evidence)
            return Verification(outcome="failed" if reasons else "verified", basis="in_run",
                                data_version=store.data_version, reasons=tuple(reasons))
        value = r.maximum if r.status == "established" else r.highest_held
        ends = r.interval_ends_utc if r.status == "established" else r.highest_held_interval_ends_utc
        rows: list[str] = []
        for eid in r.transient.evidence_ids:
            ev = evidence.get(eid)
            if ev is None or ev.value is None or ev.metric != r.metric or ev.region != r.identity.region \
                    or value is None or abs(float(ev.value) - value) > 1e-9 or ev.valid_at_utc not in ends:
                reasons.append(f"in-run evidence {eid} does not match the result")
            else:
                rows += ev.source_row_ids
        if r.status != "unavailable" and tuple(rows) != r.source_row_ids:
            reasons.append("the in-run evidence's source rows are not the result's")
    return Verification(outcome="failed" if reasons else "verified", basis="in_run", data_version=store.data_version,
                        reasons=tuple(reasons))


def _parse(obj: AnyResult | ReportedResult | dict[str, Any]) -> AnyResult:
    """The result an object carries: a demand maximum (``analytical_result/1``, parsed exactly as before) or, by its
    ``schema_version``, a forecast comparison (``forecast_result/1``, D27)."""
    if isinstance(obj, ReportedResult):
        return obj.result
    if isinstance(obj, AnalyticalResult | ForecastResult):
        return obj
    d = obj.get("result", obj) if "server_verification" in obj else obj
    if isinstance(d, dict) and d.get("schema_version") == FORECAST_SCHEMA:
        return ForecastResult.model_validate(d)
    return AnalyticalResult.model_validate(d)


def verify_loaded(obj: AnyResult | ReportedResult | dict[str, Any], *, store: Store | None,
                  selection: Selection | None = None) -> Verification:
    """A result read back from JSON (an API response, a saved or exported record): parsed, checked for consistency,
    and re-derived from the pinned store. Any verification statement the JSON carries is ignored."""
    try:
        r = _parse(obj)
    except ValidationError as exc:
        d = obj.get("result", obj) if isinstance(obj, dict) and "server_verification" in obj else obj
        name = FORECAST_SCHEMA if isinstance(d, dict) and d.get("schema_version") == FORECAST_SCHEMA else \
            "analytical_result/1"
        article = "a" if name == FORECAST_SCHEMA else "an"
        return Verification(outcome="failed", basis="on_load", data_version=None,
                            reasons=(f"not {article} {name}: {exc.error_count()} schema error(s)",))
    reasons = _integrity(r)
    version = store.data_version if store is not None else None
    if reasons:
        return Verification(outcome="failed", basis="on_load", data_version=version, reasons=tuple(reasons))
    if store is None:
        return Verification(outcome="unverifiable", basis="on_load", data_version=None,
                            reasons=("the pinned store is not available here",))
    if why := _known(r):
        return Verification(outcome="unverifiable", basis="on_load", data_version=version, reasons=(why,))
    if r.identity.data_version != store.data_version:
        return Verification(outcome="unverifiable", basis="on_load", data_version=version,
                            reasons=(f"pinned data {r.identity.data_version} is not the store's {store.data_version}",))
    if selection is None:
        from .selection import load_selection

        selection = load_selection()
    outcome, more = _rederive(r, store, selection)
    return Verification(outcome=outcome, basis="on_load", data_version=version, reasons=tuple(more))


# -- the verified-result registry ---------------------------------------------------------------------------------------
_ADMISSION = object()


@dataclass(frozen=True)
class VerifiedResult:
    """A result the runtime verifier admitted. Only ``ResultRegistry`` can create one; never serialised."""
    result: AnyResult
    verification: Verification
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._token is not _ADMISSION:
            raise PermissionError("a VerifiedResult is created only by ResultRegistry, after verification")


class ResultRegistry:
    """One investigation's results: every one computed is reported with its verification; only verified ones are
    admitted, and only admitted ones are returned by ``verified``."""

    def __init__(self) -> None:
        self._verified: dict[str, VerifiedResult] = {}
        self._reported: list[ReportedResult] = []

    def _admit(self, r: AnyResult, v: Verification) -> None:
        if v.outcome == "verified":
            self._verified[r.result_id] = VerifiedResult(r, v, _ADMISSION)

    def submit_in_run(self, r: AnyResult, *, store: Store, selection: Selection, evidence: EvidenceRegistry,
                      trace: Any = None) -> Verification:
        v = verify_in_run(r, store=store, selection=selection, evidence=evidence)
        self._reported.append(ReportedResult(result=r, server_verification=v))
        self._admit(r, v)
        if trace is not None:
            trace.add("result", "analytical_result", result_id=r.result_id, result_kind=r.identity.kind,
                      measure=r.identity.measure, status=r.status, verification=v.outcome, reasons=list(v.reasons))
        return v

    def submit_loaded(self, obj: AnyResult | ReportedResult | dict[str, Any], *, store: Store | None,
                      selection: Selection | None = None) -> Verification:
        v = verify_loaded(obj, store=store, selection=selection)
        if v.outcome == "verified":
            self._admit(_parse(obj), v)
        return v

    def verified(self, result_id: str) -> VerifiedResult | None:
        return self._verified.get(result_id)

    def reported(self) -> list[ReportedResult]:
        return list(self._reported)
