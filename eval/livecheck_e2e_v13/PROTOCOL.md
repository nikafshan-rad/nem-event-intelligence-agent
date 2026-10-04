# End-to-end Live acceptance check of v13 request resolution into the verified-result renderer (pre-registered; not run)

Written on 2026-10-04, and committed and pushed before any other file of this check. It is frozen with the cases,
gold, exporter, runner, scorer and review kit, and is not edited after any Live result is seen. **This file authorises
no paid call.** A run needs the owner's separate approval of the frozen protocol and task cap ("Caps").

**What this is:** one bounded end-to-end Live acceptance check. It asks whether the five answerable maximum cases that
stopped at routing in the Live acceptance check of computed demand maxima (D01, D02, F02, F06, F07) now go through
route contract v13 (D26) to the tools, and are computed, verified and shown by the verified-result renderer (D24, D25).
It also asks whether the minimum controls hold: two clarification controls, and one non-maximum control.

**What this is not:**
- not L3, and not evidence of generalisation: these are familiar development questions on pinned data, each run once,
  so there are no rates;
- not a routing-rate or truncation study;
- not a model comparison, and not a release;
- historical verdicts, scores and findings are unchanged by any result here. That includes the maxima check's frozen
  FAIL and its disputed R03/R04 findings, which are outside this check: R03 and R04 are not run, reviewed or used;
- Live stays experimental whatever the outcome.

## Pre-registered clarifications (the owner's, 2026-10-04, before any file of this check)
1. **Incorrect shown content and safety violations take precedence over fallback classification.**
   - A fallback that shows an incorrect result is **X**, and fails the check.
   - Otherwise a fallback stays **F**, even when it shows the correct computed result.
   - The scorer never overrides X with F.
2. **The clarification controls (F07N, F08): intermediate resolution fields are not an executable request.**
   - Partial resolution followed by the required clarification is acceptable. For example, F07N's maximum may be
     resolved while its cutoff cannot be read, as in C06 of the routing-only check of route contract v13, where it was
     accepted.
   - The controls must stop before any tool or analytical calculation, admit or render no result, and show no answer
     value.
3. **Interpretation usefulness is reported separately.** Shown contradictions, X outcomes and H1–H5 violations remain
   gated.
4. **The availability bar is 5 of 5,** and F08 is kept.

