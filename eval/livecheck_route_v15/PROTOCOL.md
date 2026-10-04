# Routing-only Live check of route contract v15 (pre-registered; not run)

Written on 2026-10-04. It is committed and pushed before any fresh question is written or any gold is drafted. It is
then frozen with the configurations, gold, runner, scorer and caps, and is not edited after any Live result is seen.

**This file authorises no paid call.** A run needs the owner's separate approval of the frozen check and of its task
cap ("Caps").

## What this is
**One bounded Live check** of the merged request contract: `main` `d38eb4d`, route contract v15, prompts v16, model
`gpt-5-mini`. It covers real-model extraction and deterministic resolution together:
- the routing model reads each question once;
- code resolves that reading;
- the resolution is assessed against independently written and independently verified gold.

**What it assesses:** domain, requested clause, operation, scope, run selection, cutoff, unsupported parts and tool
eligibility. A schema-valid response establishes nothing by itself.

**What it is not:**
- an end-to-end check;
- an answer review: no H1–H5 review is made, and no answer is produced;
- L3;
- evidence of generalisation.

No tool runs, nothing is calculated and nothing is synthesised. Historical verdicts are unchanged by any result here,
and Live stays experimental.

**The verdict, and only this:** acceptance of v15 request extraction and resolution, on this sample of 10 familiar
development questions and 7 fresh questions.

## What is frozen (`FREEZE.json`, written by `freeze.py`)
- **The code:** the commit `d38eb4d` and, separately, its `src/` tree. The checkout's `src/` must equal that tree.
- **The routing contract:** prompts v16 (their tree) and route contract v15.
- **The model and its settings:** `gpt-5-mini`; the routing output cap of 2,000 tokens, unchanged; the default
  reasoning effort, not sent.
- **These files, by SHA-256:**
  - this protocol;
  - the capability brief, the writer's and reviewer's briefs, and their outputs and reports;
  - `cases.json` and `GOLD.json`;
  - the gold builder, runner, orchestrator, scorer and freeze script;
  - every source file a question is copied from.
- **Also frozen:** the call order, the caps, and the starting ledger.

Nothing in the code, prompts, model, configurations, gold, criteria or caps changes between the freeze and the end of
the run. If a change turns out to be needed, the run is not started, or the run in progress stops, and that is
reported.

## Scope: 17 configurations, 2 calls each, 34 routing calls

**Familiar development questions:** copied unchanged from their sources; a test checks this. Familiar means seen during
development.

