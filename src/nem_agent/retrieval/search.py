"""Eligibility-filtered hybrid search.

Order of operations (eligibility is applied BEFORE ranking, so ineligible text can never be ranked or quoted):

1. **Eligibility**: document type; publication time <= ``as_of`` (unknown publication time is ineligible in an
   as-of view); event-specific documents (market notices, event reports) are eligible only when the query is
   scoped to a region and window that match the document's region and date (±1 day).
2. **Candidates**: BM25 over FTS5 and cosine similarity over vectors, each limited to the eligible set (top 30).
3. **Fusion**: reciprocal-rank fusion (k = 60).
4. **Rerank** of the fused top candidates: query-term coverage plus a bonus for a definitional sentence about the
   queried term ("<term> ... is/means/refers to"). Deterministic and labelled; not a learned reranker.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from .. import config, paths
from ..timeutil import NEM_TZ, parse_iso
from .embed import Embedder, load_model2vec

EVENT_SPECIFIC = {"market_notice", "event_report"}
DEFN_WORDS = {"definition", "define", "defined", "meaning", "explain", "explained", "term", "terms", "data", "s", "nem",
              "used", "use", "context", "field", "value"}
DEFN_QUERY_RE = re.compile(r"\b(definition|define[sd]?|meaning|what (is|are|does)|mean(s)? by|explain)\b", re.I)
STOP = {"the", "a", "an", "of", "and", "or", "in", "on", "for", "to", "is", "are", "was", "what", "does", "do", "how",
        "did", "this", "that", "with", "by", "at", "as", "be", "it", "from", "about", "which", "mean", "means", "aemo"}


class IndexMissingError(RuntimeError):
    pass


@lru_cache(maxsize=4)
def _load(index_dir: str, stamp: float) -> tuple[list[dict[str, Any]], Any, Embedder, dict[str, Any]]:
    d = Path(index_dir)
    manifest = json.loads((d / "index_manifest.json").read_text())
    con = sqlite3.connect(d / "corpus.sqlite")
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT * FROM chunks ORDER BY rowid")]
    con.close()
    vecs = np.load(d / "embeddings.npy")
    owner = np.load(d / "vector_owner.npy")
    info = manifest["embedder"]
    if info["backend"] == "model2vec":
        emb = load_model2vec(allow_download=False)
    else:
        z = np.load(d / "fallback_svd.npz")
        emb = Embedder("lexical-svd-fallback", info["model_id"], None, _svd={"idf": z["idf"], "components": z["components"]})
    return rows, (vecs, owner), emb, manifest


def load_index(index_dir: Path | None = None) -> tuple[list[dict[str, Any]], Any, Embedder, dict[str, Any]]:
    d = index_dir or paths.index_dir()
    m = d / "index_manifest.json"
    if not m.exists():
        raise IndexMissingError(f"no document index at {d}; run `make index`")
    return _load(str(d), m.stat().st_mtime)


def indexed_doc_ids(index_dir: Path | None = None) -> set[str]:
    rows, _vecs, _emb, _m = load_index(index_dir)
    return {r["doc_id"] for r in rows}


def eligibility(row: dict[str, Any], *, region: str | None, event_start: datetime | None, event_end: datetime | None,
                as_of: datetime | None, doc_types: list[str] | None) -> tuple[bool, str]:
    if doc_types and row["doc_type"] not in doc_types:
        return False, "doc_type_filtered"
    if as_of is not None:
        if not row["publication_date"]:
            return False, "publication_time_unknown_in_as_of_view"
        if parse_iso(row["publication_date"]) > as_of:
            return False, "published_after_as_of"
    if row["doc_type"] in EVENT_SPECIFIC:
        if region is None or event_start is None or event_end is None:
            return False, "event_document_requires_region_and_window"
        if row["event_region"] != region:
            return False, "wrong_region"
        if not row["event_date"]:
            return False, "event_date_unknown"
        d = datetime.fromisoformat(row["event_date"]).date()
        lo = (event_start.astimezone(NEM_TZ) - timedelta(days=1)).date()
        hi = (event_end.astimezone(NEM_TZ) + timedelta(days=1)).date()
        if not lo <= d <= hi:
            return False, "wrong_date"
        return True, f"{row['doc_type']} for {region} dated {row['event_date']} within the event window ±1 day"
    return True, "general reference document" + (" published before as_of" if as_of else "")


def _fts_query(q: str) -> str:
    toks = [t for t in re.findall(r"[A-Za-z0-9_]+", q.lower()) if t not in STOP and len(t) > 1]
    return " OR ".join(f'"{t}"' for t in toks[:24]) or '"demand"'


def search(query: str, *, region: str | None = None, event_start: datetime | None = None,
           event_end: datetime | None = None, as_of: datetime | None = None, top_k: int = 5,
           doc_types: list[str] | None = None, index_dir: Path | None = None) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows, vecs, emb, _manifest = load_index(index_dir)
    excluded: dict[str, int] = {}
    reasons: dict[int, str] = {}
    for i, r in enumerate(rows):
        ok, why = eligibility(r, region=region, event_start=event_start, event_end=event_end, as_of=as_of,
                              doc_types=doc_types)
        if ok:
            reasons[i] = why
        else:
            excluded[why] = excluded.get(why, 0) + 1
    allowed = np.array(sorted(reasons), dtype=np.int64)
    if not len(allowed):
        return [], excluded
    # BM25 candidates (restricted to eligible rowids)
    d = index_dir or paths.index_dir()
    con = sqlite3.connect(d / "corpus.sqlite")
    allowed_rowids = {int(i) + 1 for i in allowed}
    bm = [(rid - 1, score) for rid, score in con.execute(
        "SELECT rowid, bm25(chunks_fts, 0.5, 3.0, 1.0) FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY 2 LIMIT 400",
        [_fts_query(query)]) if rid in allowed_rowids][:30]
    con.close()
    phrase = " ".join(t for t in re.findall(r"[a-z0-9_]+", query.lower()) if t not in STOP | DEFN_WORDS)
    is_defn_query = bool(DEFN_QUERY_RE.search(query)) and bool(phrase)
    # Definition-style questions: the dense query also carries the templated form "<term> is defined as".
    qv = emb.encode([query + (f". {phrase} is defined as" if is_defn_query else "")])[0]
    mat, owner = vecs
    sims = mat @ qv
    best: dict[int, float] = {}
    allowed_set = set(int(i) for i in allowed)
    for vi in np.argsort(-sims):
        ci = int(owner[vi])
        if ci in allowed_set and ci not in best:
            best[ci] = float(sims[vi])
            if len(best) >= 30:
                break
    dense = sorted(best.items(), key=lambda kv: -kv[1])
    fused: dict[int, float] = {}
    for rank, (i, _) in enumerate(bm):
        fused[i] = fused.get(i, 0.0) + 1.0 / (60 + rank + 1)
    for rank, (i, _) in enumerate(dense):
        fused[i] = fused.get(i, 0.0) + 1.0 / (60 + rank + 1)
    terms = [t for t in re.findall(r"[a-z0-9_]+", query.lower()) if t not in STOP and len(t) > 2]
    cands = sorted(fused, key=lambda i: -fused[i])[:50]

    # a definitional sentence: the term starts a sentence and is followed by is/are/means/refers to
    defn = re.compile(rf"(?:^|[.:;]\s+|\u201c)(?:the )?{re.escape(phrase)}(?: in a region| \([^)]{{0,40}}\))?\s+"
                      r"(?:is|are|means|refers to)\b", re.I) if phrase else None

    def rerank(i: int) -> float:
        txt = (rows[i]["title"] + " " + (rows[i]["section"] or "") + " " + rows[i]["text"]).lower()
        cov = sum(1 for t in set(terms) if t in txt) / max(1, len(set(terms)))
        is_defn = bool(defn and defn.search(rows[i]["text"]))  # definitional sentence about the queried term
        return fused[i] + 0.01 * cov + (0.03 if is_defn and is_defn_query else 0.0)

    ranked = sorted(cands, key=lambda i: (-rerank(i), rows[i]["chunk_id"]))[: max(1, min(top_k, config.MAX_RETRIEVAL_TOP_K))]
    budget = config.MAX_RETRIEVED_CHARS
    hits = []
    for i in ranked:
        r = rows[i]
        text = r["text"][: max(200, min(len(r["text"]), budget))]
        budget -= len(text)
        hits.append({
            "chunk_id": r["chunk_id"], "doc_id": r["doc_id"], "title": r["title"], "url": r["url"], "text": text,
            "section": r["section"], "page": r["page"], "publication_date": r["publication_date"], "doc_type": r["doc_type"],
            "event_region": r["event_region"], "event_date": r["event_date"], "eligible": True,
            "eligibility_reason": reasons[i], "score": round(rerank(i), 5), "instruction_like": bool(r["instruction_like"]),
        })
        if budget <= 0:
            break
    return hits, excluded
