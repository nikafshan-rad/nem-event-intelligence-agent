"""Issue I-15 (docs/issue-tracker.md): a traced number's stated time must be the time of the evidence supporting it.

Held-out v6 Z03 (Live, 2026-10-02) showed: "… (half-hour ending 2026-08-06T03:00:00Z / 2026-08-06 13:00 AEST) was 1204.0
MW …, and the window's maximum operational demand was 1408.0 MW (half-hour ending 2026-08-06T09:00:00Z)." The claim for
1204.0 cites ev0917, the half-hour ending 13:00Z; at 03:00Z the value is 1147.0 MW (ev0897). The sentence-wide time
check passed it, because 1408.0's right time was in the same sentence.

Unit cases use SYNTHETIC registries; the end-to-end cases replay Z03's saved Live record through the SYNTHETIC fake
transport (no network, no key).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from nem_agent.agent.request import InvestigateRequest
from nem_agent.evidence import EvidenceRegistry
from nem_agent.service import investigate
from nem_agent.validation import (
    QUOTED_RE,
    SENTENCE_RE,
    _narratives,
    claim_time_violations,
    narrative_numbers,
    number_spans,
)
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

LIVE = Path(__file__).resolve().parents[2] / "artifacts" / "live"


def _registry(*items: tuple[str, float, str | None, int | None, str]) -> tuple[EvidenceRegistry, list[str]]:
    """(metric, value, valid_at_utc, interval_minutes, evidence_class) -> a registry and the evidence IDs."""
    reg = EvidenceRegistry()
    ids = []
    for metric, value, at, minutes, cls in items:
        ev = reg.add(evidence_class=cls, metric=metric, value=value, unit="MW", region="TAS1", valid_at_utc=at,
                     interval_minutes=minutes, source_row_ids=[f"row:{metric}:{at}"], source_urls=[], tool_call_id="t")
        ids.append(ev.evidence_id)
    return reg, ids


def _claims(*pairs: tuple[float, str]) -> SimpleNamespace:
    return SimpleNamespace(numeric_claims=[SimpleNamespace(value=v, rounding=0.0, evidence_id=e) for v, e in pairs])


def _codes(sentence: str, reg: EvidenceRegistry, report: SimpleNamespace) -> list[str]:
    return [v.code for v in claim_time_violations("summary[0]", sentence, report, reg, frozenset(), frozenset())]


# The Z03 shape: 03:00Z = 13:00 AEST holds 1147.0; 13:00Z holds 1204.0; 09:00Z holds the window maximum 1408.0
REG, (AT03, AT13, AT09) = _registry(("opdemand_actual", 1147.0, "2026-08-06T03:00:00Z", 30, "observed"),
                                    ("opdemand_actual", 1204.0, "2026-08-06T13:00:00Z", 30, "observed"),
                                    ("opdemand_actual", 1408.0, "2026-08-06T09:00:00Z", 30, "observed"))
Z03_SENTENCE = ("The half-hour operational demand for the half-hour containing that interval (half-hour ending "
                "2026-08-06T03:00:00Z / 2026-08-06 13:00 AEST) was {v} MW (operational demand, 30-minute), and the "
                "window's maximum operational demand was 1408.0 MW (half-hour ending 2026-08-06T09:00:00Z).")


# ------------------------------------------------------------------------------------------------ the Z03 shape
def test_the_z03_sentence_is_rejected_and_its_correction_passes():
    assert _codes(Z03_SENTENCE.format(v="1204.0"), REG, _claims((1204.0, AT13), (1408.0, AT09))) == ["CLAIM_TIME_MISMATCH"]
    assert _codes(Z03_SENTENCE.format(v="1147.0"), REG, _claims((1147.0, AT03), (1408.0, AT09))) == []


def test_another_numbers_right_time_does_not_cover_a_wrong_one():
    """The sentence-wide check's gap: here 1408.0's right time sits in the same sentence."""
    s = "Demand was 1204.0 MW at 2026-08-06T03:00:00Z, and the maximum was 1408.0 MW at 2026-08-06T09:00:00Z."
    assert _codes(s, REG, _claims((1204.0, AT13), (1408.0, AT09))) == ["CLAIM_TIME_MISMATCH"]


# ------------------------------------------------------------------------------------------------ equal values
def test_an_equal_value_elsewhere_in_the_evidence_does_not_justify_the_time():
    """Only the evidence supporting the claim counts, never another item with the same value at the stated time."""
    reg, (claimed, _other) = _registry(("opdemand_actual", 1204.0, "2026-08-06T13:00:00Z", 30, "observed"),
                                      ("dispatch_totaldemand", 1204.0, "2026-08-06T03:00:00Z", 5, "observed"))
    s = "Operational demand for the half-hour ending 2026-08-06T03:00:00Z was 1204.0 MW."
    assert _codes(s, reg, _claims((1204.0, claimed))) == ["CLAIM_TIME_MISMATCH"]


def test_equal_values_claimed_at_different_times_are_not_guessed():
    reg, (late, early) = _registry(("opdemand_actual", 1204.0, "2026-08-06T13:00:00Z", 30, "observed"),
                                   ("dispatch_totaldemand", 1204.0, "2026-08-06T03:00:00Z", 5, "observed"))
    both = _claims((1204.0, late), (1204.0, early))
    s = "Operational demand for the half-hour ending 2026-08-06T03:00:00Z was 1204.0 MW."
    assert _codes(s, reg, both) == ["CLAIM_TIME_AMBIGUOUS"]  # it fits one claim; which one is not said
    assert _codes(s.replace("1204.0 MW", f"1204.0 MW [{early}]"), reg, both) == []  # the marker says which
    assert _codes(s.replace("1204.0 MW", f"1204.0 MW [{late}]"), reg, both) == ["CLAIM_TIME_MISMATCH"]
    s2 = "It was 1204.0 MW at both 2026-08-06T03:00:00Z and 2026-08-06T13:00:00Z."  # every candidate's time stated
    assert _codes(s2, reg, both) == []
    s3 = "Operational demand for the half-hour ending 2026-08-06T05:00:00Z was 1204.0 MW."  # fits neither
    assert _codes(s3, reg, both) == ["CLAIM_TIME_MISMATCH"]


# ------------------------------------------------------------------------------------------------ valid forms
@pytest.mark.parametrize("sentence", [
    "Demand was 1147.0 MW for the half-hour ending 2026-08-06T03:00:00Z.",  # UTC, interval end
    "Demand was 1147.0 MW for the half-hour ending 2026-08-06 13:00 AEST.",  # local equivalent
    "Demand was 1147.0 MW (2026-08-06T03:00:00Z = 2026-08-06 13:00 AEST).",  # both
    "Demand was 1147.0 MW for the half-hour starting 2026-08-06T02:30:00Z.",  # interval start
    "The half-hour containing the interval ending 2026-08-06T02:55:00Z had 1147.0 MW.",  # an instant inside it
    "Demand was 1147.0 MW at 13:00 AEST.",  # a clock with its zone, no date
    "Between 2026-08-06T02:00:00Z and 2026-08-06T04:00:00Z demand reached 1147.0 MW.",  # a range containing it
    "From 2026-08-06T02:00:00Z (2026-08-06 12:00 AEST) to 2026-08-06T04:00:00Z, demand reached 1147.0 MW.",
    "Demand was 1147.0 MW.",  # no stated time: nothing claimed, nothing checked
])
def test_equivalent_times_interval_labels_and_ranges_pass(sentence):
    assert _codes(sentence, REG, _claims((1147.0, AT03))) == []


@pytest.mark.parametrize("sentence", [
    "Demand was 1147.0 MW for the half-hour ending 2026-08-06T13:00:00Z.",  # UTC read as local
    "Demand was 1147.0 MW at 03:00 AEST.",  # local clock that is not the evidence's
    "Demand was 1147.0 MW (2026-08-06T03:00:00Z / 2026-08-06 23:00 AEST).",  # one of two stated times wrong
    "Between 2026-08-06T05:00:00Z and 2026-08-06T08:00:00Z demand reached 1147.0 MW.",  # a range missing it
])
def test_a_wrong_time_is_rejected(sentence):
    assert _codes(sentence, REG, _claims((1147.0, AT03))) == ["CLAIM_TIME_MISMATCH"]


def test_shared_and_trailing_times_go_to_their_own_numbers():
    reg, (p50, p10, p90) = _registry(("opdemand_forecast_poe50", 1519.0, "2026-07-30T17:00:00Z", 30, "aemo_forecast"),
                                     ("opdemand_forecast_poe10", 1616.0, "2026-07-30T17:00:00Z", 30, "aemo_forecast"),
                                     ("opdemand_forecast_poe90", 1422.0, "2026-07-30T17:00:00Z", 30, "aemo_forecast"))
    forecasts = _claims((1519.0, p50), (1616.0, p10), (1422.0, p90))
    shared = ("For the half-hour ending 2026-07-30T17:00:00Z (2026-07-31 02:30 ACST): POE50 = 1519.0 MW, "
              "POE10 = 1616.0 MW, POE90 = 1422.0 MW.")
    assert _codes(shared, reg, forecasts) == []
    reg2, (a, b) = _registry(("dispatch_totaldemand", 10046.72, "2026-07-30T20:30:00Z", 5, "observed"),
                             ("dispatch_totaldemand", 11432.7, "2026-07-30T21:30:00Z", 5, "observed"))
    change = ("Dispatch total demand rose by 1385.98 MW, from 10046.72 MW in the 5-minute interval ending "
              "2026-07-30T20:30:00Z = 2026-07-31 06:30 AEST to 11432.7 MW in the 5-minute interval ending "
              "2026-07-30T21:30:00Z = 2026-07-31 07:30 AEST.")  # the controller's change sentence (I-2b)
    assert _codes(change, reg2, _claims((10046.72, a), (11432.7, b))) == []
    swapped = change.replace("from 10046.72", "from 11432.7").replace("to 11432.7", "to 10046.72")
    assert _codes(swapped, reg2, _claims((10046.72, a), (11432.7, b))) == ["CLAIM_TIME_MISMATCH"] * 2


def test_a_time_after_and_inside_brackets_belongs_to_its_own_clause():
    """Held-out v4 W18: the interval ending 23:05Z is the price rise's; −718.24 MW is the 5-minute interval ending
    23:10Z. A comma inside brackets still lists equivalents, and a number's own time in the brackets is still checked."""
    reg, (flow,) = _registry(("net_interchange", -718.24, "2026-08-19T23:10:00Z", 5, "observed"))
    w18 = ("The price spike may be associated with interconnector flow changes around the 5-minute intervals "
           f"2026-08-19T23:05:00Z–2026-08-19T23:15:00Z (see the observed net interchange −718.24 MW [{flow}] and the "
           "price rise from the interval ending 2026-08-19T23:05:00Z).")
    assert _codes(w18, reg, _claims((-718.24, flow))) == []
    own = f"(The observed net interchange was −718.24 MW [{flow}] in the interval ending 2026-08-19T23:05:00Z.)"
    assert _codes(own, reg, _claims((-718.24, flow))) == ["CLAIM_TIME_MISMATCH"]
    listed = ("The net interchange was −718.24 MW (interval ending 2026-08-19T23:10:00Z, 2026-08-20 09:10 AEST) and "
              "{t}.")
    assert _codes(listed.format(t="fell later"), reg, _claims((-718.24, flow))) == []
    assert _codes(listed.replace("09:10 AEST", "09:05 AEST").format(t="fell later"), reg,
                  _claims((-718.24, flow))) == ["CLAIM_TIME_MISMATCH"]


