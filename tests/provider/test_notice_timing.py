"""Notice timing is checked, not just mentioned: a sentence that sets a market notice's time before, between or after
the event must be right about it, whatever zone it is written in.

Real pinned data (dispatch prices and AEMO notices) through the tools and the validator; the SYNTHETIC fake transport
only supplies the draft. VIC1, 2026-08-20 (AEST, UTC+10): the Hazelwood notice gives 1100 hrs NEM time = 01:00Z; the
six intervals at or above 300 $/MWh end between 23:05Z and 23:45Z on the 19th, and the price extreme's interval ends
23:10Z. SA1, 2026-07-30 (ACST, UTC+09:30): the Belalie-Davenport line outage notice gives 1630 hrs NEM time = 06:30Z
= 16:00 ACST, between the first and last of 214 high-price intervals; the price extreme's interval ends 16:35Z.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from nem_agent.validation import _EventTimes, _timing_statements, validate
from tests.provider.fake_model import FakeModel
from tests.provider.test_heldout_v2_fixes import NOTICE_Q, _vic_notice_investigation

pytestmark = pytest.mark.synthetic

TIMING = {"NOTICE_TIMING_CONTRADICTED", "NOTICE_TIMING_UNVERIFIED", "NOTICE_TIMING_OMITTED", "NOTICE_TIME_ZONE_MISMATCH"}


@pytest.fixture(scope="module")
def vic(selection):
    res, _ = _vic_notice_investigation(selection, lambda tl, timing: [])
    return res


def _critical(res, *lines: str, question: str | None = None) -> list[tuple[str, str]]:
    """Validate the investigation's report with these summary lines, citing the region's notice (Hazelwood for VIC1,
    Belalie-Davenport for SA1) as a model's draft would."""
    from nem_agent.report import Citation

    ch = next(c for c in res.registry.chunks.values() if c.doc_id in ("market_notice_144893", "market_notice_144693"))
    cite = Citation(citation_id="c1", chunk_id=ch.chunk_id, doc_id=ch.doc_id, title=ch.title, url=ch.url,
                    doc_type=ch.doc_type, quote=ch.text.split(". ")[0], supports="the notice")
    rep = res.report.model_copy(update={"summary": list(lines), "citations": [cite],
                                        **({"question": question} if question else {})})
    v = validate(rep, res.registry, window=res.resolution.window, records=res.records, event_kind=res.resolution.kind)
    return [(x.code, x.detail) for x in v.critical]


def _timing_codes(res, *lines: str, **kw) -> set[str]:
    return {c for c, _ in _critical(res, *lines, **kw)} & TIMING


# ------------------------------------------------------------------------------------------------ correct statements
@pytest.mark.parametrize("line", [
    # the controller's wording: the notice time on two bases, the relation, and the interval's own time
    "The Hazelwood bus tie outage notice gives 2026-08-20 11:00 AEST (01:00 UTC), after the last 5-minute interval at "
    "or above the analysis threshold, which ended 2026-08-20 09:45 AEST.",
    "The notice's 01:00 UTC is after the price spike.",                                  # UTC basis, the whole spike
    "The notice time, 2026-08-20T01:00:00Z, came after the price extreme's interval (2026-08-19T23:10:00Z).",
    "AEMO's outage notice gives 11:00 NEM, later than the last high-price interval.",    # NEM-time basis
    # the event as the subject: read the right way round
    "The last high-price interval had ended before the notice time of 2026-08-20 11:00 AEST.",
    "Before the notice's 11:00 AEST, all of the high-price intervals had passed.",
])
def test_correct_timing_statements_pass(vic, line):
    assert _timing_codes(vic, line, question=NOTICE_Q) == set()


