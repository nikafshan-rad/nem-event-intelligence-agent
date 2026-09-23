"""Embeddings for hybrid retrieval.

Primary: a pinned model2vec static embedding model (``minishlab/potion-retrieval-32M``, MIT licence), which is
distilled from a sentence-transformer and runs locally with numpy (no torch). If it cannot be downloaded, the
index falls back to **lexical-derived vectors** (hashed TF-IDF reduced by SVD). The index manifest names the
backend, and the fallback is never described as a neural embedding model.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Any

import numpy as np

from .. import paths

MODEL_ID = "minishlab/potion-retrieval-32M"
MODEL_REVISION = "6fc8051fab2a1e0ee76689cf08c853792ac285e7"  # pinned; see docs/decisions.md


@dataclass
class Embedder:
    backend: str  # "model2vec" | "lexical-svd-fallback"
    model_id: str
    revision: str | None
    _model: Any = None
    _svd: Any = None  # (vocab_dim, components) for the fallback

    def encode(self, texts: list[str]) -> np.ndarray:
        if self.backend == "model2vec":
            vecs = np.asarray(self._model.encode(texts), dtype=np.float32)
        else:
            vecs = _hashed_tfidf(texts, self._svd["idf"]) @ self._svd["components"]
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (vecs / norms).astype(np.float32)

    def info(self) -> dict[str, Any]:
        return {"backend": self.backend, "model_id": self.model_id, "revision": self.revision,
                "is_neural_embedding": self.backend == "model2vec"}


def load_model2vec(allow_download: bool = True) -> Embedder:
    from huggingface_hub import snapshot_download
    from model2vec import StaticModel

    local = snapshot_download(MODEL_ID, revision=MODEL_REVISION, cache_dir=str(paths.models_dir()),
                              local_files_only=not allow_download,
                              allow_patterns=["config.json", "model.safetensors", "modules.json", "tokenizer.json",
                                              "special_tokens_map.json", "README.md"])
    model = StaticModel.from_pretrained(local)
    return Embedder("model2vec", MODEL_ID, MODEL_REVISION, _model=model)


# ------------------------------------------------------------------------------------ lexical fallback
_TOKEN = re.compile(r"[a-z0-9]+")
DIM = 2 ** 14


def _hashed_tfidf(texts: list[str], idf: np.ndarray) -> np.ndarray:
    m = np.zeros((len(texts), DIM), dtype=np.float32)
    for i, t in enumerate(texts):
        for tok in _TOKEN.findall(t.lower()):
            h = int(hashlib.md5(tok.encode()).hexdigest()[:8], 16) % DIM
            m[i, h] += 1.0
    m = np.log1p(m) * idf
    return m


def fit_lexical_fallback(corpus_texts: list[str], k: int = 128) -> Embedder:
    df = np.zeros(DIM, dtype=np.float32)
    for t in corpus_texts:
        for h in {int(hashlib.md5(tok.encode()).hexdigest()[:8], 16) % DIM for tok in _TOKEN.findall(t.lower())}:
            df[h] += 1
    idf = np.log((1 + len(corpus_texts)) / (1 + df)) + 1.0
    x = _hashed_tfidf(corpus_texts, idf)
    k = min(k, min(x.shape) - 1) if min(x.shape) > 1 else 1
    _, _, vt = np.linalg.svd(x - 0.0, full_matrices=False)
    comps = vt[:k].T.astype(np.float32)
    return Embedder("lexical-svd-fallback", "hashed-tfidf+svd", None, _svd={"idf": idf, "components": comps})


def cosine_top(query_vec: np.ndarray, mat: np.ndarray, allowed: np.ndarray, k: int) -> list[tuple[int, float]]:
    if not len(allowed):
        return []
    sims = mat[allowed] @ query_vec
    order = np.argsort(-sims)[:k]
    return [(int(allowed[i]), float(sims[i])) for i in order if not math.isnan(float(sims[i]))]
