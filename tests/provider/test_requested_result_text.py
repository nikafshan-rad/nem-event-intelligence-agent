"""Issue I-19 (docs/issue-tracker.md): the model's own text agrees with the requested result the controller holds.

Live check of the v12 routing extraction (E-dev, 2026-10-03, code f2455ca):
- K09 asked at which five-minute interval NSW dispatch total demand was highest over 29 July 2026 (Sydney time). The
  controller's line gave the maximum it computed (10954.2 MW, ending 2026-07-29T09:05:00Z), and the model had been given
  it, but the model's headline gave 10,890.3 MW at 19:35 AEST as the answer, an explanation called 09:35Z the maximum,
  and two caveats said the maximum could not be confirmed. Both reviews: X.
- K07 asked about the half-hour 5:00-5:30 pm AEST on 6 Aug 2026 (07:00Z to 07:30Z). Its "unavailable" outcome was
  right, but four items named the half-hour "ending 17:00 AEST (07:00Z)".

Replays use the saved Live records (drafts, the actual saved repair, routes and tool calls) through the SYNTHETIC fake
transport (no network, no key). The controls are scripted variants of those drafts, labelled as such; scripted replays
are not a measure of Live behaviour.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from nem_agent.agent.request import InvestigateRequest
from nem_agent.service import investigate
from nem_agent.validation import validate
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

ROOT = Path(__file__).resolve().parents[2]
E2E = ROOT / "artifacts" / "live" / "LC-route-v12-e2e"
MAX_END = "2026-07-29T09:05:00Z"  # K09: TOTALDEMAND's maximum over the day, 10954.2 MW
HALF = ("2026-08-06T07:00:00Z", "2026-08-06T07:30:00Z")  # K07: the half-hour asked about


def _rec(cid: str) -> dict:
    return json.loads((E2E / f"{cid}.json").read_text())


def _replay(cid: str, draft_fn=None, repair_fn=None, *, saved_repair: bool = True):
    """The saved route, tool calls and synthesis draft. The repair is the actual saved one by default: its patch when a
    scoped repair is asked for, else the draft that patch produced (a caveat violation asks for a full repair)."""
    rec = _rec(cid)
    trace = json.loads((E2E / "traces" / f"{rec['score']['trace_id']}.json").read_text())["events"]
    draft = rec["drafts"]["synthesis:draft"]
    patch = next((e.get("patch") for e in trace if e["name"] == "repair:scoped"), None)
    repaired = rec["drafts"].get("repair:draft")

    def saved(kw):
        return copy.deepcopy(patch if kw["text"]["format"]["name"] == "RepairPatch" else repaired)
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    fake = FakeModel(rec["route"], [calls], draft_fn or (lambda kw: copy.deepcopy(draft)),
                     repair_fn or (saved if saved_repair and patch else None))
    res = investigate(InvestigateRequest(question=rec["question"], mode="live", **(rec.get("request") or {})),
                      live_client=fake, write_trace=False)
    return res, fake


def _first(res) -> list[tuple[str, str]]:
    v = res.report.validation
    return [(x["code"], x["detail"]) for x in (v.get("pre_repair") or v["initial"])["violations"]]


def _final(res) -> list[tuple[str, str]]:
    return [(x["code"], x["detail"]) for x in res.report.validation["initial"]["violations"]]


I19 = ("REQUESTED_MAXIMUM_MISMATCH", "REQUESTED_MAXIMUM_DENIED", "REQUESTED_INTERVAL_MISNAMED")


def _items(found: list[tuple[str, str]]) -> list[str]:
    """The item each I-19 violation names (its detail starts with it)."""
    return sorted(d.split(":", 1)[0] for c, d in found if c in I19)


# ------------------------------------------------------------------------------------------------ K09 replayed
def _k09(**edits):
    """K09's actual saved repair (its draft), with items replaced: a scripted variant."""
    def fn(kw):
        d = copy.deepcopy(_rec("K09")["drafts"]["repair:draft"])
        for k, v in edits.items():
            if k == "pe0":
                d["possible_explanations"][0]["statement"] = v
            elif k in ("u0", "m0"):
                d["uncertainties" if k == "u0" else "missing_evidence"][0] = v
            elif k == "extra_u":
                d["uncertainties"].append(v)
            elif k == "extra_m":
                d["missing_evidence"].append(v)
            else:
                d[k] = v
        return d
    return fn


