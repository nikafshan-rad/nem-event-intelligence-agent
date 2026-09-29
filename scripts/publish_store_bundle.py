"""Publish the approved bytes of every current pin as one bundle asset, so a CI runner restores them with two API
calls instead of one per asset (docs/pinned-store.md, "Bundles").

Every object is taken from the approved-bytes store itself and checked against its key and its current pin before
it is packed; nothing comes from a publisher and nothing is re-pinned. The bundle goes into a new release (the store
is add-only), is downloaded back and checked, and only then is its entry appended to data/pinned_store.json.

Usage: python scripts/publish_store_bundle.py --release pinned-bytes-bundle-2026-09-28 [--dry-run] [--local-dir DIR]
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def build_bundle(objects: list[tuple[dict[str, Any], bytes]], out: Path) -> dict[str, Any]:
    """A gzip-compressed tar of the objects, each named by its SHA-256 key; members in key order, with fixed
    metadata, so the same objects give the same archive."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        for obj, data in sorted(objects, key=lambda x: x[0]["sha256"]):
            ti = tarfile.TarInfo(obj["sha256"])
            ti.size, ti.mtime, ti.mode, ti.uid, ti.gid, ti.uname, ti.gname = len(data), 0, 0o444, 0, 0, "", ""
            tf.addfile(ti, io.BytesIO(data))
    with open(out, "wb") as fh, gzip.GzipFile(fileobj=fh, mode="wb", mtime=0, filename="") as gz:
        gz.write(raw.getvalue())
    blob = out.read_bytes()
    return {"sha256": hashlib.sha256(blob).hexdigest(), "size": len(blob),
            "objects": sorted(o["sha256"] for o, _ in objects)}


def main() -> int:
    from nem_agent import pinstore
    from nem_agent.selection import load_selection

    ap = argparse.ArgumentParser()
    ap.add_argument("--release", required=True, help="new release tag for the bundle (the store is add-only)")
    ap.add_argument("--dry-run", action="store_true", help="build and check the bundle; upload nothing")
    ap.add_argument("--local-dir", help="read objects from a local content-addressed directory (tests)")
    args = ap.parse_args()

    if not pinstore.safe_name(args.release):
        print(f"refused: release name {args.release!r} is not a plain name (letters, digits, '.', '_', '-')")
        return 2
    sel = load_selection()
    index = pinstore.load_index()
    if any(b["release"] == args.release for b in index.get("bundles", [])):
        print(f"refused: a bundle in release {args.release} is already recorded")
        return 2
    src_by_id = {s.source_id: s for s in sel.sources}
    backend = (pinstore.LocalDirBackend(Path(args.local_dir)) if args.local_dir
               else pinstore.GitHubReleaseBackend(index["store"]["repository"]))  # per-object, never from a bundle
    objects: list[tuple[dict[str, Any], bytes]] = []
    for src in sel.sources:
        obj = pinstore.current_object(index, src)
        if obj is None:
            print(f"refused: {src.source_id} has no current store object")
            return 2
        data = backend.get(obj)
        if data is None or not pinstore.satisfies(obj, data, src_by_id[src.source_id]):
            print(f"refused: store object {obj['sha256'][:12]} ({src.source_id}) is missing or does not match its pin")
            return 2
        objects.append((obj, data))
    asset = f"approved-bytes-{args.release}.tar.gz"
    work = Path(tempfile.mkdtemp(prefix="store-bundle-"))
    built = build_bundle(objects, work / asset)
    entry = {"release": args.release, "asset": asset, **built,
             "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "note": ("the approved bytes of every current pin in one asset, taken from the store and checked against "
                      "their keys and pins; restore checks this SHA-256, then every object again")}
    print(json.dumps({k: v for k, v in entry.items() if k != "objects"} | {"n_objects": len(built["objects"]),
                                                                          "bytes_packed": sum(len(d) for _, d in objects)}))
    if args.dry_run:
        return 0
    if args.local_dir:
        pinstore.LocalDirBackend(Path(args.local_dir)).put(built["sha256"], (work / asset).read_bytes())
    else:
        gh = pinstore.GitHubReleaseBackend(index["store"]["repository"])
        target = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO).stdout.strip()
        gh.publish(args.release, [work / asset], f"Approved-bytes bundle {args.release}",
                   "One asset holding the approved bytes of every current pin (see docs/pinned-store.md, Bundles). "
                   "The objects are unchanged; each is still verified against its SHA-256 key and its pin on restore.",
                   target)
        check = pinstore.GitHubReleaseBackend(index["store"]["repository"], bundles=[entry])
        got = sum(1 for o, d in objects if check.get(o) == d)  # downloaded back: the bundle hash and every object
        if got != len(objects):
            print(f"refused: only {got} of {len(objects)} objects came back intact; the index is not changed")
            return 2
    index.setdefault("bundles", []).append(entry)
    pinstore.index_path().write_text(json.dumps(index, indent=2) + "\n")
    print(f"recorded bundle {asset} ({len(objects)} objects) in {pinstore.index_path()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
