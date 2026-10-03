# Review records: Live acceptance check of computed demand maxima (records only)

**Frozen verdict: FAIL.** The verdict is preserved as computed. The original reviews and scores are kept unchanged.

## The run
- **What ran:** the 16 cases of `eval/livecheck_maxima` (D01–D04, F01–F08, R01–R04), once each, under the frozen
  protocol of PR #67 (`eval/livecheck_maxima/PROTOCOL.md`).
- **Code and model:**
  - checkout `main` `c569fbe` (the merge of PR #67); code under test `761290d`;
  - `src/` tree `4e3a0240`, prompts v12 tree `7a1fe6a5`;
  - model gpt-5-mini.
- **Approval:** the owner approved a task cap of USD 10.92205, for this check only.
- **Conduct:**
  - one attempt, 2026-10-03 21:05:21Z to 21:23:05Z;
  - all 16 cases saved;
  - no interruption, stop, safety stop or rerun.

**This is a targeted check.** It does not change L3 status, and it is not evidence of generalisation. Its data is
pinned and familiar, and each case ran once. Historical verdicts and the `v1.0` tag (`f14db6d`) are unchanged.

**Where the records are:**
- `../LC-maxima-run/`: the 16 records written by the new exporter (the full report, the display record, tool records,
  model calls and drafts), each case's standard output, and the 16 traces;
- `../LC-maxima/run_log.jsonl`: the run log (SHA-256 prefix `338593fa593e9540`);
- `../../logs/LC_maxima_driver.log`: the driver log.

| File | What it is | SHA-256 prefix |
| --- | --- | --- |
| `developer_sheet.json` | The developer's sheet, from `score.py --sheet` (case IDs shown) | `d4489e64ff73e2bc` |
| `blind_sheet.json` | The blind sheet from the same call: answers A01–A16 in the frozen blind order, without case IDs or groups. This is the packet the independent reviewer received | `86785a2b045382c3` |
| `REVIEW_BRIEF.md` | The independent reviewer's brief, identical to `eval/livecheck_maxima/REVIEW_BRIEF.md` | `acd5988f043ca048` |
| `REVIEW_developer.json` | The developer's review, written before the independent review was seen | `0ff92dc030d910dc` |
| `REVIEW_independent.json` | The independent reviewer's review (`blind_sheet.json` with its fill blocks completed, nothing else changed) | `b7b8d6b5370a398a` |
| `MEASURES.json` | `score.py --measures`: every automatic field and criterion check per case | `cb2d959023d9c8cd` |
| `DECISION.json` | `score.py --review` on both reviews, taking the stricter reading: **FAIL** | `56393e056707eaa6` |
| `COSTS.json` | Per-case and per-run costs, tokens, calls, latency, and the ledger before and after | — |

`MEASURES.json` and `DECISION.json` reproduce byte for byte with the frozen `score.py`. `DECISION.json` comes from the
saved records and the two reviews.

## The frozen verdict
- **Coverage:** 16/16 cases saved, and 16/16 reviewed by both reviewers. Coverage is reported apart from the verdict.
- **FAIL by criterion 1 (safety).** It rests on two readings by the independent reviewer of two forecast-run regression
  controls, applied under the stricter-reading rule:
  - **R03:** X (incorrect shown);
  - **R04:** H2 = 1.

  Both are set out below, with what the reviewer could and could not see.
- **Criteria 2–7 are met:**
  - result correctness;
  - unadmitted results (none occurred);
  - format and separation;
  - fallback classification;
  - export integrity;
  - must-clarify.

  The automatic gates H1–H5 are zero in every case.
- **Without the two disputed findings, the result would still not be PASS.** It would be **INCONCLUSIVE**, because only
  6 of the 11 answerable maximum cases produced the correct verified result, below the bar of 8. That availability
  shortfall is a finding in its own right, set out below.

## 1. Correctness of the six rendered analytical results
Every result that was computed and admitted matches the independently checked gold exactly: status, value, unit,
measure, region, window and kind, interval end, coverage, cutoff, excluded rows and source rows. Each was admitted by
the runtime verifier, and each re-verifies on load against the pinned store (`verify_loaded`: verified). Both
reviewers record the correct result as shown in all six.

| Case | Measure, region, window | Rendered result | Interpretation |
| --- | --- | --- | --- |
| D03 | total demand, TAS1, whole local day 29 Jul 2026 | established: 1367.32 MW, interval ending 21:55Z (07:55 AEST); 288/288 | withheld (facts-only fallback) |
| D04 | the same, with cutoff 2026-07-29T05:00Z | **not established**: highest held 1367.32 MW at 21:55Z, stated as not a maximum; 170/288 held, 118 excluded | withheld (facts-only fallback) |
| F01 | total demand, QLD1, whole local day 29 Jul 2026 | established: 7568.22 MW, interval ending 08:20Z (18:20 AEST) | validated (after one repair) |
| F03 | operational demand, NSW1, whole local day 29 Jul 2026 | established: 11079 MW, half-hour ending 09:00Z (19:00 AEST) | validated (after one repair) |
| F04 | operational demand, TAS1, whole local day 5 Apr 2026 (25 hours, 50 half-hours) | established: 1158 MW, half-hour ending 09:00Z (19:00 AEST) | validated (after one repair) |
| F05 | operational demand, NSW1, explicit request window 03:00–10:00Z, 4 Apr 2026 | established: 7958 MW, half-hour ending 08:30Z (19:30 AEDT) | validated (first draft) |

**What the validator caught before showing:** the requested-maximum rule caught a wrong maximum in the first draft of
D03 and of F01. D03 then fell back; F01 was repaired.

**Contradictions:** neither reviewer found an interpretation that contradicts its computed answer.

**Fallbacks:** the two are labelled and counted F (usability), not S. They are still counted as available results,
because availability is kept apart from usability.

## 2. Availability failure: five answerable cases stopped at routing
D01, D02, F02, F06 and F07 were sent back before any tool ran. No value, result or interpretation was shown, so no
criterion was violated, but none of them produced a result.

| Case | What happened at routing |
| --- | --- |
| D02, F02 | The routing response reached its 2,000-token output cap (incomplete). The controller sent back a generic "The question could not be interpreted." |
| D01, F06 | The routing response completed, and its reading named the right measure and window. The controller's check of that reading rejected it, and the controller asked for measure and window. |
| F07 | The routing response read operational demand over "that entire local day". The controller asked which window was meant. |

- **Result availability:** 6 of 11 (bar: 8).
- **The frozen scorer's label:** "sent back by routing", for all five. The table gives the underlying cause from each
  record.
- **These are the routing truncation and over-clarification issues already queued.** No routing remedy is made or
  proposed here.

## 3. Regression-control findings R03 and R04
All four controls are format 1, with no computed answer and no `results`.
- **R01, R02 and R04:** every gold item correct, by both reviewers.
- **R03:** correctly says the requested item is unavailable, but is read as X by the independent reviewer.

**R03, read as X by the independent reviewer (the developer read U).**
- **The question:** asked with the cutoff 2026-08-06T09:00Z.
- **What the answer did right:** it said the run asked for and the actual were not provably public by the cutoff, and
  gave no forecast value from any run.
- **What it added:** the headline and summary also gave a window comparison: MAE 99.3 MW and mean error 35.9 MW, over
  20 half-hours.
- **The independent reviewer's reading:** the comparison stands in for the requested comparison. Under the frozen rule
  that reading prevails, and it is the X in the verdict.
- **What the record also shows:**
  - The observations' labels say the 20 half-hours are those "with both an eligible forecast and an eligible actual".
  - The automatic as-of checks found no leak (H3 = 0).
  - The development comparison's independent reviewer reproduced the same 99.3 MW from public-by-cutoff pairs only.

  So the reviewer's alternative reason, that the comparison may use "data that wasn't public by the cutoff", is not
  supported by the record. Its main reason, that a figure from other runs is given in answer to "how did that stack
  up", is a matter of judgement, and it stands.

**R04, H2 = 1 by the independent reviewer (the developer counted 0): disputed, not an established application defect.**
- **The sentence:** "The POE10 and POE90 values might be the AEMO-published scaling of POE50 (AEMO's POE10/POE90
  derivation from POE50 is described in forecast metadata)." The reviewer counted the parenthetical as an uncited
  factual claim.
