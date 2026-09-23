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
