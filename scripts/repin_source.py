#!/usr/bin/env python
"""Accept ONE revised source version after review. This is the only way a pin changes; verification is never relaxed.

A publisher revision is first detected and described by the publisher-refresh check (``make refresh-check``,
docs/source-governance.md). Accepting it is an explicit reviewer action:

1. The reviewer reads the refresh report and passes the reviewed identity with ``--expect`` (raw SHA-256 for files,
   canonical content hash for API responses), their name with ``--approved-by``, what the publisher changed and why
   the new version is acceptable.
2. With ``--report`` the script refuses unless that report lists this source as ``changed`` with the same new identity.
3. The script fetches the URL again and refuses unless the content equals ``--expect`` exactly, so the pin never
   drifts to whatever the server returns at run time.
4. The old pin moves to the entry's ``superseded`` history (hashes, dates, version metadata, report, approver, reason).
   A verified copy of the old bytes, if this machine has one, is kept in ``data/pinned_store/<identity>`` (local and
   git-ignored: publisher files are not redistributed, and a GitHub Actions cache is not an archive).
5. ``data/SOURCES.md`` is regenerated. The pin change then goes through a pull request, where CI checks that every
   changed pin carries such a history entry (``scripts/check_pin_changes.py``).

Usage:
  python scripts/repin_source.py --source-id aemo_so_op_3705 --expect <sha256> \\
      --report artifacts/source_refresh/<run>/report.json --approved-by "A. Reviewer" \\
      --publisher-revision "Version 98, effective 23 September 2026 (was Version 97, 1 April 2026)" \\
      --reason "AEMO replaced the PDF at the same URL; Version 97 is no longer served"
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from nem_agent import http, paths, rawstore  # noqa: E402
from nem_agent.refresh import describe  # noqa: E402
from nem_agent.selection import Selection  # noqa: E402


def _write_sources_md(sel: dict, path: Path) -> None:
    spec = importlib.util.spec_from_file_location("source_probe", REPO / "scripts" / "source_probe.py")
    assert spec and spec.loader
    probe = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = probe  # dataclasses in the probe resolve their module through sys.modules
    spec.loader.exec_module(probe)
    probe.write_sources_md(sel, path)


def _identity(dataset: str, data: bytes) -> str:
    return rawstore.content_sha256(dataset, data) or hashlib.sha256(data).hexdigest()


def _keep_old_bytes(entry: dict) -> tuple[str, bytes | None]:
    """Copy the verified old bytes into the local content-addressed store; say where, or why not."""
    p = rawstore.local_path_for(entry["dataset"], entry["url"])
    old_id = entry.get("content_sha256") or entry["sha256"]
    if not p.exists():
        return "not kept: this machine holds no copy of the superseded bytes", None
    data = p.read_bytes()
    if _identity(entry["dataset"], data) != old_id and hashlib.sha256(data).hexdigest() != entry["sha256"]:
        return "not kept: the local copy does not match the superseded pin", None
    store = paths.data_dir() / "pinned_store"
    store.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, store / old_id)
    (store / f"{old_id}.json").write_text(json.dumps({"source_id": entry["source_id"], "url": entry["url"],
                                                      "sha256": entry["sha256"], "retrieved_at": entry["retrieved_at"]},
                                                     indent=2) + "\n")
    return (f"kept on this machine only: data/pinned_store/{old_id} (git-ignored, not redistributed; other machines "
            "cannot obtain it once the publisher has replaced it)"), data


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source-id", required=True)
    ap.add_argument("--expect", required=True, help="reviewed identity of the new content (64 hex characters)")
    ap.add_argument("--approved-by", required=True, help="the reviewer accepting the new version")
    ap.add_argument("--publisher-revision", required=True, help="what the publisher changed, as verified")
    ap.add_argument("--reason", required=True, help="why the new version is acceptable")
    ap.add_argument("--report", help="refresh-check report.json that lists this change")
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
    report_ref = metadata = None
    if args.report:
        rp = Path(args.report)
        rep = json.loads(rp.read_text())
        row = next((r for r in rep.get("sources", []) if r["source_id"] == args.source_id), None)
        if row is None or row.get("result") != "changed" or row.get("new_identity") != args.expect:
            print(f"REFUSED: report {rp} does not list {args.source_id} as changed to {args.expect}; the pin is unchanged")
            return 1
        report_ref = {"run_id": rep.get("run_id"), "generated_at": rep.get("generated_at"),
                      "sha256": hashlib.sha256(rp.read_bytes()).hexdigest(), "path": str(rp)}
        metadata = row.get("metadata")

    body = None
    for attempt in range(1 + (rawstore.MISMATCH_RETRIES.get(entry["dataset"], 0) if api else 0)):
        if attempt:
            time.sleep(rawstore.MISMATCH_RETRY_WAIT_S)
        res = http.fetch(entry["url"])
        if not res.ok or res.body is None:
            print(f"REFUSED: fetch failed ({res.error or res.status}); the pin is unchanged")
            return 1
        if _identity(entry["dataset"], res.body) == args.expect:
            body = res.body
            break
    if body is None:
        print(f"REFUSED: fetched {'content_sha256' if api else 'sha256'} {_identity(entry['dataset'], res.body)} != "
              f"--expect {args.expect}; the pin is unchanged (review the content that is served now)")
        return 1
    if entry["dataset"] == "AEMO_PDF" and not body.startswith(b"%PDF-"):
        print("REFUSED: the response is not a PDF; the pin is unchanged")
        return 1

    kept, old = _keep_old_bytes(entry)
    if metadata is None:
        metadata = {"pinned": describe(entry["dataset"], old) if old is not None else None,
                    "current": describe(entry["dataset"], body)}
    digest = hashlib.sha256(body).hexdigest()
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry.setdefault("superseded", []).append({
        "sha256": entry["sha256"], "content_sha256": entry.get("content_sha256"), "size": entry["size"],
        "last_modified": entry.get("last_modified"), "retrieved_at": entry["retrieved_at"], "superseded_at": now,
        "new_sha256": digest, "publisher_revision": args.publisher_revision, "reason": args.reason,
        "approved_by": args.approved_by, "refresh_report": report_ref, "metadata": metadata, "old_bytes": kept,
    })
    entry.update({"sha256": digest, "size": len(body), "http_status": res.status,
                  "content_type": res.content_type, "last_modified": res.last_modified, "retrieved_at": now})
    if api:
        entry["content_sha256"] = args.expect
    Selection.model_validate(sel)  # the result must still satisfy the strict selection schema
    sel_path.write_text(json.dumps(sel, indent=2, sort_keys=False) + "\n")
    _write_sources_md(sel, sel_path.parent / "SOURCES.md")
    print(json.dumps({"source_id": args.source_id, "old": entry["superseded"][-1]["sha256"], "new_sha256": digest,
                      "new_content_sha256": entry.get("content_sha256") if api else None, "size": len(body),
                      "approved_by": args.approved_by, "old_bytes": kept}, indent=2))
    print("RE-PINNED. Open a pull request with data/source_selection.json and data/SOURCES.md; rebuild with "
          "`make data` / `make index`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