# ------------------------------------------------------------------------------------------------ wrong statements
@pytest.mark.parametrize("line, fragment", [
    # reversed: the notice time is after every high-price interval
    ("The Hazelwood bus tie outage notice gives 2026-08-20 11:00 AEST (01:00 UTC), before the first 5-minute "
     "interval at or above the analysis threshold.", "is before the first 5-minute interval at or above 300 $/MWh"),
    ("The notice's 01:00 UTC came before the price spike.", "it is after it"),
    ("The notice time of 2026-08-20 11:00 AEST fell during the high-price intervals.", "is within the 5-minute intervals"),
    # reversed with the event as the subject
    ("The first high-price interval began after the notice's 11:00 AEST.", "is before the first"),
    # against a stated time: 23:45 UTC on the 19th is 75 minutes before the notice
    ("The notice's 01:00 UTC is before 23:45 UTC.", "is before 23:45 UTC"),
])
def test_reversed_or_wrong_relations_are_rejected(vic, line, fragment):
    found = [d for c, d in _critical(vic, line, question=NOTICE_Q) if c == "NOTICE_TIMING_CONTRADICTED"]
    assert found and any(fragment in d for d in found), found


def test_a_wrong_interval_time_is_rejected_even_with_the_right_relation(vic):
    """A zone slip: the last interval ended 23:45 UTC = 09:45 AEST; '23:45 AEST' is a different instant."""
    found = [d for c, d in _critical(vic, "The notice gives 2026-08-20 11:00 AEST, after the last 5-minute interval "
                                          "at or above the analysis threshold, which ended 23:45 AEST.",
                                     question=NOTICE_Q) if c == "NOTICE_TIMING_CONTRADICTED"]
    assert found == ["summary[0]: gives '23:45 AEST' for the last 5-minute interval at or above 300 $/MWh, which runs "
                     "from 2026-08-19T23:40Z to 2026-08-19T23:45Z"]


@pytest.mark.parametrize("line", ["The outage notice gives 2026-08-20 11:00 UTC, after the price spike.",
                                  "The outage notice time, 11:00 UTC, came after the spike."])
def test_the_notice_clock_under_the_wrong_zone_is_rejected(vic, line):
    """The notice's 1100 hrs is NEM time (01:00 UTC). '11:00 UTC' is a real price-interval time, so the general time
    check accepts it; the notice-time check does not, whether or not the question asks about the notice."""
    for q in (NOTICE_Q, "What happened to VIC1 prices on 2026-08-20?"):
        found = [d for c, d in _critical(vic, line, question=q) if c == "NOTICE_TIME_ZONE_MISMATCH"]
        assert found and "2026-08-20T01:00Z (11:00 NEM time)" in found[0]


def test_hypothetical_statements_are_not_read_as_claims(vic):
    line = "It is not known whether work began before the spike, although the notice gives 2026-08-20 11:00 AEST."
    assert _timing_codes(vic, line, question="What happened to VIC1 prices on 2026-08-20?") == set()  # not checked
    assert _timing_codes(vic, line, question=NOTICE_Q) == {"NOTICE_TIMING_OMITTED"}  # ... and not counted


def test_comparisons_the_registered_prices_cannot_settle_are_rejected(selection):
    """Without the price timeline for the window, 'after the last high-price interval' cannot be verified."""
    ev = next(e for e in selection.events if e.event_id == "VIC1-20260820T0910-hi")
    turn = [("find_market_events", {"region": "VIC1", "start_utc": ev.window_start_utc, "end_utc": ev.window_end_utc,
                                    "kind": "high_price", "threshold_aud_per_mwh": None, "max_results": 5}),
            ("retrieve_public_evidence", {"query": "Hazelwood outage", "region": "VIC1", "top_k": 5,
                                          "event_start_utc": ev.window_start_utc, "event_end_utc": ev.window_end_utc,
                                          "as_of_utc": None, "doc_types": ["market_notice"]})]
    fake = FakeModel({"intent": "market_event_review", "region": "VIC1", "event_date": "2026-08-20", "as_of_utc": None,
                      "needs_clarification": False, "clarification_reason": None, "clarification": None,
                      "out_of_scope": False}, [turn],
                     lambda kw: {"status": "abstained", "headline": "x", "summary": [], "document_statements": [],
                                 "observation_evidence_ids": [], "numeric_claims": [], "possible_explanations": [],
                                 "published_findings": [], "citations": [], "uncertainties": [], "missing_evidence": [],
                                 "forecast_mae_evidence_id": None})
    from nem_agent.agent.request import InvestigateRequest
    from nem_agent.service import investigate

    res = investigate(InvestigateRequest(question=NOTICE_Q, mode="live"), live_client=fake, write_trace=False)
    assert _timing_codes(res, "The outage notice gives 2026-08-20 11:00 AEST, after the last high-price interval.") \
        == {"NOTICE_TIMING_UNVERIFIED"}
    # a comparison with a stated time needs no price series
    assert _timing_codes(res, "The outage notice gives 2026-08-20 11:00 AEST, after 2026-08-20 09:10 AEST.") == set()