| Config | Source | Request fields | Tests | Set |
| --- | --- | --- | --- | --- |
| D01 | K14 (`eval/livecheck_i15_17/cases.json`) | none | Named run; forecast and actual for one half-hour | supply |
| D02 | K06 (`eval/livecheck_i15_17/cases.json`) | none | Last run issued before a half-hour; forecast and actual | supply |
| D03 | FC04 (`eval/cases.json`) | none | Window comparison over a day | supply |
| D04 | D28's stated-window question (`tests/provider/test_forecast_request.py`) | none | A stated window, used exactly | supply |
| D05 | Y07 (`eval/holdout_v5/cases.json`) | none | Target, window and cutoff separation | supply |
| D06 | H06 (`eval/holdout_v2/cases.json`) | none | Mixed: a demand forecast and a weather expectation | supply |
| D07 | Z07 (`eval/holdout_v6/cases.json`) | none | Mixed: a demand forecast and a temperature expectation | supply |
| D08 | FC02 (`eval/cases.json`) | none | An ambiguous forecast reference | ambiguity |
| D09 | D29's weather-only question (`tests/provider/test_forecast_domain.py`) | none | Weather only | containment |
| D10 | F07 (`eval/livecheck_maxima/cases.json`) | `as_of_utc` 2025-10-05T02:00:00Z (the case's own) | Demand-maximum regression control | supply |

**Fresh questions:** written by an independent writer (see "Gold") to these specifications. They are new to
development, and seven questions show nothing about generalisation.

| Config | Specification | Set |
| --- | --- | --- |
| N01 | A temperature forecast only, asking for its highest or maximum value | containment |
| N02 | AEMO's price forecasts only, for a past day | containment |
| N03 | A genuinely ambiguous reference to "the forecasts" for a region and date: what is forecast is not shown, and demand, price or weather are all plausible | containment |
| N04 | Negation: declines a weather or temperature forecast, and asks for AEMO's operational demand forecast | supply |
| N05 | Negation: declines the operational demand forecast, and asks for a weather or temperature forecast | containment |
| N06 | Quoted background about a demand forecast, then a request for a temperature or weather forecast | containment |
| N07 | Quoted background about a weather forecast, then a request for AEMO's operational demand forecast, compared with actual demand | supply |

**The sets:**
- **Supply:** 10 configurations, 20 calls: D01–D07, D10, N04 and N07.
- **Containment:** 6 configurations, 12 calls: D09, N01, N02, N03, N05 and N06.
- **Ambiguity:** D08 (FC02), reported separately. It is in neither the supply nor the containment totals.

**The order:** two rounds, each running all 17 configurations. Within each round the order is shuffled once at the
freeze and recorded.

**Each call is one process:**
- `LiveController.route`: one routing call to the hosted model, under the ledger's cap;
- `service.resolve_routed`: request resolution.

That is exactly the first step of a Live investigation. No dispatcher is created, no tool runs, nothing is calculated
or synthesised, and nothing is written except the check's records and the ledger entry.

## Gold (`GOLD.json`)
Gold states what each question means and what the assistant, within its supported capabilities, should do with it.

**What gold is not built from:**
- the application's code or its output;
- D28 or D29 behaviour taken as given.

The assistant's supported capabilities are described in plain terms in `CAPABILITIES.md`, written for this check. It
is not the prompts and not the code.

1. **The writer**, a fresh agent working only in a kit outside the repository, with no access to the implementation,
   tests, prompts or earlier questions:
   - first writes N01–N07 with their gold;
   - after that output is fixed and hashed, writes gold for D01–D10 from those questions and `CAPABILITIES.md` alone.

   Its kit checks for overlap with hashed 6-word sequences of earlier questions and of the prompts, with no earlier
   text in the kit.
2. **The reviewer**, a second fresh agent working only in its own kit, blind to the gold:
   - reads each of the 17 questions itself;
   - gives its own reading;
   - computes every UTC bound with its own code.
3. **`gold.py`:**
   - **Builds:** `cases.json` and `GOLD.json` from the writer's output.
   - **Checks mechanically:** half-hour counts against bounds, bounds on the half-hour grid, and local-time
     conversions recomputed with `zoneinfo`.
   - **Cross-checks against frozen verified sources:** the run rules of K14 and K06, F07's maximum and cutoff, and the
     target half-hours and cutoffs of Y07, H06 and Z07.
   - **Compares** the gold with the reviewer's reading (`--compare`).
4. **Disagreements:**
   - **A mechanical slip** (arithmetic, a copying error) is corrected and recorded.
   - **A disagreement on meaning, or on any gated item,** is not resolved by the developer. It is reported to the
     owner, and the check is not frozen until the owner rules.

   Everything is recorded in `PROVENANCE.md`.

**Spans:** gold does not require one exact extraction string. Any grounded span (words located in the question) is
accepted when it overlaps the gold's anchors for the request and none of its excluded anchors (quoted background,
declined requests, the other part of a mixed question).

## Outcomes
Each call's resolution is mapped to one of these outcomes:

| Outcome | Means | Read from the resolution |
| --- | --- | --- |
| **resolved** | Proceeds with a request: an operational-demand forecast request, or (D10) a demand-maximum request | status `ok` |
| **clarify_unsupported** | Sent back: the forecast asked for is of a kind the assistant does not provide | `needs_clarification`, with the forecast request missing `domain_unsupported` |
| **clarify_which_forecast** | Sent back: which forecast is meant is not shown, or the readings of it conflict | `needs_clarification`, with the forecast request missing `domain`, or a `domain` conflict |
| **clarify_mixed** | Sent back: a demand forecast and another kind are both asked for, and cannot be separated | `needs_clarification`, with the forecast request missing `domain_mixed` |
| **refusal** | Refused as out of scope | status `refused` |
| **event_review_unsupported** | An event review that explicitly says the forecast part is not answered, and blocks both demand-forecast tools | status `ok`, intent `market_event_review`, both demand-forecast tools ineligible, a note beginning "Not answered:" |
| **event_review_unclear** | An event review that says a forecast is mentioned without showing which, and blocks both demand-forecast tools | status `ok`, intent `market_event_review`, both tools ineligible, the note "The question also mentions a forecast without showing which" |
| **other send-back** | Sent back or refused for any other reason | any other `needs_clarification` |

