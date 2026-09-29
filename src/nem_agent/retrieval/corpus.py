"""Build the public-document corpus from the selected, checksummed publisher files.

Document types:

* ``definition`` — AEMO *Demand Terms in EMMS Data Model*, the MMS Data Model Report table pages, the NEM fact sheet;
* ``procedure``  — AEMO power-system operating procedures (SO_OP_3704/3705/3710);
* ``market_notice`` — AEMO market notices from NEMWeb (event-specific; region and date parsed from the notice).

Every chunk keeps ``doc_id, title, url, publication_date, doc_type, event_region, event_date, page, section,
chunk_hash`` and a flag when the text contains instruction-like phrases. Such text is data, never instructions.
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .. import rawstore
from ..selection import Selection, SourceEntry
from ..timeutil import NEM_TZ, UTC, iso_utc

CHUNK_CHARS = 1100
OVERLAP_CHARS = 150

INJECTION_RE = re.compile(
    r"(ignore (all |any )?(previous|prior|above) (instructions|rules)|disregard (the )?(system|previous)|"
    r"system prompt|you are now (a|an|the)|new instructions\s*:|approve (the|this) (case )?note|publish_case_note|"
    r"call the tool|developer mode|jailbreak)", re.I)

PDF_META: dict[str, dict[str, str]] = {
    # doc_id -> doc_type and how the publication/effective date is read from the first page text
    "aemo_demand_terms": {"doc_type": "definition"},
    "aemo_nem_fact_sheet": {"doc_type": "definition"},
    "aemo_so_op_3704": {"doc_type": "procedure"},
    "aemo_so_op_3705": {"doc_type": "procedure"},
    "aemo_so_op_3710": {"doc_type": "procedure"},
}
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
REGION_NAMES = {"NSW": "NSW1", "QLD": "QLD1", "SA": "SA1", "TAS": "TAS1", "VIC": "VIC1"}
STATE_NAMES = {"New South Wales": "NSW1", "Queensland": "QLD1", "South Australia": "SA1", "Tasmania": "TAS1",
               "Victoria": "VIC1"}


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    url: str
    doc_type: str
    publication_date: str | None  # ISO UTC timestamp from which the text is treated as public
    event_region: str | None
    event_date: str | None        # ISO date (market-time calendar date) for event-specific documents
    page: int | None
    section: str | None
    text: str
    chunk_hash: str
    source_sha256: str
    instruction_like: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\u201c\"'•])")


def split_sentences(text: str, min_len: int = 30) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(text) if len(s.strip()) >= min_len]


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _windows(text: str, size: int = CHUNK_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    out, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            cut = text.rfind(". ", start + size // 2, end)
            end = cut + 1 if cut > 0 else end
        out.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
        sp = text.find(" ", start)
        start = sp + 1 if 0 < sp < end else start
    return [o for o in out if o]


# ---------------------------------------------------------------------------------------------- PDFs
def _pdf_date(first_pages: str, meta_date: str | None) -> str | None:
    """Conservative publication time: the LATEST of the date stated in the text (effective date, or a month,
    taken as the end of that month) and the PDF modification date (end of that day)."""
    cands: list[datetime] = []
    m = re.search(r"Effective date:\s*(\d{1,2})\s+([A-Za-z]+)\s+(20\d\d)", first_pages)
    if m and m.group(2).lower() in MONTHS:
        cands.append(datetime(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)), tzinfo=NEM_TZ))
    else:
        m = re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d\d)\b",
                      first_pages)
        if m:
            y, mo = int(m.group(2)), MONTHS[m.group(1).lower()]
            cands.append(datetime(y + (mo == 12), mo % 12 + 1, 1, tzinfo=NEM_TZ) - timedelta(seconds=1))
    if meta_date:
        m = re.match(r"D:(\d{4})(\d\d)(\d\d)", meta_date)
        if m:
            cands.append(datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), 23, 59, 59, tzinfo=NEM_TZ))
    return iso_utc(max(cands)) if cands else None


# Running headers/footers of the AEMO PDFs in the corpus (removed before chunking)
_DOC_REF = re.compile(r"AEMO\s*\|\s*Doc Ref:\s*SO_OP_\d+\s*\|\s*\d{1,2}\s+[A-Za-z]+\s+\d{4}\s*Page \d+ of \d+", re.I)
_BOILERPLATE = [re.compile(p, re.I) for p in (
    r"©\s*AEMO\s*\d{4}\s*\|\s*Demand Terms in EMMS Data Model\s*\d{1,3}\b",
    r"^\s*(Public\s*)+$",
    r"^\s*aemo\.com\.au\s*$",
)]


def _strip_boilerplate(text: str) -> str:
    out: list[str] = []
    for ln in text.splitlines():
        if _DOC_REF.search(ln):
            ln = _DOC_REF.sub(" ", ln)
            # the running title sits on the previous non-empty line (e.g. "Dispatch procedure")
            if out and len(out[-1].strip()) < 40 and not out[-1].rstrip().endswith("."):
                out.pop()
        for pat in _BOILERPLATE:
            ln = pat.sub(" ", ln)
        if ln.strip():
            out.append(ln)
    return "\n".join(out)


# Front matter carries no domain content but matches many queries (version histories, tables of contents,
# legal notices); it is excluded from the index and counted in the manifest.
FRONT_MATTER_RE = re.compile(r"(VERSION RELEASE HISTORY|Version release history|Current version release details|"
                             r"^Contents\b|Important notice PURPOSE|The material in this publication may be used)", re.M)

_HEADING = re.compile(r"^(?:A?\d{1,2}(?:\.\d{1,2}){0,2}\.?)\s+[A-Z][A-Za-z0-9 ,&()'/\-%]{3,80}$")


def pdf_chunks(src: SourceEntry, path: Path) -> list[Chunk]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = [(i + 1, _strip_boilerplate(p.extract_text() or "")) for i, p in enumerate(reader.pages)]
    meta: Any = reader.metadata or {}
    title = (src.coverage or {}).get("title") or (meta.get("/Title") if meta else None) or src.source_id
    pub = _pdf_date(" ".join(t for _, t in pages[:2]), meta.get("/ModDate") if meta else None)
    doc_type = PDF_META.get(src.source_id, {}).get("doc_type", "definition")
    chunks: list[Chunk] = []
    section = None
    for pno, text in pages:
        lines = [ln.strip() for ln in text.splitlines()]
        buf: list[str] = []
        segs: list[tuple[str | None, str]] = []
        for ln in lines:
            if _HEADING.match(ln) and not re.search(r"\.{4,}|\s\d+$", ln):
                if buf:
                    segs.append((section, " ".join(buf)))
                    buf = []
                section = ln
            elif ln:
                buf.append(ln)
        if buf:
            segs.append((section, " ".join(buf)))
        for sec, seg in segs:
            seg = re.sub(r"\s+", " ", seg).strip()
            if len(seg) < 40 or re.fullmatch(r"[\d .\-|©A-Za-z]{0,60}", seg) or FRONT_MATTER_RE.search(seg):
                continue
            for w in _windows(seg):
                chunks.append(Chunk(
                    chunk_id=f"{src.source_id}#p{pno}c{len(chunks)}", doc_id=src.source_id, title=title, url=src.url,
                    doc_type=doc_type, publication_date=pub, event_region=None, event_date=None, page=pno,
                    section=sec, text=w, chunk_hash=_hash(w), source_sha256=src.sha256,
                    instruction_like=bool(INJECTION_RE.search(w))))
    return chunks


# ---------------------------------------------------------------------------------------------- MMS DM
def _cells(row_html: str) -> list[str]:
    cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S | re.I)
    return [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip() for c in cells]


def mms_chunks(src: SourceEntry, path: Path, published: str | None) -> list[Chunk]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    parts = re.split(r"<h2>\s*<a name=\"\d+\">Table:\s*", raw)
    chunks: list[Chunk] = []
    for part in parts[1:]:
        name = re.match(r"([A-Z0-9_]+)", part)
        if not name:
            continue
        table = name.group(1)
        form = re.search(r'<table class="Form".*?</table>', part, re.S)
        comment = ""
        if form:
            for row in re.findall(r"<tr>(.*?)</tr>", form.group(0), re.S):
                c = _cells(row)
                if len(c) == 2 and c[0] in ("Comment", "Description") and c[1]:
                    comment += f" {c[0]}: {c[1]}."
        content = re.search(r"<a name=\"\d+\">Content</a>.*?(<table.*?</table>)", part, re.S)
        fields = []
        if content:
            for row in re.findall(r"<tr>(.*?)</tr>", content.group(1), re.S)[1:]:
                c = _cells(row)
                if len(c) >= 4 and c[0]:
                    fields.append(f"{c[0]} ({c[1]}{', mandatory' if c[2] == 'X' else ''}): {c[3] or 'no comment'}.")
        head = f"MMS Data Model table {table}.{comment}"
        body = head + " Fields: " + " ".join(fields)
        pieces = _windows(body, size=1400, overlap=0) if len(body) > 1400 else [body]
        for i, piece in enumerate(pieces):
            text = piece if i == 0 else f"MMS Data Model table {table} (continued). {piece}"
            chunks.append(Chunk(
                chunk_id=f"{src.source_id}#{table}#{i}", doc_id=src.source_id,
                title="AEMO MMS Data Model Report (Electricity)", url=src.url, doc_type="definition",
                publication_date=published, event_region=None, event_date=None, page=None, section=f"Table: {table}",
                text=text, chunk_hash=_hash(text), source_sha256=src.sha256, instruction_like=bool(INJECTION_RE.search(text))))
    return chunks


def mms_published(path: Path) -> str | None:
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", path.read_text(encoding="utf-8", errors="replace"))))
    m = re.search(r"Published by:\s*AEMO\s*(\d\d)/(\d\d)/(20\d\d)", t)
    if not m:
        return None
    return iso_utc(datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)), 23, 59, 59, tzinfo=NEM_TZ))


# ---------------------------------------------------------------------------------------------- notices
def parse_notice(text: str) -> dict[str, Any]:
    def field(label: str) -> str | None:
        m = re.search(rf"^{label}\s*:\s*(.+)$", text, re.M)
        return m.group(1).strip() if m else None

    created = field("Creation Date")
    created_dt = None
    if created:
        m = re.match(r"(\d\d)/(\d\d)/(\d{4})\s+(\d\d):(\d\d):(\d\d)", created)
        if m:
            d, mo, y, hh, mi, ss = map(int, m.groups())
            created_dt = datetime(y, mo, d, hh, mi, ss, tzinfo=NEM_TZ).astimezone(UTC)
    ext = field("External Reference") or ""
    reason = text.split("Reason :", 1)[1] if "Reason :" in text else text
    reason = re.sub(r"-{10,}|END OF REPORT", " ", reason)
    reason = re.sub(r"\s+", " ", reason).strip()
    head = ext + " " + reason[:300]
    found: set[str] = set()
    for m in re.finditer(r"\b(NSW|QLD|SA|TAS|VIC)\s+[Rr]egion\b|\bin (?:the )?(NSW|QLD|SA|TAS|VIC)\b", head):
        found.add(REGION_NAMES[m.group(1) or m.group(2)])
    found |= set(re.findall(r"\bRegion\s+(NSW1|QLD1|SA1|TAS1|VIC1)\b", head))
    for name, code in STATE_NAMES.items():
        if name in head:
            found.add(code)
    region = next(iter(found)) if len(found) == 1 else None  # multi-region or unknown -> not region-specific
    ev_date = None
    m3 = re.search(r"(\d\d)/(\d\d)/(20\d\d)\s*$", ext)
    if m3:
        ev_date = f"{m3.group(3)}-{m3.group(2)}-{m3.group(1)}"
    elif created_dt:
        ev_date = created_dt.astimezone(NEM_TZ).date().isoformat()
    return {"notice_id": field("Notice ID"), "type": field("Notice Type ID"), "type_desc": field("Notice Type Description"),
            "external_reference": ext, "created_utc": iso_utc(created_dt) if created_dt else None, "region": region,
            "event_date": ev_date, "reason": reason}


# A notice that cancels an earlier one names it: "The Forecast LOR2 condition … advised in AEMO Electricity Market
# Notice No. 144624 is cancelled at 0920 hrs 27/07/2026", "Refer to Market Notice 144636 Direction is cancelled from
# …", "CANCELLATION - … Refer to market notice: 144637 AEMO has ceased …" (held-out v4 W19 relied on three reserve
# forecasts that later notices had cancelled).
_CANCEL_TITLE_RE = re.compile(r"\bcancel", re.I)
_CANCELLED_TEXT_RE = re.compile(r"\b(?:is|are|been) cancelled\b|\bcancelled (?:at|from)\b|\bceased\b", re.I)
_NOTICE_REF_RE = re.compile(r"(?:Notice No\.?|Market Notice:?)\s*(\d{5,7})\b", re.I)
NOTICE_NUMBER_RE = re.compile(r"^market_notice_(\d+)#")


def cancelled_notices(title: str, text: str) -> list[str]:
    """The numbers of the earlier market notices this notice cancels; none unless it says it cancels something."""
    if not (_CANCEL_TITLE_RE.search(title or "") or _CANCELLED_TEXT_RE.search(text or "")):
        return []
    return list(dict.fromkeys(_NOTICE_REF_RE.findall(text or "")))


def notice_chunk(src: SourceEntry, path: Path) -> Chunk | None:
    raw = path.read_text(encoding="utf-8", errors="replace")
    n = parse_notice(raw)
    if not n["notice_id"]:
        return None
    title = f"AEMO market notice {n['notice_id']} ({n['type']}): {n['external_reference']}"[:240]
    text = f"{n['external_reference']}. {n['reason']}".strip()
    text = text[:2400]
    return Chunk(chunk_id=f"{src.source_id}#0", doc_id=src.source_id, title=title, url=src.url, doc_type="market_notice",
                 publication_date=n["created_utc"], event_region=n["region"], event_date=n["event_date"], page=None,
                 section=n["type"], text=text, chunk_hash=_hash(text), source_sha256=src.sha256,
                 instruction_like=bool(INJECTION_RE.search(text)))


# ---------------------------------------------------------------------------------------------- build
def build_corpus(sel: Selection, log: Any = print) -> tuple[list[Chunk], list[dict[str, Any]]]:
    chunks: list[Chunk] = []
    status: list[dict[str, Any]] = []
    cover = next((s for s in sel.sources if s.source_id == "mms_dm_cover"), None)
    mms_pub = None
    if cover:
        rf = rawstore.get(cover.dataset, cover.url, expected_sha256=cover.sha256)
        if rf.available:
            mms_pub = mms_published(Path(rf.local_path))
    for src in sel.sources:
        if src.dataset not in ("AEMO_PDF", "MMS_DATA_MODEL_HTML", "MARKET_NOTICE") or src.role in ("document_toc", "document_cover"):
            continue
        rf = rawstore.get(src.dataset, src.url, expected_sha256=src.sha256, max_bytes=30_000_000)
        if rf.rolled_off:
            from ..recover import recover_from_archive

            rf = recover_from_archive(src.dataset, src.url, src.sha256, log=log) or rf
        if not rf.available:
            entry: dict[str, Any] = {"source_id": src.source_id, "ok": False, "error": rf.error, "rolled_off": rf.rolled_off,
                                     "pin_status": rf.pin_status, "upstream": rf.upstream}
            if rf.rolled_off and src.dataset == "MARKET_NOTICE":
                from ..recover import notice_archive_listing

                lst = notice_archive_listing()
                entry["archive_checked"] = {k: lst[k] for k in ("url", "http_status", "checked_at", "n_files")}
            status.append(entry)
            if not rf.rolled_off:
                log(f"[index] MISSING {src.source_id} ({rf.pin_status}): {rf.error}")
            continue
        p = Path(rf.local_path)
        try:
            if src.dataset == "AEMO_PDF":
                new = pdf_chunks(src, p)
            elif src.dataset == "MMS_DATA_MODEL_HTML":
                new = mms_chunks(src, p, mms_pub)
            else:
                c = notice_chunk(src, p)
                new = [c] if c else []
        except Exception as exc:  # parse failure: record, never invent text
            status.append({"source_id": src.source_id, "ok": False, "error": f"{type(exc).__name__}: {exc}",
                           "pin_status": "unavailable", "upstream": rf.upstream})
            continue
        chunks.extend(new)
        status.append({"source_id": src.source_id, "ok": True, "chunks": len(new), "fetch": rf.status,
                       "pin_status": "pinned", "upstream": rf.upstream})
    return chunks, status
