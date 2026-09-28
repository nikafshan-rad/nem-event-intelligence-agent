"""G5: SYNTHETIC corruptions of real replay reports must each be detected; nothing critical survives the pipeline."""

from __future__ import annotations

import pytest

from nem_agent.evaluation.adversarial import build_fixtures, run_fixture

pytestmark = pytest.mark.synthetic


@pytest.fixture(scope="module")
def fixtures(selection):
    return {f.name: f for f in build_fixtures(selection)}


EXPECTED = {
    "invented_mw_value": "NUMERIC_UNTRACKED",
    "claim_value_changed": "CLAIM_VALUE_MISMATCH",
    "wrong_unit": "CLAIM_UNIT_MISMATCH",
    "edited_quote": "CITATION_QUOTE_NOT_FOUND",
    "quote_from_irrelevant_report": "FINDING_WRONG_REGION",
    "paraphrased_finding": "FINDING_NOT_QUOTED",
    "citation_not_retrieved": "CITATION_UNKNOWN_CHUNK",
    "time_mislabelled": "TIME_NOT_IN_EVIDENCE",
    "claim_other_region": "CLAIM_REGION_MISMATCH",
    "interval_mislabelled": "CLAIM_INTERVAL_MISMATCH",
    "hypothesis_time_unzoned": "TIME_ZONE_MISSING",
    "part_of_day_from_utc": "TIME_OF_DAY_UNVERIFIED",
    "unsupported_causality": "UNSUPPORTED_CAUSALITY",
    "unhedged_hypothesis": "HYPOTHESIS_UNHEDGED",
    "injection_echo": "INJECTION_ECHO",
    "injected_text_quoted": "INJECTION_QUOTED_AS_EVIDENCE",
    "later_forecast_in_as_of_answer": "ASOF_LEAK",
    "post_event_weather_as_forecast": "ASOF_LEAK_RETROSPECTIVE",
    "incompatible_metric_comparison": "METRIC_INCOMPATIBLE",
    "observation_altered": "OBS_MISMATCH",
}


def test_all_fixtures_present(fixtures):
    assert set(fixtures) == set(EXPECTED)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_corruption_detected_and_neutralised(fixtures, name):
    r = run_fixture(fixtures[name])
    assert r["detected"], r
    assert r["critical_after_fallback"] == 0, r


def test_base_reports_are_clean(selection):
    from nem_agent.evaluation.adversarial import _base

    for intent in ("market_event_review", "forecast_review"):
        res = _base(selection, intent)
        assert res.report.validation["initial"]["n_critical"] == 0


def test_narrative_number_extraction_ignores_times_ids_and_quotes():
    from nem_agent.validation import narrative_numbers

    text = ("SA1 price peaked at $4,981.00/MWh for the interval ending 2026-07-31 02:05 ACST (UTC+0930); "
            "5-minute data; POE50; notice [s01] says: “At 1140 hrs 275 kV”; unit AGLHAL.")
    assert narrative_numbers(text) == [4981.0]


def test_narrative_numbers_unicode_hyphen_and_issued_ids_only():
    from nem_agent.validation import narrative_numbers

    # a non-breaking hyphen is the same duration label; the price is still caught
    assert narrative_numbers("peak 5\u2011minute RRP of $4,981.00/MWh") == [4981.0]
    # an exact chunk id issued in this request is an identifier ...
    ids = frozenset({"market_notice_144693#0"})
    assert narrative_numbers("see [market_notice_144693#0]", ids) == []
    # ... but not when it was not issued, and ids never hide the numbers around them
    assert narrative_numbers("see [market_notice_144693#0]") == [0.0]
    assert narrative_numbers("see [x#4981] and 12 MW", ids) == [4981.0, 12.0]


def test_narrative_numbers_ignore_aemo_dates_but_not_notice_details():
    from nem_agent.validation import narrative_numbers

    assert narrative_numbers("AEMO's notice of 30/07/2026 [c1]") == []
    # clock times without a time zone and equipment identifiers stay flagged: they belong inside a quote
    assert narrative_numbers("at 1140 hrs breaker 6675 tripped on 30/07/2026") == [1140.0, 6675.0]
    assert narrative_numbers("45/07/2026") == [45.0, 7.0, 2026.0]  # not a date


def test_degree_celsius_is_the_same_unit_as_c():
    from nem_agent.validation import _unit

    assert _unit("\u00b0C") == _unit("C") == "C" and _unit("MW") != _unit("C")


