#!/usr/bin/env python
"""Add approved publisher bytes to the approved-bytes store (maintainer action; docs/pinned-store.md).

Collects, for every pin in data/source_selection.json, the local copy whose bytes match the pin, plus any verified
copies of superseded pins in data/pinned_store/ (for example SO_OP_3705 Version 97, recovered from the 2026-09-23
CI cache). Every file is re-hashed before upload. New objects go into a NEW release (draft → upload → publish);
existing objects are never replaced or deleted. data/pinned_store.json records each object with its URL, original
retrieval time, pin, attribution, reuse terms and approval history; commit it in a pull request.

Usage:
  python scripts/publish_pinned_store.py --release pinned-bytes-2026-09-27 --target <commit sha> [--dry-run]
  python scripts/publish_pinned_store.py --release T --local-dir /tmp/store     # local backend (tests, mirrors)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from nem_agent import paths, pinstore, rawstore  # noqa: E402
from nem_agent.selection import SourceEntry, load_selection  # noqa: E402

REPOSITORY = "nikafshan-rad/nem-event-intelligence-agent"
TERMS = {
    "AEMO": {
        "summary": "AEMO's general copyright permission: anyone may use AEMO Material for any purpose, with accurate and "
                   "appropriate attribution of the material and AEMO as its author; no specific permission needed.",
        "quote": "In addition to the uses permitted under copyright laws, AEMO confirms its general permission for anyone "
                 "to use AEMO Material for any purpose, but only with accurate and appropriate attribution of the "
                 "relevant AEMO Material and AEMO as its author. You do not need to obtain specific permission to use "
                 "AEMO Material in this way.",
        "page": "https://www.aemo.com.au/privacy-and-legal-notices/copyright-permissions",
        "evidence": "live page answers HTTP 403 to scripted clients; text read from the Internet Archive capture "
                    "https://web.archive.org/web/20260923180705/https://www.aemo.com.au/privacy-and-legal-notices/"
                    "copyright-permissions (captured 2026-09-23T18:07:05Z; decoded HTML sha256 "
                    "5d09ba4e7303d6e7553d32f3cfbb870b098c772d636df8d51108a788892e817b)",
        "exclusions": "confidential documents and reports commissioned by others who may own the copyright are not "
                      "AEMO Material (none of the pinned files is either)",
    },
    "NASA": {
        "summary": "NASA POWER asks for its two acknowledgement texts in any publication, and requests (does not require) "
                   "notification of publications and of transmission of POWER data to other researchers; no copyright "
                   "restriction is stated.",
        "page": "https://power.larc.nasa.gov/docs/referencing/",
        "evidence": "fetched 2026-09-27T23:15:28Z, sha256 97f49593dd0878b38a1d134e5c2e41df1cd192f08668d3dfa81d37fcaef2059b",
    },
}
LABEL = {"DISPATCHIS": "NEMWeb DispatchIS report", "DISPATCH_SCADA": "NEMWeb Dispatch SCADA report",
         "OPDEM_FORECAST_HH": "NEMWeb operational demand forecast", "OPDEM_ACTUAL_HH": "NEMWeb actual operational demand",
         "OPDEM_ACTUAL_DAILY": "NEMWeb next-day actual operational demand", "PUBLIC_PRICES": "NEMWeb Public_Prices report",
         "MARKET_NOTICE": "AEMO market notice", "MMSDM_DUDETAILSUMMARY": "MMS Data Model monthly archive",
         "MMS_DATA_MODEL_HTML": "MMS Data Model Report page", "AEMO_PDF": "AEMO publication"}


def attribution(src: SourceEntry, data: bytes, retrieved_at: str) -> str:
    name = Path(src.url.split("?")[0]).name
    if src.dataset == "NASA_POWER_HOURLY":
        ver = (json.loads(data).get("header", {}).get("api") or {}).get("version", "2.x.x").lstrip("v")
        return ("The data was obtained from National Aeronautics and Space Administration (NASA) Langley Research "
                "Center's Prediction Of Worldwide Energy Resources (POWER) project funded through the NASA Earth "
                f"Science Division. The data was obtained from the POWER Project's Hourly {ver} version on "
                f"{retrieved_at[:10].replace('-', '/')}.")
    return (f"Source: Australian Energy Market Operator (AEMO), {LABEL.get(src.dataset, 'AEMO material')} {name}, "
            f"{src.url}, retrieved {retrieved_at}. © AEMO. Used under AEMO's general copyright permission, with "
            "attribution.")


def approval_events(src: SourceEntry, sel_generated_at: str, superseded_index: int | None) -> list[dict[str, Any]]:
    """History of the pin this object satisfies: approved at G0 or by a re-pin; superseded later, if so."""
    g0 = {"event": "approved", "at": sel_generated_at,
          "by": "G0 source selection (scripts/source_probe.py, scripts/verify_selection.py), accepted in PR #1 "
                "(merged 2026-09-25 by nikafshan-rad)", "basis": "probe-verified publisher file, docs/progress.md G0"}
    hist = src.superseded
    if superseded_index is None:  # the current pin
        if not hist:
            return [g0]
        last = hist[-1]
        return [{"event": "approved", "at": last.superseded_at,
                 "by": last.approved_by or "re-pin in PR #2 (commit c6face3), merged 2026-09-27 by nikafshan-rad",
                 "basis": f"{last.publisher_revision}. Reason: {last.reason}"}]
    rec = hist[superseded_index]
    first = g0 if superseded_index == 0 else {"event": "approved", "at": hist[superseded_index - 1].superseded_at,
                                              "by": hist[superseded_index - 1].approved_by or "earlier re-pin"}
    return [first, {"event": "superseded", "at": rec.superseded_at, "by_pin": rec.new_sha256,
                    "reason": f"{rec.publisher_revision}. {rec.reason}"}]


def verified_bytes(p: Path, src: SourceEntry, ident: dict[str, str]) -> bytes | None:
    if not p.exists():
        return None
    data = p.read_bytes()
    if ident["kind"] == "sha256":
        return data if hashlib.sha256(data).hexdigest() == ident["value"] else None
    try:
        return data if rawstore.content_sha256(src.dataset, data) == ident["value"] else None
    except ValueError:  # not a JSON response (e.g. another object in the local store)
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--release", required=True, help="new release tag for the objects added now")
    ap.add_argument("--target", default="main", help="commit the release tag points at")
    ap.add_argument("--dry-run", action="store_true", help="build and check the index; upload nothing")
    ap.add_argument("--local-dir", help="use a local content-addressed directory instead of GitHub releases")
    args = ap.parse_args()

    sel = load_selection()
    index = pinstore.load_index()
    index["schema_version"] = pinstore.INDEX_VERSION
    index["store"] = ({"backend": "local-dir", "path": args.local_dir} if args.local_dir else
                      {"backend": "github-release", "repository": REPOSITORY,
                       "access": "private repository; readable by collaborators and by this repository's workflows",
                       "immutability": "enable Settings > Releases > 'Enable release immutability' so published "
                                       "assets cannot be modified or deleted"})
    index["terms"] = TERMS
    index.setdefault("objects", [])
    index.setdefault("unavailable", [])
    have = {o["sha256"] for o in index["objects"]}
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    new: list[tuple[dict[str, Any], bytes]] = []

    def add(src: SourceEntry, data: bytes, ident: dict[str, str], status: str, retrieved_at: str,
            events: list[dict[str, Any]], extra: dict[str, Any]) -> None:
        h = hashlib.sha256(data).hexdigest()
        if h in have:
            return
        obj = {"sha256": h, "size": len(data), "source_id": src.source_id, "dataset": src.dataset, "url": src.url,
               "retrieved_at": retrieved_at, "pin": ident, "status": status,
               "publisher": "NASA" if src.dataset == "NASA_POWER_HOURLY" else "AEMO",
               "attribution": attribution(src, data, retrieved_at),
               "terms": "NASA" if src.dataset == "NASA_POWER_HOURLY" else "AEMO",
               "approval": [*events, {"event": "stored", "at": now, "release": args.release,
                                      "verified": "sha256 of the stored bytes and the pin identity"}],
               "release": args.release, **extra}
        index["objects"].append(obj)
        have.add(h)
        new.append((obj, data))

    missing = []
    for src in sel.sources:
        ident = pinstore.pin_identity(src)
        p = rawstore.local_path_for(src.dataset, src.url)
        data = verified_bytes(p, src, ident)
        if data is None:
            if pinstore.current_object(index, src) is None:
                missing.append(src.source_id)
            continue
        meta = json.loads(p.with_name(p.name + ".meta.json").read_text()) if p.with_name(p.name + ".meta.json").exists() else {}
        add(src, data, ident, "current", meta.get("retrieved_at") or src.retrieved_at,
            approval_events(src, sel.generated_at, None),
            {"content_type": meta.get("content_type") or src.content_type,
             "last_modified": meta.get("last_modified") or src.last_modified})
        for i, sp in enumerate(src.superseded):
            sident = {"kind": "content_sha256", "value": sp.content_sha256} if sp.content_sha256 else \
                     {"kind": "sha256", "value": sp.sha256}
            kept = paths.data_dir() / "pinned_store"
            found = next((c for c in sorted(kept.glob("[0-9a-f]" * 64))
                          if verified_bytes(c, src, sident) is not None), None) if kept.exists() else None
            if found is None:
                if not any(u["source_id"] == src.source_id and u["pin_value"] == sident["value"]
                           for u in index["unavailable"]):
                    index["unavailable"].append({"source_id": src.source_id, "pin_value": sident["value"],
                                                 "why": "no verified copy of the superseded bytes was found"})
                continue
            info = json.loads(found.with_name(found.name + ".json").read_text()) \
                if found.with_name(found.name + ".json").exists() else {}
            add(src, found.read_bytes(), sident, "superseded", info.get("retrieved_at") or sp.retrieved_at,
                approval_events(src, sel.generated_at, i), {"provenance": info.get("recovered_from")})

    problems = pinstore.verify_index(sel, index)
    print(json.dumps({"new_objects": len(new), "new_bytes": sum(len(d) for _, d in new), "total_objects":
                      len(index["objects"]), "missing_locally": missing, "index_problems": problems[:10]}, indent=2))
    if problems or missing:
        print("NOT PUBLISHED: fix the problems above first")
        return 1
    if args.dry_run or not new:
        print("DRY RUN: nothing uploaded" if args.dry_run else "NOTHING NEW TO STORE")
        return 0
    if args.local_dir:
        backend = pinstore.LocalDirBackend(Path(args.local_dir))
        for obj, data in new:
            backend.put(obj["sha256"], data)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            files = []
            for obj, data in new:
                f = Path(tmp) / obj["sha256"]
                f.write_bytes(data)
                files.append(f)
            notes = (f"Approved publisher bytes, content-addressed by SHA-256 ({len(new)} objects, "
                     f"{sum(len(d) for _, d in new) / 1e6:.1f} MB). The index with URLs, retrieval times, pins, "
                     "attribution and approval history is data/pinned_store.json.\n\n"
                     f"AEMO material: {TERMS['AEMO']['summary']}\n\nNASA POWER: {TERMS['NASA']['summary']}\n")
            pinstore.GitHubReleaseBackend(REPOSITORY).publish(args.release, files, f"Approved publisher bytes "
                                                              f"({args.release})", notes, args.target)
    pinstore.index_path().write_text(json.dumps(index, indent=2) + "\n")
    print(f"STORED {len(new)} objects in {'local dir ' + args.local_dir if args.local_dir else 'release ' + args.release}; "
          "commit data/pinned_store.json in a pull request")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