# ------------------------------------------------------------------------------------------------ SA1, ACST (UTC+09:30)
@pytest.fixture(scope="module")
def sa(selection):
    from nem_agent.agent.request import InvestigateRequest
    from nem_agent.service import investigate
    from tests.provider.fake_model import outputs

    ev = selection.primary
    turn = [("get_price_timeline", {"region": "SA1", "start_utc": ev.window_start_utc, "end_utc": ev.window_end_utc,
                                    "as_of_utc": None}),
            ("retrieve_public_evidence", {"query": "Belalie-Davenport line outage", "region": "SA1", "top_k": 8,
                                          "event_start_utc": ev.window_start_utc, "event_end_utc": ev.window_end_utc,
                                          "as_of_utc": None, "doc_types": ["market_notice"]})]

    def report(kw):
        hit = next(h for v in outputs(kw).values() for h in v.get("result", {}).get("results", [])
                   if h["doc_id"] == "market_notice_144693")
        quote = hit["text"].split(". ")[0]
        return {"status": "answered", "headline": "x", "summary": [], "document_statements": [],
                "observation_evidence_ids": [], "numeric_claims": [], "possible_explanations": [],
                "published_findings": [], "citations": [{"citation_id": "c1", "chunk_id": hit["chunk_id"],
                                                         "quote": quote, "supports": "notice"}],
                "uncertainties": [], "missing_evidence": [], "forecast_mae_evidence_id": None}
    fake = FakeModel({"intent": "market_event_review", "region": "SA1", "event_date": "2026-07-31", "as_of_utc": None,
                      "needs_clarification": False, "clarification_reason": None, "clarification": None,
                      "out_of_scope": False}, [turn], report)
    return investigate(InvestigateRequest(question="Did the Belalie-Davenport line outage matter for the SA1 spike on "
                                                   "2026-07-31?", mode="live"), live_client=fake, write_trace=False)


def test_acst_statements_are_checked_in_utc(sa):
    assert _timing_codes(sa, "The line outage notice gives 2026-07-30 16:00 ACST, between the first and last 5-minute "
                             "intervals at or above the analysis threshold.") == set()
    assert _timing_codes(sa, "The line outage notice time (06:30 UTC) is before the price extreme.") == set()
    assert _timing_codes(sa, "The line outage notice gives 2026-07-30 16:00 ACST, after the last 5-minute interval "
                             "at or above the analysis threshold.") == {"NOTICE_TIMING_CONTRADICTED"}
    # the ACST clock labelled AEST is half an hour off: a zone slip, and nothing is set against the event
    assert _timing_codes(sa, "The line outage notice gives 2026-07-30 16:00 AEST, after the price extreme.") \
        == {"NOTICE_TIMING_OMITTED", "NOTICE_TIME_ZONE_MISMATCH"}


# ------------------------------------------------------------------------------------------------ the rule itself
def _et(kind="low_price"):
    t0 = datetime(2026, 7, 28, 10, 0, tzinfo=UTC)
    low = [t0 + timedelta(minutes=5 * i) for i in range(1, 7)]  # 10:05Z-10:30Z below the low threshold
    return _EventTimes(kind, {"high": [], "low": low}, low[2], True, (300.0, 0.0))


