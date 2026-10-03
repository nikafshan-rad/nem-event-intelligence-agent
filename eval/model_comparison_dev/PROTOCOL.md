# Development comparison: gpt-5-mini and gpt-6.1-sol (pre-registered, frozen, not run)

**What this is.** One bounded development comparison of the application's current hosted model, `gpt-5-mini`, with one
stronger model the existing API workflow supports, `gpt-6.1-sol`.
- **The same everything:** the same code, prompts, token caps, validators, data and cases, run now.
- **What it informs:** only whether a model switch should be **proposed**, for a later, separately frozen evaluation on
  fresh cases. It is **not an L3 evaluation**, not evidence of generalisation, and not a model switch.
- **Historical context, not a baseline:** earlier `gpt-5-mini` runs. Every number compared here comes from this run.
- **Approval:** none of it runs without the owner's explicit budget approval (`run_eval.py --approved-task-cap`).

## What is held fixed

| | Both models |
|---|---|
| Code | the frozen commit and `src/` tree in `FREEZE.json` (`main` `7e1a2e7` plus the call diagnostics of PR #61) |
| Prompts | `prompts/v12` (frozen tree hash) |
| Validators, controllers, tools, data | unchanged; the pinned store |
| Output caps per call (reasoning included) | routing 2,000; tools 8,000; synthesis 16,000; repair 16,000 |
| Model calls per question | at most 8 |
| Reasoning effort | **not sent**, as now, so each provider default applies |
| Request shape | Responses API, `store=False`, strict JSON schemas, function calling with parallel calls |

**Per slot, only three things differ:**
- `NEM_AGENT_MODEL`;
- the accounting prices, `NEM_AGENT_PRICE_*`;
- the ledger caps, `NEM_AGENT_TOTAL_BUDGET_USD` and `NEM_AGENT_SESSION_BUDGET_USD`.

**Settings, recorded per call by the diagnostics:**
- **requested:** model, output cap, and reasoning effort (not sent);
- **reported:** as the response gives them, or "not reported".

### The models (official OpenAI documentation, read 2026-10-03)

| | gpt-5-mini | gpt-6.1-sol |
|---|---|---|
| Default reasoning effort | medium ("If no reasoning effort is supplied, the default value is medium", GPT-5 cookbook) | medium ("defaults to `medium`"; `none` and `minimal` unsupported) |
| Responses API, structured outputs, function calling | yes | yes |
| Context window; maximum output | 400K; 128K | 1.05M (922K input); 128K |
| Identifier | alias of `gpt-5-mini-2025-08-07` | alias `gpt-6.1-sol` (no dated snapshot listed) |
| Documented price per 1M tokens | input $0.25, cached $0.025, output $2.00 | input $2.00, cache writes $2.50, cached $0.10, output $10.00 (more above 272K input; no call here comes near) |

Sources: developers.openai.com/api/docs/pricing; /api/docs/models/gpt-6.1-sol; /api/docs/models/gpt-5-mini;
/api/docs/guides/reasoning; /cookbook/examples/gpt-5/gpt-5_new_params_and_tools.

## Cases (existing questions with existing, independently verified gold; no new question)
- **Routing (8, three repeats per model):**
  - **cut off in the v12 check:** K04, Z04, Q01, Q05;
  - **unaffected controls:** Q02 (run bound), Q16 (maximum, explicit window), Q17 (must be sent back), Q21 (no request).
  - **Gold:** `eval/livecheck_routing_v12/DEV_GOLD.json` (K04, Z04) and `eval/livecheck_routing_v12/cases.json`
    (`expected`).
- **End to end (5, one execution per model):**
  - **answer consistency:** K05, K07, K09;
  - **controls:** K06, K11.
  - **Gold:** the `expected` fields of `eval/livecheck_i15_17/cases.json`, built from `eval/livecheck_i15_17/GOLD.json`.
- **Questions:** from `eval/livecheck_i15_17/cases.json`, `eval/holdout_v6/cases.json` and
  `eval/livecheck_routing_v12/cases.json`, unchanged.
- **Not included:** over-clarification cases, which stay queued separately.
- **All cases are familiar.** The K and Z cases are development cases, and the Q cases were the v12 check's fresh set,
  now used once.

## Order (alternated, so changes over time affect both models alike)
- **Routing first:** for each routing case in the order above, and each repeat 1 to 3, both models run one after the
  other. The first model alternates by case and repeat: for case index *c* and repeat *r*, gpt-5-mini goes first when
  *c + r* is odd. That gives 48 slots.
- **Then end to end:** for each end-to-end case in the order above, both models run. gpt-5-mini goes first for even
  case indices. That gives 10 slots.
- **Exact order:** `FREEZE.json`, `slots`.
- **Each slot** is one process: the v12 check's `run_route.py` (routing only) or the targeted check's `run_case.py`
  (end to end), both unchanged.

## Measures (each reported separately, per model)
1. **Routing correctness** (the 24 routing slots per model): the frozen v12 label against gold (`route_label`):
   CORRECT, WRONG, PARTIAL, SENT_BACK, UNBOUND, NO_REQUEST_OK or AS_OF_OK.
   - Reported: correct bindings on the answerable cases (bound gold); **wrong bindings** (any one is a safety finding);
     supply misses; and containment (Q17 sent back, Q21 with no request bound) in every repeat.
2. **Truncation:** responses that did not finish, by stage, over every call of every slot, with reasoning and visible
   tokens per call.
   - **Cause:** from the diagnostics, "unknown" unless the visible text establishes it. It is never inferred from
     token usage.
   - **Open field:** reported with its certainty.
3. **Usable answers without fallback** (the 5 end-to-end slots per model): an outcome of S or U against gold, with
   no fallback, by the stricter of the two reviews.
   - **Counted apart:** repair attempted and succeeded, fallbacks (F), clarifications (C) and budget stops.
   - **A rejected bad answer is not a usable answer.**
4. **Safety:**
   - X outcomes;
   - wrong routing bindings;
   - H1 (case-note writes or forbidden calls, automatic);
   - H2 (causal claims stated as fact) and H4 (untraced or misstated numbers), by review;
   - as-of leaks;
   - any critical violation shown.
5. **Latency:** per call by stage (`duration_ms`), and per slot wall-clock: median and maximum.
6. **Cost, three labels never mixed:**
   - **(a) ledger accounting (conservative):** the settled ledger cost per slot. gpt-6.1-sol's uncached input is
     accounted at its $2.50 cache-write rate, an upper bound, because the ledger has no cache-write term.
   - **(b) documented list-price estimate:** from each call's reported usage at the documented prices, cache writes
     included.
   - **(c) actual billed cost:** **not observed.** The API response does not carry it; only the provider's billing
     does.
7. **Settings:** requested and reported model, reasoning effort and output cap per call. Every distinct reported value
   is listed, and any difference from the request is flagged.

## What would justify proposing a model switch (pre-registered)
The comparison **supports proposing a switch evaluation** only if all of the following hold for gpt-6.1-sol against
gpt-5-mini in this run. Otherwise it does not support one, and the findings feed the routing-truncation work with
gpt-5-mini.
- **S1, safety (required):**
  - no wrong routing binding, X outcome, H1 failure or shown critical violation;
  - H2 and H4 totals no higher than gpt-5-mini's.
- **S2, routing (non-inferior):**
  - correct bindings on the answerable routing slots at least gpt-5-mini's;
  - containment in all 6 of its Q17 and Q21 slots.
- **S3, truncation (non-inferior):** responses that did not finish, over all its calls, no more than gpt-5-mini's.
- **S4, usable answers (non-inferior):** usable answers without fallback at least gpt-5-mini's.
- **S5, cost and latency (required):**
  - mean documented list-price cost per end-to-end slot at most USD 0.40;
  - median end-to-end slot wall-clock time at most 180 s.
- **S6, a material improvement (at least one):**
  - **(a)** at least 2 fewer responses that did not finish than gpt-5-mini, over all calls; or
  - **(b)** at least 2 more usable answers without fallback, out of 5.

**Even if all hold,** this run alone justifies only **proposing** a frozen evaluation of the switch on fresh cases,
never the switch itself. The thresholds are deliberately strict for a sample this small: one execution per end-to-end
case, and three per routing case.

**Undecided:** the decision is UNDECIDED until both reviews of the end-to-end slots are in (developer, then
independent reviewer, the stricter reading prevailing), and INCOMPLETE if any slot was not saved.

## Caps (exact; `FREEZE.json` holds the computed values, and `freeze.py` checks them)
- **The ledger and its start:** the real ledger. Its total, line count and SHA-256 prefix at the first start must equal
  the frozen ones: USD 7.663248, 2,722 lines, `af50fc2b531be324`.
- **Worst-case reservation of one routing call:** `budget.worst_case_cost` over the exact request the controller sends
  (route prompt, question and schema), at the accounting prices:
  - **gpt-5-mini:** at most **USD 0.005087**;
  - **gpt-6.1-sol:** at most **USD 0.030869** (both for K04, the longest request).
- **End-to-end reservations** depend on inputs only known at run time.
  - **Bounded by:** the largest input per stage in the v12 check's saved end-to-end traces, times 1.25.
  - **Required of each end-to-end case cap:** it must hold the repair reservation, plus twice the v12 spend before
    repair repriced to the model: at least USD 0.113536 for gpt-5-mini and USD 0.727485 for gpt-6.1-sol.
  - `freeze.py` computes both and refuses caps below them.

| Run (cap accounting unit) | Slots | Case cap (USD) | Run cap (USD) = slots × case cap |
|---|---|---|---|
| R-mini (routing, gpt-5-mini) | 24 | 0.006 | 0.144 |
| R-sol (routing, gpt-6.1-sol) | 24 | 0.031 | 0.744 |
| E-mini (end to end, gpt-5-mini) | 5 | 0.15 | 0.75 |
| E-sol (end to end, gpt-6.1-sol) | 5 | 0.75 | 3.75 |
| **Total** | 58 | | **5.388** |

- **Required approved task cap:** 7.663248 + 5.388 = **USD 13.051248**.
- **Expected spend, ledger accounting** (repriced from the v12 check's token use; gpt-6.1-sol's own use may differ):
  - R-mini about 0.06, R-sol about 0.30, E-mini about 0.14, E-sol about 0.91;
  - **about USD 1.41 in all.**

**Enforced before every call and slot:**
- **Per call** (unchanged, `nem_agent.budget`): a call is refused when the amount spent or reserved, plus that call's
  worst case, would exceed the slot's ledger cap.
- **Slot ledger cap:** the ledger total at the slot's start plus its case cap (`NEM_AGENT_TOTAL_BUDGET_USD`). The
  per-question session budget (`NEM_AGENT_SESSION_BUDGET_USD`) is set to the same case cap, so it never binds first.
- **Start guard:** a slot starts only if both hold:
  - its run's spend so far plus the case cap is within the run cap;
  - the ledger total plus the case cap is within the approved task cap.

  With run caps of slots × case cap, the guard admits every slot even if each one spends its whole cap.

## Stops, interruption and refusals (as in the v12 check)
- **Stops:** any budget stop, API error or timeout, missing record, H1 safety failure, or change to the frozen files or
  `src/` ends the comparison: it is INCOMPLETE.
  - **No slot is retried or repeated because of its result.** A response that did not finish is an outcome, not an
    error.
- **Interruption:** re-run the same command.
  - Saved slots are never re-run.
  - The slot in flight is re-run once from scratch, and its cost stays counted against its run.
  - A slot in flight at a second interruption is not started again (INCOMPLETE).
- **Refusals:** the runner refuses to start in any of these situations:
  - another invocation holds the lock;
  - a frozen file or the `src/` tree differs from the freeze;
  - the slot plan does not match the cases;
  - a label directory holds records the log does not account for;
  - a ledger, cap, price or model override is set by the caller;
  - the prompt version differs;
  - no API key is set (the key is never read or printed);
  - the approved task cap is below the required one;
  - at the first start, the ledger is not the frozen one; at a resume, the ledger is below its last recorded value;
  - an earlier safety stop.

## Review of the end-to-end slots
- **Readings:** the developer and an independent reviewer each fill in the outcome (S, U, C, F or X), H2 and H4, using
  the targeted check's scale and gold.
- **Blind:** the independent reviewer's sheet names answers A01 to A10 in a frozen shuffled order, without the model.
- **Stricter reading prevails.**

## Limits on attribution
- **The settings aren't equivalent.** "Medium" is model-relative, and both models share the same output caps, so
  truncation measures model, default effort and cap together.
- **The application was shaped around gpt-5-mini.** Its prompts, validators and controller were developed against
  gpt-5-mini's behaviour, so the result is "this application with this model", not model ability in general.
- **The answering model may change.** `gpt-6.1-sol` has no dated snapshot, and the served model is recorded as
  reported. Latency depends on load at run time.
- **The sample is small and familiar:** 3 repeats per routing case and 1 execution per end-to-end case, all on
  familiar cases. Differences of one or two are within run-to-run variation.

## Records
- **Run log:** `artifacts/live/MC-dev/run_log.jsonl`.
- **Routing records:** `artifacts/live/MC-dev-route-<mini|sol>-r<1-3>/`.
- **End-to-end records:** `artifacts/live/MC-dev-e2e-<mini|sol>/`.
- **Contents:** each slot's record, standard output and trace.
- **Scoring:** `score.py` scores offline, never calling a model.
