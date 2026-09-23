"""Structured, redacted trace of one investigation (route, tool, retrieve, validate, approve, model calls)."""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import paths

_SECRET_PATTERNS = [re.compile(r"sk-[A-Za-z0-9_\-]{8,}"), re.compile(r"(?i)(api[_-]?key|authorization)\s*[:=]\s*\S+")]


def redact(value: Any) -> Any:
    if isinstance(value, str):
        out = value
        for pat in _SECRET_PATTERNS:
            out = pat.sub("[REDACTED]", out)
        key = os.environ.get("OPENAI_API_KEY")
        if key and len(key) > 8:
            out = out.replace(key, "[REDACTED]")
        return out
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if k.lower() in {"api_key", "authorization", "openai_api_key"} else redact(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


@dataclass
class Trace:
    trace_id: str = field(default_factory=lambda: f"tr-{uuid.uuid4().hex[:12]}")
    started_at: str = field(default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
    events: list[dict[str, Any]] = field(default_factory=list)
    _t0: float = field(default_factory=time.monotonic)

    def add(self, kind: str, name: str, **data: Any) -> dict[str, Any]:
        ev = {"seq": len(self.events) + 1, "t_ms": round((time.monotonic() - self._t0) * 1000, 1), "kind": kind,
              "name": name, **redact(data)}
        self.events.append(ev)
        return ev

    def as_dict(self) -> dict[str, Any]:
        return {"trace_id": self.trace_id, "started_at": self.started_at, "events": self.events}

    def write(self, directory: Path | None = None) -> Path:
        d = directory or paths.artifacts_dir() / "traces"
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{self.trace_id}.json"
        p.write_text(json.dumps(self.as_dict(), indent=2, default=str))
        return p
