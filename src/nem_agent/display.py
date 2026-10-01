"""Plain display text (issue I-4), applied after the complete answer has been validated.

The model works in the tools' terms (claims carry evidence IDs; tool outputs name tools and fields), and the controller
writes its diagnostics in the same terms, so answers showed "[ev0436]", "(compare_forecast_actual)",
"peak_half_hour_end_utc" and "ev0878 (project_analysis_threshold) is not a time-stamped observation". Here, outside
quotations only, evidence-ID markers are removed, tool and internal field names become readable words, and controller
notes are put in plain language. Disclosures (a tool call unavailable, refused, failed or blocked; a search not
performed; a stopped run; part of the model's answer left out) are kept in plain words; the one diagnostic that only
reclassifies a value still shown as a claim is not shown. No rewrite adds a number. The structured fields (claims,
observations, citations, search scope, source manifest, validation) keep every ID and provenance detail, and each
changed line keeps its original in ``validation.display_rewrites``.
"""

from __future__ import annotations

import re
from typing import Any

from .report import InvestigationReport
from .validation import QUOTED_RE

TOOL_NAMES = {
    "find_market_events": "the market-event search", "get_price_timeline": "the price timeline",
    "get_forecast_runs": "the forecast-run data", "get_actual_demand": "the actual-demand data",
    "compare_forecast_actual": "the forecast-versus-actual comparison", "get_generation_change": "the generation-change data",
    "get_weather_context": "the weather data", "retrieve_public_evidence": "the document search",
    "get_regional_prices": "the regional-price lookup",
}
# internal field and context names (tool arguments and outputs, controller context), never AEMO's own identifiers
FIELD_NAMES = {
    "evidence_id": "evidence reference", "evidence_ids": "evidence references", "chunk_id": "passage reference",
    "chunk_ids": "passage references", "observation_evidence_ids": "observations", "numeric_claims": "numeric claims",
    "published_findings": "published findings", "search_scope": "search record", "clock_times": "clock times",
    "project_analysis_threshold": "analysis threshold", "as_of": "as-of time", "as_of_utc": "as-of time (UTC)",
    "start_utc": "start (UTC)", "end_utc": "end (UTC)", "event_start_utc": "event window start (UTC)",
    "event_end_utc": "event window end (UTC)", "target_start_utc": "target start (UTC)", "target_end_utc": "target end (UTC)",
    "target_end_local": "target end (local time)", "interval_end_utc": "interval end (UTC)",
    "interval_end_local": "interval end (local time)", "published_at_utc": "publication time (UTC)",
    "available_at_utc": "availability time (UTC)", "peak_half_hour_end_utc": "peak half-hour end (UTC)",
    "peak_half_hour_end_local": "peak half-hour end (local time)", "event_peak_interval_end_utc": "peak interval end (UTC)",
    "event_peak_interval_end_local": "peak interval end (local time)", "forecast_targets_utc": "forecast target period (UTC)",
    "forecast_targets_local": "forecast target period (local time)", "run_id": "forecast run", "run_selector": "run selection",
    "latest_available": "latest available", "latest_before_target": "latest before the target",
    "latest_available_as_of": "latest available at the as-of time", "revision_policy": "revision policy",
    "operational_demand_mw": "operational demand (MW)", "threshold_aud_per_mwh": "threshold ($/MWh)",
    "max_results": "result limit", "top_k": "result count", "doc_types": "document types",
    "issued_at_utc": "issue time (UTC)", "error_pct": "percentage error", "run_issued_at_utc": "run issue time (UTC)",
    "run_available_at_utc": "run availability time (UTC)", "publication_date": "publication date",
    "lead_hours": "lead time (hours)", "poe10_mw": "POE10 (MW)", "poe50_mw": "POE50 (MW)", "poe90_mw": "POE90 (MW)",
    "totaldemand_at_peak": "TOTALDEMAND at the peak", "totaldemand_at_minimum": "TOTALDEMAND at the minimum",
    "totaldemand_around_peak": "TOTALDEMAND around the peak",
    "totaldemand_around_minimum": "TOTALDEMAND around the minimum", "netinterchange_at_peak": "net interchange at the peak",
    "largest_changes": "largest changes", "market_notice": "market notice", "citation_id": "citation reference",
    "missing_evidence": "missing evidence", "possible_explanations": "possible explanations",
}
_EV_LIST = r"ev\d{4}(?:\s*(?:,|;|and|&)?\s*ev\d{4})*(?:,?\s*etc\.?)?"
# a label naming the references: "evidence_id:", "threshold evidence:", "supporting evidence", "threshold and count:"
_EV_LABELS = r"(?:[A-Za-z_]\w*\s+){0,2}evidence(?:[ _]ids?)?\s*:?\s*|see\s*:?\s*|(?:[A-Za-z_]\w*\s+){0,3}[A-Za-z_]\w*\s*:\s*"
_EV_LABEL = f"(?:{_EV_LABELS})?"
# a reference item: IDs, after one of those labels or a lower-case label of up to three words ("threshold ev0878");
# a bracket of nothing but such items is a reference marker (I-4b, F04: "(ev0876; threshold ev0878)"), removed whole
_EV_ITEM = rf"(?:{_EV_LABELS}|(?-i:(?:[a-z][a-z'’-]*\s+){{1,3}}))?{_EV_LIST}"
_EV_GROUP_RE = re.compile(rf"\s*[\[(]\s*{_EV_ITEM}(?:\s*(?:[;,]|\band\b)\s*{_EV_ITEM})*\s*[\])]", re.I)
_EV_PART_RE = (re.compile(r"\s*[;,]\s*" + _EV_LABEL + _EV_LIST + r"(?=\s*[;,)\]])", re.I),  # "(…; evidence_id: ev0626)"
               re.compile(r"(?<=[(\[])\s*" + _EV_LABEL + _EV_LIST + r"\s*[;,]\s*", re.I),  # "(evidence_id: ev0625; …"
               re.compile(r"(?:(?<=\d)|(?<=MW)|(?<=Wh)|(?<=%))\s*[;,]?\s*" + _EV_LIST + r"(?=\s*[;,.)\]]|\s*$)"),  # "−82.59 MW ev0438)"
               re.compile(r"\s*\(see [^()]*?" + _EV_LIST + r"\)", re.I))  # "(see SCADA change ev0940)"