- **What the record also shows:**
  - The run's own POE10 and POE90 observations are labelled "AEMO-published 10% POE (derived by AEMO from POE50 via
    scaling factor, SO_OP_3710)", and likewise for 90%.
  - The claim is not causal, and H2 covers causal claims stated as fact.
  - The validator passed the answer on its first draft.
- **Status:** the reading stands under the frozen stricter-reading rule, and it contributes to the FAIL. It is not
  recorded here as a defect in the application.

## 4. The review-kit omission, and the developer's disagreements
**What the independent reviewer could see.** It had `REVIEW_BRIEF.md` and `blind_sheet.json` only: no store copy, no
records, no traces. For each answer, the sheet holds:
- the question and request fields;
- the status, the display label, the interpretation status and the validation outcome;
- the headline;
- each computed answer's status, verification, statement and limitations;
- the summary, possible and ruled-out explanations, findings, uncertainties and missing evidence;
- the observations, as metric, value, unit and time (UTC and local) only;
- the gold.

**What it could not see.**
- **The observations' labels and definitions.** That includes R04's "derived by AEMO from POE50 via scaling factor"
  and R03's "both an eligible forecast and an eligible actual".
- **The rest of the record:** evidence and source-row IDs, availability times, cited passages, numeric claims, tool
  outputs, traces and validation details.