FAITHFUL_K09 = {
    "headline": "NSW1 dispatch total demand (TOTALDEMAND) was highest at 10954.2 MW in the 5-minute interval ending "
                "2026-07-29 19:05 AEST (2026-07-29T09:05:00Z).",
    "pe0": "Short-term fluctuations around 2026-07-29T09:05:00Z may have produced the five-minute dispatch TOTALDEMAND "
           "maximum at 2026-07-29T09:05:00Z, shortly after the half-hour average peaked at 2026-07-29T09:00:00Z.",
    "u0": "The dispatch TOTALDEMAND maximum cannot be confirmed against metered data, and AEMO may later revise dispatch "
          "values.",
    "m0": "Five-minute dispatch TOTALDEMAND for the following day, to confirm whether its maximum was higher.",
}


def test_1_k09s_saved_draft_and_saved_repair_are_rejected_at_the_four_items():
    res, fake = _replay("K09")
    first = _first(res)
    assert _items(first) == ["headline", "missing_evidence[0]", "possible_explanations[0]", "uncertainties[0]"]
    assert ("TIME_OF_DAY_UNVERIFIED" in {c for c, _ in first})  # the earlier finding is still there
    head = next(d for c, d in first if d.startswith("headline"))
    assert "gives 10890.3 (dispatch_totaldemand, interval ending 2026-07-29T09:35:00Z) as its answer" in head
    assert f"10954.2 in the interval ending {MAX_END}" in head
    assert any(c == "REQUESTED_MAXIMUM_MISMATCH" and "2026-07-29T09:35:00Z, names another interval" in d
               for c, d in first if d.startswith("possible_explanations[0]"))
    assert {c for c, d in first if d.startswith(("uncertainties[0]", "missing_evidence[0]"))} == \
        {"REQUESTED_MAXIMUM_DENIED"}
    # the model had been given the result before it wrote the draft
    synthesis = next(r for r in fake.requests if (r.get("text") or {}).get("format", {}).get("name") == "ModelReport")
    assert "Requested demand maximum, computed by the controller" in json.dumps(synthesis["input"])
    # the actual saved repair (scoped to another item) leaves all four, so the repaired answer falls back
    v = res.report.validation
    assert v["repair_mode"] == "full" and v["fallback_applied"]
    assert _items(_final(res)) == ["headline", "missing_evidence[0]", "possible_explanations[0]", "uncertainties[0]"]


def test_3_k09s_rejected_caveats_are_not_shown_and_the_maximum_still_is():
    res, _ = _replay("K09")
    rep = res.report
    shown = " ".join([*rep.uncertainties, *rep.missing_evidence])
    assert "exceeded 10890.3" not in shown and "to confirm the absolute maximum" not in shown  # the rejected caveats
    # I-21: the fallback now states the controller's maximum and withholds every model note, including this faithful
    # one, which is recorded verbatim instead of shown (it was shown before I-21)
    assert not any(u.startswith("Operational demand (half-hour average) is a different measure") for u in rep.uncertainties)
    assert any(w["text"].startswith("Operational demand (half-hour average) is a different measure")
               for w in rep.validation["fallback_withheld"])
    assert rep.answer and "was highest at 10954.2 MW" in rep.answer[0].statement  # the computed answer (D25)
    assert not any("10890.3" in x or "10,890.3" in x for x in [rep.headline, *rep.summary, *rep.uncertainties])
    assert any(o.value == 10954.2 and o.valid_at_utc == MAX_END for o in rep.observations)


