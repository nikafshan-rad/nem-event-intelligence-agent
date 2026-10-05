"""The standard Live investigation's progress panel (D36).

While a Live investigation runs, the panel shows the current stage and the elapsed time, and draws the existing price
and demand charts from the tool results so far: only successful results that match the resolved region, window and
cutoff, labelled as retrieved data from the pinned snapshot, never as an answer. It shows no model text: the answer
appears only once the run is finalized, on the page below. This shortens the blank wait; it does not shorten the run.

**Clicks during a run.** Streamlit asks a running script to rerun or stop by raising, at the script's next Streamlit
command, an exception that derives from ``BaseException`` but not from ``Exception``. Without the panel the script
issues no command while the investigation runs, so a click takes effect only when it ends. The panel issues commands
between stages, so it keeps such a request (``_kept``) and raises it once the result is stored (``resume``): the run is
never cut short, as before. No Streamlit internals are imported. Errors (``Exception``) are not kept: the controller
drops a failing callback and records it once. Interrupts and exits (``KeyboardInterrupt``, ``SystemExit``,
``GeneratorExit``) are never kept.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import streamlit as st

from nem_agent.progress import Progress
from nem_agent.timeutil import REGION_TZ
from nem_agent.ui_data import (
    EARLY_DATA_FAILED,
    EARLY_DATA_LABEL,
    demand_chart,
    early_chart_notes,
    early_chart_records,
    frames,
    price_chart,
    result_provenance,
)

STAGES = {"routing": "Reading the question (routing call)",
          "tools": "Choosing and running tools (model turn {turn})",
          "synthesis": "Writing the answer (model)",
          "checking": "Checking the draft (independent validator)",
          "repair": "Repairing the draft (one repair turn)",
          "finalizing": "Final validation"}
# what the demand chart's title says when no forecast is drawn, by stage (the finished page keeps its own wording)
NO_FORECAST_YET = "no forecast retrieved so far"
NO_FORECAST_DONE = "no forecast runs were retrieved"
NO_FORECAST_FAILED = "no forecast runs were retrieved before the run failed"
_NEVER_KEPT = (KeyboardInterrupt, SystemExit, GeneratorExit)


def _md(text: str) -> str:
    return text.replace("$", "\\$")


class LiveProgress:
    """The callback ``service.investigate`` is given for a standard Live run, and the panel it draws in."""

    def __init__(self) -> None:
        self.t0 = time.monotonic()
        self.theme = "dark" if getattr(getattr(st.context, "theme", None), "type", "light") == "dark" else "light"
        self.box = st.status("Live investigation: starting", expanded=True)
        with self.box:
            self.steps_slot = st.empty()
            self.data_slot = st.empty()
        self.steps: list[list[Any]] = []  # [label, started at (s), ended at (s) or None]
        self.region: str | None = None
        self.window: Any = None
        self.as_of: Any = None
        self.records: tuple[Any, ...] = ()
        self.no_forecast = NO_FORECAST_YET
        self.deferred: BaseException | None = None

    def elapsed(self) -> float:
        return time.monotonic() - self.t0

    @contextmanager
    def _kept(self) -> Iterator[None]:
        """Keep a rerun or stop request raised by a Streamlit command in the block; let everything else through."""
        try:
            yield
        except (Exception, *_NEVER_KEPT):
            raise
        except BaseException as request:  # Streamlit's rerun or stop request: honoured by ``resume``
            self.deferred = self.deferred or request

    # -- the callback ------------------------------------------------------------------------------------------------
    def __call__(self, ev: Progress) -> None:
        with self._kept():
            self._update(ev)

    def _update(self, ev: Progress) -> None:
        now = self.elapsed()
        if ev.stage == "routed":
            self.region, self.window, self.as_of = ev.region, ev.window, ev.as_of
        elif ev.stage == "tool_results":
            # after a model turn more tools may follow; the event before synthesis (no turn) comes after the last one
            self.records, self.no_forecast = ev.records, NO_FORECAST_YET if ev.turn is not None else NO_FORECAST_DONE
            self._draw(EARLY_DATA_LABEL)
        else:
            if self.steps and self.steps[-1][2] is None:
                self.steps[-1][2] = now
            self.steps.append([STAGES[ev.stage].format(turn=ev.turn), now, None])
        # the page cannot redraw while a model call is under way, so the time is stated as of the update, never as a
        # clock that seems to run: when the current stage began, and how long each finished stage took
        label, began = (self.steps[-1][0], self.steps[-1][1]) if self.steps else ("starting", now)
        self.box.update(label=f"Live investigation: {label} · began {began:.0f} s into the run "
                              f"(updated at each stage)")
        self._list_steps()

    def _list_steps(self) -> None:
        self.steps_slot.markdown("\n".join(
            f"- {label}: {end - start:.1f} s" if end is not None else f"- {label}: running since {start:.0f} s"
            for label, start, end in self.steps))

    def _draw(self, caption: str) -> None:
        """The existing charts, from matching successful results only, under ``caption``; the data limitations."""
        recs = early_chart_records(self.records, self.region, self.window, self.as_of)
        pdf, ddf = frames(recs, self.region)
        notes = early_chart_notes(self.records, self.region, self.window, self.as_of)
        with self.data_slot.container():
            if self.region and (not pdf.empty or not ddf.empty):
                st.caption(caption)
                tz = REGION_TZ[self.region]
                if not pdf.empty:
                    st.altair_chart(price_chart(pdf, self.region, tz, self.theme), width="stretch")
                if not ddf.empty:
                    st.altair_chart(demand_chart(ddf, self.region, tz, self.theme, no_forecast=self.no_forecast),
                                    width="stretch")
            if notes:
                st.markdown(_md("**Data limitations so far**\n" + "\n".join(f"- {n}" for n in notes)))

    # -- the outcome ---------------------------------------------------------------------------------------------------
    def finish(self, res: Any) -> None:
        """The run returned a result (an answer, a fallback, a budget stop or a clarification): its own outcome is the
        panel's label, and the early charts go, since the finished result below draws its own."""
        with self._kept():
            now = self.elapsed()
            if self.steps and self.steps[-1][2] is None:
                self.steps[-1][2] = now
            prov = result_provenance(res.report.model_dump(), res.usage)
            self.data_slot.empty()
            self._list_steps()
            self.box.update(label=f"Live investigation ended after {now:.1f} s: {prov['label']}",
                            state="error" if prov["kind"] == "live_stopped" else "complete", expanded=False)

    def fail(self, exc: BaseException) -> None:
        """The run raised: no answer exists. The early charts stay, relabelled so they cannot read as an answer."""
        with self._kept():
            now = self.elapsed()
            if self.steps and self.steps[-1][2] is None:
                self.steps[-1][2] = now
            self.box.update(label=f"Live investigation failed after {now:.1f} s ({type(exc).__name__}): no answer "
                                  "was produced", state="error", expanded=True)
            self._list_steps()
            self.no_forecast = NO_FORECAST_FAILED
            try:
                self._draw(EARLY_DATA_FAILED)
            except Exception:  # the outcome above stands; the run's own error is what propagates
                self.data_slot.empty()

    def resume(self) -> None:
        """A rerun or stop asked for during the run takes effect now, after the result is kept."""
        if self.deferred is not None:
            raise self.deferred