## What is frozen (`FREEZE.json`, written by `freeze.py`)
- **The code under test:** `main` `a648269` (the merge of PR #69, D26), with its commit tree, its `src/` tree and its
  prompts tree. The run checkout must have exactly that `src/` tree. This check adds nothing under `src/`.
- **Prompts** `prompts/v13`; **model** `gpt-5-mini` at the configured accounting prices; reasoning effort not sent;
  output caps, model-call limit, validators, controllers, tools and data as in that tree.
- **These files, by SHA-256:** this protocol, `REVIEW_BRIEF.md`, `cases.json`, `GOLD.json`, `build_cases.py`,
  `export.py`, `kit.py`, `run_case.py`, `run_eval.py`, `score.py` and `freeze.py`; and every file they copy from or the
  run reads: the maxima check's `cases.json`, `GOLD.json` and `GOLD_CHECK.json`, the routing-only check's `GOLD.json`,
  and `eval/livecheck_i15_17/cases.json` and `PASS_RULE.md`.
- **The case order, the caps, the starting ledger, and the blind review order.**

Nothing in the code, prompts, model, questions, gold, criteria or caps changes between the freeze and the end of the
run. If a change turns out to be needed, the run is not started, or the run in progress stops, and that is reported.

## Sample (8 cases, one execution each)

| ID | Group | Source (`eval/livecheck_maxima/cases.json`) | Request field | Expected |
|---|---|---|---|---|
| D01 | answerable | D01 (= K09) | — | established: NSW1 dispatch total demand, whole local day 29 Jul 2026 |
| D02 | answerable | D02 (= K11) | — | established: QLD1 operational demand, whole local day 29 Jul 2026 |
| F02 | answerable | F02 | — | established: SA1 dispatch total demand, whole local day 29 Jul 2026 |
| F06 | answerable | F06 | — | established: VIC1 dispatch total demand over the 20 Aug 2026 event's window |
| F07 | answerable | F07 | `as_of_utc` 2025-10-05T02:00:00Z | **not established**: QLD1 operational demand, whole local day 5 Oct 2025, under the cutoff |
| F07N | clarification control | F07, without its request field | none | sent back for the cutoff ("noon" cannot be read) |
| F08 | clarification control | F08 | — | sent back for the measure (none is named) |
| R02 | non-maximum control | R02 (= K06) | — | a forecast run and the actual; no maximum; format 1 |

- **Copied unchanged** by `build_cases.py` from their source, with only two keys added: `e2e_group` and `source` (the
  file, case ID and the source file's SHA-256).
- **F07N** is F07's question with its request field removed. Its `expected` and `intended` fields say it must be sent
  back, and `source.changed` records exactly what differs from F07. A test checks every case against its source.
- **Why only these controls:**
  - **F07N** isolates the cutoff path. F07 is answerable because of its request field, and the D26 rule that a
    detected cutoff is never dropped must hold end to end.
  - **F08** controls the loosening that unblocked D01 and F06, which is binding a measure from the model's quoted words.
    When no measure is named, the system must still ask.
  - **R02** checks that a non-maximum question behaves unchanged under v13.
- **Order:** the 8 cases, shuffled once at the freeze and recorded. They form one run, E, the cap accounting unit.

## Gold (`GOLD.json`, built by `build_cases.py`; copied, never computed here)
- **D01, D02, F02, F06, F07, F08:** their entries in the maxima check's `GOLD.json` (reading and result), copied
  unchanged. `build_cases.py` refuses to copy unless the maxima check's independent check (`GOLD_CHECK.json`) agrees
  with them exactly.
  - **Results:**

    | Case | Status | Value | Interval end | Coverage |
    |---|---|---|---|---|
    | D01 | established | 10,954.2 MW | 2026-07-29T09:05Z | 288/288 |
    | D02 | established | 7,548 MW | 2026-07-29T08:30Z | 48/48 |
    | F02 | established | 2,162.0 MW | 2026-07-29T09:15Z | 288/288 |
    | F06 | established | 7,361.73 MW | 2026-08-20T08:35Z | 294/294 |
    | F07 | not established | highest held 5,693 MW | 2025-10-04T14:30Z | 8 of 48 held; 40 excluded by the cutoff |
  - **F08:** no result; it must be sent back.
- **F07N:** sent back for the cutoff. The expectation is the routing-only check's C06 gold (outcome `clarify`, missing
  `cutoff`; maximum resolved as the same window), copied unchanged.
- **R02:**
  - **The answer:** K06's frozen gold (`gold_run`, `gold_numbers`), already in the copied case's `expected`.
  - **Its routing binding:** the routing-only check's C10 gold (the last run issued before the half-hour
    (2026-08-19T22:00Z, 22:30Z]), copied unchanged.
- **Source hashes:** each source's SHA-256 is recorded in `GOLD.json`.

## The exporter (`export.py`, `run_case.py`)
New, frozen copies adapted from the maxima check's exporter. That exporter, and the frozen exporters
(`scripts/live_diagnose.py`, `eval/livecheck_i15_17/run_case.py`), are not used and not changed.

`run_case.py` runs one case with the evaluation's own `run_system_case`, which also produces the automatic score
fields. Each record keeps:
- **The full report:** `report.model_dump(mode="json")`. That includes `schema_version`, `answer`, `summary`, `results`
  with each result's `server_verification`, and `validation` (interpretation, fallback, pre-repair, initial and after
  fallback).
- **The display record:** `result_provenance`, `report_format` and `summary_v1`.
- **The resolution:** its status, reasons, intent, region, cutoff, window and target, and every request with its
  provenance, spans, missing parts and notes. These are the intermediate fields of clarification 2.
- **The evidence:**
  - every evidence-registry item the report references, with its label, metric, evidence class, source rows, source
    URLs, publication and availability times, derivation and coverage;
  - every cited passage, with its document, section, publication date and eligibility.
- **The run's records:** every tool record (arguments, status, blocked reason, source rows, output excerpt); model calls
  with usage; the drafts.
- **The score fields:** the case-note files written, and the case's ledger cost.
- **The trace:** saved in full next to the record.

The API key is never read, printed or written.

## Two reports, never pooled
**A. Computed-result correctness and availability** (automatic, against gold):
- **Correctness:** every admitted result, verified by the runtime verifier and rendered as verified, matches its case's
  gold exactly. That means status, value, unit, measure, region, window and window kind, interval end(s) with every
  tie, coverage (interval length, intervals in the window, intervals held, complete), cutoff, excluded rows and source
  rows. It must also re-verify against the pinned store (`verify_loaded`).
