"""G6: the 40-case suite is well-formed, split without leakage, gold-labelled from real rows, and runnable."""

from __future__ import annotations

import re

import pytest

from nem_agent.evaluation.runner import load_cases, run_baseline_retrieval_only, run_system_case, summarise


@pytest.fixture(scope="module")
def cases():
    return load_cases()


def test_forty_cases_in_stated_categories(cases):
    assert cases["n_cases"] == len(cases["cases"]) == 40
    assert cases["category_counts"] == {"market_event": 10, "forecast": 10, "document": 8,
                                        "ambiguous_unavailable": 6, "adversarial_citation_approval": 6}
    assert len({c["case_id"] for c in cases["cases"]}) == 40


def test_split_by_group_without_leakage(cases):
    groups: dict[str, set[str]] = {}
    for c in cases["cases"]:
        groups.setdefault(c["group"], set()).add(c["split"])
        if c.get("expected", {}).get("event_id"):
            assert c["group"].startswith("G")
    assert all(len(s) == 1 for s in groups.values())
    assert {c["split"] for c in cases["cases"]} == {"dev", "test"}


def test_provenance_and_synthetic_flags(cases):
    for c in cases["cases"]:
        p = c["provenance"]
        assert {"synthetic", "human_review_needed", "gold_derivation", "data_version"} <= set(p)
        kind = c["expected"].get("kind", "")
        if kind.startswith(("approval", "synthetic")):
            assert p["synthetic"] is True
        if c["category"] in ("market_event", "forecast"):
            assert p["synthetic"] is False


def test_gold_numbers_come_from_real_rows(cases, real_store):
    rolled = real_store.snapshot.get("rolled_off_sources", {})
    for c in cases["cases"]:
        for g in c["expected"].get("gold_numbers", []):
            if not g.get("source_row_id"):
                continue
            row = real_store.row(g["source_row_id"])
            if row is None:  # allowed only when its own file rolled off NEMWeb Current (docs/data-retention.md)
                m = re.search(r"_DAILY_(\d{8})_", g["source_row_id"])
                assert m and f"opdem_actual_daily_{m.group(1)}" in rolled, g
                continue
            value = row.get("rrp", row.get("operational_demand_mw"))
            assert value == pytest.approx(g["value"]), (c["case_id"], g)


def test_runner_on_subset_produces_denominators(cases):
    subset = [c for c in cases["cases"] if c["case_id"] in {"EV01", "FC02", "DOC01", "AMB04", "ADV06"}]
    rows = [run_system_case(c, "replay") for c in subset]
    s = summarise(rows)
    assert s["gold_numbers"]["denominator"] == 3 and s["gold_numbers"]["numerator"] == 3
    assert s["as_of_leaks"] == 0 and s["unauthorized_writes"] == 0
    assert s["numeric_traceability_on_accepted"]["numerator"] == s["numeric_traceability_on_accepted"]["denominator"]
    b = [run_baseline_retrieval_only(c) for c in subset]
    assert summarise(b)["gold_numbers"]["numerator"] == 0  # the document-only baseline cannot produce numbers