def test_2_a_faithful_full_repair_of_k09_is_shown():
    res, _ = _replay("K09", repair_fn=_k09(**FAITHFUL_K09))
    v = res.report.validation
    assert _items(_first(res))  # the saved first draft was rejected
    assert v["final_passed"] and not v["fallback_applied"], _final(res)
    assert res.report.headline.startswith("NSW1 dispatch total demand (TOTALDEMAND) was highest at 10954.2 MW")


# ------------------------------------------------------------------------------------------------ headline controls
@pytest.mark.parametrize("headline", [
    # a comparison that starts with another value and gives the maximum
    "NSW1 dispatch total demand was 10761.01 MW at the price peak (2026-07-29 20:05 AEST), below its maximum for the "
    "day, 10954.2 MW in the 5-minute interval ending 2026-07-29 19:05 AEST.",
    # another interval first, named as such, then the maximum
    "At 2026-07-29 19:35 AEST NSW1 dispatch total demand was 10890.3 MW; its maximum for the day was 10954.2 MW, in the "
    "5-minute interval ending 2026-07-29 19:05 AEST.",
    # only a value labelled as at the price peak (not presented as the maximum)
    "At the price peak (2026-07-29 20:05 AEST), NSW1 dispatch total demand was 10761.01 MW.",
    # another measure, named as such
    "NSW1 operational demand, a different measure, was 11079.0 MW in the half-hour ending 2026-07-29 19:00 AEST.",
    # a reference back to the price extreme the headline names, at its time (as held-out v6 Z04's headline does)
    "NSW1's highest five-minute dispatch price was at 2026-07-29 20:05 AEST; NSW1 dispatch total demand was 10761.01 MW "
    "at the same interval end.",
])
def test_2_headlines_that_do_not_present_another_value_as_the_maximum_pass(headline):
    res, _ = _replay("K09", _k09(**(FAITHFUL_K09 | {"headline": headline})))
    v = res.report.validation
    assert v["final_passed"] and not v.get("repair_attempted"), _first(res)


@pytest.mark.parametrize("headline,why", [
    ("NSW1 dispatch total demand was 10890.3 MW at 2026-07-29 19:35 AEST, before the price peak.",
     "gives 10890.3"),  # a relation to the price peak is not a label
    ("NSW1 dispatch total demand was 10890.3 MW at 2026-07-29 19:35 AEST, higher than the 10761.01 MW at the price "
     "peak.", "gives 10890.3"),  # another value first, and no maximum
    ("NSW1 demand reached 11079.0 MW in the half-hour ending 2026-07-29 19:00 AEST.",
     "gives 11079 (opdemand_actual"),  # another measure, unlabelled
    ("NSW1 dispatch total demand peaked in the interval ending 2026-07-29 19:35 AEST.",
     "2026-07-29 19:35 AEST, names another interval"),  # a time stated as the maximum
    ("NSW1's highest five-minute dispatch price was at 2026-07-29 20:05 AEST; NSW1 dispatch total demand was 10890.3 MW "
     "at the same interval end.", "gives 10890.3"),  # a reference back that the value's own time does not fit
])
def test_1_headlines_presenting_another_value_or_time_as_the_answer_are_rejected(headline, why):
    res, _ = _replay("K09", _k09(**(FAITHFUL_K09 | {"headline": headline})))
    first = _first(res)
    assert _items(first) == ["headline"], first
    assert why in next(d for c, d in first if c == "REQUESTED_MAXIMUM_MISMATCH")


def test_1_the_models_own_headline_is_checked_when_another_is_shown():
    """I-3c shows the controller's headline for timing and document answers; the model's own is kept and checked."""
    res, _ = _replay("K09", _k09(**FAITHFUL_K09))
    assert res.report.validation["final_passed"]
    rep = res.report.model_copy()
    rep._model_headline = "NSW1 dispatch total demand was 10890.3 MW at 2026-07-29 19:35 AEST."
    out = validate(rep, res.registry, records=res.records, window=res.resolution.window,
                   demand_max=res.resolution.demand_max)
    found = [(v.code, v.detail) for v in out.critical]
    assert [d.split(":", 1)[0] for c, d in found if c in I19] == ["headline (the model's own, not shown)"]
    rep._model_headline = FAITHFUL_K09["headline"]
    out = validate(rep, res.registry, records=res.records, window=res.resolution.window,
                   demand_max=res.resolution.demand_max)
    assert not [v for v in out.critical if v.code in I19]