# IDs right after a label ("the net interchange value ev0438.", "YENDONWF ev0984,"): the IDs go and the label stays,
# unless the word before them is one that makes them a noun ("compare those values to ev0538"; left to _EV_RE)
_EV_AFTER_LABEL_RE = re.compile(rf"\b([\w'’-]+)\s+{_EV_LIST}(?=\s*(?:[;,.)\]]|$)|\s+(?:and|or|but)\b)")
_NOUN_BEFORE = {"to", "than", "with", "between", "in", "into", "including", "include", "includes", "of", "for", "from",
                "at", "by", "on", "as", "and", "or", "nor", "versus", "vs", "against", "like", "via", "per", "the", "a",
                "an", "is", "are", "was", "were", "be", "been", "see", "compare", "compared", "relative", "matching"}
_EV_WORD_RE = re.compile(r"\bevidence(?:[ _](?:ids?|references?))?\s*:?\s*(?=ev\d{4})", re.I)  # "with evidence ev0948"
_EV_RE = re.compile(r"\b" + _EV_LIST)  # a reference used as a noun: "compare those values to ev0538"
_TOOL_RE = re.compile(r"\b(?:([Tt]he) )?(" + "|".join(TOOL_NAMES) + r")(\s+search_scope)?\b")
# a tool's name alone in quote marks is the model naming it (under three words, so not a checked quotation, and no
# source document contains one); every other quotation is left exactly as written
_QUOTED_TOOL_RE = re.compile(r"[“\"]\s*(" + "|".join(TOOL_NAMES) + r")\s*[”\"]")
_FIELD_RE = re.compile(r"\b(" + "|".join(sorted(FIELD_NAMES, key=len, reverse=True)) + r")\b")
# the system's own workflow in plain words (I-4c, W19: "as shown in the notice timings returned to the controller"). Only
# phrases with a workflow verb or noun: "generation output", "SCADA traces", "the forecast model" or a bare "the
# controller" are left alone, as is quoted text.
_DETERMINER = r"(?:\b(the|these|those|this|any|no|its|their)\s+)?"
_WORKFLOW: tuple[tuple[re.Pattern[str], Any], ...] = (
    (re.compile(r"\b(?:returned|given|passed|sent|provided|supplied) to the controller\b", re.I),
     "retrieved in this investigation"),
    (re.compile(r"\b(computed|calculated|derived|produced|returned|provided|supplied|given|written|shown) by the "
                r"controller\b", re.I), r"\1 in this investigation"),
    (re.compile(r"\bfrom the controller\b", re.I), "from this investigation"),
    (re.compile(r"\b(?:returned|provided|supplied|given|reported)\s+by\s+the\s+tools?\b", re.I),
     "retrieved in this investigation"),
    (re.compile(_DETERMINER + r"(?:(?:returned|current|available)\s+)?tool[- ](?:outputs?|results?|responses?)\b", re.I),
     lambda m: f"{m.group(1) or 'the'} retrieved data"),
    (re.compile(r"\btool values\b", re.I), "retrieved values"),
    (re.compile(r"\b([Tt])he tools?(?=\s+(?:reported|reports|returned|returns|showed|shows|indicated|indicates|found|"
                r"gave|gives)\b)"), r"\1he retrieved data"),
    (re.compile(r"\bin the (?:retrieved|returned) set\b", re.I), "among the retrieved documents"),
    (re.compile(r"\bthe (?:retrieved|returned) set\b", re.I), "the retrieved documents"),
    (re.compile(r"\b([Tt])he model judged the question\b"), r"\1he question was judged"),  # the routing refusal
    (re.compile(r"\b([Tt])he routing model returned invalid output\b"), r"\1he question could not be interpreted"),
)
_COMPUTED_RE = re.compile(r"\b([Cc])ontroller[- ]computed\b")
_FALLBACK_HEADLINE_RE = re.compile(r"^(Validated facts only: the generated narrative failed independent validation) "
                                   r"\([A-Z_, ]+\)")
