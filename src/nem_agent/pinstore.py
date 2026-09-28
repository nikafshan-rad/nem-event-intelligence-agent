"""Approved-bytes store: durable, access-controlled copies of the exact publisher bytes a reviewer approved.

Why: publishers replace files (AEMO SO_OP_3705 Version 97 → 98), roll them off (NEMWeb market notices), or serve
inconsistent values (NASA POWER), and a GitHub Actions cache is deleted after 7 days without use. Pinned builds
therefore restore approved bytes from this store instead of downloading them again (docs/pinned-store.md).

* Every object is keyed by the SHA-256 of the stored bytes. The index ``data/pinned_store.json`` (in git, reviewed in
  pull requests) records, per object: source id and URL, original retrieval time, the pin it satisfies (raw SHA-256,
  or the canonical content hash for API responses), whether that pin is current or superseded, the publisher's
  attribution and reuse terms, the approval history, and the release that holds it.
* Backends: assets of GitHub releases in this private repository (``GitHubReleaseBackend``), or a local directory
  (``LocalDirBackend``, used by tests and as a local mirror). Objects are only ever added: never replaced or deleted.
* ``restore`` writes into ``data/raw`` only bytes that hash to their key **and** match a *current* pin. Superseded
  objects stay in the store for audit and comparison but are never restored into a build. Nothing is substituted.

The publisher-refresh check stays separate and never changes the index or the pins.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import paths, rawstore
from .selection import Selection, SourceEntry, load_selection
from .timeutil import iso_utc

INDEX_VERSION = 1
REQUIRED_FIELDS = ("sha256", "size", "source_id", "dataset", "url", "retrieved_at", "pin", "status", "publisher",
                   "attribution", "terms", "approval", "release")


def index_path() -> Path:
    return paths.data_dir() / "pinned_store.json"


def load_index(path: Path | None = None) -> dict[str, Any]:
    p = path or index_path()
    if not p.exists():
        return {"schema_version": INDEX_VERSION, "objects": []}
    return json.loads(p.read_text())


def pin_identity(src: SourceEntry) -> dict[str, str]:
    if src.content_sha256 is not None:
        return {"kind": "content_sha256", "value": src.content_sha256}
    return {"kind": "sha256", "value": src.sha256}


def satisfies(obj: dict[str, Any], data: bytes, src: SourceEntry) -> bool:
    """The bytes hash to the object's key and are exactly what the current pin approves."""
    if hashlib.sha256(data).hexdigest() != obj["sha256"] or len(data) != obj["size"]:
        return False
    ident = pin_identity(src)
    if obj["pin"] != ident:
        return False
    if ident["kind"] == "sha256":
        return obj["sha256"] == ident["value"]
    try:
        return rawstore.content_sha256(src.dataset, data) == ident["value"]
    except ValueError:  # not a JSON response
        return False


def _content(dataset: str, data: bytes) -> str | None:
    try:
        return rawstore.content_sha256(dataset, data)
    except ValueError:
        return None


def current_object(index: dict[str, Any], src: SourceEntry) -> dict[str, Any] | None:
    ident = pin_identity(src)
    for o in index.get("objects", []):
        if o["source_id"] == src.source_id and o["status"] == "current" and o["pin"] == ident:
            return o
    return None


