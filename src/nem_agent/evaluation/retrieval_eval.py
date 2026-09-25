"""Retrieval evaluation on the human-reviewed gold fixture (`eval/retrieval_gold.json`)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import paths
from ..retrieval.search import load_index, search
from ..timeutil import parse_iso


def _relevant(hit: dict[str, Any], rel: dict[str, str], full_text: dict[str, str]) -> bool:
    return hit["doc_id"] == rel["doc_id"] and rel["snippet"] in full_text[hit["chunk_id"]]


def evaluate(gold_path: Path | None = None, k: int = 5, index_dir: Path | None = None) -> dict[str, Any]:
    gold = json.loads((gold_path or paths.repo_root() / "eval" / "retrieval_gold.json").read_text())
    rows, _, _, manifest = load_index(index_dir)
    full = {r["chunk_id"]: r["text"] for r in rows}
    indexed = {r["doc_id"] for r in rows}
    per_q = []
    found_total = rel_total = hit_q = unavailable = 0
    rr_sum = 0.0
    for q in gold["queries"]:
        f = q.get("filters", {})
        hits, _excluded = search(q["query"], region=f.get("region"),
                                event_start=parse_iso(f["event_start_utc"]) if f.get("event_start_utc") else None,
                                event_end=parse_iso(f["event_end_utc"]) if f.get("event_end_utc") else None,
                                as_of=parse_iso(f["as_of_utc"]) if f.get("as_of_utc") else None,
                                top_k=k, doc_types=f.get("doc_types"), index_dir=index_dir)
        gone = [rel for rel in q["relevant"] if rel["doc_id"] not in indexed]  # rolled off the publisher
        unavailable += len(gone)
        labelled = [rel for rel in q["relevant"] if rel["doc_id"] in indexed]
        found = [rel for rel in labelled if any(_relevant(h, rel, full) for h in hits[:k])]
        first = next((i + 1 for i, h in enumerate(hits[:k]) if any(_relevant(h, rel, full) for rel in q["relevant"])), None)
        found_total += len(found)
        rel_total += len(labelled)
        if not labelled:
            per_q.append({"qid": q["qid"], "query": q["query"], "corpus_unavailable": True, "relevant": 0, "found": 0})
            continue
        hit_q += first is not None
        rr_sum += 1.0 / first if first else 0.0
        per_q.append({"qid": q["qid"], "query": q["query"], "found": len(found), "relevant": len(labelled),
                      "first_relevant_rank": first, "top_ids": [h["chunk_id"] for h in hits[:k]],
                      "missed": [r for r in q["relevant"] if r not in found]})
    n = sum(1 for q in per_q if not q.get("corpus_unavailable"))
    return {
        "labelled_items_unavailable_in_corpus": unavailable,
        "queries_unavailable_in_corpus": sum(1 for q in per_q if q.get("corpus_unavailable")),
        "k": k, "corpus_version": manifest["corpus_version"], "embedder": manifest["embedder"],
        "recall_at_k": {"numerator": found_total, "denominator": rel_total,
                        "value": round(found_total / rel_total, 4) if rel_total else None,
                        "definition": "labelled (doc, snippet) items found in top-k / all labelled items (micro)"},
        "hit_at_k": {"numerator": hit_q, "denominator": n, "value": round(hit_q / n, 4) if n else None},
        "mrr_at_k": {"sum_reciprocal_rank": round(rr_sum, 4), "denominator": n, "value": round(rr_sum / n, 4) if n else None},
        "per_query": per_q,
    }