def test_low_price_events_use_the_low_threshold_intervals():
    notice = datetime(2026, 7, 28, 9, 0, tzinfo=UTC)
    ok, v = _timing_statements("summary[0]", "The notice gives 09:00 UTC, before the first negative-price interval.",
                               {notice}, _et())
    assert ok == {notice} and v == []
    _, v = _timing_statements("summary[0]", "The notice gives 09:00 UTC, after the negative-price intervals.",
                              {notice}, _et())
    assert [x.code for x in v] == ["NOTICE_TIMING_CONTRADICTED"]
    # a high-price interval named in a low-price event: there is none to compare with
    _, v = _timing_statements("summary[0]", "The notice gives 09:00 UTC, before the high-price intervals.",
                              {notice}, _et())
    assert [x.code for x in v] == ["NOTICE_TIMING_CONTRADICTED"] and "has none" in v[0].detail


def test_between_two_stated_times_and_unanchored_relations():
    notice = datetime(2026, 7, 28, 10, 12, tzinfo=UTC)
    ok, v = _timing_statements("summary[0]", "The notice's 10:12 UTC falls between 10:05 UTC and 10:30 UTC.",
                               {notice}, _et())
    assert ok == {notice} and v == []
    _, v = _timing_statements("summary[0]", "The notice's 10:12 UTC falls between 10:20 UTC and 10:30 UTC.",
                              {notice}, _et())
    assert [x.code for x in v] == ["NOTICE_TIMING_CONTRADICTED"]
    # a relation with nothing to compare against is neither a claim nor a violation
    ok, v = _timing_statements("summary[0]", "The notice's 10:12 UTC came before demand rose.", {notice}, _et())
    assert ok == set() and v == []


# ------------------------------------------------------------------------------------------------ which questions
def test_the_trigger_covers_paraphrases_not_one_wording():
    from nem_agent.agent.request import asks_if_notice_event_caused as asks

    for q in ("Did the transformer trip matter for the spike?",
              "Was the Hazelwood outage behind the VIC1 spike?",
              "How much of the SA1 price run-up can be put down to the Heywood transfer limit?",
              "Would prices have spiked without the Belalie-Davenport line outage?"):
        assert asks(q), q
    for q in ("Did low wind cause the SA1 price spike on 2026-07-31?",           # not a notice-reported incident
              "What was the Heywood interconnector flow at the peak?",          # a fact about equipment
              "Why was the POE50 forecast so far off on 2026-07-31?",           # a forecast question
              "What happened to VIC1 prices on 2026-08-20?"):
        assert not asks(q), q


def test_the_trigger_on_independently_written_paraphrases():
    """Three sets of 30 + 30 questions written blind by independent agents. Sets 1 and 2 were each scored once and the
    vocabulary extended afterwards (development data); set 3 was scored once against the final vocabulary and is the
    measurement: 24/30 positives, 2/30 false positives (both definition or summary questions, which are routed as
    document questions, where the check does not apply)."""
    import json
    from pathlib import Path

    from nem_agent.agent.request import asks_if_notice_event_caused as asks

    sets = json.loads((Path(__file__).parent / "data" / "notice_trigger_paraphrases.json").read_text())["sets"]
    for name in ("set1", "set2"):
        assert all(asks(p["question"]) for p in sets[name]["positive"]), name
        assert not any(asks(n["question"]) for n in sets[name]["negative"]), name
    s3 = sets["set3"]
    assert sum(asks(p["question"]) for p in s3["positive"]) >= s3["blind_result"]["positives_matched"] == 24
    assert sum(asks(n["question"]) for n in s3["negative"]) <= s3["blind_result"]["false_positives"] == 2


def test_module_fixtures_do_not_touch_the_real_ledger(vic, sa):
    from nem_agent import budget, paths

    assert budget.ledger_path() != paths.artifacts_dir() / "live_budget" / "ledger.jsonl"