# a controller diagnostic about the answer's own structure (the value is still shown, as a claim): kept in the record
_UNSHOWN_NOTE_RE = re.compile(r"^ev\d{4} \([a-z0-9_]+\) is not a time-stamped observation; listed only as a claim$")
_DROPPED = (  # the controller left part of the model's answer out: said in plain words
    (re.compile(r"^model referenced unknown or non-numeric evidence id \S+$"),
     "An observation the answer listed is not shown: its evidence is not among this investigation's records."),
    (re.compile(r"^model listed a published finding for unknown or unretrieved citation \S+$"),
     "A published finding the answer listed is not shown: its source passage was not retrieved in this investigation."),
    (re.compile(r"^model referenced forecast MAE evidence \S+, which no compare_forecast_actual call returned$"),
     "The forecast-versus-actual summary is not shown: the answer referred to a comparison that was not returned."),
)
_TOOL_NOTE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*): (unavailable|refused|error|blocked) — (.*)$", re.S)
_BLOCKED = (  # the dispatcher's reasons for not running a call
    (re.compile(r"'[^']*' already called"), "its call limit had been reached"),
    (re.compile(r"optional diagnostic budget exhausted"), "the limit on optional checks had been reached"),
    (re.compile(r"'[^']*' is not in the \S+ playbook"), "it is not used for this kind of question"),
    (re.compile(r"invalid arguments|arguments are not valid JSON|arguments must be"), "the request was invalid"),
    (re.compile(r"as_of_utc \S+ is later than the request cutoff"), "it asked for data later than the question's as-of time"),
)
_CALL_AGAIN_RE = re.compile(r";\s*call again with [^.]*$")  # an instruction written for the model


def _tool(m: re.Match[str], first: bool) -> str:
    """A tool's readable name, keeping the text's own article and capitalising at the start of a sentence."""
    article, name, scope = m.groups()
    words = TOOL_NAMES[name] + (" record" if scope else "")
    if article:
        words = article + words[3:]
    elif (first and m.start() == 0) or re.search(r"[.!?]\s+$", m.string[:m.start()]):
        words = words[0].upper() + words[1:]
    return words


def _plain(segment: str, first: bool) -> str:
    s, last = segment, None
    while s != last:
        last = s
        s = _EV_GROUP_RE.sub("", s)
        for part in _EV_PART_RE:
            s = part.sub("", s)
        s = _EV_AFTER_LABEL_RE.sub(lambda m: m.group(0) if m.group(1).lower() in _NOUN_BEFORE else m.group(1), s)
    if first and not segment[:1].isspace():
        s = s.lstrip()
    s = _EV_RE.sub(lambda m: "the listed observation" + ("s" if len(re.findall(r"ev\d{4}", m.group(0))) > 1 else ""),
                   _EV_WORD_RE.sub("", s))
    s = _TOOL_RE.sub(lambda m: _tool(m, first), s)
    s = _FIELD_RE.sub(lambda m: FIELD_NAMES[m.group(1)], s)
    for pattern, plain in _WORKFLOW:
        s = pattern.sub(plain, s)
    if first and s[:1].islower() and s[:1] != segment[:1]:  # a rewrite at the start of the text
        s = s[0].upper() + s[1:]
    return _COMPUTED_RE.sub(lambda m: "Computed" if m.group(1) == "C" else "computed", s)