@pytest.mark.parametrize("lead", ["issued", "issued_at_utc", "published_at_utc", "available_at_utc", "as of",
                                  "provably public as-of", "after the price extreme at", "before"])
def test_issue_as_of_publication_and_relational_times_are_not_the_values_time(lead):
    reg, (p50,) = _registry(("opdemand_forecast_poe50", 1519.0, "2026-07-30T17:00:00Z", 30, "aemo_forecast"))
    s = (f"The run ({lead} 2026-07-30T11:47:59Z = 2026-07-30 21:47 AEST) gives POE50 = 1519.0 MW for the half-hour "
         "ending 2026-07-30T17:00:00Z.")
    assert _codes(s, reg, _claims((1519.0, p50))) == []
    assert _codes(s.replace("ending 2026-07-30T17:00:00Z", "ending 2026-07-30T18:00:00Z"), reg,
                  _claims((1519.0, p50))) == ["CLAIM_TIME_MISMATCH"]


def test_derived_evidence_keeps_the_sentence_level_check_only():
    """A count or mean spans a window; its registry time is the window's end, not a time stated for it."""
    reg, (count,) = _registry(("intervals_meeting_threshold", 6.0, "2026-07-30T21:35:00Z", 5, "derived"))
    s = "Six intervals, 6 in all, met the threshold between 2026-07-30T20:30:00Z and 2026-07-30T21:05:00Z."
    assert _codes(s, reg, _claims((6.0, count))) == []