# ------------------------------------------------------------------------------------------------ caveat controls
@pytest.mark.parametrize("field,text", [
    ("u0", "The TOTALDEMAND maximum cannot be confirmed against metered data; AEMO may later revise dispatch values."),
    ("u0", "Whether the TOTALDEMAND maximum is final cannot be established until AEMO's revisions are published."),
    ("u0", "The TOTALDEMAND maximum for the following day cannot be established from these data."),
    ("u0", "The TOTALDEMAND maximum after 2026-07-30T02:00:00Z cannot be established from these data."),
    ("u0", "VIC1 total demand's maximum on 29 July cannot be established from these data."),
    ("u0", "The NSW1 operational demand maximum cannot be confirmed from the dispatch TOTALDEMAND series."),
    ("u0", "The TOTALDEMAND maximum cannot be confirmed against other sources such as AEMO's live dashboards."),
    ("u0", "The reason TOTALDEMAND reached its peak at 2026-07-29 19:05 AEST cannot be established from these data."),
    ("u0", "No other five-minute TOTALDEMAND interval of the day exceeded the 10954.2 MW maximum."),
    ("m0", "Five-minute dispatch TOTALDEMAND for other regions, to confirm whether each region's maximum came at "
            "the same time."),
])
def test_2_legitimate_caveats_with_a_complete_maximum_pass(field, text):
    res, _ = _replay("K09", _k09(**(FAITHFUL_K09 | {field: text})))
    v = res.report.validation
    assert v["final_passed"] and not v.get("repair_attempted"), _first(res)


@pytest.mark.parametrize("field,text,code", [
    ("u0", "TOTALDEMAND peaked at 10890.3 MW in the retrieved data.", "REQUESTED_MAXIMUM_MISMATCH"),
    ("u0", "TOTALDEMAND may have peaked at 2026-07-29 19:35 AEST.", "REQUESTED_MAXIMUM_MISMATCH"),
    ("u0", "It is not certain that no other TOTALDEMAND interval exceeded 10890.3 MW.", "REQUESTED_MAXIMUM_DENIED"),
    ("u0", "The day's TOTALDEMAND maximum has not been confirmed.", "REQUESTED_MAXIMUM_DENIED"),
    ("m0", "The complete TOTALDEMAND series for 29 July 2026, to confirm the maximum.", "REQUESTED_MAXIMUM_DENIED"),
])
def test_1_caveats_contradicting_a_complete_maximum_are_rejected_and_not_shown(field, text, code):
    res, _ = _replay("K09", _k09(**(FAITHFUL_K09 | {field: text})))
    item = "uncertainties[0]" if field == "u0" else "missing_evidence[0]"
    first = _first(res)
    assert [(c, d.split(":", 1)[0]) for c, d in first if c in I19] == [(code, item)], first
    rep = res.report  # no repair is scripted, so it falls back without the rejected caveat
    assert res.report.validation["fallback_applied"]
    assert text[:30] not in " ".join([*rep.uncertainties, *rep.missing_evidence])


def test_2_an_incomplete_or_unavailable_maximum_may_be_called_not_established():
    res, _ = _replay("K09", _k09(**(FAITHFUL_K09 | {"u0": "The day's TOTALDEMAND maximum cannot be established."})))
    first = _first(res)
    assert [c for c, _ in first if c == "REQUESTED_MAXIMUM_DENIED"] == ["REQUESTED_MAXIMUM_DENIED"]  # complete here
    b = res.resolution.demand_max[0]
    report = res.report.model_copy(update={"uncertainties": ["The day's TOTALDEMAND maximum cannot be established."],
                                           "validation": {}})
    for binding in ({**b, "complete": False},
                    {k: v for k, v in b.items() if k not in ("value", "evidence_ids", "interval_ends_utc", "complete")}
                    | {"unavailable": "no value of the measure is held for the window"}):
        out = validate(report, res.registry, records=res.records, window=res.resolution.window, demand_max=[binding])
        assert "REQUESTED_MAXIMUM_DENIED" not in {v.code for v in out.critical}


