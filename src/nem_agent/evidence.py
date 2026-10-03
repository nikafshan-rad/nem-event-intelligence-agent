"""Per-request evidence registry.

Every number a tool returns is registered here with its unit, valid time, source rows and evidence class.
The report validator (G5) accepts a numeric claim only if it resolves to one of these items; every cited
document passage must be registered as a retrieved chunk. The registry is filled by deterministic tool code,
never by the model.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from .timeutil import iso_utc

EvidenceClass = Literal[
    "observed",                     # AEMO actual / dispatch observation
    "aemo_forecast",                # AEMO-issued forecast value
    "derived",                      # computed by project code from registered items (e.g. forecast error)
    "retrospective_context",        # NASA POWER reanalysis-style weather, available only after the fact
    "published_document",           # text from a retrieved public document
]


@dataclass
class EvidenceItem:
    evidence_id: str
    evidence_class: EvidenceClass
    metric: str
    value: float | None
    unit: str
    region: str | None
    valid_at_utc: str | None
    interval_minutes: int | None
    source_row_ids: list[str]
    source_urls: list[str]
    tool_call_id: str
    published_at_utc: str | None = None
    available_at_utc: str | None = None
    derivation: str | None = None
    label: str | None = None
    coverage: dict[str, Any] | None = None  # an aggregate over intervals: what it was computed from (I-20)

    def as_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        if d["coverage"] is None:  # only aggregates carry it; every other item is serialised as before
            del d["coverage"]
        return d


def aggregate_coverage(window: tuple[datetime, datetime], interval_minutes: int, included: Iterable[datetime],
                       excluded_by_as_of: int | None = None) -> dict[str, Any]:
    """What an aggregate over intervals was computed from (I-20, K05: an MAE over one paired half-hour of a 12-hour
    window was described as covering "the 24-hour target window"), from the calculation's own inputs:
    - **the requested analysis window** (the call's own start and end, interval-ending: (start, end]);
    - **the intervals included** (their ends), and how many the window holds (``intervals_expected``);
    - **the interval length**, the **contiguous runs** of included intervals and the **gaps** around and between them.
      The runs are never the span from the first included interval to the last: sparse intervals spanning a window
      are not continuous coverage of it;
    - **intervals left out by an as-of cutoff,** when the tool knows them (else None)."""
    w0, w1 = window
    step = timedelta(minutes=interval_minutes)
    ends = sorted({t for t in included if w0 < t <= w1})
    runs: list[list[datetime]] = []
    for t in ends:
        if runs and t - runs[-1][1] == step:
            runs[-1][1] = t
        else:
            runs.append([t - step, t])
    gaps, at = [], w0
    for a, b in runs:
        if a > at:
            gaps.append([at, a])
        at = b
    if at < w1:
        gaps.append([at, w1])
    expected = round((w1 - w0) / step)
    return {"window_utc": [iso_utc(w0), iso_utc(w1)], "interval_minutes": interval_minutes,
            "intervals_expected": expected, "intervals_included": len(ends),
            "included_ends_utc": [iso_utc(t) for t in ends],
            "runs_utc": [[iso_utc(a), iso_utc(b)] for a, b in runs], "gaps_utc": [[iso_utc(a), iso_utc(b)] for a, b in gaps],
            "complete": len(ends) == expected and not gaps, "contiguous": len(runs) == 1,
            "excluded_by_as_of": excluded_by_as_of}


@dataclass
class ChunkItem:
    chunk_id: str
    doc_id: str
    title: str
    url: str
    text: str
    section: str | None
    page: int | None
    publication_date: str | None
    doc_type: str
    event_region: str | None
    event_date: str | None
    eligible: bool
    eligibility_reason: str
    tool_call_id: str
    score: float | None = None
    instruction_like: bool = False

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class EvidenceRegistry:
    items: dict[str, EvidenceItem] = field(default_factory=dict)
    chunks: dict[str, ChunkItem] = field(default_factory=dict)
    _n: int = 0

    def add(self, **kw: Any) -> EvidenceItem:
        self._n += 1
        eid = f"ev{self._n:04d}"
        item = EvidenceItem(evidence_id=eid, **kw)
        self.items[eid] = item
        return item

    def add_chunk(self, chunk: ChunkItem) -> ChunkItem:
        self.chunks[chunk.chunk_id] = chunk
        return chunk

    def get(self, evidence_id: str) -> EvidenceItem | None:
        return self.items.get(evidence_id)

    def by_class(self, cls: str) -> list[EvidenceItem]:
        return [i for i in self.items.values() if i.evidence_class == cls]

    def as_dict(self) -> dict[str, Any]:
        return {"items": {k: v.as_dict() for k, v in self.items.items()},
                "chunks": {k: v.as_dict() for k, v in self.chunks.items()}}
