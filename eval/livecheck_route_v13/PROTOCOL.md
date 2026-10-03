# Routing-only Live check of route contract v13 (pre-registered; not run)

Written on 2026-10-04, and committed and pushed before any other file of this check. It is frozen with the
configurations, gold, runner and scorer, and is not edited after any Live result is seen. **This file authorises no
paid call.** A run needs the owner's separate approval of the frozen protocol and task cap ("Caps").

**What this is:** one bounded Live check of the merged route contract v13 (D26, `main` `a648269`): routing and request
resolution only, on existing questions. **What it is not:** an end-to-end check, L3, or evidence of generalisation.
It is development evidence on familiar questions. Historical verdicts are unchanged by any result here, and Live
stays experimental.

**The verdict, and only this:** acceptance of v13 request extraction and resolution on this development sample. The
completion and truncation of D02 and F02 are reported separately. **A PASS does not imply that whitespace
degeneration or routing truncation has been fixed:** those calls are too few to show any rate.

## What is frozen (`FREEZE.json`, written by `freeze.py`)
- **The code:** `main` `a648269` (its commit tree and `src/` tree), prompts v13 (its tree), model `gpt-5-mini`, the
  routing output cap (2,000 tokens) and the default reasoning effort (not sent).
- **These files, by SHA-256:**
  - this protocol, `cases.json`, `GOLD.json`;
  - `gold.py`, `run_route.py`, `run_eval.py`, `score.py` and `freeze.py`;
  - every source file the gold is read from.
- **Also frozen:** the call order, the caps, and the starting ledger.

Nothing in the code, prompts, model, configurations, gold, criteria or caps changes between the freeze and the end of
the run. If a change turns out to be needed, the run is not started, or the run in progress stops, and that is
reported.

## Scope: 10 distinct questions, 11 configurations, 32 routing calls