def test_correct_local_and_utc_times_pass_and_shifted_times_fail(selection):
    from nem_agent.evaluation.adversarial import _base
    from nem_agent.validation import validate

    base = _base(selection)
    res = base.resolution
    peak = next(c for c in base.report.numeric_claims if c.unit == "$/MWh" and c.value > 1000)
    price = f"${peak.value:,.2f}/MWh"

    def time_codes(sentence):
        r = base.report.model_copy(update={"summary": [*base.report.summary, sentence]})
        return [x for x in validate(r, base.registry, window=res.window, records=base.records).violations
                if x.code == "TIME_NOT_IN_EVIDENCE"]
    assert not time_codes(f"The price peaked at {price} at 2026-07-31 02:05 ACST (2026-07-30T16:35:00Z).")
    assert time_codes(f"The price peaked at {price} at 2026-07-31 02:35 ACST.")          # shifted 30 minutes
    assert time_codes(f"The price peaked at {price} at 2026-07-30 16:35 ACST.")          # UTC relabelled as local
    assert time_codes("The window opened at 2026-07-29 03:17 ACST.")                     # no tool returned it


def test_document_claims_must_be_cited_and_supported(selection):
    from nem_agent.agent.request import InvestigateRequest
    from nem_agent.service import investigate
    from nem_agent.validation import support, validate

    res = investigate(InvestigateRequest(question="What does operational demand mean?", mode="replay"), write_trace=False)
    rep = res.report
    assert rep.intent == "source_explanation" and rep.citations
    cid = rep.citations[0].citation_id
    chunk = res.registry.chunks[rep.citations[0].chunk_id].text

    def codes(summary):
        r = rep.model_copy(update={"summary": summary})
        return {x.code for x in validate(r, res.registry, records=res.records).violations}
    assert "DOC_CLAIM_UNCITED" in codes(["Operational demand is measured every half-hour."])
    # a claim the cited definition does not make
    assert "DOC_CLAIM_UNSUPPORTED" in codes([f"Operational demand is forecast from weather models and published daily [{cid}]."])
    close = f"Operational demand in a region is demand met by local scheduled and semi-scheduled generation [{cid}]."
    assert support(close, chunk) >= 0.6 and not codes([close]) & {"DOC_CLAIM_UNCITED", "DOC_CLAIM_UNSUPPORTED"}


def test_hyphenated_identifiers_are_names_but_numbers_beside_them_are_checked():
    """L2 live run: '2' inside the constraint set S-DVBL_BC-2CP was read as an untracked number."""
    from nem_agent.validation import narrative_numbers

    assert narrative_numbers("constraint set S-DVBL_BC-2CP was invoked") == []
    assert narrative_numbers("S-DVBL_BC-2CP limited flows to 250 MW on the 275 kV line") == [250.0, 275.0]


def test_single_quoted_text_is_not_a_quote():
    """L2 run 3: single quotes stay unquoted text, so an apostrophe can never hide a number from the check."""
    from nem_agent.validation import narrative_numbers

    assert narrative_numbers("'At 1140 hrs the 275 kV breaker 6675 tripped.' [c1]") == [1140.0, 275.0, 6675.0]
    assert narrative_numbers("AEMO's price was 4981 in the region's peak") == [4981.0]
    assert narrative_numbers("“At 1140 hrs the 275 kV breaker 6675 tripped.” [c1]") == []


def test_numbers_must_be_described_at_their_own_resolution(selection):
    """L2 live run 4: an hourly sample of the 5-minute RRP was presented as 'the peak half-hour had RRP = …'."""
    from nem_agent.evaluation.adversarial import _base
    from nem_agent.validation import validate

    base = _base(selection)
    reg = base.registry
    five = next(c for c in base.report.numeric_claims if reg.get(c.evidence_id).interval_minutes == 5 and c.unit == "$/MWh")
    half = next(c for c in base.report.numeric_claims if reg.get(c.evidence_id).interval_minutes == 30)

    def interval_codes(sentence, claims=None):
        r = base.report.model_copy(update={"summary": [*base.report.summary, sentence],
                                           **({"numeric_claims": claims} if claims else {})})
        return [x.detail for x in validate(r, reg, window=base.resolution.window, records=base.records).violations
                if x.code == "CLAIM_INTERVAL_MISMATCH"]
    assert not interval_codes(f"The 5-minute price was ${five.value:,.2f}/MWh.")
    assert not interval_codes(f"In the half-hour containing the 5-minute peak, demand was {half.value:,.1f} {half.unit}.")
    assert interval_codes(f"The half‑hour price was ${five.value:,.2f}/MWh.")
    assert interval_codes(f"Demand in that 5-minute interval was {half.value:,.1f} {half.unit}.")
    relabelled = [c.model_copy(update={"text": "half-hour RRP"}) if c is five else c for c in base.report.numeric_claims]
    assert interval_codes("No numbers here.", relabelled) == [f"{five.claim_id}: labelled 30-minute but "
                                                             f"{five.evidence_id} is a 5-minute value"]