**Tool eligibility** is read from the resolution. The demand-forecast tools (`get_forecast_runs`,
`compare_forecast_actual`) are **eligible** when the status is `ok` and the intent's playbook offers at least one of
them that the resolution does not mark ineligible. This is exactly what Live would offer. Gold states one of:
- **eligible:** a resolved operational-demand forecast request;
- **not used:** a forecast of another kind, or an unclear one;
- **not restricted:** D10, which asks no forecast.

**Acceptable outcomes per set** (the gold confirms each case, and may narrow these but never widen them):
- **Supply:** resolved, with every gated item equal to gold.
- **Ambiguity (D08):** clarify_which_forecast; or resolved as an operational-demand forecast request with every gated
  item equal to gold. That means the independently verified target half-hour, cutoff, run rule, operation and
  eligibility; no other field is relaxed.
- **Containment, another kind** (D09, N01, N02, N05, N06): clarify_unsupported, clarify_which_forecast, refusal, or
  event_review_unsupported.
- **Containment, ambiguous** (N03): clarify_which_forecast, or event_review_unclear.

## Gated items
**For a resolved outcome:**
- region;
- domain: operational demand;
- the requested clause: its grounded words overlap the gold's request anchors and none of its excluded anchors;
- operation;
- scope: kind among the gold's kinds, exact UTC bounds, and half-hour count;
- run selection: rule, target half-hour and issue time;
- cutoff;
- maximum: D10's exact measure and window; no other configuration may bind one;
- unsupported parts: every part the gold lists is named, and none where it lists none;
- tool eligibility.

**For every call, whatever its outcome:** any bound request, region or cutoff must equal gold.

**The model's reading** is reported for every call, so that misreadings code caught are visible. It covers its intent,
domain, clause words, operation, scope, run, cutoff and unsupported words. It is not gated by itself.

## Classes and their precedence
**Each call gets exactly one class**, tested in this order:
1. **Violation** (FAIL), on any saved record, including an incomplete or invalid response:
   - **Wrong binding:** a bound forecast request, maximum, run, region or cutoff that differs from gold; or a
     resolved request with any gated item different from gold.
   - **Dropped cutoff:** a cutoff is detected, the resolution proceeds, and no cutoff is applied.
   - **Incorrect tool eligibility:** the demand-forecast tools are eligible where gold says "not used". This includes
     an event review that leaves them available for another kind's forecast.
   - **Missed request:** the resolution proceeds without the gold's forecast request or maximum.
   - **Omitted unsupported part:** the resolution proceeds without naming an unsupported part the question explicitly
     requests.
   - **Unsupported part wrongly claimed:** the resolution names one where gold has none, for example a declined or
     quoted request.
2. **Unassessable:** the record is missing, or lacks a field a gated assessment needs. This makes the check
   INCOMPLETE.
3. **Incomplete or invalid response:** rejected before it could be read (fail-closed). It is an extraction miss.
   - It never counts as containment, or as supply.
   - If it proceeds, it is still assessed under class 1.
4. **Correct resolved request:** an acceptable resolved outcome, with every gated item equal to gold.
5. **Correct clarification or unsupported handling:** an acceptable outcome other than resolved.
6. **Unnecessary clarification:** a supply configuration that is sent back, or refused.
7. **Contained for another reason:** a containment or ambiguity configuration sent back, refused, or handled in an
   event review in a way that is not one of its acceptable outcomes, with nothing bound wrongly. It is not containment
   evidence.

## Acceptance criteria (the verdict, in this order)
1. **FAIL** if any call is classed as a violation. Each violation is a demonstrated failure, whatever the coverage.
   This includes D08's calls.
2. Otherwise **INCOMPLETE** if any of the 34 calls is missing or unassessable.
3. Otherwise **INCONCLUSIVE** if either bar is unmet. Saved rejected responses count as extraction misses, never as
   correct handling.
   - **Supply:** each of the 10 supply configurations has at least 1 correct resolved request, and the 20 supply calls
     have at least 17 together. The six containment configurations and D08 are not in these totals.
   - **Demonstrated containment:** each of the 6 containment configurations has at least 1 call classed as correct
     clarification or unsupported handling.
4. Otherwise **PASS**: v15 request extraction and resolution accepted on this sample.

Correctness (criterion 1) and usefulness (criterion 3) are reported separately, so clarifying every question cannot
pass.

**Reported apart from the verdict:**
- D08's two calls, each against its two acceptable outcomes;
- familiar and fresh configurations in separate tables;
- each outcome type, so a less specific containment (clarify_which_forecast for a weather question) is visible.

