"""Typed model of ``data/source_selection.json`` (written by the G0 probe, consumed by ingestion)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import paths

ALLOWED_URL_PREFIXES = (
    "https://nemweb.com.au/",
    "https://www.aemo.com.au/-/media/",
    "https://power.larc.nasa.gov/api/",
)

Dataset = Literal[
    "DISPATCHIS",
    "DISPATCH_SCADA",
    "PUBLIC_PRICES",
    "OPDEM_FORECAST_HH",
    "OPDEM_ACTUAL_HH",
    "OPDEM_ACTUAL_DAILY",
    "MARKET_NOTICE",
    "MMSDM_DUDETAILSUMMARY",
    "MMS_DATA_MODEL_HTML",
    "AEMO_PDF",
    "NASA_POWER_HOURLY",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SupersededPin(_Strict):
    """A previous pin kept after a reviewed re-pin (scripts/repin_source.py): the publisher revised the content."""

    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_sha256: str | None = Field(None, pattern=r"^[0-9a-f]{64}$")
    size: int = Field(gt=0)
    last_modified: str | None = None
    retrieved_at: str
    superseded_at: str
    new_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    publisher_revision: str = Field(min_length=3, description="what the publisher changed, as verified by a reviewer")
    reason: str = Field(min_length=3)
    # Recorded by scripts/repin_source.py since the source-governance workflow (docs/source-governance.md); optional
    # only because the first three re-pins (2026-09-25) predate it.
    approved_by: str | None = Field(None, min_length=2)
    refresh_report: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = Field(None, description="publisher version / API metadata, pinned and current")
    old_bytes: str | None = Field(None, description="where the superseded bytes are kept, or why they are not")


class SourceEntry(_Strict):
    source_id: str
    dataset: Dataset
    role: str
    url: str = Field(min_length=12)
    container_kind: Literal["archive", "current", "document", "api"]
    publisher: str
    http_status: int
    content_type: str | None = None
    size: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_sha256: str | None = Field(None, pattern=r"^[0-9a-f]{64}$",
                                       description="canonical hash for API responses with volatile metadata")
    retrieved_at: str
    last_modified: str | None = None
    coverage: dict[str, Any] | None = None
    schema_fields: dict[str, list[str]] | None = None
    issue_time_provenance: str | None = None
    events: list[str] = Field(default_factory=list)
    notes: str | None = None
    superseded: list[SupersededPin] = Field(default_factory=list)

    @field_validator("url")
    @classmethod
    def _allowed(cls, v: str) -> str:
        if not v.startswith(ALLOWED_URL_PREFIXES):
            raise ValueError(f"URL {v!r} is not under an allowlisted publisher prefix")
        return v


class SeriesSpec(_Strict):
    dataset: Dataset
    table: str
    field: str
    definition: str
    interval_minutes: int
    unit: str


class Comparison(_Strict):
    comparison_id: str
    forecast: SeriesSpec
    actual: SeriesSpec
    evidence: list[str]


class EventSelection(_Strict):
    event_id: str
    role: Literal["primary", "evaluation"]
    region: str
    timezone: str
    kind: Literal["high_price", "low_price"]
    peak_interval_end_utc: str
    peak_interval_end_market: str
    peak_rrp: float
    window_start_utc: str
    window_end_utc: str
    intervals_meeting_threshold_in_window: int
    selection_reason: str
    checks: dict[str, Any]


class Selection(_Strict):
    schema_version: Literal[1] = 1
    generated_at: str
    probe_version: str
    analysis_threshold: dict[str, Any]
    market_time: dict[str, Any]
    availability: dict[str, Any]
    host_checks: list[dict[str, Any]]
    primary_event_id: str
    events: list[EventSelection] = Field(min_length=1)
    comparisons: list[Comparison] = Field(min_length=1)
    sources: list[SourceEntry] = Field(min_length=1)
    attempted_unavailable: list[dict[str, Any]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def event(self, event_id: str) -> EventSelection:
        for ev in self.events:
            if ev.event_id == event_id:
                return ev
        raise KeyError(event_id)

    @property
    def primary(self) -> EventSelection:
        return self.event(self.primary_event_id)

    def sources_for(self, dataset: str) -> list[SourceEntry]:
        return [s for s in self.sources if s.dataset == dataset]


def load_selection(path: Path | None = None) -> Selection:
    p = path or paths.selection_path()
    return Selection.model_validate(json.loads(p.read_text()))
