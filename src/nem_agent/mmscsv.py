"""Parser for AEMO MMS "CSV" report files (``C``/``I``/``D`` record format) and nested NEMWeb zips.

Integrity rules enforced here (a file that breaks one raises :class:`MmsFormatError`; callers never
fill gaps with invented rows):

* the first record is a ``C`` header carrying the report name and AEMO creation date/time;
* every ``D`` row belongs to a table declared by a preceding ``I`` row with the same field count;
* the file ends with ``C,"END OF REPORT",<n>`` where ``n`` equals the number of lines in the file,
  so a truncated download is detected;
* required fields per table are checked by :func:`require_fields` (schema-drift detection).
"""

from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime

from .timeutil import parse_market

TableKey = tuple[str, str, str]  # (report, subtype, version)


class MmsFormatError(ValueError):
    """The file does not follow the AEMO MMS CSV contract."""


class SchemaDriftError(MmsFormatError):
    """A table is missing fields this project depends on."""


@dataclass
class MmsFile:
    member_path: str
    report_name: str
    created_at_utc: datetime
    created_at_market: str
    line_count: int
    tables: dict[TableKey, list[str]] = field(default_factory=dict)
    sha256: str = ""


@dataclass(frozen=True)
class Record:
    line_no: int  # 1-based line number within the CSV member
    table: TableKey
    values: dict[str, str]


def parse_mms_csv(
    data: bytes,
    member_path: str,
    wanted: set[tuple[str, str]] | None = None,
    line_prefixes: tuple[str, ...] | None = None,
) -> tuple[MmsFile, list[Record]]:
    """Parse one CSV member. ``wanted`` limits returned records to (report, subtype) pairs.

    ``line_prefixes`` is a performance filter for very large multi-table files (e.g. DispatchIS): only
    ``D`` lines starting with one of the prefixes are CSV-decoded, but *all* lines are counted and all
    ``I`` rows are parsed so the integrity checks still cover the full file.
    """
    text = data.decode("utf-8-sig", errors="strict")
    lines = text.splitlines()
    if not lines:
        raise MmsFormatError(f"{member_path}: empty file")
    first = next(csv.reader([lines[0]]))
    if len(first) < 7 or first[0] != "C":
        raise MmsFormatError(f"{member_path}: missing C header row")
    try:
        created = parse_market(f"{first[5]} {first[6]}")
    except ValueError as exc:
        raise MmsFormatError(f"{member_path}: bad creation timestamp in C row: {exc}") from exc
    last = next(csv.reader([lines[-1]]))
    if len(last) < 3 or last[0] != "C" or last[1] != "END OF REPORT":
        raise MmsFormatError(f"{member_path}: missing END OF REPORT trailer (truncated file?)")
    try:
        declared = int(last[2])
    except ValueError as exc:
        raise MmsFormatError(f"{member_path}: bad END OF REPORT count {last[2]!r}") from exc
    if declared != len(lines):
        raise MmsFormatError(f"{member_path}: END OF REPORT says {declared} lines but file has {len(lines)}")

    mf = MmsFile(
        member_path=member_path,
        report_name=first[2],
        created_at_utc=created,
        created_at_market=f"{first[5]} {first[6]}",
        line_count=len(lines),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    records: list[Record] = []
    for idx, line in enumerate(lines[1:-1], start=2):
        kind = line[:2]
        if kind == "I,":
            row = next(csv.reader([line]))
            key: TableKey = (row[1], row[2], row[3])
            mf.tables[key] = row[4:]
            continue
        if kind != "D,":
            if kind == "C,":
                continue
            raise MmsFormatError(f"{member_path}:L{idx}: unexpected record type {line[:10]!r}")
        if line_prefixes is not None and not line.startswith(line_prefixes):
            continue
        row = next(csv.reader([line]))
        key = (row[1], row[2], row[3])
        header = mf.tables.get(key)
        if header is None:
            raise MmsFormatError(f"{member_path}:L{idx}: D row for undeclared table {key}")
        if len(row) - 4 != len(header):
            raise MmsFormatError(
                f"{member_path}:L{idx}: {len(row) - 4} values but table {key} declares {len(header)} fields"
            )
        if wanted is not None and (key[0], key[1]) not in wanted:
            continue
        records.append(Record(line_no=idx, table=key, values=dict(zip(header, row[4:], strict=True))))
    return mf, records


def require_fields(mf: MmsFile, report: str, subtype: str, fields: Iterable[str]) -> TableKey:
    """Return the highest-version table key for (report, subtype) after checking required fields."""
    candidates = sorted((k for k in mf.tables if k[0] == report and k[1] == subtype), key=lambda k: int(k[2]))
    if not candidates:
        raise SchemaDriftError(f"{mf.member_path}: table {report}/{subtype} not present")
    key = candidates[-1]
    missing = [f for f in fields if f not in mf.tables[key]]
    if missing:
        raise SchemaDriftError(f"{mf.member_path}: table {report}/{subtype} v{key[2]} missing fields {missing}")
    return key


def iter_csv_members(container: bytes, container_name: str) -> Iterator[tuple[str, bytes]]:
    """Yield (member_path, csv_bytes) from a NEMWeb zip, descending into nested zips (archives)."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(container))
    except zipfile.BadZipFile as exc:
        raise MmsFormatError(f"{container_name}: not a valid zip ({exc})") from exc
    with zf:
        for info in sorted(zf.infolist(), key=lambda i: i.filename):
            if info.is_dir():
                continue
            payload = zf.read(info)
            lower = info.filename.lower()
            if lower.endswith(".zip"):
                for inner_path, inner in iter_csv_members(payload, info.filename):
                    yield f"{info.filename}/{inner_path}", inner
            elif lower.endswith(".csv"):
                yield info.filename, payload
