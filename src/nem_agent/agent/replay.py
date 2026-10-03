"""Scripted replay controller (no LLM).

It runs the *same* dispatcher, tools, retrieval and validators as the live path. Tool choice and arguments come
from fixed per-intent scripts, and the report text comes from deterministic templates filled only with
registered evidence. Every report it produces says ``generator = "scripted-replay-controller/1"``. This is not
model reasoning and is never presented as live tool calling.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from ..evidence import EvidenceRegistry
from ..report import (
    Citation,
    EventWindow,
    ForecastComparison,
    Hypothesis,
    InvestigationReport,
    NumericClaim,
    Observation,
    PublishedFinding,
    Versions,
)
from ..timeutil import NEM_TZ, half_hour_end_for, iso_utc, local_str, parse_iso
from . import demand_max
from .dispatcher import Dispatcher, ToolCallRecord
from .request import Resolution

CONTROLLER_VERSION = "scripted-replay-controller/1"
WEATHER_WORDS = re.compile(r"\b(weather|temperature|hot|cold|wind|windy|solar|irradiance|heat)\b", re.I)
GEN_WORDS = re.compile(r"\b(generat\w*|unit|units|outage|trip|scada|supply)\b", re.I)
FORECAST_WORDS = re.compile(r"\b(forecast\w*|poe|predict\w*)\b", re.I)
NOTICE_WORDS = re.compile(r"\bmarket notices?\b|\bnotices? (say|said|says|state)\b", re.I)


def fmt_price(v: float) -> str:
    return f"${v:,.2f}/MWh"


def fmt_mw(v: float) -> str:
    return f"{v:,.0f} MW"


def fmt_signed_mw(v: float) -> str:
    return f"{v:+,.0f} MW"


def fmt_pct(v: float) -> str:
    return f"{v:+.1f}%"


class Composer:
    """Collects numeric claims, observations and citations while text is being written."""

    def __init__(self, registry: EvidenceRegistry, region: str | None) -> None:
        self.reg = registry
        self.region = region
        self.claims: list[NumericClaim] = []
        self.observations: list[Observation] = []
        self.citations: list[Citation] = []
        self._obs_ids: set[str] = set()

    def num(self, evidence_id: str, style: str = "mw", text: str = "") -> str:
        item = self.reg.get(evidence_id)
        if item is None or item.value is None:
            raise KeyError(f"evidence {evidence_id} missing")
        v = float(item.value)
        if style == "price":
            s, shown, tol, unit = fmt_price(v), round(v, 2), 0.01, "$/MWh"
        elif style == "pct":
            s, shown, tol, unit = fmt_pct(v), round(v, 1), 0.051, "%"
        elif style == "signed_mw":
            s, shown, tol, unit = fmt_signed_mw(v), round(v), 0.51, "MW"
        elif style == "count":
            s, shown, tol, unit = f"{v:,.0f}", round(v), 0.0, item.unit
        elif style == "raw":
            s, shown, tol, unit = f"{v:g} {item.unit}", v, 0.01, item.unit
        else:
            s, shown, tol, unit = fmt_mw(v), round(v), 0.51, "MW"
        self.claims.append(NumericClaim(claim_id=f"c{len(self.claims) + 1:03d}", text=text or s, value=shown,
                                        unit=unit, evidence_id=evidence_id, rounding=tol))
        return s

    def observe(self, evidence_id: str | None) -> None:
        if not evidence_id or evidence_id in self._obs_ids:
            return
        item = self.reg.get(evidence_id)
        if item is None or item.value is None or not item.valid_at_utc:
            return
        if item.evidence_class == "published_document":
            return
        self._obs_ids.add(evidence_id)
        rows = item.source_row_ids or [f"derived:{item.derivation}"]
        self.observations.append(Observation(
            metric=item.metric, value=float(item.value), unit=item.unit, valid_at_utc=item.valid_at_utc,
            valid_at_local=local_str(parse_iso(item.valid_at_utc), self.region) if self.region else None,
            interval_minutes=item.interval_minutes, evidence_id=evidence_id, source_row_ids=rows[:12],
            evidence_class=item.evidence_class,
            label=(item.label or item.derivation or item.metric)[:300]))

    def cite(self, hit: dict[str, Any], supports: str, prefer: list[str] | None = None) -> Citation:
        quote = best_sentence(hit["text"], prefer or [])
        for c in self.citations:
            if c.chunk_id == hit["chunk_id"] and c.quote == quote:
                return c
        c = Citation(citation_id=f"s{len(self.citations) + 1:02d}", chunk_id=hit["chunk_id"], doc_id=hit["doc_id"],
                     title=hit["title"], url=hit["url"], section=hit.get("section"), page=hit.get("page"),
                     publication_date=hit.get("publication_date"), doc_type=hit["doc_type"], quote=quote,
                     supports=supports[:400])
        self.citations.append(c)
        return c


_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"'])")


def best_sentence(text: str, prefer: list[str], max_len: int = 400) -> str:
    """An exact substring of ``text``: the sentence with most preferred terms (ties -> earliest)."""
    sents = [s.strip() for s in _SENT.split(text) if len(s.strip()) >= 20] or [text.strip()]
    def score(s: str) -> int:
        low = s.lower()
        return sum(low.count(p.lower()) for p in prefer)
    best = max(sents, key=lambda s: (score(s), -sents.index(s)))
    if len(best) > max_len:
        best = best[:max_len].rsplit(" ", 1)[0]
    return best


def ok(recs: list[ToolCallRecord], name: str) -> list[ToolCallRecord]:
    return [r for r in recs if r.name == name and r.status == "ok"]


def usable_hits(rec: ToolCallRecord) -> list[dict[str, Any]]:
    """Retrieved passages that may be quoted. Passages with instruction-like text are untrusted and never quoted."""
    return [h for h in rec.view.get("results", []) if not h.get("instruction_like")]


def flagged_hits(recs: list[ToolCallRecord]) -> int:
    return sum(1 for r in ok(recs, "retrieve_public_evidence") for h in r.view.get("results", []) if h.get("instruction_like"))


def forecast_focus(res: Resolution) -> tuple[datetime, datetime]:
    """The project's forecast-review scope: a 12-hour slice (24 half-hours) around the event peak, clipped to the
    window. Shared by the replay and live controllers so both answer the same question."""
    assert res.window is not None
    a, b = res.window
    centre = parse_iso(res.event.peak_interval_end_utc) if res.event else a + (b - a) / 2
    c = half_hour_end_for(centre)
    lo, hi = max(a, c - timedelta(hours=6)), min(b, c + timedelta(hours=6))
    t = getattr(res, "target", None)
    if t is not None and not (lo <= t[0] and t[1] <= hi):  # the half-hour asked about is in the slice compared (I-10)
        lo, hi = max(a, t[1] - timedelta(hours=6)), min(b, t[1] + timedelta(hours=6))
    return lo, hi


class ReplayController:
    def __init__(self, dispatcher: Dispatcher, registry: EvidenceRegistry, versions: Versions) -> None:
        self.d, self.reg, self.versions = dispatcher, registry, versions
        self._result_lines: list[dict[str, Any]] = []  # provenance of the maximum lines written (I-21)

    # ------------------------------------------------------------------ plans
    def run(self, res: Resolution) -> InvestigationReport:
        getattr(self, f"_plan_{res.intent}")(res)
        return getattr(self, f"_synth_{res.intent}")(res)

    def _window_args(self, res: Resolution) -> dict[str, Any]:
        assert res.window is not None
        return {"region": res.region, "start_utc": iso_utc(res.window[0]), "end_utc": iso_utc(res.window[1])}

    def _as_of(self, res: Resolution) -> str | None:
        return iso_utc(res.as_of) if res.as_of else None

    def _focus(self, res: Resolution) -> tuple[datetime, datetime]:
        return forecast_focus(res)

    def _plan_market_event_review(self, res: Resolution) -> None:
        w = self._window_args(res)
        q = res.request.question
        self.d.call("find_market_events", {**w, "kind": res.kind})
        self.d.call("get_price_timeline", {**w, "as_of_utc": self._as_of(res)})
        self.d.call("get_actual_demand", {**w, "revision_policy": "latest_available", "as_of_utc": self._as_of(res)})
        ev_date = res.event.peak_interval_end_market[:10].replace("/", "-") if res.event else ""
        self.d.call("retrieve_public_evidence", {
            "query": f"{res.region} region market notice {ev_date} price constraint outage contingency",
            "region": res.region, "event_start_utc": w["start_utc"], "event_end_utc": w["end_utc"],
            "as_of_utc": self._as_of(res), "top_k": 5, "doc_types": ["market_notice"]})
        self.d.call("retrieve_public_evidence", {
            "query": "regional reference price RRP dispatch price definition operational demand", "top_k": 3,
            "doc_types": ["definition"], "as_of_utc": self._as_of(res)})
        peak = self._peak_time(res)
        extras: list[str] = []
        if WEATHER_WORDS.search(q):
            extras.append("get_weather_context")
        if GEN_WORDS.search(q) or len(extras) < 2:
            extras.append("get_generation_change")
        if len(extras) < 2:
            extras.append("compare_forecast_actual")
        for name in extras[:2]:
            if name == "get_weather_context":
                self.d.call(name, {**w, "as_of_utc": self._as_of(res)})
            elif name == "get_generation_change" and peak is not None:
                self.d.call(name, {"region": res.region, "start_utc": iso_utc(peak - timedelta(hours=1)),
                                   "end_utc": iso_utc(peak + timedelta(minutes=30)), "top_n": 5,
                                   "as_of_utc": self._as_of(res)})
            elif name == "compare_forecast_actual":
                lo, hi = self._focus(res)
                self.d.call(name, {"region": res.region, "target_start_utc": iso_utc(lo), "target_end_utc": iso_utc(hi),
                                   "run_selector": "latest_before_target", "as_of_utc": self._as_of(res)})

    def _plan_forecast_review(self, res: Resolution) -> None:
        lo, hi = self._focus(res)
        t = {"region": res.region, "target_start_utc": iso_utc(lo), "target_end_utc": iso_utc(hi)}
        self.d.call("get_forecast_runs", {**t, "as_of_utc": self._as_of(res), "max_runs": 4})
        self.d.call("get_actual_demand", {"region": res.region, "start_utc": iso_utc(lo), "end_utc": iso_utc(hi),
                                          "revision_policy": "latest_available", "as_of_utc": self._as_of(res)})
        if res.as_of:
            self.d.call("compare_forecast_actual", {**t, "run_selector": "latest_available_as_of",
                                                    "as_of_utc": self._as_of(res)})
        else:
            self.d.call("compare_forecast_actual", {**t, "run_selector": "latest_before_target"})
            self.d.call("compare_forecast_actual", {**t, "run_selector": "min_lead_hours", "min_lead_hours": 24})
        self.d.call("retrieve_public_evidence", {
            "query": "operational demand forecast 50% POE most probable 10% 90% scaling factor load forecasting",
            "top_k": 4, "doc_types": ["definition", "procedure"], "as_of_utc": self._as_of(res)})
        self.d.call("retrieve_public_evidence", {
            "query": "major factors considered in the demand forecasting statistical models temperature",
            "top_k": 2, "doc_types": ["procedure"], "as_of_utc": self._as_of(res)})
        if WEATHER_WORDS.search(res.request.question):
            self.d.call("get_weather_context", {"region": res.region, "start_utc": iso_utc(lo), "end_utc": iso_utc(hi),
                                                "as_of_utc": self._as_of(res)})

    def _plan_source_explanation(self, res: Resolution) -> None:
        args: dict[str, Any] = {"query": res.request.question[:300], "top_k": 5, "as_of_utc": self._as_of(res)}
        if res.region:
            args["region"] = res.region
        if res.window:
            args["event_start_utc"], args["event_end_utc"] = iso_utc(res.window[0]), iso_utc(res.window[1])
        self.d.call("retrieve_public_evidence", args)

    def _peak_time(self, res: Resolution) -> datetime | None:
        tl = ok(self.d.records, "get_price_timeline")
        if tl:
            key = "peak" if res.kind == "high_price" else "minimum"
            return parse_iso(tl[0].view[key]["interval_end_utc"])
        return parse_iso(res.event.peak_interval_end_utc) if res.event else None

    # ------------------------------------------------------------------ shared pieces
    def _notice_gap(self, res: Resolution) -> list[str]:
        """Name the notices selected for this event that the local corpus no longer holds (rolling retention)."""
        if res.event is None:
            return []
        from ..retrieval.search import IndexMissingError, indexed_doc_ids

        try:
            have = indexed_doc_ids()
        except IndexMissingError:
            return []
        selected = [s for s in self.d.selection.sources
                    if s.dataset == "MARKET_NOTICE" and res.event.event_id in s.events]
        absent = [s for s in selected if s.source_id not in have]
        if not absent:
            return []
        return [f"{len(absent)} of {len(selected)} AEMO market notices selected for this event's window are not in the "
                "local corpus: they have rolled off NEMWeb's rolling 'Current' folder and were not found in NEMWeb's "
                "Archive/Market_Notice directory (its listing was empty when checked), so any statement they contained "
                "is unavailable on this machine (see docs/data-retention.md)."]

    def _base(self, res: Resolution, comp: Composer, headline: str, summary: list[str], **kw: Any) -> InvestigationReport:
        missing: list[str] = self._notice_gap(res)
        for r in self.d.records:
            if r.status in ("unavailable", "refused", "error", "blocked"):
                missing.append(f"{r.name}: {r.status} — {(r.missing or [r.blocked_reason or ''])[0]}"[:400])
            else:
                missing.extend(m[:400] for m in r.missing[:3])
        missing += [f"required tool not executed: {t}" for t in self.d.required_missing()]
        ew = None
        if res.window and res.region:
            ew = EventWindow(start_utc=iso_utc(res.window[0]), end_utc=iso_utc(res.window[1]),
                             start_local=local_str(res.window[0], res.region), end_local=local_str(res.window[1], res.region),
                             timezone=res.routing.get("region_tz") or "")
        urls: dict[str, set[str]] = {}
        for o in comp.observations:
            item = self.reg.get(o.evidence_id)
            for u in (item.source_urls if item else []):
                urls.setdefault(u, set()).add(o.evidence_id)
        manifest = {
            "data_version": self.versions.data, "corpus_version": self.versions.corpus,
            "sources": [{"url": u, "evidence_ids": sorted(ids)[:10]} for u, ids in sorted(urls.items())],
            "documents": sorted({(c.doc_id, c.url) for c in comp.citations}),
        }
        out = InvestigationReport(
            question=res.request.question, mode="replay", intent=res.intent, region=res.region,
            as_of=iso_utc(res.as_of) if res.as_of else None, event_window=ew, headline=headline, summary=summary,
            observations=comp.observations, citations=comp.citations, numeric_claims=comp.claims,
            missing_evidence=list(dict.fromkeys(missing)), source_manifest=manifest, trace_id=self.d.trace.trace_id,
            versions=self.versions, generator=CONTROLLER_VERSION, **kw)
        # provenance (I-21): every note in a Replay answer is written by the code; a maximum line counts only where it
        # was put in this report's summary
        out._provenance = {
            "result_lines": [r for r in self._result_lines
                             if r["summary_index"] < len(summary) and summary[r["summary_index"]] == r["text"]],
            "controller_notes": {"uncertainties": list(range(len(out.uncertainties))),
                                 "missing_evidence": list(range(len(out.missing_evidence)))}}
        self._result_lines = []
        return out

    def _standard_uncertainties(self, res: Resolution) -> list[str]:
        u = [
            "Co-occurring observations are not causes. Anything beyond the observed data is listed as a hypothesis.",
            "No AEMO market event report could be checked: aemo.com.au report pages refused scripted access when "
            "the sources were probed, so the corpus holds AEMO market notices, definitions and procedures only.",
            "Dispatch prices are the values published in real time with their PRICE_STATUS; later price revisions "
            "were not ingested.",
        ]
        if res.as_of:
            u.append("As-of view: only data provably public by the cutoff is used, applying the conservative "
                     "publication margin measured from NEMWeb listings; some data that existed may be excluded.")
        return u

    def _definition_citations(self, comp: Composer) -> list[str]:
        sents = []
        for r in ok(self.d.records, "retrieve_public_evidence"):
            if (r.args or {}).get("doc_types") not in (["definition"], ["definition", "procedure"]):
                continue
            for h in usable_hits(r)[:2]:
                c = comp.cite(h, f"Definition context from {h['title']}", ["regional reference price", "rrp",
                                                                            "operational demand", "poe", "probability"])
                sents.append(f"[{c.citation_id}] “{c.quote}”")
        return sents

    def _notice_findings(self, comp: Composer, res: Resolution) -> tuple[list[PublishedFinding], list[dict[str, Any]]]:
        findings, used = [], []
        for r in ok(self.d.records, "retrieve_public_evidence"):
            if (r.args or {}).get("doc_types") != ["market_notice"]:
                continue
            lo = res.window[0].astimezone(NEM_TZ).date().isoformat() if res.window else ""
            hi = res.window[1].astimezone(NEM_TZ).date().isoformat() if res.window else ""
            for h in usable_hits(r):
                if h["doc_type"] != "market_notice" or h.get("event_region") != res.region:
                    continue
                if not (lo <= (h.get("event_date") or "") <= hi):
                    continue  # adjacent-day notices are retrieved context, not findings about this window
                c = comp.cite(h, f"AEMO market notice in {res.region} dated within the investigated window",
                              ["tripped", "outage", "constraint", "contingency", "direction", "price", "invoked"])
                findings.append(PublishedFinding(
                    statement=f"An AEMO market notice for {res.region} [{c.citation_id}] says: “{c.quote}” "
                              "The notice does not state any effect on price.",
                    citation_ids=[c.citation_id], doc_type="market_notice", applies_to_event=True))
                used.append(h)
        return findings, used

    # ------------------------------------------------------------------ market_event_review
    def _synth_market_event_review(self, res: Resolution) -> InvestigationReport:
        comp = Composer(self.reg, res.region)
        recs = self.d.records
        tl = ok(recs, "get_price_timeline")
        if not tl:
            return self._abstain(res, comp, "No price data is available for the requested region and window, so the "
                                            "event cannot be reviewed.")
        v = tl[0].view
        key = "peak" if res.kind == "high_price" else "minimum"
        pk = v[key]
        thr_id = v["analysis_threshold"]["evidence_id"]
        for eid in (pk["evidence_id"], v["minimum"]["evidence_id"], v["peak"]["evidence_id"], v["mean_rrp"]["evidence_id"],
                    v["intervals_at_or_above_threshold"]["evidence_id"]):
            comp.observe(eid)
        word = "peaked at" if res.kind == "high_price" else "fell to"
        headline = (f"{res.region} 5-minute dispatch price {word} {comp.num(pk['evidence_id'], 'price')} for the interval "
                    f"ending {pk['interval_end_local']}.")
        s1 = (f"In the investigated window the price ranged from {comp.num(v['minimum']['evidence_id'], 'price')} to "
              f"{comp.num(v['peak']['evidence_id'], 'price')}. The unweighted mean of the 5-minute prices was "
              f"{comp.num(v['mean_rrp']['evidence_id'], 'price')}, and "
              f"{comp.num(v['intervals_at_or_above_threshold']['evidence_id'], 'count')} five-minute intervals were at or above "
              f"the project analysis threshold of {comp.num(thr_id, 'price')} (a project setting, not an AEMO label).")
        summary = [s1]
        if v.get("totaldemand_at_peak") and res.kind == "high_price":
            comp.observe(v["totaldemand_at_peak"]["evidence_id"])
            ni = v.get("netinterchange_at_peak")
            s = (f"At that interval, dispatch TOTALDEMAND (AEMO: 'Demand (less loads)', a dispatch quantity that is not "
                 f"operational demand) was {comp.num(v['totaldemand_at_peak']['evidence_id'], 'mw')}")
            if ni:
                comp.observe(ni["evidence_id"])
                s += (f" and NETINTERCHANGE ('Net interconnector flow from the regional reference node') was "
                      f"{comp.num(ni['evidence_id'], 'signed_mw')}")
            summary.append(s + ".")
        summary += self._maximum_lines(res, comp, len(summary))
        hyps: list[Hypothesis] = []
        act = ok(recs, "get_actual_demand")
        peak_t = parse_iso(pk["interval_end_utc"])
        if act:
            av = act[0].view
            hh = iso_utc(half_hour_end_for(peak_t))
            at_peak = next((s for s in act[0].data["series"] if s["interval_end_utc"] == hh), None)
            comp.observe(av["max"]["evidence_id"])
            if at_peak:
                comp.observe(at_peak["evidence_id"])
                summary.append(
                    f"Actual operational demand ({at_peak['revision']} values) was "
                    f"{comp.num(at_peak['evidence_id'], 'mw')} in the half-hour containing the price {key}; the window "
                    f"maximum was {comp.num(av['max']['evidence_id'], 'mw')} (half-hour ending {av['max']['interval_end_local']}).")
                if res.kind == "high_price":
                    if at_peak["operational_demand_mw"] < av["max"]["operational_demand_mw"]:
                        hyps.append(Hypothesis(
                            statement="Demand level alone may not explain the price peak, because operational demand in "
                                      "the peak half-hour was below the window maximum. Supply-side factors (offers, "
                                      "availability or network limits) could have contributed.",
                            supporting_evidence_ids=[at_peak["evidence_id"], av["max"]["evidence_id"]],
                            what_would_test_it="Bid/offer (BIDPEROFFER) and binding-constraint (DISPATCHCONSTRAINT) data for "
                                               "the peak interval, which this project has not analysed."))
                    else:
                        hyps.append(Hypothesis(
                            statement="The price peak coincided with the highest operational demand in the window, so higher "
                                      "demand may have contributed; supply-side factors could also have played a part.",
                            supporting_evidence_ids=[at_peak["evidence_id"], av["max"]["evidence_id"]],
                            what_would_test_it="Offer and constraint data for the peak interval (not analysed here)."))
        gen = ok(recs, "get_generation_change")
        if gen and gen[0].view["largest_changes"]:
            u = gen[0].view["largest_changes"][0]
            comp.observe(u["change_mw"]["evidence_id"])
            summary.append(f"The largest unit-level SCADA change in the 90-minute window starting one hour before the peak was {u['duid']} "
                           f"({comp.num(u['change_mw']['evidence_id'], 'signed_mw')}); this is an observation, not an "
                           "outage diagnosis.")
            hyps.append(Hypothesis(
                statement=f"Changes in unit output around the peak (largest: {u['duid']}) might reflect changed supply "
                          "conditions; SCADA readings alone cannot show why output changed.",
                supporting_evidence_ids=[u["change_mw"]["evidence_id"]],
                what_would_test_it="Unit availability and bid data, plus any AEMO notice about that unit."))
        cmp_ = ok(recs, "compare_forecast_actual")
        fc = None
        if cmp_:
            fc = self._forecast_comparison(cmp_[0], comp)
            summary.append(f"For the half-hours around the peak, the latest AEMO POE50 forecast available before each "
                           f"half-hour had a mean absolute error of {comp.num(cmp_[0].view['mae_mw']['evidence_id'], 'mw')}.")
        wx = ok(recs, "get_weather_context")
        uncertainties = self._standard_uncertainties(res)
        if wx:
            uncertainties.append("Weather values are retrospective model-derived context at one point (NASA POWER), "
                                 "not the forecast information available at the time.")
            for p, sm in wx[0].view["summary"].items():
                comp.observe(sm["max"]["evidence_id"])
                summary.append(f"Retrospective NASA POWER {p} at {wx[0].view['point']} peaked at "
                               f"{comp.num(sm['max']['evidence_id'], 'raw')} in the window (context, not a cause).")
        findings, notices = self._notice_findings(comp, res)
        if notices:
            hyps.append(Hypothesis(
                statement=f"Network events or limit changes that AEMO notified for {res.region} during the window may have "
                          "affected interconnector or local limits. The notices do not state any effect on price.",
                supporting_evidence_ids=[],
                what_would_test_it="Constraint marginal values and interconnector limits for the peak interval."))
        else:
            uncertainties.append(f"No AEMO market notice matching {res.region} and the window was retrieved.")
        defs = self._definition_citations(comp)
        if defs:
            summary.append("Definitions used: " + " ".join(defs))
        status = "answered" if not self.d.required_missing() and all(
            r.status == "ok" for r in recs if r.name in self.d.playbook.required) else "answered_with_caveats"
        return self._base(res, comp, headline, summary, forecast_comparison=fc, possible_explanations=hyps,
                          published_findings=findings, uncertainties=uncertainties, status=status)

    def _maximum_lines(self, res: Resolution, comp: Composer, start: int) -> list[str]:
        """Each demand measure's maximum the question asks for, computed by code over the requested window from the
        controller's own call, as sentences (``demand_max``; I-17: held-out v6 Z04). Recorded for the validator, and
        their provenance for the facts-only fallback (I-21): ``start`` is where the caller puts them in the summary,
        which is only appended to afterwards."""
        measures = demand_max.requested_measures(res)
        if not measures or not res.region:
            return []
        res.demand_max = [demand_max.compute(self.d, res, m) for m in measures]

        def num(eid: str) -> str:
            comp.observe(eid)
            return comp.num(eid, "raw")
        lines: list[str] = []
        for j, b in enumerate(res.demand_max):
            k = len(comp.claims)
            lines.append(demand_max.sentence(b, res.region, num, res.as_of))
            self._result_lines.append({"binding": j, "summary_index": start + j, "text": lines[-1],
                                       "claims": [c.model_copy() for c in comp.claims[k:]]})
        return lines

    def _forecast_comparison(self, rec: ToolCallRecord, comp: Composer) -> ForecastComparison:
        v = rec.view
        la = v["largest_abs_error"]
        comp.observe(v["mae_mw"]["evidence_id"])
        comp.observe(v["mean_error_mw"]["evidence_id"])
        comp.observe(la["error_evidence_id"])
        return ForecastComparison(
            status="ok", run_selector=v["run_selector"] + (f" ({v['min_lead_hours']} h)" if v.get("min_lead_hours") else ""),
            as_of_utc=v.get("as_of_utc"), definition_check=v["definition_check"], n_pairs=v["n_pairs"],
            mae_mw=v["mae_mw"]["value"], mae_evidence_id=v["mae_mw"]["evidence_id"],
            mean_error_mw=v["mean_error_mw"]["value"], mean_error_evidence_id=v["mean_error_mw"]["evidence_id"],
            largest_abs_error=la, note=f"{v['error_definition']}; {v['actuals_are']}.")

    # ------------------------------------------------------------------ forecast_review
    def _synth_forecast_review(self, res: Resolution) -> InvestigationReport:
        comp = Composer(self.reg, res.region)
        recs = self.d.records
        cmps = ok(recs, "compare_forecast_actual")
        runs = ok(recs, "get_forecast_runs")
        uncertainties = self._standard_uncertainties(res)[1:]
        uncertainties.insert(0, "POE10/POE90 are AEMO-published values derived from POE50 by scaling factors "
                                "(SO_OP_3710); they are not calibrated uncertainty intervals.")
        summary: list[str] = self._maximum_lines(res, comp, 0)
        hyps: list[Hypothesis] = []
        fc = None
        if res.as_of and runs:
            rv = runs[0].view
            latest = rv["runs"][-1]
            focus = iso_utc(half_hour_end_for(parse_iso(res.event.peak_interval_end_utc))) if res.event else None
            first_val = next((v for v in latest["values"] if v["target_end_utc"] == focus), latest["values"][0])
            comp.observe(first_val["poe50_evidence_id"])
            summary.append(
                f"As of {local_str(res.as_of, res.region or 'SA1')}, the latest run provably public was issued at "
                f"{local_str(parse_iso(latest['issued_at_utc']), res.region or 'SA1')}; its POE50 for the half-hour ending "
                f"{first_val['target_end_local']} was {comp.num(first_val['poe50_evidence_id'], 'mw')}.")
            summary.append("Runs created after the cutoff, or created before it but not provably public by then, were "
                           "excluded (counts are in the tool trace).")
        if not cmps:
            if res.as_of and runs:
                headline = (f"{res.region}: as-of forecast view built from runs provably public by the cutoff; actuals "
                            "published after the cutoff were not used.")
                return self._base(res, comp, headline, summary, possible_explanations=[], published_findings=[],
                                  uncertainties=uncertainties, status="answered_with_caveats",
                                  forecast_comparison=ForecastComparison(
                                      status="unavailable", definition_check="n/a", as_of_utc=iso_utc(res.as_of),
                                      note="Actual demand for the target half-hours had not been published by the cutoff, "
                                           "so no error can be computed in an as-of view."))
            return self._abstain(res, comp, "No aligned forecast/actual pairs are available for the requested window.")
        main = cmps[0]
        fc = self._forecast_comparison(main, comp)
        v = main.view
        la = v["largest_abs_error"]
        sel_text = {"latest_before_target": "the latest AEMO POE50 run available before each half-hour",
                    "latest_available_as_of": "the latest AEMO POE50 run provably public at the cutoff",
                    "min_lead_hours": "the latest run available at least the stated lead time ahead",
                    "run_id": "the requested run"}[v["run_selector"]]
        n_txt = comp.num(v["n_pairs_evidence_id"], "count")
        err_txt = (f"over {n_txt} half-hour(s) with published actuals, {sel_text} had a mean absolute error of "
                   f"{comp.num(v['mae_mw']['evidence_id'], 'mw')} and a mean error of "
                   f"{comp.num(v['mean_error_mw']['evidence_id'], 'signed_mw')} (positive = forecast above actual)")
        if res.as_of and summary:
            headline = f"{res.region} as-of forecast view: " + summary[0][0].lower() + summary[0][1:]
            summary = summary[1:] + [f"For targets already past at the cutoff, {err_txt}."]
        else:
            headline = f"{res.region} operational demand: {err_txt}."
        summary.append(
            f"The largest miss was for the half-hour ending {la['target_end_local']}: "
            f"{comp.num(la['error_evidence_id'], 'signed_mw')}"
            + (f" ({comp.num(la['error_pct_evidence_id'], 'pct')} of actual)" if la.get("error_pct_evidence_id") else "")
            + ".")
        for extra in cmps[1:]:
            ev_ = extra.view
            comp.observe(ev_["mae_mw"]["evidence_id"])
            summary.append("Using only runs issued at least a day ahead (the day-ahead view), the mean absolute error was "
                           f"{comp.num(ev_['mae_mw']['evidence_id'], 'mw')}.")
        act = ok(recs, "get_actual_demand")
        if act:
            used = act[0].view["revisions_used"]
            uncertainties.append(f"Actuals used: revision policy '{act[0].view['revision_policy']}' "
                                 f"({'updated next-day values' if used.get('updated') else 'initial real-time values'}); "
                                 "in this snapshot no updated value differed from its initial value"
                                 if act[0].view["intervals_where_updated_differs_from_initial"] == 0 else
                                 "Some updated actuals differ from the initial values; see the tool trace.")
        docs = ok(recs, "retrieve_public_evidence")
        if docs and la.get("error_pct") is not None and abs(la["error_pct"]) >= 3:
            hit = next((h for d_ in docs for h in usable_hits(d_) if "temperature" in h["text"].lower()), None)
            if hit:
                c = comp.cite(hit, "Inputs to AEMO's demand forecasting system", ["temperature", "major factors"])
                hyps.append(Hypothesis(
                    statement="The larger misses might relate to inputs that AEMO's demand forecasting system uses, such as "
                              f"weather ({c.citation_id}). Those inputs are not in the files used here, so this cannot be "
                              "tested.",
                    supporting_evidence_ids=[la["error_evidence_id"]],
                    what_would_test_it="AEMO's forecast input data or a separately evaluated model."))
        defs = self._definition_citations(comp)
        if defs:
            summary.append("Definitions used: " + " ".join(defs))
        return self._base(res, comp, headline, summary, forecast_comparison=fc, possible_explanations=hyps,
                          published_findings=[], uncertainties=uncertainties,
                          status="answered" if not self.d.required_missing() else "answered_with_caveats")

    # ------------------------------------------------------------------ source_explanation
    def _synth_source_explanation(self, res: Resolution) -> InvestigationReport:
        comp = Composer(self.reg, res.region)
        docs = ok(self.d.records, "retrieve_public_evidence")
        hits = usable_hits(docs[0]) if docs else []
        if not hits:
            return self._abstain(res, comp, "No retrieved public document answers this question, so no answer is given.")
        if NOTICE_WORDS.search(res.request.question) and not any(h["doc_type"] == "market_notice" for h in hits):
            # the question asks what an AEMO notice said; quoting some other document would not answer it
            return self._abstain(res, comp, "The question asks what an AEMO market notice said, but no market notice "
                                            "matching the region and date is in the local corpus, so it cannot be quoted.")
        terms = [t for t in re.findall(r"[a-z0-9]{4,}", res.request.question.lower())
                 if t not in {"what", "does", "mean", "with", "that", "this", "from", "about", "aemo", "have", "which"}]
        top = hits[0]
        c = comp.cite(top, f"Answer to: {res.request.question[:200]}", terms)
        headline = f"According to the retrieved AEMO text [{c.citation_id}]: “{c.quote}”"
        summary = []
        for h in hits[1:3]:
            c2 = comp.cite(h, "Supporting context", terms)
            summary.append(f"Related AEMO text [{c2.citation_id}]: “{c2.quote}”")
        findings = []
        if res.region and res.window:
            for h in hits:
                if h["doc_type"] == "market_notice" and h.get("event_region") == res.region:
                    c3 = comp.cite(h, "Event-specific AEMO notice", terms)
                    findings.append(PublishedFinding(statement=f"An AEMO market notice [{c3.citation_id}] says: “{c3.quote}”",
                                                     citation_ids=[c3.citation_id], doc_type="market_notice",
                                                     applies_to_event=True))
        unc = ["The answer quotes retrieved public text; it does not add facts from general knowledge.",
               "Retrieval can miss relevant passages; the quoted passages are the best matches in the local corpus."]
        if flagged_hits(self.d.records):
            unc.append("A retrieved passage contained instruction-like text; it was treated as untrusted data and not used.")
        return self._base(res, comp, headline, summary, published_findings=findings, uncertainties=unc,
                          status="answered")

    # ------------------------------------------------------------------ abstention
    def _abstain(self, res: Resolution, comp: Composer, why: str) -> InvestigationReport:
        return self._base(res, comp, f"Abstained: {why}", [], uncertainties=[why], status="abstained")