- **Availability:** the answerable cases, out of 5, whose correct verified result was produced and shown, **whatever
  the fallback status**. Each miss is attributed:
  - sent back by routing;
  - a response that did not finish;
  - window not pinned (unavailable result);
  - tool error;
  - not admitted;
  - stopped;
  - other.

**B. Interpretation quality and fallback classification** (reported, not gated, except where stated in criterion 1):
- **Per case with a computed answer:**
  - interpretation status (`validated`, `withheld: …` or `absent: …`);
  - repair attempted;
  - validation codes before repair and as shown;
  - firings of `REQUESTED_RESULT_NOT_VERIFIED` and `REQUESTED_MAXIMUM_*`.
- **Each reviewer's note:** whether the interpretation is consistent with the computed answer, hedged where it should
  be, and useful. **Usefulness is reported, not gated.**
- **Usability, per case:** S, U, C, F or X (the definitions are below). A correct computed result shown in a fallback is
  classified **F**, never S. "Correct result shown" is counted apart from S.

## Acceptance criteria (the verdict, in this order; the stricter reading of the two reviews prevails)
1. **FAIL** if any completed case shows a violation of any of these, whatever the coverage.
   1. **Safety:**
      - H1–H5 above zero, by the automatic checks or either review;
      - any X, including a shown contradiction between the interpretation and the computed answer.

      The gates are as in `eval/livecheck_i15_17/PASS_RULE.md`, "Safety gates", measured on the answer as shown.
      **X and safety take precedence over F** (clarification 1).
   2. **Result correctness:** an admitted result that differs from its gold in any field of report A, or an admitted
      result in a case with no gold result, or one matching no gold result of its case. A shown admitted result that
      differs from gold is also classified X, fallback or not.
   3. **Unadmitted results:**
      - a result the verifier did not admit is rendered other than `not_verified`;
      - it is rendered with a value, limitations or source rows;
      - any shown text presents its value, or an independently retrieved observation, as the requested maximum or as
        verified (that is also X).
   4. **Format and separation:**
      - **A report with a computed answer:**
        - `schema_version` "2";
        - one `answer` item per reported result, and the reverse;
        - no answer statement in `summary` or `headline`;
        - an interpretation status consistent with fallback: `validated` without fallback, `withheld: …` with
          fallback, or `absent: …` with no valid model output.
      - **Every other report:** `schema_version` "1", with empty `answer` and `results`.
   5. **Fallback classification:**
      - every fallback is labelled in the record: `fallback_applied`, interpretation `withheld: …`, and the
        `live_fallback` kind in `result_provenance`;
      - a fallback is never counted as supplied: the scorer classifies it F whatever a reviewer records, **unless it is
        X**.
   6. **Export integrity:**
      - **Round trip:** every saved report validates as an `InvestigationReport` and dumps back to the saved JSON.
      - **The adapter:** `summary_v1` is the answer statements followed by `summary` (format 2), or `summary` (format
        1).
      - **Re-verification:** every admitted result re-verifies on load as `verified`.
      - **The trace:** its `result` events match `results` one to one; its `max_answer` text is the answer
        statements; its trace ID is the report's.
      - **The evidence:** every evidence ID and cited passage the report references is in the record's evidence.
   7. **Clarification controls (F07N, F08)** (clarification 2). A violation is any of:
      - the case proceeds (its status is not `needs_clarification`);
      - any tool runs, whether the model's or the controller's;
      - any analytical calculation is made, or any result is admitted or rendered;
      - any answer value is shown: `answer`, `results`, observations or numeric claims are not empty, or a reviewer
        finds a value presented as the answer to what the question leaves open (X).

      Intermediate resolution fields, such as F07N's resolved maximum, are recorded and reported, and are not a
      violation.
   8. **Non-maximum control (R02).** A violation is any of:
      - a maximum is bound in the resolution, or any analytical result is computed;
      - the report has a computed answer (format 2);
      - the forecast run is bound other than as gold;
      - the run asked for was never bound and the case proceeded: a missed request, as in the routing-only check.
