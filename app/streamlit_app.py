"""NEM Event Intelligence Agent — thin Streamlit UI over the same service used by the CLI and API."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nem_agent import paths
from nem_agent.agent.request import InvestigateRequest
from nem_agent.approvals import CaseNoteStore, note_content_from_report
from nem_agent.budget import BudgetExceeded
from nem_agent.selection import load_selection
from nem_agent.timeutil import REGION_TZ, local_str, parse_iso, region_zone
from nem_agent.ui_data import (
    NO_MODEL_ANSWER,
    demand_chart,
    frames,
    observation_table,
    price_chart,
    result_provenance,
)

st.set_page_config(page_title="NEM Event Intelligence", layout="wide")


def md(text: str) -> str:
    """Escape '$' so Streamlit does not render currency as LaTeX."""
    return text.replace("$", "\\$")

LIVE_OK = bool(os.environ.get("OPENAI_API_KEY"))
sel = load_selection()

# the experimental confirmed-request workflow is opt-in; the standard investigation below is the default, unchanged
sys.path.insert(0, str(Path(__file__).resolve().parent))
from confirm_flow import LABEL as CONFIRM_FLOW  # noqa: E402

if st.sidebar.toggle(CONFIRM_FLOW, value=False, key="workflow_confirm_flow",
                     help="Off: the standard investigation (default). On: the request is shown as the system read it, "
                          "what is open is asked one question at a time, and only the request you confirm runs."):
    import confirm_flow

    confirm_flow.render(sel, LIVE_OK, md)
    st.stop()

with st.sidebar:
    st.header("Investigation")
    mode = st.radio("Mode", ["replay", "live"], index=0, horizontal=True, disabled=not LIVE_OK,
                    help="REPLAY: scripted controller over real data, no LLM. LIVE needs OPENAI_API_KEY.")
    if not LIVE_OK:
        st.caption("LIVE is disabled: no OPENAI_API_KEY in this environment.")
    labels = {e.event_id: f"{e.region} · {local_str(parse_iso(e.peak_interval_end_utc), e.region)[:16]} · "
                          f"{e.peak_rrp:,.2f} $/MWh{' (primary)' if e.role == 'primary' else ''}" for e in sel.events}
    event_id = st.selectbox("Verified event", list(labels), format_func=labels.get)
    ev = sel.event(event_id)
    day = parse_iso(ev.peak_interval_end_utc).astimezone(region_zone(ev.region)).date()
    presets = {
        "Market event review": f"What happened around the {ev.region} price {'spike' if ev.kind == 'high_price' else 'fall'} "
                               f"on {day}? How did price, operational demand and generation move?",
        "Forecast review": f"How did AEMO's issued operational demand forecasts compare with actual demand in {ev.region} "
                           f"on {day}?",
        "Definition": "What does operational demand mean?",
        "Causal bait": f"Did low wind cause the {ev.region} price spike on {day}?",
    }
    preset = st.radio("Question preset", list(presets))
    question = st.text_area("Question", presets[preset], height=110, max_chars=1000)
    as_of = st.text_input("As-of cutoff (optional, ISO-8601 with offset)", "",
                          placeholder="e.g. 2026-07-30T14:35:00Z")
    run = st.button("Investigate", type="primary", use_container_width=True)
    st.divider()
    st.subheader("Data and sources")
    try:
        from nem_agent.sources import source_statuses

        _src = source_statuses(sel)
        _sm = _src["summary"]
        st.caption(f"data `{_src['data_version']}` · corpus `{_src['corpus_version']}`")
        st.markdown(f"- **{_sm['pinned']}** pinned sources in use (verified by hash)\n"
                    f"- **{_sm['revised_in_use_pending_review']}** revised upstream; pinned version still used, "
                    "review pending\n"
                    f"- **{_sm['revised_excluded']}** revised upstream and excluded (no verified copy)\n"
                    f"- **{_sm['unavailable_excluded']}** unavailable and excluded (reported as missing evidence)")
        _odd = [r for r in _src["sources"] if r["category"] != "pinned" or r.get("note")]
        if _odd:
            with st.expander(f"{len(_odd)} source(s) not plainly pinned"):
                st.dataframe([{"source": r["source_id"], "status": r["category"], "in use": r["in_use"],
                               "why": (r.get("reason") or r.get("note") or "")[:160]} for r in _odd],
                             use_container_width=True, hide_index=True)
        if _src["refresh_check"]:
            st.caption(f"Last publisher-refresh check: {_src['refresh_check']['generated_at']}")
    except Exception as _exc:  # the panel is informational; investigations still fail closed on their own
        st.caption(f"Source status unavailable: {type(_exc).__name__}")

st.title("NEM Event Intelligence Agent")
selected = "LIVE — hosted model with read-only tools" if mode == "live" else "REPLAY — scripted controller, no LLM"
st.markdown(f"**Selected mode:** `{selected}` · data `{sel.generated_at[:10]}` snapshot · independent public-data "
            "project (AEMO NEMWeb + NASA POWER), not affiliated with AEMO.")

# D36: a new Live investigation replaces the earlier result at once, its charts included; else a plain container
area = st.empty().container() if run and mode == "live" else st.container()
with area:
    if run:
        from nem_agent.service import investigate

        try:
            req = InvestigateRequest(question=question, mode=mode, as_of_utc=as_of.strip() or None)
        except Exception as exc:  # bounded, user-facing error
            st.error(f"Invalid request: {exc}")
            st.stop()
        if mode == "live":  # D36: the stage, the elapsed time and early data charts while the run goes on
            from live_progress import LiveProgress

            st.session_state.pop("result", None)  # the earlier run's result never reappears after this one
            progress = LiveProgress()
            try:
                result = investigate(req, progress=progress)
            except BudgetExceeded as exc:  # D34: refused before any call: shown as a budget stop, with no answer
                if exc.result is None:
                    progress.fail(exc)
                    raise
                result = exc.result
            except Exception as exc:
                progress.fail(exc)
                raise
            st.session_state["result"] = result
            progress.finish(result)
            progress.resume()
        else:
            with st.spinner("Running tools, retrieval and validation..."):
                try:
                    st.session_state["result"] = investigate(req)
                except BudgetExceeded as exc:  # D34: refused before any call: shown as a budget stop, with no answer
                    if exc.result is None:
                        raise
                    st.session_state["result"] = exc.result

    res = st.session_state.get("result")
    if res is None:
        st.info("Choose a verified event and a question, then press **Investigate**. Every number shown is a tool value "
                "with its AEMO source row; every quote is checked against the retrieved text.")
        st.stop()

    rep = res.report.model_dump()
    region = rep["region"]
    status_icon = {"answered": "✅", "answered_with_caveats": "⚠️", "needs_clarification": "❓", "abstained": "⛔",
                   "refused": "⛔"}[rep["status"]]
    v = rep["validation"]
    prov = result_provenance(rep, res.usage)
    # the label comes from the report on screen, never from the mode selector
    banner = {"replay": st.info, "live_answer": st.success, "live_fallback": st.warning, "live_no_answer": st.info,
              "live_no_interpretation": st.warning, "live_stopped": st.warning}
    banner[prov["kind"]](f"**Result shown: {prov['label']}** · trace `{rep['trace_id']}`")
    if rep["mode"] != mode:
        st.warning(f"The result below was produced in {rep['mode'].upper()} mode. Press **Investigate** to run "
                   f"{mode.upper()}.")
    short_status = {"answered": "answered", "answered_with_caveats": "caveats", "needs_clarification": "clarify",
                    "abstained": "abstained", "refused": "refused"}[rep["status"]]
    short_validation = {"passed on the first draft": "passed", "passed after one repair": "passed (1 repair)",
                        "passed": "passed", NO_MODEL_ANSWER: "no answer"}.get(
        prov["validation"], "facts only" if "fallback" in prov["validation"] else prov["validation"])
    cols = st.columns(4)
    cols[0].metric("Status", f"{status_icon} {short_status}")  # metric tiles truncate long values; full text below
    cols[1].metric("Validation", short_validation)
    cols[2].metric("Tool calls", len(res.records))
    cols[3].metric("Latency", f"{res.latency_ms / 1000:,.1f} s")
    st.caption(f"Status: {rep['status'].replace('_', ' ')} · independent validation: {prov['validation']}")
    if rep.get("answer"):  # D25: the computed answer's availability, apart from the interpretation's status
        st.caption(f"Computed answer: {prov['computed_answer']} · interpretation: {prov['interpretation']}")
    if rep["mode"] == "live":
        lc = st.columns(4)
        lc[0].metric("Model", prov["model"] or "-")
        lc[1].metric("Model calls", prov["model_calls"])
        lc[2].metric("Tokens in / out", f"{prov['input_tokens']:,} / {prov['output_tokens']:,}")
        lc[3].metric("Cost (USD)", "-" if prov["cost_usd"] is None else f"{prov['cost_usd']:.4f}")
        st.caption(f"generator `{prov['generator']}` · prompts `{prov['prompt']}` · cost: {prov['cost_note']}")
    st.subheader(md(rep["headline"]))
    # D25: the computed answer, rendered by code from verified results, shown apart from the narrative
    if rep.get("answer"):
        st.markdown("**Computed answer** (computed by code from the pinned data; a value is shown only when its result "
                    "was verified)")
        for a in rep["answer"]:
            st.markdown(md(f"- {a['statement']}"))
            for lim in a["limitations"]:
                st.caption(md(lim))
            if a["source_row_ids"]:
                st.caption("source rows: " + ", ".join(f"`{r}`" for r in a["source_row_ids"]))
        if rep["summary"]:
            st.markdown("**Interpretation** (written by the model and checked by the independent validator)"
                        if rep["mode"] == "live" else "**Narrative** (scripted controller)")
    for s in rep["summary"]:
        st.markdown(md(f"- {s}"))

    if region:
        theme = "dark" if getattr(getattr(st.context, "theme", None), "type", "light") == "dark" else "light"
        pdf, ddf = frames(res.records, region)
        tz = REGION_TZ[region]
        peak = rep["observations"][0]["valid_at_utc"] if rep["observations"] and rep["observations"][0]["metric"] == "dispatch_rrp" else None
        if not pdf.empty:
            st.altair_chart(price_chart(pdf, region, tz, theme, peak), use_container_width=True)
        if not ddf.empty:
            st.altair_chart(demand_chart(ddf, region, tz, theme), use_container_width=True)
        if not pdf.empty or not ddf.empty:
            st.caption("Price is 5-minute and demand is half-hourly; each is drawn at its native resolution as an "
                       "interval-ending step. The forecast line is the latest AEMO POE50 run available before each half-hour. "
                       "Dispatch TOTALDEMAND is not operational demand and is not plotted against forecasts.")

    left, right = st.columns([3, 2])
    with left:
        st.markdown("#### Observations (tool values with source rows)")
        obs = observation_table(rep)
        if not obs.empty:
            st.dataframe(obs, use_container_width=True, hide_index=True)
            with st.expander("Trace a value to the publisher's bytes"):
                from nem_agent.store import Store, trace_row

                rows = sorted({r for o in rep["observations"] for r in o["source_row_ids"] if ":L" in r})
                if rows:
                    rid = st.selectbox("Source row", rows)
                    tr = trace_row(Store(), rid)
                    st.markdown(f"[{tr['source_url']}]({tr['source_url']}) → `{tr['member']}` line {tr['line_no']}")
                    st.code(tr["raw_line"][:600], language="text")
                    st.caption(f"container sha256 recorded {tr['container_sha256_recorded'][:16]}… recomputed "
                               f"{tr['container_sha256_recomputed'][:16]}…")
        if rep.get("forecast_comparison"):
            st.markdown("#### Forecast comparison")
            st.json(rep["forecast_comparison"], expanded=False)
    with right:
        st.markdown("#### Possible explanations (hypotheses, not findings)")
        for h in rep["possible_explanations"] or [{"statement": "none offered", "what_would_test_it": "-"}]:
            st.markdown(md(f"- *{h['statement']}*  \n  test: {h['what_would_test_it']}"))
        if rep.get("ruled_out_explanations"):
            st.markdown("#### Ruled out by the evidence (validated)")
            for h in rep["ruled_out_explanations"]:
                st.markdown(md(f"- {h['statement']}"))
        st.markdown("#### Published findings (event-specific AEMO notices)")
        for f in rep["published_findings"] or [{"statement": "No matching AEMO notice was retrieved for this region and window."}]:
            st.markdown(md(f"- {f['statement']}"))
        st.markdown("#### Uncertainties and missing evidence")
        for u in rep["uncertainties"] + rep["missing_evidence"]:
            st.markdown(md(f"- {u}"))

    st.markdown("#### Citations")
    for c in rep["citations"]:
        loc = f"p.{c['page']}" if c.get("page") else (c.get("section") or "")
        pub = f" · published {c['publication_date'][:10]}" if c.get("publication_date") else ""
        st.markdown(md(f"**[{c['citation_id']}]** [{c['title']}]({c['url']}) {loc}{pub} — “{c['quote']}”"))
    if not rep["citations"]:
        st.caption("No citations.")
    if rep.get("search_scope"):
        st.markdown("#### Document searches (what was and was not searched)")
        st.dataframe([{"query": s["query"][:80], "region": s["region"] or "none",
                       "window (UTC)": " – ".join(x or "none" for x in s["event_window_utc"]),
                       "document types": ", ".join(s["document_types"] or ["all"]), "results": s["results"],
                       "market notices": s["market_notices"]} for s in rep["search_scope"]],
                     use_container_width=True, hide_index=True)

    with st.expander("Tool trace (actual calls, arguments, outcomes)"):
        st.dataframe([{"call": r.call_id, "tool": r.name, "status": r.status, "optional": r.optional,
                       "ms": r.duration_ms, "args": str(r.args or r.raw_args)[:200], "note": (r.blocked_reason or
                       (r.missing[0] if r.missing else ""))[:160]} for r in res.records], use_container_width=True,
                     hide_index=True)
        st.caption(f"trace id {rep['trace_id']} · generator {rep['generator']} · versions {rep['versions']}")
    with st.expander("Validation details"):
        st.json(v, expanded=False)
    with st.expander("Held-out evaluation report"):
        p = paths.artifacts_dir() / "eval" / "report.md"
        st.markdown(p.read_text() if p.exists() else "Run `make eval` to generate the report.")
    with st.expander("Local case note (approval demo; mock reviewers, nothing leaves this machine)"):
        store = CaseNoteStore()
        if st.button("1. Propose note from this report"):
            prop = store.propose(note_content_from_report(res.report), author="analyst (you)")
            st.session_state["proposal"] = prop
        prop = st.session_state.get("proposal")
        if prop:
            st.code(f"proposal {prop.proposal_id}\ncontent sha256 {prop.content_sha256}", language="text")
            if st.button("2. Approve exact hash as mock-reviewer-b"):
                st.session_state["approval"] = store.approve(prop.proposal_id, "mock-reviewer-b", prop.content_sha256)
            appr = st.session_state.get("approval")
            if appr and st.button("3. Publish locally (idempotent)"):
                st.json(store.publish(prop.proposal_id, appr.approval_id)["status"])
