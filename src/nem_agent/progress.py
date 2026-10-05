"""Progress of a standard Live investigation, for display while it runs (D36).

A caller of ``service.investigate`` may pass ``progress``, a callable that receives one ``Progress`` per stage. It
carries no model text: the stage, the tool-turn number, the resolved region, window and cutoff, and a snapshot of the
tool records so far. Without a callback nothing changes. A callback that raises is not called again: the run goes on
exactly as it would without one (no retry, no repeated tool or model call), and the trace records the failure once.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

Stage = Literal["routing", "routed", "tools", "tool_results", "synthesis", "checking", "repair", "finalizing"]


@dataclass(frozen=True)
class Progress:
    """One stage of a standard Live investigation.

    - ``routing``: the routing call is about to be sent; ``routed``: the request is resolved (``status``, and the
      region, window and cutoff when it was);
    - ``tools``: a tool-choosing model turn is about to be sent (``turn``); ``tool_results``: tools have run
      (``records``, every call so far, successful or not);
    - ``synthesis``: the report is about to be written; ``checking``: the draft goes to the independent validator;
      ``repair``: the one repair turn is about to be sent; ``finalizing``: the final validation.
    """

    stage: Stage
    turn: int | None = None
    status: str | None = None
    region: str | None = None
    window: tuple[datetime, datetime] | None = None
    as_of: datetime | None = None
    records: tuple[Any, ...] = ()


ProgressCallback = Callable[[Progress], None]
