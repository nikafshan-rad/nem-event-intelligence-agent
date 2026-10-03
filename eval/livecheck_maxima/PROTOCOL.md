# Live acceptance check of computed demand maxima (pre-registered; not run)

Written 2026-10-03, and committed and pushed **before any fresh question is written**. It is frozen with the cases and
gold, and is not edited after any Live result is seen. **This file authorises no paid call.** Running needs the owner's
separate approval of the frozen protocol and task cap (see "Caps").

**What this is:** one bounded Live acceptance check of the demand-maximum slice as merged in D24 (typed, verified
results) and D25 (the computed answer rendered apart from the interpretation). It runs the frozen code once per case.

**What this is not:**
- not L3, and not evidence of generalisation: the data is pinned and familiar, and each case runs once, so there are
  no rates;
- not a model comparison, and not a release;
- historical scores and verdicts are unchanged by any result here;
- Live stays experimental whatever the outcome.

## Pre-registered clarifications (the owner's, 2026-10-03, before any question was written)
1. **Criterion 3 concerns the computed-answer value.** Independently retrieved observations may remain. They must not
   be presented as the requested maximum, or imply successful verification.
2. **Verdict precedence,** in this order:
   - a demonstrated acceptance violation means **FAIL**, even if coverage is incomplete;
   - otherwise, missing cases or reviews mean **INCOMPLETE**;
   - with complete coverage and all criteria met, fewer than 8 of the 11 answerable maximum cases producing the
     correct verified result means **INCONCLUSIVE**;
   - **PASS** requires complete coverage, all criteria met, and at least 8 of the 11 correct results produced.

   Coverage is always reported separately from the verdict.
3. **Gold applies the request's as-of cutoff** to publication and revision eligibility. For operational demand, gold
   takes the latest eligible revision, never a later revision unavailable at the cutoff.

Result availability, interpretation quality and overall usability are kept separate. The regression controls report
their answer quality as well as their format.

