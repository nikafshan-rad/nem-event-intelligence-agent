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
