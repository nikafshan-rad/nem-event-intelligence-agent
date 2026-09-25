"""Per-request evidence registry.

Every number a tool returns is registered here with its unit, valid time, source rows and evidence class.
The report validator (G5) accepts a numeric claim only if it resolves to one of these items; every cited
document passage must be registered as a retrieved chunk. The registry is filled by deterministic tool code,
never by the model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

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

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


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
