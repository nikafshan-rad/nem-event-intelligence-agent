# Routing-only Live check of route contract v15: results of the one approved run (diagnostic)

**The combined verdict, as frozen: FAIL.** It is computed by `eval/livecheck_route_v15/score.py` under `PROTOCOL.md`
as amended by `AMENDMENT_1.md`, unchanged. No architectural acceptance is claimed. The run was approved for
diagnostic attribution only: it was known before the run that the combined criteria could not PASS (N04 and N07).

**These are counts from one sample, not reliability rates:** 34 calls, 2 on each of 17 questions, of a
non-deterministic model. Differences of one or two calls are within run-to-run variation. Ten familiar development
questions and seven fresh ones show nothing about generalisation.

**Scope:** routing and request resolution only. No tool ran, nothing was calculated, and no answer was written, so
nothing here bears on answers. There was no H1–H5 review.

## Records
| What | Where |
| --- | --- |
| The 34 records (the routing decision, the full resolution, the tools Live would offer, usage and cost), each call's standard output, and its trace | `artifacts/live/LC-route-v15-run/` (`<NN>-<config>.json`, `.stdout.txt`, `traces/`) |
| The run log and the driver log | `artifacts/live/LC-route-v15/run_log.jsonl`, `artifacts/logs/LC_route_v15_driver.log` |
| Every assessment: layer 1 (extraction) with its items and errors, layer 2 (class, outcome, eligibility), attribution, and layer 3 | `SCORE.json` (this directory); `python eval/livecheck_route_v15/score.py` reproduces it byte for byte from the committed records, offline |
| The cost reconciliation | `COSTS.json` (this directory) |

