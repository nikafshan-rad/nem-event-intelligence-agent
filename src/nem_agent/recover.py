"""Recover files that rolled off NEMWeb "Current" from NEMWeb "Archive" bundles, by name, with checksum proof.

NEMWeb keeps individual files in ``Reports/Current`` for a limited time, then bundles the *same zip files* into
daily/weekly/monthly archives. When a pinned Current URL answers 404, this module looks for a member with the same
file name inside the Archive containers whose start date could cover it, and accepts the member only if its bytes
hash to the SHA-256 recorded by the probe.

Market notices: NEMWeb has a ``Reports/Archive/Market_Notice/`` directory, but its listing contained no files
when checked (2026-09-27). Rolled-off notices are looked up there by file name (plain or inside a zip bundle)
and accepted only on a SHA-256 match; every lookup records what the listing contained and when.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from . import nemweb, rawstore
from .timeutil import iso_utc


def extract_verified_member(container: bytes, name: str, expected_sha256: str) -> bytes | None:
    """Return the member called ``name`` (at any nesting depth) whose bytes hash to ``expected_sha256``."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(container))
    except zipfile.BadZipFile:
        return None
    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            data = zf.read(info)
            if Path(info.filename).name == name and hashlib.sha256(data).hexdigest() == expected_sha256:
                return data
            if info.filename.lower().endswith(".zip") and len(data) < 200_000_000:
                inner = extract_verified_member(data, name, expected_sha256)
                if inner is not None:
                    return inner
    return None


NOTICE_ARCHIVE_DIR = "/Reports/Archive/Market_Notice/"
_notice_listing: dict[str, Any] = {}


def notice_archive_listing() -> dict[str, Any]:
    """The NEMWeb Archive/Market_Notice listing, fetched once per process: files by name plus when and what was seen."""
    if not _notice_listing:
        res, entries = nemweb.list_dir(NOTICE_ARCHIVE_DIR)
        files = [e for e in entries if not e.is_dir]
        _notice_listing.update(url=nemweb.NEMWEB + NOTICE_ARCHIVE_DIR, http_status=res.status, checked_at=iso_utc(datetime.now(UTC)),
                               n_files=len(files), files={e.name: e.url for e in files})
    return _notice_listing


def recover_notice_from_archive(url: str, expected_sha256: str, log: Any = print) -> rawstore.RawFile | None:
    name = unquote(Path(urlparse(url).path).name)
    listing = notice_archive_listing()
    cands = [u for n, u in listing["files"].items() if n == name] + \
            [u for n, u in listing["files"].items() if n.lower().endswith(".zip")]
    for cand in cands:
        got = rawstore.get("MARKET_NOTICE_ARCHIVE", cand)
        if not got.available:
            continue
        raw = Path(got.local_path).read_bytes()
        data = raw if hashlib.sha256(raw).hexdigest() == expected_sha256 else extract_verified_member(raw, name, expected_sha256)
        if data is not None:
            return _store_recovered("MARKET_NOTICE", url, data, expected_sha256, cand, got.sha256, "text/plain", log)
    return None


def _store_recovered(dataset: str, url: str, data: bytes, expected_sha256: str, source: str, container_sha: str | None,
                     content_type: str, log: Any) -> rawstore.RawFile:
    path = rawstore.local_path_for(dataset, url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    now = iso_utc(datetime.now(UTC))
    meta = {"url": url, "sha256": expected_sha256, "size": len(data), "http_status": 200,
            "content_type": content_type, "last_modified": None, "retrieved_at": now,
            "recovered_from_archive": source, "archive_sha256": container_sha,
            "note": "Current URL rolled off; identical bytes recovered from the NEMWeb Archive"}
    path.with_name(path.name + ".meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True))
    log(f"[data] RECOVERED {Path(urlparse(url).path).name} from {source} (sha256 verified)")
    return rawstore.RawFile(dataset, url, str(path), expected_sha256, len(data), 200, content_type, None, now,
                            "recovered_from_archive", f"recovered from {source}", upstream="unavailable")


def recover_from_archive(dataset: str, url: str, expected_sha256: str, log: Any = print) -> rawstore.RawFile | None:
    if dataset == "MARKET_NOTICE":
        return recover_notice_from_archive(url, expected_sha256, log=log)
    dirs = nemweb.DATASET_DIRS.get(dataset)
    if dirs is None or dirs[1] is None or "/reports/current/" not in url.lower():
        return None
    name = unquote(Path(urlparse(url).path).name)
    m = re.search(r"_(\d{8})(?:\d{4})?_", name)
    if not m:
        return None
    member_day = datetime.strptime(m.group(1), "%Y%m%d").date()
    _res, entries = nemweb.list_dir(dirs[1])
    starts = [(nemweb.archive_start(dataset, e.name), e) for e in entries if not e.is_dir]
    cands = sorted(((d.date(), e) for d, e in starts if d is not None and d.date() <= member_day),
                   key=lambda x: x[0], reverse=True)[:2]
    for _start, e in cands:
        arc = rawstore.get(f"{dataset}_ARCHIVE", e.url)
        if not arc.available:
            continue
        data = extract_verified_member(Path(arc.local_path).read_bytes(), name, expected_sha256)
        if data is None:
            continue
        return _store_recovered(dataset, url, data, expected_sha256, e.url, arc.sha256, "application/zip", log)
    return None