## The report (`score.py`, offline; it never calls a model)
1. **The verdict,** with the supply and containment bars.
2. **Per call:**
   - its class and outcome;
   - every gated item against gold, with its provenance (the model's quoted words with their offsets, the question
     parser, or the request field);
   - the eligible tools.
3. **The model's reading against gold,** per call: misreadings code contained, and correct readings.
4. **Violations.**
5. **Unnecessary clarifications, contained-for-another-reason calls and extraction misses,** with their reasons and,
   for incomplete responses, their recorded diagnostics:
   - status and incomplete reason;
   - reasoning and visible tokens;
   - visible characters, whitespace share and trailing whitespace;
   - the open JSON field;
   - the diagnosed cause.
6. **D08's section.**
7. **Token usage, latency and cost,** per call and in total.
   - **Measured:** input, cached, output and reasoning tokens, and duration.
   - **Ledger accounting:** each call's ledger cost.
   - **Not observable:** the billed amount.

**The report must not claim:**
- end-to-end answer correctness;
- any H1–H5 answer review;
- any rate;
- that truncation or whitespace degeneration is fixed;
- generalisation.

## Caps
- **Starting ledger:** the real ledger. At the first start, its total, line count and SHA-256 prefix must equal USD
  9.227365, 3,158 lines, `4250ef88a8ad3d35`.
- **Per call: USD 0.006.**
  - At the freeze, `freeze.py` measures each configuration's actual routing request: the real routing path with a
    capturing stub, no call and no ledger write. Its exact worst-case reservation must be at most USD 0.006.
  - If any exceeds it, the freeze refuses and this is reported as a blocker. The cap is never raised automatically.
- **Run cap:** 34 × 0.006 = **USD 0.204**.
- **Required approved task cap:** 9.227365 + 0.204 = **USD 9.431365**. The standing configured cap (USD 5.00) is
  already exceeded, so nothing runs without the owner's approval of this cap.
- **Expected spend:** about USD 0.10 (0.08–0.13). The v13 routing check measured a median of USD 0.0022 per call, and
  v15's prompt and schema are longer.
- **Enforced before each call:**
  - **the case cap** (`nem_agent.budget`): the ledger total at the call's start plus 0.006;
  - **the start guard:** a call starts only if the run's spend so far plus 0.006 is within the run cap, and the ledger
    total plus 0.006 is within the approved task cap.
- **Interrupted attempts stay counted.** The cost of an attempt in flight at an interruption stays counted against the
  run cap, and no retry allowance is added. If interruptions exhaust the run cap, the start guard stops the run and
  the check is INCOMPLETE. The caps are not raised.

## Stops, interruption and refusals
- **Stops:** any of these ends the run, and what was not run makes the check INCOMPLETE:
  - a budget stop;
  - an API error or timeout;
  - a missing record;
  - a safety stop (a case-note write or forbidden call);
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
  - the prompt version is not v16, or the route contract is not v15;
  - no API key is set (never read or printed);
  - the approved task cap is below the required one;
  - at the first start, the ledger is not the frozen one, or at a resume it is below its last recorded value;
  - the check has ended.

## Records
- **Run log:** `artifacts/live/LC-route-v15/run_log.jsonl`.
- **Records:** `artifacts/live/LC-route-v15-run/<NN>-<config>.json`, with each call's standard output, and its trace
  under `traces/`.
- **Each record keeps:**
  - the full routing decision (v15, with its contract);
  - every routing event of the trace;
  - the full resolution: status, reasons, intent, region, cutoff, window, target, and every request with its
    provenance, spans and offsets, notes and ineligible tools;
  - the tools Live would offer;
  - the case-note file count, and the ledger cost.
- **Scoring:** `score.py` scores offline and never calls a model.

## Limitations
- **The sample is small:** 17 questions, 2 calls each. There are no rates, and differences of one or two calls are
  within run-to-run variation.
- **Familiar questions** were seen during development. Seven fresh questions are not evidence of generalisation.
- **Routing only:** nothing here bears on answers, tools or synthesis.
- **Known limits of the merged code are not changed here.** The queued wording defect of the unanswered-part note
  ("a another kind of forecast") may appear in notes. It is not scored, and not fixed.
- **The 2,000-token routing cap is unchanged** while v15's output is longer than v13's. Incomplete responses are
  extraction misses and count against supply.