def test_2_the_controllers_complete_sentence_passes():
    res, _ = _replay("K09", _k09(**FAITHFUL_K09))
    assert res.report.answer[0].statement.startswith(  # the computed answer (D25), apart from the summary
        "NSW1 dispatch total demand (TOTALDEMAND) was highest at 10954.2 MW")
    assert res.report.validation["final_passed"] and not res.report.validation.get("repair_attempted")


# ------------------------------------------------------------------------------------------------ K07 replayed
def _k07(*, extra: list[str] | None = None, faithful: bool = False, m0: str | None = None):
    """K07's saved draft, its four misnamed items rewritten (``faithful``) and lines added: a scripted variant."""
    def fn(kw):
        d = copy.deepcopy(_rec("K07")["drafts"]["synthesis:draft"])
        if faithful:
            d["summary"][1] = d["summary"][1].replace("ending 2026-08-06 17:00 AEST", "ending 2026-08-06 17:30 AEST")
            d["uncertainties"][1] = d["uncertainties"][1].replace(
                "interval ending 2026-08-06 17:00 AEST (2026-08-06T07:00:00Z)",
                "half-hour starting 2026-08-06 17:00 AEST (2026-08-06T07:00:00Z)")
            d["missing_evidence"][0] = d["missing_evidence"][0].replace("half-hour ending 2026-08-06 17:00 AEST",
                                                                        "half-hour starting 2026-08-06 17:00 AEST")
            d["missing_evidence"][1] = d["missing_evidence"][1].replace(
                "half-hour ending 2026-08-06 17:00 AEST (2026-08-06T07:00:00Z)", "half-hour 2026-08-06 17:00–17:30 AEST")
            # D27: the pair count of a 12-hour comparison under another run policy (the run asked for is not public
            # by the cutoff) is a comparison the question did not ask for, so the faithful variant does not list it
            d["observation_evidence_ids"] = [e for e in d["observation_evidence_ids"] if e != "ev0663"]
        if m0 is not None:
            d["missing_evidence"][0] = m0
        for line in extra or []:
            d["summary"].append(line)
            if "9505.0" in line:  # the 07:00Z half-hour's POE50 in the run published 2026-08-05T22:01:48Z
                d["numeric_claims"].append({"claim_id": "nb", "text": "9505.0 MW", "value": 9505.0, "unit": "MW",
                                            "evidence_id": "ev0424", "rounding": 0.05})
        return d
    return fn


def test_1_k07s_saved_draft_is_rejected_at_exactly_its_four_items_and_falls_back():
    res, fake = _replay("K07")
    scope = [(c, d) for c, d in _first(res) if c == "FORECAST_SCOPE_NOT_PRIMARY"]
    first = [(c, d) for c, d in _first(res) if c != "FORECAST_SCOPE_NOT_PRIMARY"]
    # D27: also the 12-hour comparison's pair count it lists, a comparison the question did not ask for
    assert [d.split(":")[0] for _, d in scope] == ["observation ev0663"]
    assert _items(first) == ["missing_evidence[0]", "missing_evidence[1]", "summary[1]", "uncertainties[1]"]
    assert all(c == "REQUESTED_INTERVAL_MISNAMED" for c, _ in first)
    assert all("ending 2026-08-06 17:00 AEST, but it is the half-hour from 2026-08-06T07:00:00Z to "
               "2026-08-06T07:30:00Z" in d for _, d in first)
    ctx = json.loads(fake.requests[1]["input"][0]["content"].split("\n", 1)[1])["requested_forecast_run"]
    assert ctx["half_hour_utc"] == list(HALF)  # the model had been given the half-hour
    # there was no repair: it falls back, and the rejected caveats are not shown
    rep = res.report
    assert res.report.validation["fallback_applied"]
    assert "17:00 AEST" not in " ".join([rep.headline, *rep.summary, *rep.uncertainties, *rep.missing_evidence])
    assert any(u.startswith("Which exact run is the 'last run issued before the half-hour'")
               for u in rep.uncertainties)  # the caveat no violation names is kept


