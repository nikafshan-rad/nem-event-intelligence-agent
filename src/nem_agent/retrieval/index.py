"""Build the hybrid index: SQLite FTS5 (BM25) + dense vectors, with a reproducible corpus version."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from .. import paths
from ..selection import Selection, load_selection
from ..timeutil import iso_utc
from .corpus import Chunk, build_corpus, split_sentences
from .embed import Embedder, fit_lexical_fallback, load_model2vec

SCHEMA = """
CREATE TABLE chunks (rowid INTEGER PRIMARY KEY, chunk_id TEXT UNIQUE, doc_id TEXT, title TEXT, url TEXT, doc_type TEXT,
  publication_date TEXT, event_region TEXT, event_date TEXT, page INTEGER, section TEXT, text TEXT, chunk_hash TEXT,
  source_sha256 TEXT, instruction_like INTEGER);
CREATE VIRTUAL TABLE chunks_fts USING fts5(title, section, text, content='chunks', content_rowid='rowid',
  tokenize='porter unicode61');
"""


def get_embedder(corpus_texts: list[str], allow_download: bool = True, log: Any = print) -> Embedder:
    try:
        return load_model2vec(allow_download=allow_download)
    except Exception as exc:  # network/model failure -> documented, labelled fallback
        log(f"[index] model2vec unavailable ({type(exc).__name__}: {exc}); using lexical-svd-fallback vectors")
        return fit_lexical_fallback(corpus_texts)


def write_index(chunks: list[Chunk], embedder: Embedder, out_dir: Path, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    db = out_dir / "corpus.sqlite"
    if db.exists():
        db.unlink()
    chunks = sorted(chunks, key=lambda c: c.chunk_id)
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    for i, c in enumerate(chunks, start=1):
        con.execute("INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (i, c.chunk_id, c.doc_id, c.title, c.url, c.doc_type, c.publication_date, c.event_region, c.event_date,
                     c.page, c.section, c.text, c.chunk_hash, c.source_sha256, int(c.instruction_like)))
    con.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild')")
    con.commit()
    con.close()
    # Multi-vector: one vector for the whole chunk plus one per sentence; a chunk's dense score is the max
    # over its vectors (static embeddings dilute a defining sentence inside a long chunk).
    texts: list[str] = []
    owner: list[int] = []
    for i, c in enumerate(chunks):
        texts.append(f"{c.section or ''}. {c.text}")
        owner.append(i)
        for sent in split_sentences(c.text):
            texts.append(sent)
            owner.append(i)
    vecs = embedder.encode(texts) if texts else np.zeros((0, 1), dtype=np.float32)
    np.save(out_dir / "embeddings.npy", vecs)
    np.save(out_dir / "vector_owner.npy", np.asarray(owner, dtype=np.int64))
    if embedder.backend != "model2vec" and embedder._svd is not None:
        np.savez(out_dir / "fallback_svd.npz", idf=embedder._svd["idf"], components=embedder._svd["components"])
    corpus_version = hashlib.sha256(json.dumps(
        {"chunks": [(c.chunk_id, c.chunk_hash) for c in chunks], "embedder": embedder.info()}, sort_keys=True
    ).encode()).hexdigest()[:16]
    by_type: dict[str, int] = {}
    for c in chunks:
        by_type[c.doc_type] = by_type.get(c.doc_type, 0) + 1
    manifest = {"corpus_version": corpus_version, "built_at": iso_utc(datetime.now(UTC)), "n_chunks": len(chunks),
                "n_docs": len({c.doc_id for c in chunks}), "chunks_by_doc_type": by_type,
                "instruction_like_chunks": sum(c.instruction_like for c in chunks),
                "embedder": embedder.info(), "vector_dim": int(vecs.shape[1]) if len(vecs) else 0,
                "n_vectors": len(texts), "dense_scoring": "max cosine over chunk + sentence vectors", **(extra or {})}
    (out_dir / "index_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def build_index(sel: Selection | None = None, out_dir: Path | None = None, allow_download: bool = True,
                log: Any = print) -> dict[str, Any]:
    sel = sel or load_selection()
    chunks, status = build_corpus(sel, log=log)
    emb = get_embedder([c.text for c in chunks], allow_download=allow_download, log=log)
    manifest = write_index(chunks, emb, out_dir or paths.index_dir(),
                           extra={"sources": status,
                                  "failed_sources": [s for s in status if not s["ok"] and not s.get("rolled_off")],
                                  "rolled_off_sources": [s["source_id"] for s in status if s.get("rolled_off")],
                                  "pin_status_counts": dict(Counter(s.get("pin_status", "unknown") for s in status))})
    log(f"[index] corpus_version={manifest['corpus_version']} chunks={manifest['n_chunks']} docs={manifest['n_docs']} "
        f"by_type={manifest['chunks_by_doc_type']} embedder={manifest['embedder']['backend']} "
        f"rolled_off={len(manifest['rolled_off_sources'])}")
    return manifest
