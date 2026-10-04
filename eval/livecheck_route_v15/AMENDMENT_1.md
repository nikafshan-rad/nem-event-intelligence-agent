# Amendment 1: a diagnostic check in three layers, with D08 re-resolved (before any run)

Written on 2026-10-04 at the owner's instruction, before any paid call and before any Live result exists. It amends
`PROTOCOL.md` (pre-registered as `78e6f47`; as committed in `6077d46`). That file and `GOLD.json` are kept unchanged as
the original record. Where they differ, this amendment governs.

**This file authorises no paid call.**

## Why
The first freeze (`6077d46`) could not PASS against the merged code, whatever the model does. N04 and N07 were known
blockers (`PROTOCOL.md`, "Known before the run"). A single verdict would not say where the next bottleneck lies: in
the model's extraction, or in deterministic resolution.

This amendment keeps that verdict, and separates three layers so the run can show which is the bottleneck.

## Unchanged
- **The sample:** the 17 questions (`cases.json`, byte-identical), the 34 calls, and the call order (the first
  freeze's seed).
- **The code and contract:** the model; the code commit and its `src/` tree; prompts v16; route contract v15; the
  2,000-token routing cap.
- **The caps.**
- **The scripts:** the per-call runner and the orchestrator (`run_route.py`, `run_eval.py`, byte-identical).
- **No application code changes** and no parser expansion.

## Layer 1: the model's extraction
**What it assesses:** the routing model's own decision, item by item, against an independently written and
independently verified extraction gold (`EXTRACTION_GOLD.json`).
- It is read from the decision alone. A resolution that matches gold says nothing about the extraction, and a
  resolution that fails says nothing either.
- It has no pass threshold.

**The extraction gold:**
1. **Format:** `EXTRACTION_FORMAT.md` says, in plain terms, what a careful reader extracts from a question. That
   reader sees only the question, never a request field.
2. **Authors:** the writer and the reviewer, the same two independent agents, each wrote one record per question, in
   their own kits and without seeing each other's. This came after their earlier outputs were fixed and hashed
   (`EXTRACTION_WRITER.json`, `EXTRACTION_REVIEWER.json`).
3. **`amend.py` combines them mechanically:**
   - labels (region, domain, operation, run rule, maximum, whether a cutoff is stated) must be equal;
   - local dates and scope kinds are what both accept;
   - key words are required only if both authors require them;
   - anchors are the union of both, with no author's request anchor on the other's excluded or unsupported anchors;
   - the extraction gold must agree with the amended gold of the same question;
   - **an item is assessed only where both authors agree on it.**
4. **Result:** the two authors agree on every label, date, key word, cutoff and anchor of all 17 questions. Their
   intent sets differ for the seven questions that are to be sent back (D08, D09, N01, N02, N03, N05, N06).
   - The writer accepts a forecast review or an event review.
   - The reviewer accepts only an event review, because a clarification runs no investigation.
   - That difference is about handling, not about reading the question. Intent is therefore recorded, not assessed,
     for those seven. The domain item still assesses whether the reader saw what is forecast.

**The items assessed** (each where it applies):
- **intent:** for the 10 questions where the authors agree;
- **region;**
- **local date:** the decision's `event_date`;
- **domain:** what the forecast is of. "Not reported" is an error unless no forecast is asked or the model refuses;
- **operation;**
- **requested clause:** grounded words on a request anchor, and on no excluded anchor;
- **scope:** the kind, and words that contain every key word;
- **unsupported part:** named on its anchor; or, where the question asks for none, none named;
- **run:** the rule, and words that contain its key words;
- **cutoff:** words that contain its key words; or none, where the question states none;
- **maximum:** the kind, measure and window, and words that contain their key words; or none, where none is asked.

A reading is **correct** when every assessed item is correct. A rejected or missing response has **no reading**.

## Layer 2: deterministic resolution and tool eligibility
**What it assesses:** each call's resolution class and outcome, as in `PROTOCOL.md` with the amended gold, and whether
the demand-forecast tools Live would offer are the gold's. Layer 2 is reported for every call.

## Attribution: layer 1 against layer 2

| The model's reading | Resolved as gold says | Sent back or contained for another reason | Violation |
| --- | --- | --- | --- |
| **correct** | correct end to end | **correct reading rejected by code** | **correct reading mis-resolved by code (a resolver defect)** |
| **incorrect** | **error caught by code** (outcome still correct) | **error caught by code** (sent back) | **incorrect reading accepted by code** |
| **none** (rejected response) | — | no reading | no reading, with a surviving violation |

The report lists every call in each cell, and counts reading errors by item. Every call is classed this way:
- **N04:** a correct reading of N04 is classed "mis-resolved by code (a resolver defect)": the code notes the declined
  weather forecast as unanswered. A reading that itself names the declined forecast is "incorrect, accepted by code".
- **N07:** a reading of N07 that copies "06:00" and "noon" is a correct extraction. When the code then cannot convert
  "noon", the call is "rejected by code".
- **Neither** is ever credited as successful end-to-end resolution.

## Layer 3: the combined acceptance criteria
`PROTOCOL.md`'s classes, precedence, supply and containment bars, and verdict are unchanged, except for D08's gold
(below).
- **Its known blockers remain:** N04 and N07, so PASS cannot occur as frozen.
- **The report gives the verdict** with `acceptance_claimed` true only on PASS. The check claims no architectural
  acceptance when known criteria fail.
- **No new pass threshold** is set for the diagnostic layers.

## D08 re-resolved
**The withdrawal:** the owner withdrew the earlier instruction that accepted reading D08 as an operational demand
forecast request.

**The agents' final readings:** both independent agents were asked for D08's genuinely acceptable outcomes under
`CAPABILITIES.md` and the question's meaning alone (`D08_WRITER.json`, `D08_REVIEWER.json`). Both, independently,
gave:
- **outcome:** `clarify_which_forecast`;
- **also acceptable:** `event_review_unclear`.

**Their rationale:**
- "The latest issued forecast" does not show what was forecast.
- For the peak half-hour of a price event, AEMO's price forecast is at least as plausible as the demand forecast, and a
  weather forecast is possible.
- `CAPABILITIES.md` says such a forecast is not assumed to be demand.

**The outcomes they rejected:**
- `resolved`: it assumes demand;
- `clarify_unsupported`, `event_review_unsupported` and `refusal`: each assumes an unsupported kind the question does
  not show;
- `clarify_mixed`: there is only one request.

**`GOLD_AMENDED.json`:** it is `GOLD.json` with D08 holding exactly those two outcomes, no resolved reading, and the
demand-forecast tools not used. The original outcomes and both rationales are recorded.

**The consequence:**
- A demand reading of D08 now binds a request where the gold has none. As for N03, that is a layer-3 violation, a
  domain error in layer 1, and "incorrect reading accepted by code".
- D08 is still reported apart, outside the supply and containment totals.

## Records added, and scripts changed
- **Added:**
  - this file;
  - `EXTRACTION_FORMAT.md`;
  - the agents' records (`D08_WRITER.json`, `D08_REVIEWER.json`, `EXTRACTION_WRITER.json`, `EXTRACTION_REVIEWER.json`);
  - `amend.py`, `GOLD_AMENDED.json`, `EXTRACTION_GOLD.json`.
- **Changed:**
  - `score.py`: layer 1, attribution, the layered report, and the amended gold;
  - `build_kit.py`: the `extraction` step;
  - `freeze.py`: the new files, and `--seed`;
  - `PROVENANCE.md`: a section for this amendment;
  - the tests.

## Re-freeze
`FREEZE.json` is rewritten with the first freeze's order seed, so the call order is the same. It records the files
above and supersedes the freeze committed in `6077d46`, which stays in the history.
