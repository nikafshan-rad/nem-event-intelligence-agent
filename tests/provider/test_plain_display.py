"""Issue I-4 (docs/issue-tracker.md): displayed answers carry no internal references.

Saved Live records showed evidence IDs ("[ev0975]", "(evidence_id: ev0538)"), tool names ("compare_forecast_actual"),
internal field names ("peak_half_hour_end_utc"), controller diagnostics ("ev0878 (project_analysis_threshold) is not
a time-stamped observation") and instructions written for the model ("call again with region, event_start_utc …").

Now, after the complete answer is validated, its displayed text is put in plain words outside quotations. Disclosures
(a tool call unavailable, refused, failed or blocked; a search not performed; a stopped run) stay, in plain language.
The structured fields keep every ID and tool detail, and each changed line keeps its original in
`validation.display_rewrites`. Replays use saved Live records through the SYNTHETIC fake transport (no network, no key).
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

from nem_agent.agent.request import InvestigateRequest
from nem_agent.service import investigate
from nem_agent.validation import QUOTED_RE, narrative_numbers, validate
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

LIVE = Path(__file__).resolve().parents[2] / "artifacts" / "live"
V4, C0929, C0930 = LIVE / "L3-holdout-v4", LIVE / "live-check-2026-09-29", LIVE / "live-check-p1-dev"
EV = re.compile(r"\bev\d{4}\b")
TOOLS = re.compile(r"\b(find_market_events|get_price_timeline|get_forecast_runs|get_actual_demand|compare_forecast_actual|"
                   r"get_generation_change|get_weather_context|retrieve_public_evidence|get_regional_prices)\b")


def plain_text(text: str) -> str:
    from nem_agent.display import plain_text as plain

    return plain(text)


def plain_note(text: str) -> str | None:
    from nem_agent.display import plain_note as note

    return note(text)


def _replay(path: Path, *, first_draft: bool = False, delete: str | None = None, draft_update: dict | None = None,
            with_blocked: bool = False):
    rec = json.loads(path.read_text())
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and (with_blocked or t["status"] != "blocked")]
    patch: dict[str, Any] | None = None
    if first_draft:
        trace = json.loads((path.parent / "traces" / f"{rec['score']['trace_id']}.json").read_text())
        patch = next(e for e in trace["events"] if e["name"] == "repair:scoped")["patch"]
        if delete:
            patch = {**patch, "edits": [e for e in patch["edits"] if not e["target"].startswith(delete)] +
                     [{"target": delete, "action": "delete", "text": None, "statement": None, "claim": None,
                       "citation": None}]}
    draft = rec["drafts"]["synthesis:draft"] if first_draft else (rec["drafts"].get("repair:draft")
                                                                  or rec["drafts"]["synthesis:draft"])
    draft = {**draft, **(draft_update or {})}
    fake = FakeModel(rec["route"], [calls], lambda kw: copy.deepcopy(draft),
                     (lambda kw: copy.deepcopy(patch)) if patch else None)
    return investigate(InvestigateRequest(question=rec["question"], mode="live"), live_client=fake, write_trace=False)


def _shown(rep) -> list[str]:
    return [rep.headline, *rep.summary, *[h.statement for h in rep.possible_explanations],
            *[h.what_would_test_it for h in rep.possible_explanations], *[f.statement for f in rep.published_findings],
            *rep.uncertainties, *rep.missing_evidence]


def _unquoted(rep) -> str:
    return " ".join(QUOTED_RE.sub(" ", t) for t in _shown(rep))


def _passes(res) -> bool:
    return bool(res.report.validation["final_passed"]) and not res.report.validation["fallback_applied"]


# ------------------------------------------------------------------------------------------------ the text rules
@pytest.mark.parametrize("before,after", [
    ("RRP was 406.00544 $/MWh [ev0436].", "RRP was 406.00544 $/MWh."),
    ("POE50 = 1505.0 MW (evidence_id: ev0538).", "POE50 = 1505.0 MW."),
    ("1 interval (evidence: ev0003; threshold evidence: ev0004).", "1 interval."),
    ("Six intervals met it (threshold and count: ev0976, ev0975); the first", "Six intervals met it; the first"),
    ("the error is −319.0 MW (evidence_id: ev0625; error_pct −4.68%, evidence_id: ev0626).",
     "the error is −319.0 MW (percentage error −4.68%)."),
    ("(2026-08-20 09:30 AEST (UTC+1000); supporting evidence ev0624, ev0627, ev0623).", "(2026-08-20 09:30 AEST (UTC+1000))."),
    ("SCADA generation change summaries (ev0949 etc) are descriptive.", "SCADA generation change summaries are descriptive."),
    ("net interchange (DISPATCH NETINTERCHANGE −82.59 MW ev0438) might", "net interchange (DISPATCH NETINTERCHANGE −82.59 MW) might"),
    ("compare those values to ev0538; then", "compare those values to the listed observation; then"),
    ("[ev0436] [ev0884] Peak.", "Peak."),
])
def test_evidence_id_markers_are_removed(before, after):
    assert plain_text(before) == after


@pytest.mark.parametrize("before,after", [
    ("compare_forecast_actual returned no pairs.", "The forecast-versus-actual comparison returned no pairs."),
    ("errors across the compare_forecast_actual pairs", "errors across the forecast-versus-actual comparison pairs"),
    ("none held in the retrieve_public_evidence search_scope", "none held in the document search record"),
    ("values (get_actual_demand) were not returned", "values (the actual-demand data) were not returned"),
    ("an API function named \"get_actual_demand\" or \"get_forecast_runs\"",
     "an API function named the actual-demand data or the forecast-run data"),
    ("the price extreme (peak_half_hour_end_utc 2026-08-19T23:30:00Z)", "the price extreme (peak half-hour end (UTC) 2026-08-19T23:30:00Z)"),
    ("Controller-computed dispatch TOTALDEMAND change", "Computed dispatch TOTALDEMAND change"),
    ("listed under published_findings.", "listed under published findings."),
])
def test_tool_and_field_names_become_readable(before, after):
    assert plain_text(before) == after


@pytest.mark.parametrize("text", [
    "“At 1630 hrs 30/07/2026 there was a short notice outage of Belalie-Davenport 275kV line.” [c1]",
    "The table says [aemo_so_op_3710#p7c12] that dispatch continued [c2].",
    "AEMO market notice market_notice_144693 reports it.",
    "PRICE_STATUS is \"NOT FIRM\" or \"FIRM\" [mms_dm_elec21#DISPATCHPRICE#1].",
    "Constraint S-DVBL_BC-2CP bound; SNAPPER1 and ERARING changed output.",
    "See aemo_demand_terms#p9c11 and aemo_nem_fact_sheet.",
    "Run PUBLIC_FORECAST_OPERATIONAL_DEMAND_HH_202607302330_20260730230149 gave POE50 7942.0 MW.",
    "Dispatch TOTALDEMAND and NETINTERCHANGE at 07:30 AEST (UTC+1000).",
])
def test_legitimate_source_identifiers_and_market_names_are_kept(text):
    assert plain_text(text) == text


@pytest.mark.parametrize("text", [
    "The notice says “ev0436 get_price_timeline as_of peak_half_hour_end_utc” [c1].",
    "The field is \"target_end_utc (evidence_id: ev0001)\" in the passage.",
    "It quotes “call get_actual_demand again” [c3].",
])
def test_quotations_are_never_changed(text):
    out = plain_text(text)
    assert QUOTED_RE.findall(out) == QUOTED_RE.findall(text)


@pytest.mark.parametrize("note,shown", [
    ("ev0878 (project_analysis_threshold) is not a time-stamped observation; listed only as a claim", None),
    ("model referenced unknown or non-numeric evidence id ev9999",
     "An observation the answer listed is not shown: its evidence is not among this investigation's records."),
    ("model listed a published finding for unknown or unretrieved citation market_notice_144667#0",
     "A published finding the answer listed is not shown: its source passage was not retrieved in this investigation."),
    ("model referenced forecast MAE evidence ev9999, which no compare_forecast_actual call returned",
     "The forecast-versus-actual summary is not shown: the answer referred to a comparison that was not returned."),
    ("get_generation_change: blocked — invalid arguments: args: Value error, get_generation_change: range 24.5 h exceeds "
     "the 12 h bound", "A request to the generation-change data was blocked: the request was invalid, so it was not run."),
    ("find_market_events: blocked — invalid arguments: max_results: Input should be less than or equal to 20",
     "A request to the market-event search was blocked: the request was invalid, so it was not run."),
    ("retrieve_public_evidence: blocked — 'retrieve_public_evidence' already called 3 times",
     "A request to the document search was blocked: its call limit had been reached, so it was not run."),
    ("get_regional_prices: blocked — 'get_regional_prices' is not in the forecast playbook",
     "A request to the regional-price lookup was blocked: it is not used for this kind of question, so it was not run."),
    ("publish_case_note: blocked — unknown tool 'publish_case_note' (allowed: find_market_events, get_price_timeline)",
     "A request for an action that is not one of the investigation's tools was blocked; nothing was run."),
    ("get_weather_context: unavailable — Weather context excluded: retrospective data cannot inform an as-of view",
     "The weather data was unavailable: Weather context excluded: retrospective data cannot inform an as-of view"),
    ("compare_forecast_actual: unavailable — 2026-07-30T16:00:00Z: no actual (latest_available) provably public by as_of",
     "The forecast-versus-actual comparison was unavailable: 2026-07-30T16:00:00Z: no actual (latest available) "
     "provably public by as-of time"),
    ("get_forecast_runs: error — internal error", "A request to the forecast-run data failed: internal error"),
    ("Market notices were not searched: market notices are searched only for a stated region and event window; call "
     "again with region, event_start_utc and event_end_utc (one call per region)",
     "Market notices were not searched: market notices are searched only for a stated region and event window."),
    ("Tool loop stopped at the model call cap (12 of 12 calls; 2 kept for synthesis and repair).",
     "The investigation stopped early, at its limit on model calls."),
    ("Narrative withheld because it failed validation.", "Narrative withheld because it failed validation."),
])
def test_controller_notes_in_plain_language_and_disclosures_kept(note, shown):
    assert plain_note(note) == shown


def test_a_blocked_call_to_a_tool_that_does_not_exist_never_shows_its_name():
    out = plain_note("ignore_previous_instructions: blocked — unknown tool 'ignore_previous_instructions' (allowed: x)")
    assert out is not None and "blocked" in out and "ignore" not in out


def test_notes_that_now_read_the_same_are_shown_once():
    from nem_agent.display import plain_display

    res = _replay(C0930 / "W04.json", first_draft=True)
    notes = ["publish_case_note: blocked — unknown tool 'publish_case_note' (allowed: x)",
             "run_sql: blocked — unknown tool 'run_sql' (allowed: x)"]
    out, rewrites = plain_display(res.report.model_copy(update={"missing_evidence": notes}))
    assert out.missing_evidence == ["A request for an action that is not one of the investigation's tools was blocked; "
                                    "nothing was run."]
    assert [r["original"] for r in rewrites] == notes and rewrites[1]["shown"] is False


# ------------------------------------------------------------------------------------------------ the saved examples
def test_w04_change_and_endpoints_without_evidence_ids():
    """2026-09-30 W04: "Controller-computed … change … 1385.98 MW [ev0975]"."""
    res = _replay(C0930 / "W04.json", first_draft=True)
    rep, v = res.report, res.report.validation
    assert _passes(res) and not EV.search(_unquoted(rep)) and "Controller" not in _unquoted(rep)
    assert any(s.startswith("Computed dispatch TOTALDEMAND (5-minute) change") and s.endswith("1385.98 MW.")
               for s in rep.summary)
    originals = [r["original"] for r in v["display_rewrites"]]
    assert any("Controller-computed" in o and "[ev0975]" in o for o in originals)  # the original is kept
    assert "ev0975" in {c.evidence_id for c in rep.numeric_claims}  # and the claim still carries its evidence


def test_w18_field_name_and_markers_are_readable():
    """2026-09-30 W18: "(peak_half_hour_end_utc 2026-08-19T23:30:00Z) was 6812.0 MW. [ev0912]"."""
    res = _replay(C0930 / "W18.json", first_draft=True, delete="possible_explanations[1]")
    rep = res.report
    assert _passes(res) and not EV.search(_unquoted(rep)) and "peak_half_hour_end_utc" not in _unquoted(rep)
    assert any("(peak half-hour end (UTC) 2026-08-19T23:30:00Z) was 6812.0 MW." in s for s in rep.summary)


@pytest.mark.parametrize("path,kw", [(C0929 / "F04.json", {}), (C0930 / "F04.json", {"first_draft": True})])
def test_f04_threshold_diagnostic_is_not_shown_but_kept(path, kw):
    res = _replay(path, **kw)
    rep, v = res.report, res.report.validation
    assert _passes(res) and not any("is not a time-stamped observation" in t for t in _shown(rep))
    hidden = [r for r in v["display_rewrites"] if r.get("shown") is False]
    assert [r["original"] for r in hidden] == ["ev0878 (project_analysis_threshold) is not a time-stamped observation; "
                                               "listed only as a claim"]
    assert "ev0878" in {c.evidence_id for c in rep.numeric_claims}


def test_f01_search_not_performed_is_disclosed_without_the_models_instruction():
    res = _replay(C0929 / "F01.json")
    rep = res.report
    assert "Market notices were not searched: market notices are searched only for a stated region and event window." \
        in rep.missing_evidence
    assert not any("call again" in t or "event_start_utc" in t for t in _shown(rep))
    assert any("call again with" in (s.market_notices or "") for s in rep.search_scope)  # the record keeps it


def test_w20_tool_names_in_a_document_answer_are_readable():
    """2026-09-29 W20: 'an API function named "get_actual_demand" or "get_forecast_runs"'."""
    res = _replay(C0929 / "W20.json")
    rep = res.report
    assert _passes(res) and not TOOLS.search(" ".join(_shown(rep)))
    assert any("named the actual-demand data or the forecast-run data" in u for u in rep.uncertainties)


# ------------------------------------------------------------------------------------------------ controls
def test_blocked_calls_in_a_saved_run_are_disclosed_in_plain_words():
    """L3 regression ADV02: calls outside the playbook and over the call limit, never retried successfully."""
    res = _replay(LIVE / "L3-regression" / "ADV02.json", with_blocked=True)
    rep, v = res.report, res.report.validation
    assert v["fallback_applied"] and v["final_passed"]
    assert "A request to the actual-demand data was blocked: it is not used for this kind of question, so it was not run." \
        in rep.missing_evidence
    assert "A request to the document search was blocked: its call limit had been reached, so it was not run." \
        in rep.missing_evidence
    assert not TOOLS.search(" ".join(rep.missing_evidence))
    originals = [r["original"] for r in v["display_rewrites"]]
    assert "get_actual_demand: blocked — 'get_actual_demand' is not in the source_explanation playbook" in originals
    blocked = {(r.name, r.blocked_reason) for r in res.records if r.status == "blocked"}  # the API's tool_calls
    assert ("retrieve_public_evidence", "'retrieve_public_evidence' already called 6 times") in blocked


def test_a_call_to_a_missing_tool_and_an_invalid_call_are_disclosed():
    """W04 (2026-09-30) with two more calls the model might make: an action that is not a tool, and an invalid
    request that is not retried. The answer is still shown, with both disclosed and neither name shown."""
    rec = json.loads((C0930 / "W04.json").read_text())
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    calls += [("publish_case_note", {"note": "SYNTHETIC"}), ("get_weather_context", {"region": "NSW1"})]
    draft = rec["drafts"].get("repair:draft") or rec["drafts"]["synthesis:draft"]
    fake = FakeModel(rec["route"], [calls], lambda kw: copy.deepcopy(draft))
    res = investigate(InvestigateRequest(question=rec["question"], mode="live"), live_client=fake, write_trace=False)
    rep = res.report
    assert _passes(res)
    blocked = [r for r in res.records if r.status == "blocked"]
    assert [r.name for r in blocked] == ["publish_case_note", "get_weather_context"]
    shown = [m for m in rep.missing_evidence if "blocked" in m]
    assert shown[0] == "A request for an action that is not one of the investigation's tools was blocked; nothing was run."
    assert shown[1].startswith("A request to the weather data was blocked: ") and shown[1].endswith("so it was not run.")
    assert not TOOLS.search(" ".join(shown)) and "publish_case_note" not in " ".join(_shown(rep))
    assert {r["original"].split(":")[0] for r in rep.validation["display_rewrites"]} >= {"publish_case_note",
                                                                                        "get_weather_context"}


@pytest.mark.parametrize("path,kw", [(V4 / "W14.json", {}), (C0930 / "W18.json", {"first_draft": True})])
def test_a_fallback_answer_loses_its_code_list_and_keeps_its_disclosure(path, kw):
    res = _replay(path, **kw)
    rep, v = res.report, res.report.validation
    assert v["fallback_applied"] and v["final_passed"]
    assert rep.headline == ("Validated facts only: the generated narrative failed independent validation. "
                            "Observations below are retrieved values with source rows.")  # I-4c: no "tool values"
    assert "Narrative withheld because it failed validation." in rep.uncertainties
    assert v["pre_repair_codes"] and any(r["where"] == "headline" and "(" in r["original"] for r in v["display_rewrites"])


def test_merged_observations_still_resolve():
    """PR #26: the repeats' IDs, kept in `observations_merged`, still resolve to a claim and a registry item."""
    res = _replay(C0930 / "W04.json", first_draft=True)
    rep = res.report
    shown = {o.evidence_id for o in rep.observations}
    claimed = {c.evidence_id for c in rep.numeric_claims}
    merged = rep.validation["observations_merged"]
    assert merged
    for entry in merged:
        assert entry["shown"] in shown and res.registry.get(entry["shown"]) is not None
        for also in entry["also"]:
            assert also["evidence_id"] in claimed and res.registry.get(also["evidence_id"]) is not None