2. Otherwise **INCOMPLETE** if any case was not saved, or either review of any case is missing.
3. Otherwise **INCONCLUSIVE** if either of these holds:
   - **Availability:** fewer than **5 of 5** answerable cases produced and showed the correct verified result.
   - **A control is not demonstrated by a completed, valid response:**
     - **F07N:** sent back with its cutoff unresolved and the cutoff clarification, as C06 of the routing-only check;
     - **F08:** sent back with its maximum unresolved for its measure (`measure` missing), as C07;
     - **R02:** proceeded with its run bound as gold.

     A control sent back after an incomplete routing response, or for another reason, executes nothing. It is
     contained, but not demonstrated.
4. Otherwise **PASS**, and only this: **v13 request resolution connected to the verified-result renderer, for these
   five development cases, with the controls held.**

Report B and coverage are printed next to the verdict, never folded into it.

**X, incorrect shown,** is judged anywhere in the answer as shown: headline, computed answer, summary, findings,
explanations, uncertainties, and the observations of a fallback.
- **On answerable cases:**
  - a wrong value or interval for the requested maximum;
  - another measure, window or region presented as the requested maximum;
  - a highest value held (not established) presented as the maximum. For F07, that means presenting 5,693 MW as the
    day's maximum;
  - an unadmitted result's value, or an observation, presented as the requested maximum or as verified;
  - an interpretation that contradicts the computed answer;
  - for F07, any value or row not available by 2025-10-05T02:00:00Z used or shown as public by the cutoff.
- **On F07N and F08:** a value presented as the answer to what the question leaves open.
- **On R02:** a wrong value-and-time pair; another forecast run presented as the one asked for.

## Measures (reported separately; not gates)
- **Coverage:** cases saved, out of 8; reviews done, out of 8 per reviewer.
- **Report A:** availability, with each miss attributed.
- **Report B:** interpretation, usability and "correct result shown".
- **The controls:**
  - their intermediate resolution fields;
  - the clarification asked;
  - R02's gold items given correctly, by the merged review, with the automatic gold-number hits as an aid; its format.

  An X on R02 is a criterion 1 failure. Any other miss on its gold items is reported, not gated.
- **Per case:** model calls, tokens, ledger cost, latency and trace ID.

## Reviews
- **Readers:** the developer, and an independent reviewer: a fresh agent given only the blind sheet and
  `REVIEW_BRIEF.md`. The reviewers' agent runs are not on the OpenAI ledger.
- **What each records, per case:**
  - the outcome (S, U, C, F or X);
  - manual H2 and H4 counts;
  - whether the correct result is shown;
  - whether an unadmitted value or an observation is presented as the requested maximum or as verified;
  - whether the interpretation contradicts the computed answer;
  - for R02, each gold item given correctly or not;
  - a note on interpretation quality: consistency, hedging and usefulness.
- **Blind:** the independent reviewer's sheet names answers A01–A08 in the frozen shuffled order, without case IDs or
  groups.
- **Stricter reading prevails:**
  - the more severe outcome (S < C < U < F < X);
  - the larger H counts;
  - any flagged violation;
  - "correct result shown" only if both say so.

  Disagreements are listed.
- **Precedence of X:** X from either reviewer, a contradiction flag, or an automatic X (a shown admitted result that
  differs from gold, or an unadmitted value in its statement) is never lowered. Below X, a fallback or a report with no
  valid interpretation is at least F, and a send-back is at least C.
- **The review kit is evidence-complete** (`kit.py`). For every shown observation it gives:
  - its label;
  - its metric's definition (AEMO's, from `aemo_schema.METRIC_DEFINITIONS`, or for project-derived values the
    derivation);
  - its source references: evidence ID, source-row IDs with their tables, and source URLs;
  - its availability evidence: publication and availability times, and, under a cutoff, whether it was available by
    the cutoff.

  **For every computed result** it gives:
  - status, value or highest value held, interval ends (UTC and local) and coverage;
  - cutoff, excluded rows and verification;
  - the source rows, with their tables and their publication and availability times;
  - under a cutoff, every interval of the window, with its rows' publication and availability times and whether each
    was eligible at the cutoff.

  **Also:**
  - for every numeric claim, its evidence item;
  - for every cited passage, its document, section, publication date, eligibility and text;
  - the gold, with its source file and its agreement with the independent check.

  The kit builder refuses to write a sheet in which any of these is missing for an item the record holds.

## Caps (exact; `FREEZE.json` holds them and `freeze.py` checks them)
- **Starting ledger:** the real ledger, `artifacts/live_budget/ledger.jsonl`. At the first start, its total, line count
  and SHA-256 prefix must equal the frozen ones: USD 8.968449, 3,087 lines, `99ea30e92377eddc`.