def plain_text(text: str) -> str:
    """``text`` with internal references made readable, quotations untouched."""
    text = _QUOTED_TOOL_RE.sub(r"\1", text)
    out: list[str] = []
    last = 0
    for m in QUOTED_RE.finditer(text):
        out += [_plain(text[last:m.start()], not out), m.group(0)]
        last = m.end()
    return "".join([*out, _plain(text[last:], not out)])


def plain_note(text: str) -> str | None:
    """A caveat in plain language, or None for a diagnostic that is not shown."""
    if _UNSHOWN_NOTE_RE.match(text):
        return None
    for r, plain in _DROPPED:
        if r.match(text):
            return plain
    m = _TOOL_NOTE_RE.match(text)
    if m:
        name, status, reason = m.groups()
        if name not in TOOL_NAMES:  # the model asked for a tool that does not exist; its name stays in the record
            return "A request for an action that is not one of the investigation's tools was blocked; nothing was run."
        if status == "unavailable":
            return f"{TOOL_NAMES[name][0].upper()}{TOOL_NAMES[name][1:]} was unavailable: {plain_text(reason)}"
        why = next((plain for r, plain in _BLOCKED if r.match(reason)), None) if status == "blocked" else None
        if why:
            return f"A request to {TOOL_NAMES[name]} was blocked: {why}, so it was not run."
        return f"A request to {TOOL_NAMES[name]} {'failed' if status == 'error' else 'was ' + status}: {plain_text(reason)}"
    if text.startswith("Tool loop stopped at the model call cap"):
        return "The investigation stopped early, at its limit on model calls."
    if text == "Model output did not match the report schema.":
        return "The model's answer was not in the expected form."
    return plain_text(_CALL_AGAIN_RE.sub(".", text))


# an amount written with a currency sign but no rate ("$845.0", I-3e, W19); already complete: "$845.0/MWh", "$845 per
# MWh", "$300.0 ($/MWh)", "$1.5 million"
_AMOUNT_RE = re.compile(r"(?<![\w.])([-+−]?)((?:A|AU)?\$)\s?([-+−]?)(\d[\d,]*(?:\.\d+)?)(?![\d,]*\.?\d)"
                        r"(?!\s*\(?\s*(?:/|per\b|(?:A|AU)?\$/|\$|[kKmMbB]n?\b|thousand\b|million\b|billion\b|MWh\b))")
_RATE_UNIT_RE = re.compile(r"\$/([A-Za-z]+)")


def complete_rates(text: str, claims: list[tuple[float, float, str | None]]) -> str:
    """``text`` with each currency amount that has no rate completed from its evidence's own unit ("$845.0" becomes
    "$845.0/MWh"), outside quotations. ``claims`` are the validated answer's (value, tolerance, evidence unit): every
    claim matching the amount must carry one and the same "$/…" unit, or the amount is left as written. No unit is
    taken from the dollar sign, the question or another value."""
    def fix(m: re.Match[str]) -> str:
        before, _, after, number = m.groups()
        value = float(number.replace(",", "")) * (-1 if {before, after} & {"-", "−"} else 1)
        units = {u for v, tol, u in claims if abs(value - v) <= tol + 1e-9 or abs(abs(value) - abs(v)) <= tol + 1e-9}
        rate = _RATE_UNIT_RE.fullmatch(next(iter(units)) or "") if len(units) == 1 else None
        return f"{m.group(0)}/{rate.group(1)}" if rate else m.group(0)

    out: list[str] = []
    last = 0
    for q in QUOTED_RE.finditer(text):
        out += [_AMOUNT_RE.sub(fix, text[last:q.start()]), q.group(0)]
        last = q.end()
    return "".join([*out, _AMOUNT_RE.sub(fix, text[last:])])


_LABEL_RE = re.compile(r"c(\d+)")
_ID_CHARS = r"\w#.:\-"