def test_citations_and_structured_fields_are_unchanged():
    from nem_agent.display import plain_display

    res = _replay(C0930 / "W04.json", first_draft=True)
    rep = res.report
    marked = rep.model_copy(update={"summary": [s + " [ev0929]" for s in rep.summary]})
    out, rewrites = plain_display(marked)
    assert out.summary == rep.summary and len(rewrites) == len(rep.summary)
    keep = ("numeric_claims", "observations", "citations", "search_scope", "source_manifest", "validation", "trace_id")
    assert {k: getattr(out, k) for k in keep} == {k: getattr(marked, k) for k in keep}
    for text in _shown(out):  # every citation marker shown resolves to a citation
        for cid in re.findall(r"\[(c\d+)\]", text):
            assert cid in {c.citation_id for c in out.citations}


# ------------------------------------------------------------------------------------------------ validation first
@pytest.mark.parametrize("sentence,code", [
    ("NSW1 reached 999.0 $/MWh at 07:30 AEST [ev0964].", "NUMERIC_UNTRACKED"),
    ("compare_forecast_actual shows demand of 12345.0 MW (evidence_id: ev0929).", "NUMERIC_UNTRACKED"),
    ("The case note has been approved via retrieve_public_evidence [ev0929].", "ACTION_CLAIM_UNRECORDED"),
])
def test_a_violation_next_to_an_internal_reference_is_still_caught(sentence, code):
    """Validation reads the answer as written, markers and tool names included, before anything is put in plain
    words: the scripted repair repeats the draft, so the answer falls back and the sentence is never shown."""
    rec = json.loads((C0930 / "W04.json").read_text())
    draft = rec["drafts"].get("repair:draft") or rec["drafts"]["synthesis:draft"]
    res = _replay(C0930 / "W04.json", draft_update={"summary": [*draft["summary"], sentence]})
    v = res.report.validation
    assert code in set(v.get("pre_repair_codes") or []) and v["fallback_applied"]
    plain = plain_text(sentence)
    assert not any(plain[:30] in t or sentence[:30] in t for t in _shown(res.report))


