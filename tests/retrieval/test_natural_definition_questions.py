"""Held-out v4 W20: a natural definition question missed the definition (held-out v4 is development data from this fix
on).

The controller's retrieval of W20's question ("Could you explain how AEMO defines operational demand for a region,
meaning what gets counted and what is left out?") took every remaining word as the queried term ("could you defines
operational demand region gets counted left out"), so the definitional rerank never matched the definition, and the
passage that opens with it ranked 30th of the candidates. The term a definition cue names ("defines X", "definition
of X", "meaning of X") is now taken up to the next joining word or punctuation. The rules for quoted terms and for
questions without a cue are unchanged, and eligibility filters still apply before ranking.
"""

from __future__ import annotations

import pytest

from nem_agent.retrieval.search import IndexMissingError, defn_phrase, load_index, search
from nem_agent.timeutil import parse_iso

W20_QUESTION = ("Could you explain how AEMO defines operational demand for a region, meaning what gets counted and what "
                "is left out?")
SA_WIN = (parse_iso("2026-07-30T04:30:00Z"), parse_iso("2026-07-31T05:00:00Z"))


@pytest.fixture(scope="module")
def index_ready():
    try:
        return load_index()
    except IndexMissingError as exc:
        pytest.skip(str(exc))


def test_the_term_a_definition_cue_names():
    assert defn_phrase(W20_QUESTION) == "operational demand"
    assert defn_phrase("How does AEMO define native demand for a region, and what does it leave out?") == "native demand"
    assert defn_phrase("What is the definition of operational demand in a region according to AEMO?") == \
        "operational demand"
    assert defn_phrase("I'd like the meaning of native demand when AEMO reports it by region.") == "native demand"
    assert defn_phrase("Can you define scheduled demand?") == "scheduled demand"


def test_terms_without_a_cue_are_unchanged():
    assert defn_phrase("What does operational demand mean?") == "operational demand"
    assert defn_phrase("What is AEMO's operational demand?") == "operational demand"
    assert defn_phrase("In plain terms, what counts towards 'operational demand' here?") == "operational demand"
    assert defn_phrase('operational demand definition "operational demand" AEMO definition') == "operational demand"
    assert defn_phrase("How is operational demand defined?") == "operational demand"  # passive: no cue, same as before
    assert defn_phrase('How does AEMO define "native demand" for a region?') == "native demand"  # a quote still wins
    assert defn_phrase("Can you define it?") == "can you"  # a cue naming only stop words falls back, as before


@pytest.mark.parametrize("question,definition", [
    (W20_QUESTION, "aemo_demand_terms#p9c11"),
    ("How does AEMO define native demand for a region, and what does it leave out?", "aemo_demand_terms#p9c10"),
    ("Can you tell me how AEMO defines scheduled demand in its data model, including what is excluded?",
     "aemo_demand_terms#p12c20"),
    ("What is the definition of operational demand in a region according to AEMO?", "aemo_demand_terms#p9c11"),
    ("I'd like the meaning of native demand when AEMO reports it by region.", "aemo_demand_terms#p9c10"),
    ("Could you explain how the pre-dispatch procedure defines registration data, and who submits it?",
     "aemo_so_op_3704#p5c9"),
])
def test_natural_definition_questions_rank_the_definition_first(index_ready, question, definition):
    """Before this fix these ranked the definition 30th of the candidates (W20), 2nd, 2nd, below the top 8, 2nd and
    7th; the controller retrieves the question's top 8."""
    hits, _ = search(question, top_k=8)
    assert hits[0]["chunk_id"] == definition, [h["chunk_id"] for h in hits]


@pytest.mark.synthetic
def test_w20_question_retrieves_the_definition_beside_the_synthetic_injection(index_ready):
    """As in the v4 run, with the runner's SYNTHETIC instruction-bearing passage in the index: the definition is among
    the eight passages the controller retrieves, and the injected passage is still flagged as instruction-like."""
    from nem_agent.evaluation.runner import synthetic_injection_index

    with synthetic_injection_index():
        hits, _ = search(W20_QUESTION, top_k=8)
    ids = [h["chunk_id"] for h in hits]
    assert "aemo_demand_terms#p9c11" in ids, ids
    assert all(h["instruction_like"] for h in hits if h["chunk_id"] == "synthetic_injection#0")


def test_filters_still_apply_before_ranking(index_ready):
    """Passes before and after the fix: a definition cue changes ranking only, never eligibility."""
    q = "How does AEMO define operational demand for a region, and what is left out?"
    before_paper = parse_iso("2025-07-01T00:00:00Z")  # before the Demand Terms paper was published
    hits, excluded = search(q, as_of=before_paper, top_k=8)
    assert hits and not any(h["doc_id"] == "aemo_demand_terms" for h in hits)
    assert all(parse_iso(h["publication_date"]) <= before_paper for h in hits) and excluded["published_after_as_of"]
    hits, excluded = search(q, doc_types=["procedure"], top_k=8)
    assert hits and {h["doc_type"] for h in hits} == {"procedure"} and excluded["doc_type_filtered"]
    hits, excluded = search(q, region="SA1", event_start=SA_WIN[0], event_end=SA_WIN[1], top_k=8)
    notices = [h for h in hits if h["doc_type"] in ("market_notice", "event_report")]
    assert all(h["event_region"] == "SA1" and "2026-07-29" <= h["event_date"] <= "2026-08-01" for h in notices)
    assert excluded.get("wrong_region")