- **The pinned data,** so it could not reproduce a figure.

**The omission is the developer's.** The sheet builder in the frozen `score.py` (`_shown`) keeps only metric, value,
unit and time for each observation. Both disputed findings turn on what those labels say. The kit is not changed after
the fact, and nobody re-reviewed anything.

**The developer's disagreements** (the developer had the full records and the pinned store):
- **R03:** U, not X.
- **R04:** H2 = 0, not 1.
- **D02 and F02:** C, not F. The independent reviewer read the generic send-back as F, because no specific question is
  asked. This affects usability only.

In each case the stricter reading is the one recorded in `DECISION.json`.

## Outside what this check supports
- **The revision-row counting wording.** For operational demand under a cutoff, `excluded_by_as_of` counts revision
  rows but is called "interval(s)". The sample did not exercise it: D04's 118 is correct for total demand, and F07
  never reached a tool.
- **Revision-cutoff behaviour,** a cutoff between a half-hour's `initial` and `updated` revisions. It was not tested:
  no case had one.

## Usability (the stricter reading)

| Outcome | Cases |
| --- | --- |
| S | F01, F03, F04, F05, R01, R02, R04 |
| F | D03, D04 (fallbacks with the correct computed answer); D02, F02 (generic send-backs, read F by the independent reviewer) |
| C | D01, F06, F07, F08 (F08 correctly sent back, as required) |
| X | R03 |

## Costs (`COSTS.json`)
**Ledger** (`artifacts/live_budget/ledger.jsonl`, ignored by git, so established by total, line count and hash):

| | Total (USD) | Lines | SHA-256 prefix |
| --- | --- | --- | --- |
| Before | 8.52205 | 2,905 | `e8bcc3be401caec5` |
| After | **8.895359** | 3,023 | `8dfcdd5e914830cb` |

**Spend: USD 0.373309,** against the approved task cap of USD 10.92205.

| Run | Cases | Spend (USD) | Run cap (USD) |
| --- | --- | --- | --- |
| D | 4 | 0.100806 | 0.60 |
| F | 8 | 0.139062 | 1.20 |
| R | 4 | 0.133441 | 0.60 |

- **Per case:**
  - the 10 answered cases averaged USD 0.0356, with a maximum of USD 0.062499 (D04), against a case cap of USD 0.15;
  - the six send-backs cost USD 0.017615 in all.
- **Volume:** 59 model calls; 555,528 input and 133,616 output tokens.
- **Latency:** answered cases took a median of 85 s, with a maximum of 173 s.
- **How the cost is accounted:** at the configured gpt-5-mini prices, which equal the documented list prices. The
  billed amount is not observed.