| Config | Question (source) | Request fields | Purpose | Repeats |
| --- | --- | --- | --- | --- |
| C01 | D02 (= K11; `eval/livecheck_maxima`) | none | Truncation variability (reported apart) | 5 |
| C02 | F02 (`eval/livecheck_maxima`) | none | Truncation variability (reported apart) | 5 |
| C03 | D01 (= K09; `eval/livecheck_maxima`) | none | Extraction of a reading v12 rejected | 3 |
| C04 | F06 (`eval/livecheck_maxima`) | none | Extraction of a reading v12 rejected | 3 |
| C05 | F07 (`eval/livecheck_maxima`) | `as_of_utc` 2025-10-05T02:00:00Z (the case's own) | The cutoff from the request field | 3 |
| C06 | F07 (the same question) | none | Containment: "noon" cannot be converted, so it must be sent back | 3 |
| C07 | F08 (`eval/livecheck_maxima`) | none | Containment: no measure named | 2 |
| C08 | Q17 (`eval/livecheck_routing_v12`) | none | Containment: a run's half-hour with no date | 2 |
| C09 | Q21 (`eval/livecheck_routing_v12`) | none | Containment: no maximum requested (demand at the price peak) | 2 |
| C10 | K06 (`eval/livecheck_i15_17`) | none | Run selection: the last run issued before a half-hour | 2 |
| C11 | K14 (`eval/livecheck_i15_17`) | none | Run selection: a run named by its issue time | 2 |

**Questions** are copied unchanged from their source files, and a test checks this.

**The order** runs in five rounds:
- **Round 1:** all 11 configurations.
- **Round 2:** all 11 again.
- **Round 3:** C01–C06.
- **Rounds 4 and 5:** C01 and C02.

Within each round the order is shuffled once at the freeze and recorded.

**Each call is one process:**
- `LiveController.route`: one routing call to the hosted model, under the ledger's cap;
- `service.resolve_routed`: request resolution.

No tool runs, nothing is calculated and nothing is written. That is exactly the first step of a Live investigation.

## Gold (`GOLD.json`, built by `gold.py` from independently checked sources)
| Config | Gold (source) |
| --- | --- |
| C01–C07 | The reading in `eval/livecheck_maxima/GOLD.json`: measure, region, window kind and bounds, cutoff; for F08, clarification. Checked exactly by an independent agent with its own code (`GOLD_CHECK.json`) |
| C06 | F07's reading, with the outcome **sent back for the cutoff**: no request field, and code cannot read "noon" (D26) |
| C08, C09 | The `expected` field in `eval/livecheck_routing_v12/cases.json`: Q17 must be clarified (no date); Q21 has no request. Verified independently (`VERIFICATION.json`) |
| C10, C11 | `gold_run` in `eval/livecheck_i15_17/cases.json`: the selection rule, the half-hour's end, and for K14 the issue time; no cutoff, no maximum. Verified independently (`VERIFICATION.json`) |

## How each call is classed (from completed, valid routing responses unless stated)
**Each call gets exactly one class:**

| Class | Applies to | Means |
| --- | --- | --- |
| **supplied** | Supply configurations (C01–C05, C10, C11) | The resolution proceeds (`ok`), and every gold item is bound exactly: region, measure, window kind and bounds; run rule, half-hour and issue time; cutoff. No other request is bound |
| **contained** | Containment configurations (C06–C09) | The expected behaviour, shown by a completed response |
| **unnecessary clarification** | Answerable configurations, and C09 | A completed response sent back |
| **wrong binding** | Any call | A bound request, region or cutoff that differs from gold |
| **missed request** | Configurations whose gold holds a maximum or run (or that must be clarified) | The resolution proceeds (`ok`) with that request never detected |
| **incomplete** | Any call | The routing response was cut off or invalid, and was rejected before parsing (fail-closed). It carries its diagnostics |

**What "contained" requires, per configuration:**
- **C06:** sent back, with the cutoff unresolved and the cutoff clarification among the reasons.
- **C07:** sent back, with no maximum bound.
- **C08:** sent back, with no run bound.
- **C09:** proceeds with no request bound and no cutoff.

**Never contained:** an incomplete response is fail-closed behaviour, not a correct interpretation, so it does not
count as contained.

## Acceptance criteria (the verdict, in this order)
1. **FAIL** if any call shows one of these:
   - a wrong binding, in a completed response;
   - an incomplete response that was not sent back;
   - a dropped cutoff: detected, the resolution proceeds, and no cutoff is applied;
   - C06 proceeding, or binding any cutoff;
   - C07 binding a maximum, or C08 binding a run;
   - C09 binding a maximum;
   - a missed request.

   Each of these is a demonstrated violation, whatever the coverage.
2. Otherwise **INCOMPLETE** if any of the 32 calls was not completed (not saved).
3. Otherwise **INCONCLUSIVE** if either of these holds:
   - **Missing containment evidence.** C06, C07, C08 and C09 must each have at least one completed, valid routing
     response showing its expected behaviour. A rejected incomplete response does not count. Missing evidence for any
     one of them means the check cannot pass.
   - **Missing supply.**
     - C03, C04 and C05 are each supplied in at least 2 of their 3 calls, and in at least 7 of their 9 together.
     - C10 and C11 are supplied in at least 3 of their 4 calls together.
4. Otherwise **PASS**: v13 request extraction and resolution accepted on this development sample.

**Reported apart from the verdict:**
- coverage;
- per call and configuration, each of the five report sections below;
- C01 and C02 in their own section: completed versus incomplete, the diagnostics of each incomplete response, and the
  resolution of each completed one against gold. A wrong binding there still fails the check, under criterion 1.

## The report (`score.py`)
1. **Exact resolution against gold:** every bound item, with its provenance (the model's quoted words with their
   offsets, the question parser, or the request field).
2. **Wrong bindings.**
3. **Unnecessary clarifications and missed requests,** with their reasons.
4. **Incomplete output and its recorded diagnostics:**
   - status and incomplete reason;
   - reasoning and visible tokens;
   - visible characters, whitespace share and trailing whitespace;
   - the open JSON field at the cutoff;
   - the diagnosed cause.
5. **Token usage, latency and cost:** per call and in total.
   - **Measured:** input, cached, output and reasoning tokens, and the call's duration.
   - **Ledger accounting:** each call's ledger cost.
   - **Not observable:** the billed amount.

## Caps
- **Starting ledger:** the real ledger. At the first start, its total, line count and SHA-256 prefix must equal the
  frozen ones: USD 8.895359, 3,023 lines, `8dfcdd5e914830cb`.
- **Per call:** USD 0.006. The exact worst-case reservation of one v13 routing call is USD 0.005093, and `freeze.py`
  computes and checks it.
- **Run cap:** 32 × 0.006 = **USD 0.192**.
- **Required approved task cap:** 8.895359 + 0.192 = **USD 9.087359**. The standing configured cap (USD 5.00) is
  already exceeded, so nothing runs without the owner's approval of this cap.
- **Expected spend:** about USD 0.07 (0.06–0.08). That assumes completed calls at a median of about USD 0.0016, and
  incomplete ones at about USD 0.0041.
- **Enforced before each call:**
  - **the case cap** (`nem_agent.budget`): the ledger total at the call's start plus 0.006;
  - **the start guard:** a call starts only if the run's spend so far plus 0.006 is within the run cap, and the ledger
    total plus 0.006 is within the approved task cap.
- **Interrupted attempts stay counted.** The cost of an attempt in flight at an interruption stays counted against
  the run cap, and no retry allowance is added. Interrupted attempts may therefore exhaust the run cap before all 32
  calls run; the start guard then stops the run, and the check is INCOMPLETE. The caps are not raised.

## Stops, interruption and refusals
- **Stops:** any of these ends the run, and what was not run makes the check INCOMPLETE:
  - a budget stop;
  - an API error or timeout;
  - a missing record;
  - a case-note write or forbidden call (a safety stop);
  - a change to frozen files or `src/`.
- **No repeats for results:** no call is repeated because of its result. A response that did not finish is an
  outcome, not an error.
- **Interruption:** re-run the same command.
  - Saved calls are never re-run.
  - The call in flight is re-run once, its cost staying counted.
  - A call in flight at a second interruption is not started again (INCOMPLETE).
- **Refusals:** the runner refuses to start when any of these holds:
  - the lock is held;
  - frozen files or `src/` differ;
  - the plan does not match the configurations;
  - the record directory holds records the log does not account for;
  - the caller sets a ledger, cap, price or model override;
  - the prompt version is not v13;
  - no API key is set (never read or printed);
  - the approved task cap is below the required one;
  - at the first start, the ledger is not the frozen one, or at a resume it is below its last recorded value;
  - the check has ended.

## Records
- **Run log:** `artifacts/live/LC-route-v13/run_log.jsonl`.
- **Records:** `artifacts/live/LC-route-v13-run/<NN>-<config>.json`, with each call's standard output, and its trace
  under `traces/`.
- **Each record keeps:**
  - the full routing decision (v13, with its contract);
  - every routing event of the trace: the call's usage, settings and status; the incomplete-output diagnostics; the
    decision with its policy notes; and the resolution;
  - the full resolution: status, reasons, intent, region, cutoff, window and target, and every request with its
    provenance, spans and offsets, unused readings, notes and cutoff;
  - the case-note file count, and the ledger cost.
- **Scoring:** `score.py` scores offline and never calls a model.

## Limitations
- Familiar questions only, each run 2–5 times: there are no rates, and differences of one or two calls are within
  run-to-run variation.
- Routing only: nothing about answers end to end.
- The known gaps of D26 are not tested beyond F07 (C06), and their outcome is already known:
  - vague narrowing words;
  - "noon" and "midday";
  - windows over two dates.