## What is frozen (`FREEZE.json`, written by `freeze.py`)
- **The code under test:** `main` `761290d` (the merge of PR #66), with its commit tree, its `src/` tree and its
  prompts tree. The run checkout must have exactly that `src/` tree. This protocol adds nothing under `src/`.
- **Prompts** `prompts/v12`; **model** `gpt-5-mini` at the configured accounting prices; reasoning effort not sent;
  output caps, model-call limit, validators, controllers, tools and data as in that tree.
- **These files, by SHA-256:** this protocol, `BRIEF.md`, `GOLD_CHECK_BRIEF.md`, `REVIEW_BRIEF.md`, `cases.json`,
  `GOLD.json`, `GOLD_CHECK.json`, `PROVENANCE.md`, `gold.py`, `export.py`, `run_case.py`, `run_eval.py`, `score.py`,
  `build_kit.py` and `freeze.py`, and the agents' outputs kept for provenance: `WRITER_OUTPUT.json`,
  `WRITER_REPORT.md` and `GOLD_CHECK_REPORT.md`. Also every file the run reads from elsewhere: the source case files, and the
  frozen gold of the reused cases.
- **The case order, the caps, the starting ledger, and the blind review order.**

Nothing in the code, prompts, model, questions, gold, criteria or caps changes between the freeze and the end of the
run. If a change turns out to be needed, the run is not started, or the run in progress stops, and that is reported.

## Sample (16 cases, one execution each)

| ID | Group | Origin | What it asks | Expected |
|---|---|---|---|---|
| D01 | Development | K09 (`eval/livecheck_i15_17`) | NSW1 dispatch total demand, whole local day 29 Jul 2026 | established |
| D02 | Development | K11 (`eval/livecheck_i15_17`) | QLD1 operational demand, whole local day 29 Jul 2026 | established |
| D03 | Development | Z04 (`eval/holdout_v6`) | TAS1 total demand (and price), whole local day 29 Jul 2026 | established |
| D04 | Development | Z04, plus the request field `as_of_utc` 2026-07-29T05:00:00Z | the same, with a cutoff inside the day | not established |
| F01–F08 | Fresh | written for this check | see "Fresh questions" | per gold |
| R01 | Regression control | K05 (`eval/livecheck_i15_17`) | a forecast run against the actual; no maximum | format 1, S |
| R02 | Regression control | K06 | the same, for another region | format 1, S |
| R03 | Regression control | K07 | the same, with a cutoff before the run was public | format 1, U |
| R04 | Regression control | K14 | a run named by its issue time | format 1, S |

- **Reused cases are copied unchanged:** question, request and expected fields. A test checks this against their
  frozen files. D04 differs from Z04 only by its request's `as_of_utc`, and by its expected fields.
- **The 11 answerable maximum cases:** D01–D04 and F01–F07. Each has exactly one gold result. F08 must be sent back.
  The regression controls ask for no maximum.
- **Order:** D01–D04, then F01–F08, then R01–R04. These are three runs, D, F and R, which are the cap accounting units.

### Fresh questions (F01–F08)
- **Writer:** a fresh agent with no conversation history. It works only in a kit outside the repository
  (`build_kit.py`), which holds:
  - the brief (`BRIEF.md`);
  - a copy of the pinned store's tables, the 8 events, and the facts of eligible windows;
  - a list of development material to avoid where possible;
  - an environment with only `duckdb` and `pytz`;
  - hashes (not text) of every 6-word sequence of earlier evaluation questions and prompts v12, with an overlap
    checker.

  It has no access to the code, prompts, tests, earlier cases, this conversation or the gold script.
- **Strata** (one question each):

  | ID | Measure | Window | Cutoff | Expected |
  |---|---|---|---|---|
  | F01, F02 | dispatch total demand | whole local day 29 Jul 2026, two different regions, neither NSW1 nor TAS1 | none | established |
  | F03 | operational demand | whole local day 29 Jul 2026, not QLD1 | none | established |
  | F04 | operational demand | whole local day 5 Apr 2026, a region with daylight saving (25-hour day, 50 half-hours) | none | established |
  | F05 | either; F05 and F06 use different measures | explicit, given in the request fields `window_start_utc` and `window_end_utc`, fully held | none | established |
  | F06 | the other measure | a listed event's window, fully held | none | established |
  | F07 | operational demand | a whole local day or a listed event's window | `as_of_utc` inside the window | not established |
  | F08 | — | a demand peak with no measure named, or with no window given | — | sent back (C) |

  - D04 covers total demand under a cutoff, so F07 uses operational demand, which also exercises revision
    eligibility.
  - The questions are worded as an analyst would ask them; the brief does not prescribe wording.
- **Output:** for each case, the question, the request fields, and the writer's intended reading: measure, region,
  window kind and bounds (UTC and local), cutoff, and expected outcome. No numbers.
- **Developer's role:** the developer may reject a question only as out of scope (it breaks its stratum or the brief's
  data rules), with the reason recorded in `PROVENANCE.md`. The developer never rewords a question.

## Gold (`gold.py` → `GOLD.json`; checked independently → `GOLD_CHECK.json`)
`gold.py` reads the pinned store's parquet files directly with duckdb. It never imports the application. For each of
the 11 answerable maximum cases it computes, from the case's intended reading:
- **Window:** interval ends in (start, end]. A whole local day runs from local midnight to the next local midnight in
  the region's IANA zone, so it is daylight-saving aware. An event window is the listed event's window. An explicit
  window is the request's fields.
- **Measure:** dispatch total demand is `regionsum_5min.totaldemand_mw` (5-minute). Operational demand is
  `opdemand_actual.operational_demand_mw` (half-hour). The two are never mixed.
- **Eligibility under a cutoff:** a row is eligible only if both its `published_at_utc` and its `available_at_utc` are
  at or before the cutoff. With no cutoff, every row is eligible.
- **Revision (operational demand):** per half-hour, among its eligible rows only, the latest revision is the one
  with the greatest `available_at_utc`, preferring `updated` on a tie. A revision not available at the cutoff is never
  used.
- **Coverage:**
  - intervals in the window = the window's length divided by the interval length;
  - held = intervals with an eligible value;
  - complete if held equals the intervals in the window.
- **Status:**
  - **established** (complete): the maximum, every interval whose value equals it exactly (ties), and their source
    rows;
  - **not established** (incomplete, some held): the highest value held, its interval(s) and source rows, marked as not
    a maximum;
  - **unavailable** (none held): the reason.
- **Also recorded:**
  - the number of source rows in the window excluded by the cutoff (both revisions counted);
  - the number of intervals with no eligible row;
  - the runner-up value;
  - for D01–D03, agreement with the reused cases' frozen gold;
  - for D03 and D04, the price facts the question also asks for (reference for the review, not a criterion).

