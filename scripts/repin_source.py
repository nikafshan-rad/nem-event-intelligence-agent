#!/usr/bin/env python
"""Re-pin ONE source after a reviewed publisher revision. Hash verification is never relaxed.

When a publisher replaces content at a pinned URL (e.g. AEMO issues a new version of a procedure PDF, or NASA POWER
moves recent days from provisional GEOS-IT to final MERRA-2 meteorology), every fresh setup fails its SHA-256
check. That failure is correct and stays in place. This script is the only way to move a pin:

1. The reviewer fetches and inspects the new content first, then passes its identity with ``--expect``: the raw
   SHA-256 for files, or the canonical content hash for API responses whose bytes carry volatile metadata.
2. The script fetches the URL again and refuses unless the identity equals ``--expect`` exactly, so the pin never
   drifts to whatever the server returns at run time.
3. The old pin moves to the entry's ``superseded`` history with what the publisher changed and why it was
   accepted; ``data/SOURCES.md`` is regenerated from the selection.

Usage:
  python scripts/repin_source.py --source-id aemo_so_op_3705 --expect <sha256> \\
      --publisher-revision "Version 98, effective 23 September 2026 (was Version 97, 1 April 2026)" \\
      --reason "AEMO replaced the PDF at the same URL; Version 97 is no longer served"
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from nem_agent import http, rawstore  # noqa: E402
from nem_agent.selection import Selection  # noqa: E402


def _write_sources_md(sel: dict, path: Path) -> None:
    spec = importlib.util.spec_from_file_location("source_probe", REPO / "scripts" / "source_probe.py")
    assert spec and spec.loader
    probe = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = probe  # dataclasses in the probe resolve their module through sys.modules
    spec.loader.exec_module(probe)
    probe.write_sources_md(sel, path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source-id", required=True)
    ap.add_argument("--expect", required=True, help="reviewed identity of the new content (64 hex characters)")
    ap.add_argument("--publisher-revision", required=True, help="what the publisher changed, as verified")
    ap.add_argument("--reason", required=True)
    ap.add_argument("--selection", default=str(REPO / "data" / "source_selection.json"))
    args = ap.parse_args()

    sel_path = Path(args.selection)
    sel = json.loads(sel_path.read_text())
    entry = next((s for s in sel["sources"] if s["source_id"] == args.source_id), None)
    if entry is None:
        print(f"REFUSED: unknown source_id {args.source_id!r}")
        return 2
    api = entry["dataset"] in rawstore.VOLATILE_JSON_KEYS
    current = entry["content_sha256"] if api else entry["sha256"]
    if args.expect == current:
        print(f"REFUSED: {args.source_id} is already pinned to {current}; nothing to re-pin")
        return 2

    res = http.fetch(entry["url"])
    if not res.ok or res.body is None:
        print(f"REFUSED: fetch failed ({res.error or res.status}); the pin is unchanged")
        return 1
    digest = hashlib.sha256(res.body).hexdigest()
    identity = rawstore.content_sha256(entry["dataset"], res.body) if api else digest
    if identity != args.expect:
        print(f"REFUSED: fetched {'content_sha256' if api else 'sha256'} {identity} != --expect {args.expect}; "
              "the pin is unchanged (review the content that is served now)")
        return 1
    if entry["dataset"] == "AEMO_PDF" and not res.body.startswith(b"%PDF-"):
        print("REFUSED: the response is not a PDF; the pin is unchanged")
        return 1

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry.setdefault("superseded", []).append({
        "sha256": entry["sha256"], "content_sha256": entry.get("content_sha256"), "size": entry["size"],
        "last_modified": entry.get("last_modified"), "retrieved_at": entry["retrieved_at"], "superseded_at": now,
        "new_sha256": digest, "publisher_revision": args.publisher_revision, "reason": args.reason,
    })
    entry.update({"sha256": digest, "size": len(res.body), "http_status": res.status,
                  "content_type": res.content_type, "last_modified": res.last_modified, "retrieved_at": now})
    if api:
        entry["content_sha256"] = identity
    Selection.model_validate(sel)  # the result must still satisfy the strict selection schema
    sel_path.write_text(json.dumps(sel, indent=2, sort_keys=False) + "\n")
    _write_sources_md(sel, sel_path.parent / "SOURCES.md")
    print(json.dumps({"source_id": args.source_id, "old": entry["superseded"][-1]["sha256"], "new_sha256": digest,
                      "new_content_sha256": entry.get("content_sha256") if api else None, "size": len(res.body),
                      "last_modified": res.last_modified, "retrieved_at": now}, indent=2))
    print("RE-PINNED. Rebuild with `make data` / `make index`; cached copies of the old content are replaced "
          "because they no longer match the pin.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