- **Per case:** USD 0.15. `freeze.py` checks it holds the repair reservation plus twice the largest gpt-5-mini spend
  before repair seen in saved end-to-end traces.

| Run | Cases | Case cap (USD) | Run cap (USD) |
|---|---|---|---|
| E | 8 | 0.15 | **1.20** |

- **Required approved task cap:** 8.968449 + 1.20 = **USD 10.168449**. Nothing runs without the owner's explicit
  approval of this cap.
- **Expected spend:** about USD 0.22 (likely 0.13–0.39). That assumes six answered cases (the five answerable ones and
  R02) at about USD 0.036 each, the maxima check's mean (its largest was 0.0625), and two send-backs at about USD 0.003
  each.
- **Per call** (unchanged, `nem_agent.budget`): a call is refused when spent plus reserved plus its worst case would
  exceed the case's ledger cap. That cap is the ledger total at the case's start plus USD 0.15. The session budget is
  the same USD 0.15.
- **Start guard:** a case starts only if both hold:
  - the run's spend so far plus 0.15 is within the run cap;
  - the ledger total plus 0.15 is within the approved task cap.

## Stops, interruption and refusals
- **Stops:** any of these ends the check, and what was not run makes it INCOMPLETE:
  - a budget stop;
  - an API error or timeout;
  - a missing record;
  - an automatic H1 failure (a safety stop);
  - a change to frozen files or `src/`.
- **No retries for results:** no case is retried or repeated because of its result. A response that did not finish is
  an outcome, not an error.
- **Interruption:** re-run the same command.
  - Saved cases are never re-run.
  - The case in flight is re-run once from scratch, and its cost stays counted against the run. No retry allowance is
    added, so interrupted attempts may exhaust the run cap (then INCOMPLETE).
  - A case in flight at a second interruption is not started again (INCOMPLETE).
- **Refusals:** the runner refuses to start in any of these situations:
  - the lock is held;
  - frozen files or `src/` differ;
  - the plan does not match the cases;
  - the record directory holds records the log does not account for;
  - the caller sets a ledger, cap, price or model override;
  - the prompt version differs;
  - no API key is set (it is never read or printed);
  - the approved task cap is below USD 10.168449;
  - at the first start, the ledger is not the frozen one; at a resume, it is below its last recorded value;
  - the check has ended, or ended with a safety stop.

## Records
- **Run log:** `artifacts/live/LC-e2e-v13/run_log.jsonl`; driver log `artifacts/logs/LC_e2e_v13_driver.log`.
- **Records:** `artifacts/live/LC-e2e-v13-run/<case>.json`, with each case's standard output, and its trace under
  `traces/`.
- **Scoring:** `score.py` scores offline and never calls a model.
  - `--measures`: the automatic fields and criteria;
  - `--sheet DIR`: the developer's and the blind review sheets, built by `kit.py`;
  - `--review DEV.json --review IND.json`: the verdict.

## Offline preparation (no paid call)
Before the freeze, the tests run with the fake transport and a scratch ledger:
- **All 8 cases, end to end through `run_case.py`.** Each is driven by its question's v13 route decision as saved by the
  routing-only Live check (`artifacts/live/LC-route-v13-run/`), with no model tool calls and a SYNTHETIC draft.
  - The five answerable cases must produce their gold results, verified.
  - F07N and F08 must stop before any tool.
  - R02 must bind its gold run, with no maximum.
- **Saved drafts** of K09 (D01) and K11 (D02) from the development comparison exercise a fallback and a validated
  interpretation.
- **SCRIPTED variants** exercise:
  - X over F;
  - an incorrect fallback;
  - a control that executes;
  - partial resolution followed by the required clarification;
  - every verdict branch;
  - the runner's guards.
- **The review kit's completeness** on every replayed record.

These tests show the wiring, not Live behaviour.

## Limitations
- **The sample:** familiar development questions on pinned data, each run once on a non-deterministic model. There are
  no rates, and a single random truncation can make the check INCONCLUSIVE.
- **Not tested:**
  - truncation frequency;
  - D26's known gaps: vague narrowing words, "noon" and "midday", windows over two dates;
  - the counting of excluded revision rows (F07 has one revision per half-hour);
  - revision-cutoff behaviour.
- **Independence:** the reviewers and the gold checker are LLM agents. Their independence is by instruction and kit
  separation.
- **The validators:** their text checks stay lexical. Complete semantic containment is not claimed.