**The independent gold check:**
- **Who:** a second fresh agent, given the kit, the questions and the request fields. It is not given the writer's
  intended readings, `gold.py` or `GOLD.json`.
- **What it does:** it records its own reading of each question and computes each result with its own code.
- **Comparison:** its readings must equal the writer's, and its results must equal `GOLD.json` exactly, before the
  freeze. That means equal status, values, interval ends, source rows and counts.
- **If they disagree:**
  - a disagreement on a reading goes back to the writer once, with the checker's reading but no gold, and the outcome
    is recorded;
  - a disagreement on a number is resolved by finding the error, and recorded.

  No gold is edited by hand.

**Known before the run (found while preparing gold; not changed, since this check changes no application code):**
- **How the tools count exclusions:** for operational demand under a cutoff, the tools count each excluded revision
  row. So the result's `coverage.excluded_by_as_of` counts rows, not half-hours, yet its `AS_OF_CUTOFF` limitation says
  "N interval(s) of the window were excluded".
- **Example:** SA1, 29 July 2026, cutoff 05:00Z. The window has 48 half-hours, 23 of them held and 25 with no
  eligible row, but the count is 66.
- **For criterion 2:** the field is compared with the excluded-row count, which is what it holds.
- **The shown sentence:** it is judged by the reviewers under the usual definitions. Nothing about it is excused in
  advance.

  For total demand, one row per interval, the two counts are equal.
- **In this sample (added after the questions and gold were written):** every case has one row per interval in its
  window. That holds for D04 (total demand) and for F07, whose day holds one revision per half-hour. So the two counts
  are equal throughout (118 and 40), and the defect is not exercised.

## The exporter (`export.py`, `run_case.py`)
**The frozen exporters are not used and not changed:** `scripts/live_diagnose.py` and
`eval/livecheck_i15_17/run_case.py`. They drop `schema_version` and `answer`.

`run_case.py` runs one case with the evaluation's own `run_system_case`, which also produces the automatic score
fields. It saves:
- **The full report:** `report.model_dump(mode="json")`, which includes:
  - `schema_version`, `answer` and `summary`;
  - `results`, each with the producing server's `server_verification`;
  - `validation`, including `interpretation`, `fallback_applied`, `pre_repair`, `initial` and `after_fallback`;
  - everything else.
- **The display record:** `result_provenance`, `report_format` and `summary_v1`.
- **The score fields:** the case-note files written, and the case's ledger cost.
- **The run's records:**
  - the routing decision;
  - every tool record (arguments, status, blocked reason, source rows, output excerpt);
  - model calls with usage;
  - the drafts.
- **The trace:** saved in full next to the record.

The API key is never read, printed or written.

## Acceptance criteria (each over every completed case; the stricter reading of the two reviews prevails)
1. **Safety:**
   - H1–H5 are zero, by the automatic checks and both reviews;
   - no case is X.

   The gates are as in `eval/livecheck_i15_17/PASS_RULE.md`, "Safety gates", measured on the answer as shown.
2. **Result correctness:**
   - **Matches gold:** every admitted result, verified by the runtime verifier and rendered as verified, matches its
     case's gold exactly. That means status, value, unit, measure, region, window and window kind, interval end(s)
     with every tie, coverage (interval length, intervals in the window, intervals held, complete), cutoff, excluded
     rows, and source rows.
   - **An extra result is a violation:** an admitted result in a case with no gold result, or one matching no gold
     result of its case.
3. **Unadmitted results** (clarification 1):
   - **The answer item:** a result the verifier did not admit renders as `not_verified`, with no value, limitations
     or source rows. Its statement contains none of the result's values.
   - **What the reviewers check:** no shown text presents an independently retrieved observation as the requested
     maximum, or implies the result was verified.
   - **If one occurs:** none is expected, and any occurrence is reported as an anomaly even when it complies.
4. **Format and separation:**
   - **A report with a computed answer:**
     - `schema_version` "2";
     - one `answer` item per reported result, and the reverse;
     - no answer statement in `summary` or `headline`;
     - an interpretation status consistent with fallback: `validated` without fallback, `withheld: …` with fallback,
       or `absent: …` with no valid model output.
   - **Every other report:** `schema_version` "1", with empty `answer` and `results`.
5. **Fallback classification:**
   - every fallback is labelled in the record: `fallback_applied`, interpretation `withheld: …`, and a fallback kind
     in `result_provenance`;
   - it is never counted as supplied: the scorer classifies it F whatever a reviewer records, and a reviewer's S on
     a fallback is reported and overridden.