# ------------------------------------------------------------------------------------------------ Z03 end to end
def _z03(draft: dict | None = None):
    rec = json.loads((LIVE / "L3-holdout-v6" / "Z03.json").read_text())
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    d = draft or rec["drafts"]["synthesis:draft"]
    fake = FakeModel(rec["route"], [calls], lambda kw: copy.deepcopy(d))
    return investigate(InvestigateRequest(question=rec["question"], mode="live"), live_client=fake,
                       write_trace=False), rec


def test_z03s_saved_answer_is_rejected_and_not_shown():
    res, _ = _z03()
    rep = res.report
    first = [(v["code"], v["detail"]) for v in rep.validation["initial"]["violations"]]
    assert [c for c, _ in first] == ["CLAIM_TIME_MISMATCH"] and first[0][1].startswith("summary[3]: 1204 is stated")
    assert rep.validation["fallback_applied"] and rep.headline.startswith("Validated facts only")
    assert not any("1204.0 MW" in s and "03:00" in s for s in rep.summary)


def test_z03_with_the_faithful_value_passes():
    _, rec = _z03()
    d = copy.deepcopy(rec["drafts"]["synthesis:draft"])
    d["summary"][3] = d["summary"][3].replace("1204.0 MW (operational demand, 30-minute) [ev0917]",
                                              "1147.0 MW (operational demand, 30-minute) [ev0897]")
    for c in d["numeric_claims"]:
        if c["claim_id"] == "n5":
            c.update(value=1147.0, evidence_id="ev0897")
    d["observation_evidence_ids"] = ["ev0897" if e == "ev0917" else e for e in d["observation_evidence_ids"]]
    res2, _ = _z03(d)
    rep = res2.report
    assert rep.validation["final_passed"] and not rep.validation["fallback_applied"]
    assert "1147.0 MW" in rep.summary[3] and "2026-08-06T03:00:00Z" in rep.summary[3]