def citation_labels(report: InvestigationReport) -> tuple[dict[str, str], dict[str, str]]:
    """Readable citation labels (I-3g, F01/F03/F04: "[aemo_so_op_3710#p7c12]"), from the answer's own citations list:
    (citation ID -> label for the citations list, and every ID the text may use -> label). Only a citation whose ID is
    a raw source ID (its passage ID, its document ID, or a passage ID with a suffix) is relabelled, with the next unused
    cN in list order, the same ID always the same label; labels such as c1 or the Replay controller's s01 are kept. A
    passage ID used in the text maps to its citation's label only when exactly one label cites that passage. Nothing
    else is mapped: an unknown ID is left as written."""
    numbers = [int(m.group(1)) for c in report.citations if (m := _LABEL_RE.fullmatch(c.citation_id))]
    following = max(numbers, default=0) + 1
    labels: dict[str, str] = {}
    for c in report.citations:
        raw = c.citation_id in (c.chunk_id, c.doc_id) or "#" in c.citation_id
        if raw and not _LABEL_RE.fullmatch(c.citation_id) and c.citation_id not in labels:
            labels[c.citation_id] = f"c{following}"
            following += 1
    by_passage: dict[str, set[str]] = {}
    for c in report.citations:
        by_passage.setdefault(c.chunk_id, set()).add(labels.get(c.citation_id, c.citation_id))
    in_text = dict(labels)
    ids = {c.citation_id for c in report.citations}
    for chunk, found in by_passage.items():
        if chunk not in ids and len(found) == 1:
            in_text[chunk] = next(iter(found))
    return labels, in_text


def relabel(text: str, in_text: dict[str, str]) -> str:
    """``text`` with each mapped citation ID shown as "[cN]", outside quotations; a label repeated side by side once."""
    if not in_text:
        return text
    keys = "|".join(re.escape(k) for k in sorted(in_text, key=len, reverse=True))
    wrapped = re.compile(rf"[\[(]\s*({keys})\s*[\])]")
    bare = re.compile(rf"(?<![{_ID_CHARS}\[])({keys})(?![{_ID_CHARS}\]])")

    def one(segment: str) -> str:
        segment = wrapped.sub(lambda m: f"[{in_text[m.group(1)]}]", segment)
        segment = bare.sub(lambda m: f"[{in_text[m.group(1)]}]", segment)
        return re.sub(r"\[(c\d+)\](?:\s*\[\1\])+", r"[\1]", segment)

    out: list[str] = []
    last = 0
    for q in QUOTED_RE.finditer(text):
        out += [one(text[last:q.start()]), q.group(0)]
        last = q.end()
    return "".join([*out, one(text[last:])])


def plain_display(report: InvestigationReport, registry: Any = None) -> tuple[InvestigationReport, list[dict[str, Any]]]:
    """The report with plain display text, and the originals of every changed or unshown line. With the evidence
    ``registry`` of an answer that passed validation, currency amounts are completed with their evidence's rate unit."""
    changed: list[dict[str, Any]] = []
    labels, in_text = citation_labels(report)
    claims: list[tuple[float, float, str | None]] = []
    if registry is not None and report.validation.get("final_passed"):
        for c in report.numeric_claims:
            ev = registry.get(c.evidence_id)
            claims.append((float(c.value), c.rounding, ev.unit if ev is not None else None))

    def text(where: str, value: str) -> str:
        new = plain_text(value)
        if claims:
            new = complete_rates(new, claims)
        new = relabel(new, in_text)
        if new != value:
            changed.append({"where": where, "original": value})
        return new

    def notes(field: str, values: list[str]) -> list[str]:
        kept: list[str] = []
        for i, v in enumerate(values):
            new = plain_note(v)
            if new is not None:
                new = relabel(new, in_text)
            if new in kept:  # two notes that now read the same are shown once, as the controller does
                new = None
            if new != v:
                changed.append({"where": f"{field}[{i}]", "original": v, **({"shown": False} if new is None else {})})
            if new is not None:
                kept.append(new)
        return kept

    headline = _FALLBACK_HEADLINE_RE.sub(r"\1", report.headline)
    if headline != report.headline:
        changed.append({"where": "headline", "original": report.headline})
        headline = relabel(plain_text(headline), in_text)
    else:
        headline = text("headline", headline)
    update: dict[str, Any] = {
        "headline": headline,
        "summary": [text(f"summary[{i}]", s) for i, s in enumerate(report.summary)],
        "possible_explanations": [h.model_copy(update={
            "statement": text(f"possible_explanations[{i}]", h.statement),
            "what_would_test_it": text(f"possible_explanations[{i}].what_would_test_it", h.what_would_test_it)})
            for i, h in enumerate(report.possible_explanations)],
        "published_findings": [f.model_copy(update={
            "statement": text(f"published_findings[{i}]", f.statement),
            "citation_ids": list(dict.fromkeys(labels.get(c, c) for c in f.citation_ids))})
            for i, f in enumerate(report.published_findings)],
        "uncertainties": notes("uncertainties", report.uncertainties),
        "missing_evidence": notes("missing_evidence", report.missing_evidence),
    }
    ruled_out = set(report.validation.get("ruled_out_explanations") or [])
    if ruled_out and not report.validation.get("fallback_applied"):  # validated exclusions shown apart (I-7c)
        kept: list[Any] = []
        moved: list[Any] = []
        recorded = {c["where"]: c for c in changed}
        for i, h in enumerate(update["possible_explanations"]):
            if i not in ruled_out:
                kept.append(h)
                continue
            where = f"possible_explanations[{i}]"
            entry = recorded.get(where) or {"where": where, "original": report.possible_explanations[i].statement}
            entry["moved_to"] = f"ruled_out_explanations[{len(report.ruled_out_explanations) + len(moved)}]"
            if where not in recorded:
                changed.append(entry)
            moved.append(h)
        update["possible_explanations"] = kept
        update["ruled_out_explanations"] = [*report.ruled_out_explanations, *moved]
    if labels:  # the citations list under the same labels; the mapping is kept with the validation record
        update["citations"] = [c.model_copy(update={"citation_id": labels.get(c.citation_id, c.citation_id)})
                               for c in report.citations]
        update["validation"] = {**report.validation, "citation_labels": labels}
    update["published_findings"] = distinct_findings(report.model_copy(update={"citations": update.get(
        "citations", report.citations)}), update["published_findings"], changed)
    return (report.model_copy(update=update), changed) if changed or labels else (report, [])