# ------------------------------------------------------------------------------------------ backends
class LocalDirBackend:
    """Content-addressed directory: ``<root>/<sha256>``. Add-only: an existing object is never replaced."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def get(self, obj: dict[str, Any]) -> bytes | None:
        p = self.root / obj["sha256"]
        return p.read_bytes() if p.exists() else None

    def put(self, sha256: str, data: bytes) -> None:
        if hashlib.sha256(data).hexdigest() != sha256:
            raise ValueError("refusing to store bytes under a key they do not hash to")
        p = self.root / sha256
        if p.exists():
            if p.read_bytes() != data:
                raise ValueError(f"object {sha256} already stored with different bytes; the store is add-only")
            return
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".part")
        tmp.write_bytes(data)
        tmp.replace(p)


Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    # The GitHub CLI reads its token from GH_TOKEN / its own login; the token never appears in arguments or logs.
    return subprocess.run(cmd, capture_output=True, text=True, timeout=1800)


class GitHubReleaseBackend:
    """Assets of releases in a private GitHub repository, named by SHA-256. Access = repository read permission.

    With "release immutability" enabled in the repository settings, published assets cannot be modified or deleted.
    Uploads go to a draft release that is published once every asset is attached; ``--clobber`` is never used.
    """

    def __init__(self, repository: str, run: Runner = _run) -> None:
        self.repository = repository
        self.run = run
        self._downloaded: dict[str, Path] = {}

    def _download(self, tag: str) -> Path:
        if tag not in self._downloaded:
            d = Path(tempfile.mkdtemp(prefix="pinstore-"))
            r = self.run(["gh", "release", "download", tag, "--repo", self.repository, "--dir", str(d)])
            if r.returncode != 0:
                raise RuntimeError(f"cannot download release {tag} from {self.repository}: {r.stderr.strip()[:300]}")
            self._downloaded[tag] = d
        return self._downloaded[tag]

    def get(self, obj: dict[str, Any]) -> bytes | None:
        p = self._download(obj["release"]) / obj["sha256"]
        return p.read_bytes() if p.exists() else None

    def publish(self, tag: str, files: list[Path], title: str, notes: str, target: str) -> None:
        existing = self.run(["gh", "release", "view", tag, "--repo", self.repository, "--json", "tagName"])
        if existing.returncode == 0:
            raise RuntimeError(f"release {tag} already exists; approved bytes are added in a new release, never replaced")
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
            fh.write(notes)
        steps = [["gh", "release", "create", tag, "--repo", self.repository, "--draft", "--title", title,
                  "--notes-file", fh.name, "--target", target]]
        for i in range(0, len(files), 50):
            steps.append(["gh", "release", "upload", tag, "--repo", self.repository, *[str(f) for f in files[i:i + 50]]])
        steps.append(["gh", "release", "edit", tag, "--repo", self.repository, "--draft=false"])
        for cmd in steps:
            r = self.run(cmd)
            if r.returncode != 0:
                raise RuntimeError(f"`{' '.join(cmd[:4])}` failed: {r.stderr.strip()[:300]}")


def backend_for(index: dict[str, Any], local_root: Path | None = None) -> LocalDirBackend | GitHubReleaseBackend:
    store = index.get("store", {})
    if local_root is not None or store.get("backend") != "github-release":
        return LocalDirBackend(local_root or paths.data_dir() / "pinned_store")
    return GitHubReleaseBackend(store["repository"])


# ------------------------------------------------------------------------------------------ restore / verify
def restore(sel: Selection | None = None, *, index: dict[str, Any] | None = None, backend: Any = None,
            strict: bool = False, log: Callable[..., None] = print) -> dict[str, Any]:
    """Put the approved bytes for every current pin into data/raw. Returns what happened per source."""
    sel = sel or load_selection()
    index = index if index is not None else load_index()
    backend = backend or backend_for(index)
    out: dict[str, list[str]] = {"already_verified": [], "restored": [], "not_in_store": [], "rejected": []}
    for src in sel.sources:
        p = rawstore.local_path_for(src.dataset, src.url)
        if p.exists():
            data = p.read_bytes()
            if hashlib.sha256(data).hexdigest() == src.sha256 or (
                    src.content_sha256 and _content(src.dataset, data) == src.content_sha256):
                out["already_verified"].append(src.source_id)
                continue
        obj = current_object(index, src)
        if obj is None:
            out["not_in_store"].append(src.source_id)
            continue
        data = backend.get(obj)
        if data is None or not satisfies(obj, data, src):
            out["rejected"].append(src.source_id)
            log(f"[store] REJECTED {src.source_id}: stored object {obj['sha256'][:12]} is missing or does not match the pin")
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".part")
        tmp.write_bytes(data)
        tmp.replace(p)
        meta = {"url": src.url, "sha256": obj["sha256"], "size": obj["size"], "retrieved_at": obj["retrieved_at"],
                "http_status": 200, "content_type": obj.get("content_type"), "last_modified": obj.get("last_modified"),
                "content_sha256": _content(src.dataset, data),
                "verified_by": f"approved-bytes store object {obj['sha256']} (release {obj['release']})",
                "restored_at": iso_utc(datetime.now(UTC))}
        p.with_name(p.name + ".meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True))
        out["restored"].append(src.source_id)
    counts = {k: len(v) for k, v in out.items()}
    log(f"[store] {json.dumps(counts)}")
    ok = not out["rejected"] and not (strict and out["not_in_store"])
    return {"ok": ok, "strict": strict, "counts": counts, **out}


def verify_index(sel: Selection | None = None, index: dict[str, Any] | None = None) -> list[str]:
    """Structural checks, no network: every current pin is covered once, every object is fully described."""
    sel = sel or load_selection()
    index = index if index is not None else load_index()
    problems: list[str] = []
    seen: set[str] = set()
    for o in index.get("objects", []):
        missing = [f for f in REQUIRED_FIELDS if not o.get(f)]
        if missing:
            problems.append(f"{o.get('sha256', '?')[:12]} ({o.get('source_id')}): missing {missing}")
        if o.get("sha256") in seen:
            problems.append(f"{o['sha256'][:12]}: listed twice")
        seen.add(o.get("sha256", ""))
        if not any(e.get("event") == "approved" for e in o.get("approval", [])):
            problems.append(f"{o.get('sha256', '?')[:12]} ({o.get('source_id')}): no approval event")
    for src in sel.sources:
        n = sum(1 for o in index.get("objects", []) if o["source_id"] == src.source_id and o["status"] == "current"
                and o["pin"] == pin_identity(src))
        if n != 1:
            problems.append(f"{src.source_id}: {n} current store objects for the pin (expected 1)")
        for sp in src.superseded:
            ident = sp.content_sha256 or sp.sha256
            if not any(o["source_id"] == src.source_id and o["status"] == "superseded" and o["pin"]["value"] == ident
                       for o in index.get("objects", [])) and not any(
                    u["source_id"] == src.source_id and u["pin_value"] == ident for u in index.get("unavailable", [])):
                problems.append(f"{src.source_id}: superseded pin {ident[:12]} is neither stored nor declared unavailable")
    return problems