def test_times_in_hypotheses_need_a_zone_and_a_verified_instant(selection):
    """L3 live, EV09: "invoked from 11:00 (see notice c1) ... in the 11:15–11:25 UTC window" set a notice's NEM time
    beside UTC times. Times in hypotheses and their tests are now checked like times in the summary."""
    from nem_agent.evaluation.adversarial import _base
    from nem_agent.report import Hypothesis
    from nem_agent.validation import _known_instants, validate

    base = _base(selection)

    def codes(statement, test="Offer data for the peak interval."):
        r = base.report.model_copy(update={"possible_explanations": [Hypothesis(
            statement=statement, what_would_test_it=test)]})
        return [(x.code, x.detail) for x in validate(r, base.registry, window=base.resolution.window,
                                                   records=base.records).violations
                if x.code in ("TIME_ZONE_MISSING", "TIME_NOT_IN_EVIDENCE", "TIME_OF_DAY_UNVERIFIED")]
    # the observed error: a bare clock time next to UTC times
    assert [c for c, _ in codes("Constraint automation invoked from 11:00 might have limited imports in the "
                                "16:30–16:40 UTC window.")] == ["TIME_ZONE_MISSING"]
    # zoned times that tools returned pass, including ranges and the region's local zone
    assert not codes("Imports might have been limited between 16:30 and 16:40 UTC, around 2026-07-31 02:05 ACST.")
    # a zoned time no tool returned, and an unzoned time in the hypothesis's test, are rejected (file publication
    # times are tool instants too, so the unreturned time is chosen from outside the known set)
    known = {u.strftime("%H:%M") for u in _known_instants(base.registry, base.records, base.report,
                                                         base.resolution.window)}
    unknown = next(f"{h:02d}:{m:02d}" for h in range(24) for m in range(1, 60, 2) if f"{h:02d}:{m:02d}" not in known)
    assert [c for c, _ in codes(f"Supply may have tightened at {unknown} UTC.")] == ["TIME_NOT_IN_EVIDENCE"]
    assert [c for c, _ in codes("Supply may have tightened.", test="Check unit trips from 11:00.")] == \
        ["TIME_ZONE_MISSING"]


def test_part_of_day_words_need_a_region_local_time_that_shows_them(selection):
    """L3 live: EV09 called 05:30–17:30 UTC "the morning window"; EV02 called a 02:05 ACST peak "afternoon"."""
    from nem_agent.evaluation.adversarial import _base
    from nem_agent.report import Hypothesis
    from nem_agent.validation import validate

    base = _base(selection)

    def tod(statement=None, headline=None):
        upd = {"possible_explanations": [Hypothesis(statement=statement, what_would_test_it="Offer data.")]} \
            if statement else {}
        if headline:
            upd["headline"] = headline
        r = base.report.model_copy(update=upd)
        return [x.detail for x in validate(r, base.registry, window=base.resolution.window, records=base.records
                                           ).violations if x.code == "TIME_OF_DAY_UNVERIFIED"]
    assert tod("Forecasts may have run low in the morning window.")                     # no time at all
    assert tod("Forecasts may have run low in the morning window 05:30–17:30 UTC.")     # 15:00 and 03:00 ACST
    assert tod(headline="Prices may have spiked in the afternoon half-hour containing the peak.")
    assert tod("Prices may have stayed high through the afternoon, peaking at 16:35 UTC.")  # 02:05 ACST
    # correct: the region-local time shows the part of the day
    assert not tod("Prices may have stayed high overnight, peaking at 2026-07-31 02:05 ACST.")
    assert not tod("Prices may have stayed high overnight, peaking at 16:35 UTC.")     # 02:05 ACST is overnight


def test_time_checks_leave_document_answers_to_the_support_check():
    """A definition may paraphrase 'evening peak' from its passage; clock-time rules apply to event and forecast
    answers, where times refer to tool data."""
    from nem_agent.agent.request import InvestigateRequest
    from nem_agent.service import investigate
    from nem_agent.validation import validate

    res = investigate(InvestigateRequest(question="What does operational demand mean?", mode="replay"), write_trace=False)
    r = res.report.model_copy(update={"headline": res.report.headline + " It is reported for the evening peak."})
    got = {x.code for x in validate(r, res.registry, records=res.records).violations}
    assert not got & {"TIME_OF_DAY_UNVERIFIED", "TIME_ZONE_MISSING"} and "narrative_clock_times" not in \
        validate(r, res.registry, records=res.records).checks_run