# ------------------------------------------------------------------------------------------------ consistency
def test_number_spans_read_the_same_numbers_as_narrative_numbers_in_every_saved_answer():
    """The positions come from the same reading: on every saved Live draft's headline and summary sentences."""
    n = 0
    for f in sorted(LIVE.glob("**/*.json")):
        if "traces" in f.parts or "review_packet" in f.parts:
            continue
        try:
            rec = json.loads(f.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        d = (rec.get("drafts") or {}).get("synthesis:draft") if isinstance(rec, dict) else None
        if not d:
            continue
        for text in [d.get("headline") or ""] + list(d.get("summary") or []):
            for s in SENTENCE_RE.split(QUOTED_RE.sub(" ", text)):
                assert [v for v, _, _ in number_spans(s)] == narrative_numbers(s), s
                n += 1
    assert n > 1000


def test_the_check_runs_on_every_narrative_place():
    """Headline, summary, hypotheses, published findings and hypothesis tests, as the sentence-wide check."""
    res, _ = _z03()
    assert "claim_times" in res.report.validation["initial"]["checks_run"]
    s = "Peak 1147.0 MW at 2026-08-06T13:00:00Z."
    report = SimpleNamespace(**{**_claims((1147.0, AT03)).__dict__, "headline": s, "summary": [s],
                                "possible_explanations": [], "published_findings": [], "forecast_comparison": None,
                                "_model_headline": None})
    assert [w for w, _ in _narratives(report)] == ["headline", "summary[0]"]


# ------------------------------------------------------------------------------------------------ interval semantics
# 1147.0 MW is the half-hour ending 2026-08-06T03:00Z: (02:30Z, 03:00Z] under the interval-ending convention.
# "ending T" must be its end, "starting T" its start, "containing T" (or a bare time) an instant in (start, end].
@pytest.mark.parametrize("phrase,ok", [
    ("for the half-hour ending 2026-08-06T03:00:00Z", True),
    ("for the half-hour ending 2026-08-06 13:00 AEST", True),
    ("for the half-hour ending 2026-08-06T03:00:00Z (2026-08-06 13:00 AEST)", True),  # the equivalent keeps "ending"
    ("for the half-hour ending 2026-08-06T02:30:00Z", False),  # its start
    ("for the half-hour ending 2026-08-06T02:45:00Z", False),  # an instant inside it
    ("for the half-hour ending 2026-08-06T03:30:00Z", False),  # the next half-hour
    ("for the half-hour ending 2026-08-06T03:00:00Z (2026-08-06 12:30 AEST)", False),  # a wrong equivalent
    ("for the half-hour starting 2026-08-06T02:30:00Z", True),
    ("for the half-hour starting 2026-08-06 12:30 AEST", True),
    ("for the half-hour starting 2026-08-06T03:00:00Z", False),  # its end
    ("for the half-hour starting 2026-08-06T02:45:00Z", False),  # an instant inside it
    ("for the half-hour starting 2026-08-06T02:00:00Z", False),  # the half-hour before
    ("for the half-hour containing 2026-08-06T02:45:00Z", True),
    ("for the half-hour containing 2026-08-06T03:00:00Z", True),  # the end belongs to it
    ("for the half-hour containing 2026-08-06T02:30:00Z", False),  # the start belongs to the half-hour before
    ("for the half-hour containing 2026-08-06T03:05:00Z", False),
    ("for the half-hour containing the 5-minute interval ending 2026-08-06T02:55:00Z", True),
    ("for the half-hour containing the 5-minute interval ending 2026-08-06T02:30:00Z", False),  # (02:25, 02:30]
    ("for the half-hour containing the interval ending 2026-08-06T02:35:00Z", True),
    ("at 2026-08-06T02:45:00Z", True),  # no qualifier: an instant in the interval
    ("at 2026-08-06T02:30:00Z", False),
    ("with interval_end_utc 2026-08-06T03:00:00Z", True),  # field names
    ("with interval_end_utc 2026-08-06T02:30:00Z", False),
    ("with interval_start_utc 2026-08-06T02:30:00Z", True),
    ("with interval_start_utc 2026-08-06T03:00:00Z", False),
])
def test_ending_starting_and_containing_are_distinct(phrase, ok):
    assert (_codes(f"Demand was 1147.0 MW {phrase}.", REG, _claims((1147.0, AT03))) == []) is ok


@pytest.mark.parametrize("phrase,ok", [
    ("in the 5-minute interval ending 2026-08-06T02:55:00Z", True),
    ("in the 5-minute interval ending 2026-08-06T02:50:00Z", False),  # its start
    ("in the 5-minute interval starting 2026-08-06T02:50:00Z", True),
    ("in the 5-minute interval starting 2026-08-06T02:55:00Z", False),  # its end
    ("in the half-hour ending 2026-08-06T03:00:00Z", True),  # (02:50, 02:55] lies inside (02:30, 03:00]
    ("in the half-hour ending 2026-08-06T02:30:00Z", False),
    ("in the half-hour starting 2026-08-06T02:30:00Z", True),
    ("in the half-hour starting 2026-08-06T03:00:00Z", False),
])
def test_a_5_minute_value_against_5_minute_and_half_hour_wording(phrase, ok):
    """A 5-minute price ending 02:55Z, i.e. (02:50Z, 02:55Z]: named as its own interval, or as the half-hour it lies in."""
    reg, (price,) = _registry(("dispatch_rrp", 450.08, "2026-08-06T02:55:00Z", 5, "observed"))
    assert (_codes(f"The price was 450.08 $/MWh {phrase}.", reg, _claims((450.08, price))) == []) is ok