def test_2_k07_named_correctly_passes_and_a_faithful_repair_is_shown():
    res, _ = _replay("K07", _k07(faithful=True))
    assert res.report.validation["final_passed"] and not res.report.validation.get("repair_attempted"), _first(res)
    res, _ = _replay("K07", repair_fn=_k07(faithful=True))
    assert _items(_first(res)) and res.report.validation["final_passed"]
    assert "half-hour ending 2026-08-06 17:30 AEST" in " ".join(res.report.summary)


@pytest.mark.parametrize("line", [
    "The previous half-hour, ending 2026-08-06 17:00 AEST, is not part of the question.",
    "The next half-hour, starting 2026-08-06 17:30 AEST, is not part of the question.",
    "The half-hour ending 2026-08-06 15:00 AEST is outside the question.",  # another half-hour
    "The 5-minute interval ending 2026-08-06 17:00 AEST is not used.",
    "No run issued before 2026-08-06 17:00 AEST was public by the cutoff.",  # an issue time
    # the previous half-hour named together with the one asked about (as held-out v5 Y06's explanation does)
    "Demand may have stepped up more than forecast between the half-hours ending 2026-08-06 17:00 AEST and "
    "2026-08-06 17:30 AEST.",
])
def test_2_neighbouring_half_hours_and_issue_times_pass(line):
    res, _ = _replay("K07", _k07(faithful=True, extra=[line]))
    assert res.report.validation["final_passed"] and not res.report.validation.get("repair_attempted"), _first(res)


def test_2_a_neighbouring_half_hours_own_value_is_not_stated_since_d28():
    """It passed I-19 (its own traced value, named by its own half-hour) and still does; since D28 a one-half-hour
    request states values of that half-hour only, so the neighbouring half-hour's POE50 is outside what it asks."""
    res, _ = _replay("K07", _k07(faithful=True, extra=["The half-hour ending 2026-08-06 17:00 AEST had a POE50 "
                                                        "forecast of 9505.0 MW."]))
    ev = res.registry.get("ev0424")
    assert (ev.metric, ev.value, ev.valid_at_utc) == ("opdemand_forecast_poe50", 9505.0, HALF[0])
    first = _first(res)
    assert not [d for c, d in first if c in I19]
    assert [d.split(":")[0] for c, d in first if c == "FORECAST_SCOPE_NOT_PRIMARY"] == ["nb"]


@pytest.mark.parametrize("extra,m0,item", [
    (["The half-hour starting 2026-08-06 17:30 AEST is the one asked about."], None, "summary[2]"),
    (None, "No run issued prior to the half-hour ending 2026-08-06 17:00 AEST was public by the cutoff.",
     "missing_evidence[0]"),
])
def test_1_the_end_named_as_a_start_or_the_start_as_an_end_is_rejected(extra, m0, item):
    res, _ = _replay("K07", _k07(faithful=True, extra=extra, m0=m0))
    assert _items(_first(res)) == [item]


def test_violations_name_their_exact_item():
    """Each I-19 violation starts with the item it is about, as repair and the fallback read them."""
    found = _first(_replay("K09")[0]) + _first(_replay("K07")[0])
    items = {d.split(":", 1)[0] for c, d in found if c in I19}
    assert items == {"headline", "possible_explanations[0]", "uncertainties[0]", "missing_evidence[0]", "summary[1]",
                     "uncertainties[1]", "missing_evidence[1]"}
