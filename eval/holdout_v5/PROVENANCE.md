# Held-out set v5: provenance

- **File:** `eval/holdout_v5/cases.json`, 20 cases (Y01–Y20), SHA-256 `c33a06a372c15f8c7442a7f9fcf4814c45c15162bbfa7904ad828afec19b4ca3`.
- **Frozen:** 2026-10-01, before any Live run on it. It will not be edited after results are seen.
- **Cases with gold labels:** G = 18, so the Q3 bar is ⌈0.8 × 18⌉ = 15. `score.py --gold` confirms it from
  the file, and `run_eval.py` refuses to start if it differs from `FREEZE.json`.
- **Not run:** no paid call has been made for this set or the regression.

## Order of work

1. **Pass rule and relevance rubric committed and pushed before the writer started:** `dd7422e`,
   2026-10-01T06:13:53Z.
2. **Kit built** outside the repository: 06:16Z.
3. **Writer started** after the kit was built. Its case file was last written at 06:26Z.
4. **Verifier started** after the writer finished.
5. **Rule and rubric completed** in the freeze commit, without reading any case (see "Changes after the writer
   started").
6. **Blind check, overlap counts and freeze.**

## Writer

A fresh subagent with no conversation history, working only inside a kit directory outside the repository.

**The kit contained:**
- `BRIEF.md` (copied here; SHA-256 `c652529e…`): v4's brief, with only the file name, version, ID prefix and split
  changed (`holdout_v5`, Y01–Y20, same category mix);
- `DATA.md`, byte-identical to v4's (`22276efd…`);
- copies of the pinned data store (seven tables, including weather) and `corpus.sqlite`, byte-identical to the
  repository's;
- `events.json`: the 8 verified events and the analysis thresholds;
- a fresh Python environment with only `duckdb` and `pytz` (the project package cannot be imported);
- `overlap/`: SHA-256 hashes of every 6-word sequence in the 98 earlier questions and in prompts v11, with a checker.
  The questions are 40 in `eval/cases.json`, 14 in held-out v2, 20 in v3, 20 in v4 and 4 in the 2026-09-29 check.

**Not in the kit:**
- the repository, its code, prompts and analyses;
- the issue tracker and any fix-specific analysis;
- any Live output or trace;
- the text of any earlier question.

**How the writer worked:**
- It listed every file it read and every command it ran, all inside the kit. It did not open the hash file.
- It added one build script of its own, `work/build_cases.py`, which runs its gold SQL and builds the cases.
- **Wording check:**
  - the first run flagged 13 cases;
  - after rewording (same region, date or time, measure and gold), a second run flagged 4;
  - the third run printed `cases with overlap: none`.
- **Mix:** 4 market_event, 4 forecast (2 as-of; Y08 also asks about weather), 4 document, 3 notice,
  2 ambiguous_unavailable (Y16 clarification, Y17 refusal), 2 adversarial, 1 injection.

## Independent gold check

A second fresh subagent checked the set with its own queries. It worked under the same kit-only rules, and was
barred from the writer's build script (`work/`) and from `overlap/`.
- **Numbers:** it re-derived every gold value. That covered 18 row-backed numbers, each confirmed by `row_id`,
  region, time and value as the right row (the window's peak or minimum, the latest revision, the designated or
  as-of forecast run).
- **Interval counts:** it recounted the 3 interval counts under several window conventions.
- **Citations:** it checked the 8 citation snippets verbatim and read each passage.
- **As-of and expected fields:** it checked the as-of cutoffs against `available_at_utc`, and every expected field
  against the brief.
- **The writer's flags:** it checked each one, by case ID.
- **Result: 20/20 PASS**, with no revision needed. The verdicts and notes are in `VERIFICATION.json` (SHA-256
  `d7407bb9…`).
- **Access:** it listed every file it read, all inside the kit. It did not open `work/` or `overlap/`.
- **Notes, not faults:**
  - **Y01:** a market-time or local calendar day would give a different count, but the question limits the count to
    the event window.
  - **Y06:** the wording is less explicit than Y05's. A publication-time reading would pick a different run.
  - **Y07:** the half-hour has no date, but only one target fits before the cutoff.
  - **Y10:** the snippet covers one of two terms, and the passage covers both.
  - **Y18:** "due to" in a hedge outside the hypotheses would count as a causal violation, as in every earlier
    round.

## Blind compatibility check by the developer (counts and IDs only)

```
python scripts/blind_check_heldout.py eval/holdout_v5/cases.json --split holdout_v5 \
  --prior eval/cases.json eval/holdout_v2/cases.json eval/holdout_v3/cases.json eval/holdout_v4/cases.json \
  eval/live_check_2026_09_29/cases.json --prompts src/nem_agent/prompts/v11
```

- **Mix:** as required (4/4/4/3/2/2/1), with IDs Y01–Y20 and split `holdout_v5`.
- **Gold numbers:** 18/18 row-backed numbers resolve in the repository's store with their values, plus 3 derived
  counts.
- **Gold citations:** 8/8 snippets are verbatim in the repository's index.
- **G = 18**, so the Q3 bar is 15. There are 2 as-of forecast cases.
- **Expected statuses:** 18 answered or answered with caveats, 1 needs clarification, 1 refused.
- **Requests:** every case builds a request.
- **Wording:** no 6-word overlap with the 98 earlier questions or prompts v11, and no exact duplicate.
- **`PROBLEMS: none`.**

**The developer did not read the questions, labels or gold values** before freezing, and will not before the run.
- **What the developer saw:** the writer's and verifier's final reports, which give case IDs, categories and short
  reasons, and the counts above.
- **What the developer copied:** the case file, by `cp`, checked by SHA-256 only.

## Points flagged for the human reviewer (by case ID)

- **Y01, Y02, Y04:** the interval counts cover the event window. The verifier found Y02's and Y04's counts the same
  under every convention, and Y01's the same under every window convention.
- **Y03:** the gold price row is "NOT FIRM", but it is the only row for its interval. Notices say the prices were
  reviewed and left unchanged, and an answer that says so is correct.
- **Y05, Y06:** the forecast run is designated by issue time (not an as-of question). Y06's wording is less explicit.
- **Y07:** an as-of case whose target half-hour is given without a date.
- **Y08:** as-of, and also asks about weather. It carries `no_retrospective_evidence`, and no weather was public by
  the cutoff.
- **Y12:** the procedure list has a single trigger to report.
- **Y14:** the same sentence also appears in a notice for another region and date. The cited notice is the right one.
- **Y16:** needs clarification per the brief, because it names two regions, although the data covers both.
- **Y18, Y19:** `must_not_contain` is the brief's list. Y18's check sentence includes the cancellation of the day's
  forecast lack-of-reserve notices.
- **Y20:**
  - its `must_not_contain` adds fragments of the injection text to the brief's list;
  - its gold snippet is long (269 characters), because shorter phrases also appear in another passage of the same
    document.

**The developer's knowledge:** the reports above were read by the developer. Beyond case IDs and categories, they
named the notices the verifier checked for Y03 and the location of Y08's weather. They quoted no question and
stated no gold value.

## Changes after the writer started

The rule and rubric were committed in `dd7422e` before the writer started. They were completed in the freeze commit
without reading any case. The changes concern only how the runs are recorded and measured. No bar, threshold, cap or
case changed.
- **Per-case process:** `run_case.py` runs `scripts/live_diagnose.py` unchanged, and also keeps
  `ruled_out_explanations` and the display record in the saved record. The standard record predates PR #36 and omits
  them.
- **H1–H5 restated as the first L3 gate measured them** (`docs/live-gates.md`, "Hard gate"):
  - **H1:** the dd7422e draft said "forbidden calls executed"; it now counts blocked attempts too, as in v4.
  - **H2, H3, H4:** measured by the named validation codes in the shown answer, plus `causal_violations` where the
    case defines it.
  - **Manual checks:** the reviewer's causal check and number check.
  - **Why:** the dd7422e draft had read H2 as a causal-phrase count over every answer, and H4 as claim violations
    only. The phrase count is now reported for the reviewer's attention and does not gate.
  - **Prompt for the review:** the writer's flags (Y18, Y19: `must_not_contain` and a negated "caused by").
- **The regression's H checks:** the reviewer reads its 18 answers for the causal and number checks, with no relevance
  labels.
- **Refusals:**
  - G must match the frozen value;
  - **ledger, at the regression's start:** the total must equal v5's recorded end;
  - **ledger, at a resume:** the total must not be below the run's last recorded value;
  - **approved task cap:** must be at least 5.760384 for v5 alone, or 6.560384 for both runs.
- **Interruption details:**
  - a case that saved its record before a kill is finished, not re-run;
  - the run cap stays as fixed at the first start.

## Overlap with earlier sets and development (unavoidable)

**Same events, data and documents.** v5 uses the same pinned data store and the same document corpus as every
earlier set and all development work.
- **Why this is unavoidable:** the store is pinned to late July–August 2026, and only these 8 events are verified.
  New events would need new source pins, which are frozen.
- **Events:** v5 uses 7 of the 8 events, and every one was used by earlier cases:

  | Event | v5 cases | earlier cases |
  | --- | --- | --- |
  | NSW1-20260731T0730-hi | 3 | 7 |
  | SA1-20260729T1755-hi | 2 | 4 |
  | SA1-20260731T0235-hi | 2 | 11 |
  | TAS1-20260731T0730-hi | 1 | 1 |
  | TAS1-20260806T1300-hi | 2 | 4 |
  | VIC1-20260728T2120-lo | 2 | 5 |
  | VIC1-20260820T0910-hi | 2 | 6 |
  | documents | 6 | – |
- **Gold documents:** 6 distinct (3 market notices, 1 definition document, 2 procedures). **All 6** were gold
  documents of earlier cases.
- **Gold rows:** 18 distinct row-backed gold numbers. **12** were gold rows of earlier cases.

**Overlap with this improvement cycle's development material.** The fixes of this improvement cycle (up to PR #36) were developed and checked
on the Live records of W04, W18, W19, W20 and F01–F04.
- **Events:** **9** of v5's 14 event-based cases are on events those cases used (NSW1-20260731T0730-hi,
  SA1-20260729T1755-hi, SA1-20260731T0235-hi, VIC1-20260820T0910-hi).
- **Documents:** **4** of v5's 8 gold citations are from documents those cases cited as gold.

**No overlap in the questions:** they are new, written blind, with no 6-word overlap with any earlier question or
prompts v11.

**What this means:** v5 tests new questions about data and documents that development has already seen. It does not
test new events, new documents or new periods. A PASS would support "the current version answers new questions
about this pinned data acceptably". It would not show generalisation beyond it.

## Regression set

`REGRESSION.json`: the 18 cases of the v3 round's regression, in that round's order.
- **The cases:** H01–H14 (former held-out v2) and ADV02, ADV04, DOC04 and EV09 (`eval/cases.json`).
- **Their status:** all are development data, used and inspected during development.
- **What they measure:** they gate only H1–H5 and are not quality evidence.
- **Earlier result:** on the v3-round code they completed with no H1–H5 violation. `score.py` reproduces H1–H5 = 0 from
  those records (`artifacts/live/L3v3-regression-{a,b}/`).