## The run
- **What ran:** main `43676d5` (PR #77 merged; tree equal to the reviewed head `38fbe91`), the code under test
  `d38eb4d`, `src/` tree `2e2e1a7`, prompts v16 and route contract v15.
- **The model:** `gpt-5-mini`, reported as `gpt-5-mini-2025-08-07` at the provider's default reasoning effort
  ("medium"; none was sent). The routing output cap was 2,000 tokens.
- **The guards, checked before the run:**
  - all 42 frozen hashes matched;
  - the starting ledger was USD 9.227365, 3,158 lines, `4250ef88a8ad3d35`;
  - no runner, lock, run log or record existed, and no override was set;
  - the dry run raised no refusal at the approved cap.
- **The calls:** 11:06:39 to 11:15:39 UTC, 34 of 34 saved in the frozen order in one attempt. There was no
  interruption, API error, budget stop or safety stop, and nothing was repeated.

## 1. The model's extraction (layer 1)
The model's own routing decision was assessed item by item against the independently verified extraction gold. It is
never inferred from the resolution.

| | Correct reading | Incorrect reading | No reading (rejected response) | Calls |
| --- | --- | --- | --- | --- |
| Familiar (D01–D10) | 12 | 3 | 5 | 20 |
| Fresh (N01–N07) | 11 | 2 | 1 | 14 |
| Together | 23 | 5 | 6 | 34 |

**The incorrect readings, by item** (domain 3, date 2, run 2):
- **D08, slot 23:** domain `operational_demand` (gold: `unclear`).
- **N03, slots 9 and 28:** domain `operational_demand` (gold: `unclear`).
- **D05, slots 13 and 34:**
  - no date given (gold: 2026-08-20);
  - the run's words were the cutoff's ("As of 2026-08-19T20:00:00Z, looking only at runs already public,"), which
    lack the key word "newest".

**Correct in both calls:** D01, D02, D03, D04, D09, N01, N02, N05, N06 and N07. Every request for another kind of
forecast (D09, N01, N02, N05, N06) was read correctly.

**Correct in the one call that produced a reading:** D06 (slot 3), D07 (slot 27) and N04 (slot 25).

## 2. Correct readings rejected or mis-resolved by code
**Correct readings rejected by code: 9 calls.** All were sent back with no tool offered.
- **D01 ×2, D02 ×2, D03 ×2 and N07 (slot 14):** the domain conflict "the operation's words are outside the requested
  clause".
  - **The cause:** the model's operation words (typically the whole question, or the question from its first word)
    extend beyond its requested clause.
  - **The rule:** D29's clause-containment rule requires the operation's and scope's words to lie inside the clause.
- **D07 (slot 27):** the conflict "the scope's words are outside the requested clause".
  - The half-hour ("half-hour closing 2026-07-29T08:00:00Z") is stated before the demand clause.
  - This is D29's known shared-scope limit.
- **N07 (slot 33):** the scope was not read, because the code does not read "noon". This is the known blocker, from a
  correct extraction that copied "06:00" and "noon".

**A correct reading mis-resolved by code: 1 call.**
- **N04 (slot 25):** a resolver defect, the known blocker. The demand request resolved as the gold says, but the code
  also named a weather forecast as not answered, which the question declines ("Leave the weather forecast out of this
  one").
- **This was the code, not the model:** the model gave no unsupported words.

## 3. Incorrect readings accepted by code, and errors caught by code
**Incorrect readings accepted by code: 1 call.**
- **D08 (slot 23):** the model read "the latest issued forecast" as an operational demand forecast. Code bound it: a
  forecast value for the SA1 event's peak half-hour, with cutoff 2026-07-30T14:35Z.
- The deterministic checks cannot detect this misreading, because the words name no other kind (D29, "Not claimed").

**Errors caught by code: 4 calls.**
- **D05, slots 13 and 34:** the incorrect readings above were sent back, through the same clause-containment conflict.
  This is a supply loss.
- **N03, slots 9 and 28:** the model's demand reading of the genuinely ambiguous question was stopped by the
  clause-containment conflict ("the scope's words are outside the requested clause"). The outcome, asking which
  forecast is meant, is one N03 accepts.

## 4. Incomplete responses: 6 calls
Every one was cut off at the unchanged 2,000-token routing cap (`max_output_tokens`), rejected before parsing, and sent
back fail-closed with "The routing model returned invalid output."

| Call | Output tokens | Reasoning tokens | Visible output |
| --- | --- | --- | --- |
| D07, slot 15 | 1,984 | 1,984 | none |
| D10, slot 17 | 1,984 | 1,984 | none |
| D10, slot 20 | 1,984 | 1,984 | none |
| D06, slot 19 | 1,984 | 1,984 | none |
| D08, slot 7 | 2,000 | 1,792 | cut off in `requested.forecast.scope_text` |
| N04, slot 8 | 2,000 | 1,728 | cut off in `requested.forecast` |

- **D10 produced no reading in either call,** so the demand-maximum control was not exercised.
- **Completed responses** used 892–1,896 output tokens (median 1,515).
- These are counts, not a truncation rate.

**D06, slot 19, precisely:**
1. **The response:** it was incomplete. All 1,984 output tokens were reasoning, and there was no visible text.
2. **The send-back:** it was rejected. The resolution's status is `needs_clarification` ("The routing model returned
   invalid output."). The tools Live would offer are none, and the trace holds only model and routing events, with no
   tool event.
3. **What remained:** the resolution record still carries **parser-derived binding metadata**, which the question
   parser computed when no routing decision was available:
   - a bound operational demand forecast request: a forecast value for the half-hour 2026-08-19T23:00Z–23:30Z;
   - the run rule `as_of_availability`;
   - the cutoff 2026-08-19T21:00Z.

   The send-back status overrides it.
4. **Why the scorer flags it:** the frozen scorer assesses a bound request whatever the status. Its clause check found
   the parser's domain evidence, the single word "demand" stored without an offset, overlapping an excluded anchor.
   - "demand" occurs twice in H06: at offset 101, in "Victorian operational demand" (the request), and at offset 199,
     in "push demand up" (inside the excluded weather question).
   - An offline reproduction of the parser places its evidence at offset 101. The record cannot show that, and the
     frozen check tests every occurrence.
5. **The result:** a scored wrong binding. It stands in the frozen verdict.
6. **What it is not:** it is **not** a tool execution, and **not** a demonstrated availability leak. No tool ran, none
   was offered, no data was read, and nothing was answered.

## 5. Actual tool execution versus tool eligibility
- **Executed:** none.
  - No call created a dispatcher, offered a tool to the model, or ran one.
  - Every record holds exactly one model call, and no trace holds a tool event.
  - There were no case-note writes or forbidden calls.
- **Eligible (what Live would have offered had the investigation continued):** demand-forecast tools in 5 of 34 calls.
  - **D04 ×2 and D06 (slot 3):** correct.
  - **D08 (slot 23):** a scored violation, since the gold says the demand tools are not used.
  - **N04 (slot 25):** eligible as the gold says, but its resolution carries the wrongly claimed weather note.
- **The other 29 calls** were sent back, so no tool would be offered.

## 6. The combined criteria (layer 3, frozen)
**FAIL**, from three scored violations:
- **D08, slot 23:** a forecast request bound where the gold has none, with demand tools eligible;
- **N04, slot 25:** an unsupported part wrongly claimed;
- **D06, slot 19:** the parser-derived binding described above.

The FAIL stands on D08 and N04 alone. The bars:

| Bar | Result |
| --- | --- |
| Supply (each of 10 configurations at least once, and at least 17 of 20) | 3 of 20 (D04 2, D06 1, every other 0): not met |
| Demonstrated containment (each of 6 configurations at least once) | 12 of 12 calls: met |
| D08, apart | slot 7 no reading (rejected response), slot 23 violation |

**Attribution, all 34 calls:**

| | Familiar | Fresh |
| --- | --- | --- |
| correct end to end | 5 | 8 |
| correct reading rejected by code | 7 | 2 |
| correct reading mis-resolved by code (a resolver defect) | 0 | 1 |
| incorrect reading accepted by code | 1 | 0 |
| error caught by code | 2 | 2 |
| no reading | 5 (one with a scored violation surviving) | 1 |

## 7. Where the supply was lost (the 20 supply calls)
3 supplied, 17 lost:

| Cause | Calls |
| --- | --- |
| **D29's clause-containment rule** (the operation's or scope's words outside the model's requested clause) | **10**: 8 correct readings (D01 ×2, D02 ×2, D03 ×2, D07, N07) and 2 incorrect ones (D05 ×2) |
| Incomplete response at the 2,000-token cap | 5 (D06, D07, D10 ×2, N04) |
| "noon" not read | 1 (N07) |
| The N04 resolver defect | 1 |

**The clause-containment rule is the largest observed source of supply loss in this sample.** That is not a claim
that validation is unnecessary:
- the same rule stopped N03's demand misreading in both calls;
- every request for another kind of forecast was sent back as unsupported (10 of 10 calls; each read correctly by the
  model);
- one misreading (D08, slot 23) passed every check.

Truncation is the second-largest observed source.

## 8. Usage and cost
- **Tokens:** 78,878 input (71,552 of them cached) and 52,978 output (45,376 of them reasoning).
- **Duration per call:** median 13.1 s, range 8.6–55.9 s.
- **Spend:** USD **0.109572**, a mean of 0.003223 per call (at least 0.001868, at most 0.004176), against the run cap
  of 0.204 and the call cap of 0.006. Every reservation equalled its frozen value, at most 0.00556. The billed amount
  was not observed: the API response does not carry it.
- **Reconciliation (`COSTS.json`):** for all 34 calls, the ledger's settlement equals the record's cost, the run log's
  cost and the usage-priced cost. Their total equals the run log's run spend and the ledger's increase.
- **The ledger:** USD 9.227365 → **9.336937**; 3,158 → **3,226** lines (68 new: 34 reservations, all settled); SHA-256
  prefix `4250ef88a8ad3d35` → **`f303c2bc70aadd8f`**. Its first 3,158 lines are byte-identical to the start.

## Unchanged
- v1.0 (`f14db6d`);
- every frozen protocol, gold, runner and scorer: all 11 freeze sets match;
- `PROTOCOL.md` and `GOLD.json` in their original form;
- the historical verdicts, including this check's FAIL;
- the code and prompts.

No fix, rule, prompt or cap change, rerun, model switch or release has been made.
