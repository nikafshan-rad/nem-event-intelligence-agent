"""The experimental confirmed-request workflow in the app (opt-in; ``nem_agent.agent.confirm``).

Question, request preview, one focused question at a time, confirmation of one exact revision, and the computed answer
of the confirmed request. The conversation state lives in this browser session only (``st.session_state``); a
confirmed revision runs once, whatever reruns follow.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from datetime import date
from typing import Any

import streamlit as st

from nem_agent.agent import confirm as C
from nem_agent.selection import Selection
from nem_agent.ui_data import observation_table, result_provenance

KEY = "confirm_flow"
LABEL = "Experimental: confirm the request first"
# progress shown while a routing call may run: feedback only, with no promised duration
READING_QUESTION = "Reading your question with the routing model. Nothing runs until you confirm the request."
READING_REPLY = "Reading your answer (the routing model reads it only if the parsers cannot)."
HISTORY = "Diagnostics: how the routing model read the question (historical)"
CURRENT = ("**Needs clarification** is worked out from the request as it stands now, and changes as you answer or edit "
           "it.")


def _state() -> dict[str, Any]:
    if KEY not in st.session_state:
        st.session_state[KEY] = C.new_state()
    return st.session_state[KEY]


def _interpreter(live_ok: bool) -> C.Interpreter | None:
    if not live_ok:
        return None
    from nem_agent.service import interpret_request

    return lambda q: interpret_request(q)


def _choose(revision: int, field: str, value: Any, sel: Selection) -> None:
    C.choose(_state(), revision, field, value, sel)


def _confirm(rid: str, sel: Selection) -> None:
    C.confirm(_state(), rid, sel)


def _restart() -> None:
    st.session_state[KEY] = C.new_state()


def render(sel: Selection, live_ok: bool, md: Callable[[str], str]) -> None:
    state = _state()
    st.title("NEM Event Intelligence Agent")
    st.warning(f"**{LABEL}** (experimental). Ask about a demand maximum or a forecast comparison. Before anything runs, "
               "the request is shown as the system read it; settle what is open, then confirm. The confirmed request "
               "is computed by code from the pinned data, with no further model call. The preview is the system's "
               "interpretation of the request, not proof that the question was understood.")
    if not live_ok:
        st.info("No OPENAI_API_KEY: **guided structured input**. Your question is recorded but not read by any model; "
                "the request is built only from the choices you make below. This is not natural-language "
                "extraction.")
    if state.get("error"):
        st.error(state.pop("error"))
    x = C.take_pending(state, sel)
    if x is not None:  # the confirmed revision runs here, once
        from nem_agent.service import execute_confirmed

        rid = C.revision_id(x)
        with st.spinner("Running the confirmed request..."):
            state["results"][rid] = execute_confirmed(x, original=state["original"])
        state["last_result"] = rid
    for m in state["history"]:
        with st.chat_message(m["role"]):
            st.markdown(md(m["text"]))
    d = C.draft_of(state)
    if d is not None:
        _draft_panel(state, d, sel, md)
    rid_done = state.get("last_result")
    if rid_done and rid_done in state["results"]:
        _result(state, rid_done, sel, md)
    done = d is not None and state.get("confirmed") is not None and state.get("confirmed") in state["results"]
    prompt = st.chat_input("Ask about a demand maximum or a forecast comparison" if d is None or done else
                           "Answer the question above (or choose an option)")
    if prompt:
        try:
            if d is None or done or d.refused:
                with st.spinner(READING_QUESTION) if live_ok else contextlib.nullcontext():
                    C.start(state, prompt, _interpreter(live_ok))
            else:
                model = live_ok and state.get("model_replies", True)
                with st.spinner(READING_REPLY) if model else contextlib.nullcontext():
                    C.reply(state, prompt, sel, _interpreter(live_ok) if model else None)
        except Exception as exc:  # the routing call failed (budget, API): nothing changed and nothing ran
            state["error"] = f"The routing call failed ({type(exc).__name__}: {str(exc)[:300]}); nothing ran."
        st.rerun()


def _draft_panel(state: dict[str, Any], d: C.Draft, sel: Selection, md: Callable[[str], str]) -> None:
    with st.container(border=True):
        st.markdown("**Request preview**")
        st.caption(C.preview_label(d))
        st.table([{"field": k, "value": v} for k, v in C.preview(d, sel)])
        st.caption(CURRENT)
    _history(state, md)
    if d.refused:
        st.error(md(d.refused))
        st.button("Start over", on_click=_restart, key=f"cf-restart-{d.revision}")
        return
    open_ = C.issues(d, sel)
    if open_:
        issue = open_[0]
        with st.chat_message("assistant"):
            st.markdown(md(issue.message))
            if issue.choices:
                cols = st.columns(min(len(issue.choices), 3))
                for i, c in enumerate(issue.choices):
                    cols[i % len(cols)].button(c.label, key=f"cf-{d.revision}-{issue.field}-{i}", on_click=_choose,
                                               args=(d.revision, issue.field, c.value, sel), use_container_width=True)
            if issue.hint:
                st.caption(f"Or type your answer below ({issue.hint}).")
        st.caption("Nothing runs while a field is open.")
    else:
        x = C.executable(d, sel)
        assert x is not None
        rid = C.revision_id(x)
        with st.chat_message("assistant"):
            st.markdown(f"The request is complete (revision `{rid}`). Confirm to run exactly the request in the preview; "
                        "any change makes a new revision that needs its own confirmation.")
            if state.get("confirmed") == rid:
                st.success(f"Revision `{rid}` confirmed.")
            else:
                st.button("Confirm and run", type="primary", key=f"cf-confirm-{rid}", on_click=_confirm,
                          args=(rid, sel))
    state["model_replies"] = st.toggle("Let the routing model read replies the parsers cannot (one call per reply)",
                                       value=state.get("model_replies", True), key=f"cf-model-{d.revision}")
    _edit_form(state, d, sel)
    st.button("Start over", on_click=_restart, key=f"cf-restart-{d.revision}")


def _history(state: dict[str, Any], md: Callable[[str], str]) -> None:
    """Every routing model reading of this question, with its notes as recorded at the time: history, not current
    requirements (those are in the preview)."""
    readings = state.get("interpretations") or []
    if not readings:
        return
    with st.expander(HISTORY):
        st.caption("Recorded when the routing model read the question (and any reply it was given). These notes are "
                   "not updated as the request changes and are not current warnings; what is still needed now is under "
                   "**Needs clarification** in the preview.")
        for n, r in enumerate(readings, 1):
            st.markdown(f"**Reading {n}**{' (the original interpretation)' if n == 1 else ''}, status "
                        f"`{r.get('status')}`, as recorded then")
            for note in r.get("reasons") or []:
                st.markdown(md(f"- Note at that time: {note}"))
            st.json(r, expanded=False)


def _edit_form(state: dict[str, Any], d: C.Draft, sel: Selection) -> None:
    """The optional shortcut: every field at once, applied in dependency order and validated like the questions."""
    with st.expander("Edit fields directly (optional)"), st.form(f"cf-form-{d.revision}"):
        ops = list(C.OPERATIONS)
        op = st.selectbox("Operation", ops, index=ops.index(d.operation) if d.operation in ops else None,
                          format_func=C.OPERATION_LABEL.get)
        ms = list(C.MEASURES)
        measure = st.selectbox("Measure (demand maximum)", ms, index=ms.index(d.measure) if d.measure in ms else None,
                               format_func=C.MEASURE_LABEL.get)
        rs = list(C.REGIONS)
        region = st.selectbox("Region", rs, index=rs.index(d.region) if d.region in rs else None,
                              format_func=C.REGION_LABEL.get)
        day = st.date_input("Date (the region's local date)", value=date.fromisoformat(d.date) if d.date else None)
        scopes = ["half_hour", "day", "event", "explicit"]
        scope = st.selectbox("Half-hour or period", scopes, index=scopes.index(d.scope_kind) if d.scope_kind else None,
                             format_func=C.SCOPE_LABEL.get)
        hh = st.text_input("Half-hour end (HH:MM, local)", d.half_hour_end or "")
        period = st.text_input("Period (HH:MM-HH:MM, local)",
                               f"{d.start_time}-{d.end_time}" if d.start_time and d.end_time else "")
        runs = list(C.RUN_LABEL)
        run = st.selectbox("Forecast run", runs, index=runs.index(d.run) if d.run in runs else None,
                           format_func=C.RUN_LABEL.get)
        issued = st.text_input("Run issued at (ISO time with zone)", d.issued_at_utc or "")
        cutoff = st.text_input("As-of cutoff (ISO time with zone; empty: none)", d.cutoff_utc or "")
        if st.form_submit_button("Apply changes"):
            new, errors = d, []
            wanted: list[tuple[str, Any]] = [("operation", op), ("measure", measure), ("region", region),
                                             ("date", day.isoformat() if isinstance(day, date) else None)]
            if scope == "half_hour":
                wanted.append(("half_hour_end", C.parse_clock(hh) if hh else None))
            elif scope == "explicit":
                wanted.append(("period", C.parse_period(period) if period else None))
            elif scope:
                wanted.append(("scope_kind", scope))
            wanted += [("run", run), ("issued_at", issued or None), ("cutoff", cutoff or "absent")]
            current = {"operation": d.operation, "measure": d.measure, "region": d.region, "date": d.date,
                       "half_hour_end": d.half_hour_end, "period": (d.start_time, d.end_time),
                       "scope_kind": d.scope_kind, "run": d.run, "issued_at": d.issued_at_utc,
                       "cutoff": d.cutoff_utc or "absent"}
            for f, v in wanted:
                if v is None or v == current.get(f) or (f == "measure" and op != "demand_maximum"):
                    continue
                try:
                    new = C.apply(new, f, v, sel)
                except ValueError as exc:
                    errors.append(f"{f}: {exc}")
            if errors:
                st.error("; ".join(errors))
            elif new is not d:
                C.edit(state, new)
                st.rerun()


def _result(state: dict[str, Any], rid: str, sel: Selection, md: Callable[[str], str]) -> None:
    res = state["results"][rid]
    rep = res.report.model_dump()
    prov = result_provenance(rep, res.usage)
    st.divider()
    current = C.draft_of(state)
    x_now = C.executable(current, sel) if current else None
    if x_now is None or C.revision_id(x_now) != rid:
        st.caption(f"The result below is for revision `{rid}`; the request has changed since.")
    orig = state.get("original") or {}
    who = (f"the routing model {orig.get('model')} (route contract {orig.get('contract')}, {orig.get('prompt')}), "
           f"{(orig.get('usage') or {}).get('model_calls', 0)} call(s)" if orig else "your choices only, no model")
    st.info(f"**Request:** read by {who}. **Your confirmation** of revision `{rid}` records the exact request you "
            "chose to run; it does not validate the routing model's reading. **Execution:** "
            f"{prov['label']}; no model call after confirmation.")
    if rep.get("answer"):  # the verified requested result first
        st.markdown("### Computed answer")
        st.caption("Computed by code from the pinned data; a value is shown only when its result was verified.")
        for a in rep["answer"]:
            st.markdown(md(f"- {a['statement']}"))
            for lim in a["limitations"]:
                st.caption(md(lim))
            if a["source_row_ids"]:
                st.caption("source rows: " + ", ".join(f"`{r}`" for r in a["source_row_ids"]))
    else:
        st.markdown("**No computed answer**: " + md(" ".join(rep.get("uncertainties") or [])[:600]))
    st.markdown(f"**Report headline** (scripted): {md(rep['headline'])}")
    st.caption(f"Status: {rep['status'].replace('_', ' ')} · independent validator on the scripted report "
               f"(numbers, sources, scope): {prov['validation']} · computed answer: {prov['computed_answer']} · "
               "model-written interpretation: none in this workflow")
    if rep["summary"]:
        st.markdown("**Narrative** (written by the scripted controller; not a model interpretation)")
        for s in rep["summary"]:
            st.markdown(md(f"- {s}"))
    obs = observation_table(rep)
    if not obs.empty:
        with st.expander("Observations (tool values with source rows)"):
            st.dataframe(obs, use_container_width=True, hide_index=True)
    with st.expander("Uncertainties and missing evidence"):
        for u in rep["uncertainties"] + rep["missing_evidence"]:
            st.markdown(md(f"- {u}"))
    with st.expander("Diagnostics: the original interpretation (historical) and the confirmed request"):
        st.markdown("**Original interpretation** (historical: the routing model's first reading, compiled by code; its "
                    "notes are as recorded then, not current)")
        st.json(state.get("original") or {"source": "no model: built from your choices"}, expanded=False)
        st.markdown("**Confirmed request** (what ran)")
        confirmed = next((e for e in res.trace.as_dict()["events"] if e.get("name") == "confirmed_request"), {})
        st.json(confirmed.get("confirmed") or {}, expanded=False)
        st.caption(f"trace `{rep['trace_id']}` · tool calls {len(res.records)} · {res.latency_ms / 1000:,.1f} s")