6. **Export integrity:**
   - **Round trip:** every saved record's report validates as an `InvestigationReport` and dumps back to the saved
     JSON.
   - **The adapter:** `summary_v1` equals the answer statements followed by `summary` (format 2), or `summary`
     (format 1).
   - **Re-verification:** every admitted result re-verifies against the pinned store with `verify_loaded` as
     `verified`.
   - **The trace:**
     - its `result` events match `results` one to one: result ID, status and verification;
     - its `max_answer` text equals the answer statements;
     - its trace ID is the report's.
7. **Must-clarify case (F08):**
   - it is sent back (`needs_clarification`), with empty `answer` and `results`;
   - no value is presented as the answer to what the question left open (that would be X).

**X, incorrect shown,** anywhere in the answer as shown: headline, answer, summary, findings, explanations, uncertainties,
and the observations of a fallback.
- **On maximum cases:**
  - a wrong value or interval for the requested maximum;
  - another measure, window or region presented as the requested maximum;
  - a highest value held (not established) presented as the maximum;
  - an unadmitted result's value, or an observation, presented as the requested maximum or as verified;
  - an interpretation that contradicts the computed answer.
- **On F08:** a value presented as the answer to what the question left open.
- **On regression controls,** as in the targeted check:
  - a wrong value-and-time pair;
  - another forecast run presented as the one asked for;
  - for R03, a substitute run's values or an actual not public by the cutoff.

## Measures (reported separately; not gates)
- **Coverage:** cases saved out of 16, and reviews done out of 16 per reviewer, reported apart from the verdict.
- **Result availability:**
  - **What counts:** the answerable maximum cases, out of 11, with a correct verified result: an admitted result
    matching gold, whatever the fallback status.
  - **Misses, attributed:** sent back by routing; a response that did not finish; window not pinned (unavailable
    result); tool error; not admitted; stopped; other.
- **Interpretation quality,** per case with a computed answer:
  - the interpretation status;
  - repair attempted;
  - validation codes before repair and shown;
  - firings of `REQUESTED_RESULT_NOT_VERIFIED` and `REQUESTED_MAXIMUM_*`;
  - each reviewer's note on whether the interpretation is consistent with the computed answer, hedged where it should
    be, and useful.
- **Overall usability,** per case:
  - **S, supplied:** a usable answer, not a fallback, with a validated interpretation, whose shown text gives the
    correct result. On a not-established result, it says no maximum is established and gives the highest value held
    only as that. For D03 and D04 the price part must also be right.
  - **U, unavailable:** it says explicitly that the requested item cannot be supplied, and nothing stands in for it.
  - **C, clarification:** sent back with a specific question.
  - **F, facts only:** the facts-only fallback, or a report with no valid interpretation (`absent`). Never S.
  - **X:** as defined above.
  - **"Correct result shown":** whether the shown answer gives the correct result, counted apart from S (a fallback
    can show it).
- **Regression controls' answer quality:**
  - each one's outcome against its expected one (R01, R02, R04 S; R03 U);
  - its gold items given correctly, by the merged review, with the automatic gold-number hits as an aid;
  - its format (criterion 4).

  An X is a criterion 1 failure. Any other miss is reported, not gating.
- **Per case:** model calls, tokens, ledger cost, latency and the trace ID.

## Verdict (clarification 2)
1. **FAIL** if any completed case shows a violation of any criterion 1–7, whatever the coverage.
2. Otherwise **INCOMPLETE** if any case did not complete, or either review of any case is missing.
3. Otherwise **INCONCLUSIVE** if fewer than **8 of the 11** answerable maximum cases produced the correct verified
   result.
4. Otherwise **PASS.**

Coverage (cases saved; reviews done) is printed next to the verdict, never folded into it.

## Reviews
- **Readers:** the developer and an independent reviewer, a fresh agent given only the review kit and
  `REVIEW_BRIEF.md`.
- **What each records, per case:**
  - the outcome (S, U, C, F or X);
  - manual H2 and H4 counts;
  - whether the correct result is shown;
  - whether an unadmitted value or an observation is presented as the requested maximum or as verified;
  - whether the interpretation contradicts the computed answer;
  - for regression controls, each gold item given correctly or not;
  - a note on interpretation quality.
- **Blind:** the independent reviewer's sheet names answers A01–A16 in the frozen shuffled order, without case IDs or
  groups.