def distinct_findings(report: InvestigationReport, findings: list[Any], changed: list[dict[str, Any]]) -> list[Any]:
    """Findings that read the same, told apart (I-3f, W19: five notices shown as two identical sentences).

    A finding quoting the same words as an earlier one but citing a different passage is a separate finding: it is
    kept, with a note naming the earlier one. Findings are never merged because their wording matches. Only a finding
    citing the same passage(s) with the same quote as an earlier one is that finding repeated: it is shown once, with
    all its citation markers and IDs. Each changed or merged line's original goes to ``changed``."""
    chunk_of = {c.citation_id: c.chunk_id for c in report.citations}
    recorded = {c["where"]: c for c in changed}

    def note(i: int, **extra: Any) -> None:
        entry = recorded.get(f"published_findings[{i}]")
        if entry is None:
            entry = {"where": f"published_findings[{i}]", "original": report.published_findings[i].statement}
            changed.append(entry)
            recorded[entry["where"]] = entry
        entry.update(extra)

    out: list[Any] = []
    at: dict[tuple[frozenset[str], str], tuple[int, int]] = {}  # (passages, quote) -> (index in out, original index)
    first: dict[str, tuple[frozenset[str], str]] = {}  # quote -> (passages, citation ID) of its first finding
    for i, f in enumerate(findings):
        q = QUOTED_RE.search(f.statement)
        if q is None or not f.citation_ids:
            out.append(f)
            continue
        quote, passages = q.group(0), frozenset(chunk_of.get(c, c) for c in f.citation_ids)
        if (passages, quote) in at:  # the same finding again: shown once, with every citation
            j, oi = at[(passages, quote)]
            kept = out[j]
            extra = [c for c in f.citation_ids if c not in kept.citation_ids]
            last = f"[{kept.citation_ids[-1]}]"
            out[j] = kept.model_copy(update={
                "statement": kept.statement.replace(last, last + "".join(f" [{c}]" for c in extra), 1),
                "citation_ids": [*kept.citation_ids, *extra], "applies_to_event": kept.applies_to_event or f.applies_to_event})
            note(oi)
            note(i, shown=False, shown_with=kept.citation_ids[0])
            continue
        if quote in first and first[quote][0] != passages:  # a separate finding with the same wording
            noun = "notice" if f.doc_type == "market_notice" else "document"
            f = f.model_copy(update={"statement": f"{f.statement} (A separate {noun}, with the same wording as "
                                                  f"[{first[quote][1]}].)"})
            note(i)
        first.setdefault(quote, (passages, f.citation_ids[0]))
        at[(passages, quote)] = (len(out), i)
        out.append(f)
    return out
