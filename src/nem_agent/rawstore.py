"""Raw publisher-file cache with an append-only manifest.

* Files are stored under ``data/raw/<dataset>/<file name>`` exactly as downloaded (immutable bytes).
* A sidecar ``<file>.meta.json`` keeps the *original* retrieval facts (URL, HTTP status, headers,
  retrieval time, SHA-256). Reuse of a cached copy is logged as a ``cache_hit`` with the original
  retrieval time, never disguised as a fresh download.
* ``data/manifest/raw_manifest.jsonl`` is append-only: one JSON line per fetch attempt / cache use.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from . import paths
from .http import fetch
from .timeutil import iso_utc


@dataclass
class RawFile:
    dataset: str
    url: str
    local_path: str
    sha256: str | None
    size: int | None
    http_status: int | None
    content_type: str | None
    last_modified: str | None
    retrieved_at: str | None  # original retrieval time of the bytes on disk
    status: str  # downloaded | cache_hit | cache_fallback | failed
    error: str | None = None

    @property
    def available(self) -> bool:
        return self.status in {"downloaded", "cache_hit", "cache_fallback", "recovered_from_archive"} and \
            self.sha256 is not None

    @property
    def rolled_off(self) -> bool:
        """The publisher answered 404 for a NEMWeb Current URL (rolling retention), as opposed to a real error."""
        return self.status == "failed" and self.http_status == 404 and "/reports/current/" in self.url.lower()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# API responses whose bytes carry volatile metadata. Their identity is a canonical content hash; every other
# publisher file keeps strict byte identity (raw SHA-256).
VOLATILE_JSON_KEYS: dict[str, tuple[str, ...]] = {"NASA_POWER_HOURLY": ("times",)}


def content_sha256(dataset: str, data: bytes) -> str | None:
    """Canonical hash of an API response with volatile keys removed (None for byte-identified datasets)."""
    keys = VOLATILE_JSON_KEYS.get(dataset)
    if keys is None:
        return None
    doc = json.loads(data)
    for k in keys:
        doc.pop(k, None)
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _matches(dataset: str, data_sha: str, data: bytes | None, expected_sha256: str | None,
             expected_content: str | None) -> bool:
    if expected_sha256 is None or data_sha == expected_sha256:
        return True
    return expected_content is not None and data is not None and content_sha256(dataset, data) == expected_content


def local_path_for(dataset: str, url: str) -> Path:
    name = unquote(Path(urlparse(url).path).name) or "index"
    query = urlparse(url).query
    if query:
        name = f"{name}__{hashlib.sha1(query.encode()).hexdigest()[:12]}.json"
    return paths.raw_dir() / dataset / name


def _append_manifest(entry: dict) -> None:
    mp = paths.manifest_path()
    mp.parent.mkdir(parents=True, exist_ok=True)
    with mp.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def _now() -> str:
    return iso_utc(datetime.now(UTC))


def get(
    dataset: str,
    url: str,
    *,
    expected_sha256: str | None = None,
    expected_content_sha256: str | None = None,
    refresh: bool = False,
    max_bytes: int = 60 * 1024 * 1024,
    timeout: float = 120.0,
) -> RawFile:
    """Return a cached or freshly downloaded publisher file. Never fabricates content."""
    path = local_path_for(dataset, url)
    meta_path = path.with_name(path.name + ".meta.json")
    cached_meta: dict | None = None
    if path.exists() and meta_path.exists():
        cached_meta = json.loads(meta_path.read_text())
        actual = sha256_file(path)
        if actual != cached_meta.get("sha256"):
            cached_meta = None  # corrupted cache: ignore it
        elif not _matches(dataset, actual, path.read_bytes(), expected_sha256, expected_content_sha256):
            cached_meta = None
    if cached_meta and not refresh:
        rf = RawFile(
            dataset=dataset, url=url, local_path=str(path), sha256=cached_meta["sha256"], size=cached_meta["size"],
            http_status=cached_meta.get("http_status"), content_type=cached_meta.get("content_type"),
            last_modified=cached_meta.get("last_modified"), retrieved_at=cached_meta["retrieved_at"], status="cache_hit",
        )
        _append_manifest({"event": "cache_hit", "at": _now(), **asdict(rf)})
        return rf

    res = fetch(url, timeout=timeout, max_bytes=max_bytes)
    if res.ok and res.body is not None:
        digest = hashlib.sha256(res.body).hexdigest()
        if not _matches(dataset, digest, res.body, expected_sha256, expected_content_sha256):
            err = f"sha256 mismatch: expected {expected_sha256}, got {digest}"
            rf = RawFile(dataset, url, str(path), digest, len(res.body), res.status, res.content_type,
                         res.last_modified, None, "failed", err)
            _append_manifest({"event": "checksum_mismatch", "at": _now(), **asdict(rf)})
            return _fallback(rf, path, meta_path, expected_sha256, expected_content_sha256)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        tmp.write_bytes(res.body)
        tmp.replace(path)
        meta: dict[str, Any] = {
            "url": url, "sha256": digest, "size": len(res.body), "http_status": res.status,
            "content_type": res.content_type, "last_modified": res.last_modified, "retrieved_at": _now(),
            "attempts": res.attempts, "content_sha256": content_sha256(dataset, res.body),
            "verified_by": ("raw_sha256" if expected_sha256 in (None, digest) else "content_sha256 (volatile API "
                            "metadata differs from the recorded bytes; values verified)"),
        }
        meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True))
        rf = RawFile(dataset, url, str(path), digest, len(res.body), res.status, res.content_type,
                     res.last_modified, meta["retrieved_at"], "downloaded")
        _append_manifest({"event": "download", "at": _now(), **asdict(rf)})
        return rf

    rf = RawFile(dataset, url, str(path), None, None, res.status, res.content_type, res.last_modified, None,
                 "failed", res.error or f"HTTP {res.status}")
    _append_manifest({"event": "fetch_failed", "at": _now(), **asdict(rf)})
    return _fallback(rf, path, meta_path, expected_sha256, expected_content_sha256)


def _fallback(failed: RawFile, path: Path, meta_path: Path, expected_sha256: str | None,
              expected_content_sha256: str | None = None) -> RawFile:
    """After a failed fetch, reuse a previously verified cached copy (clearly labelled) if one exists."""
    if path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text())
        actual = sha256_file(path)
        if actual == meta.get("sha256") and _matches(failed.dataset, actual, path.read_bytes(), expected_sha256,
                                                      expected_content_sha256):
            rf = RawFile(failed.dataset, failed.url, str(path), actual, meta["size"], meta.get("http_status"),
                         meta.get("content_type"), meta.get("last_modified"), meta["retrieved_at"], "cache_fallback",
                         f"live fetch failed ({failed.error}); using cached copy retrieved {meta['retrieved_at']}")
            _append_manifest({"event": "cache_fallback", "at": _now(), **asdict(rf)})
            return rf
    return failed