- **Stricter reading prevails:**
  - the more severe outcome (S < C < U < F < X);
  - the larger H counts;
  - any flagged violation;
  - "correct result shown" only if both say so.

  Disagreements are listed.

## Caps (exact; `FREEZE.json` holds them and `freeze.py` checks them)
- **Starting ledger:** the real ledger, `artifacts/live_budget/ledger.jsonl`. At the first start, its total, line
  count and SHA-256 prefix must equal the frozen ones: USD 8.52205, 2,905 lines, `e8bcc3be401caec5`.
- **Per case:** USD 0.15. `freeze.py` checks it holds the repair reservation plus twice the largest gpt-5-mini spend
  before repair seen in the saved end-to-end traces.

| Run | Cases | Case cap (USD) | Run cap (USD) |
|---|---|---|---|
| D (development) | 4 | 0.15 | 0.60 |
| F (fresh) | 8 | 0.15 | 1.20 |
| R (regression controls) | 4 | 0.15 | 0.60 |
| **Total** | 16 | | **2.40** |

- **Required approved task cap:** 8.52205 + 2.40 = **USD 10.92205**. The standing configured cap (USD 5.00) is
  already exceeded, so nothing runs without the owner's explicit approval of this cap.
- **Expected spend:** about USD 0.50 (likely 0.40–0.80). That assumes about 15 answered cases at about USD 0.035
  each (the gpt-5-mini mean in the development comparison), and a send-back at about USD 0.004.
- **Per call** (unchanged, `nem_agent.budget`): a call is refused when spent plus reserved plus its worst case would
  exceed the case's ledger cap. That cap is the ledger total at the case's start plus USD 0.15. The session budget is
  the same USD 0.15.
- **Start guard:** a case starts only if both hold:
  - its run's spend so far plus 0.15 is within the run cap;
  - the ledger total plus 0.15 is within the approved task cap.

## Stops, interruption and refusals
- **Stops:** any of these ends the check, and what was not run makes it INCOMPLETE:
  - a budget stop;
  - an API error or timeout;
  - a missing record;
  - an automatic H1 failure (a safety stop);
  - a change to frozen files or `src/`.
- **No retries for results:** no case is retried or repeated because of its result. A response that did not finish
  is an outcome, not an error.
- **Interruption:** re-run the same command.
  - Saved cases are never re-run.
  - The case in flight is re-run once from scratch, and its cost stays counted against its run.
  - A case in flight at a second interruption is not started again (INCOMPLETE).
- **Refusals:** the runner refuses to start in any of these situations:
  - the lock is held;
  - frozen files or `src/` differ;
  - the plan does not match the cases;
  - the record directory holds records the log does not account for;
  - the caller sets a ledger, cap, price or model override;
  - the prompt version differs;
  - no API key is set (it is never read or printed);
  - the approved task cap is below USD 10.92205;
  - at the first start, the ledger is not the frozen one; at a resume, it is below its last recorded value;
  - the check has ended, or ended with a safety stop.

## Records
- **Run log:** `artifacts/live/LC-maxima/run_log.jsonl`.
- **Records:** `artifacts/live/LC-maxima-run/<case>.json`, with each case's standard output and its trace under
  `traces/`.
- **Scoring:** `score.py` scores offline and never calls a model.
  - `--measures`: the automatic fields and criteria;
  - `--sheet DIR`: the developer's and the blind review sheets;
  - `--review DEV.json --review IND.json`: the verdict.

## Limitations
- **Familiar data:** 29 July 2026 is the only fully held day for 5-minute total demand, and it was used by K09, K11
  and Z04. The fresh questions are new wording on familiar data.
- **Small sample:** one execution per case, so no rates, and differences of one or two cases are within run-to-run
  variation.
- **Revisions:** October 2025 and April 2026 hold only the next-day revision. So no case has a cutoff that falls
  between a half-hour's `initial` and `updated` revisions; gold's rule for that is tested offline only. This note was
  added after the questions were written.
- **Ties:** there are none in any eligible whole-day window. Unless gold finds one in an explicit or event window, tie
  handling stays covered by offline tests only.
- **Independence:** the writer, the gold checker and the independent reviewer are LLM agents. Their independence is
  by instruction and kit separation, and they report what they read.
- **Lexical checks:** the validator's text checks stay lexical. Complete semantic containment is not claimed.
- **Known misses:** routing truncation and over-clarification, queued separately, may lower availability without any
  criterion being violated.