@pytest.mark.parametrize("path,kw", [
    (C0930 / "W04.json", {"first_draft": True}), (C0930 / "W18.json", {"first_draft": True, "delete": "possible_explanations[1]"}),
    (C0929 / "F01.json", {}), (C0929 / "F04.json", {}), (C0929 / "W20.json", {}), (V4 / "W08.json", {}),
    (V4 / "W14.json", {}),
])
def test_the_displayed_answer_passes_validation_and_adds_no_number(path, kw):
    res = _replay(path, **kw)
    rep = res.report
    assert not validate(rep, res.registry, records=res.records).critical
    rewrites = rep.validation.get("display_rewrites", [])
    assert rewrites
    before = {r["where"]: r["original"] for r in rewrites}
    fields = {"headline": [rep.headline], "summary": rep.summary,
              "possible_explanations": [h.statement for h in rep.possible_explanations],
              "published_findings": [f.statement for f in rep.published_findings]}
    for where, original in before.items():  # each rewritten line, against its own original
        name, _, idx = where.partition("[")
        if name in fields and "." not in where:
            shown = fields[name][int(idx[:-1]) if idx else 0]
            assert set(narrative_numbers(shown)) <= set(narrative_numbers(original)), where
    notes = [*rep.uncertainties, *rep.missing_evidence]  # lines not shown shift the rest, so compare the lists
    original_notes = [*notes, *(r["original"] for r in rewrites if r["where"].startswith(("uncertainties", "missing")))]
    assert set(narrative_numbers(" ".join(notes))) <= set(narrative_numbers(" ".join(original_notes)))
