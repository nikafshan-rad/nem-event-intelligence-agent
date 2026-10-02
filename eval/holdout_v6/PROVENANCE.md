# Held-out set v6, development check and L3 regression: provenance

- **File:** `eval/holdout_v6/cases.json`, 20 cases (Z01–Z20), SHA-256
  `1c3467b478df7ad7a6e87104c30276a030a2de49252e75af04723fd2a9283da2`.
- **Frozen:** 2026-10-02, before any Live run on it. It will not be edited after results are seen.
- **Cases with gold labels:** G = 18 (every case except Z16 and Z17, the clarification and refusal cases), so the Q3
  bar is ⌈0.8 × 18⌉ = 15. `score.py --gold` confirms it from the file, and `run_eval.py` refuses to start if it differs
  from `FREEZE.json`.
- **Strata:**
  - **Unused (6):** Z04 (market_event, TAS1 on local 29 July 2026) and Z11–Z15 (notice; Z15 is the one routine
    price-review notice).
  - **Familiar (14):** Z01–Z03, Z05–Z10, Z16–Z20.
- **Not run:** no paid call has been made for runs A, B or C.

## Order of work

1. **Pass rule and relevance rubric committed and pushed before the writer started:** `3bf5baa`,
   2026-10-02T07:58:34Z.
2. **One amendment, still before the writer started:** `6fb0151`, 08:00:23Z. The unused pool's search is made at the
   frozen code commit `6413076`, because the proposal (PR #47) names the pool's region-day to define it.
3. **Kit built** outside the repository with `build_kit.py`: 08:02:22Z.
4. **Writer started** after the kit was built. Its case file was last written at 08:13:38Z.
5. **Verifier started** after the writer finished: 20/20 PASS, no revision.
6. **Blind check, provenance check and freeze.**

## Writer

A fresh subagent with no conversation history, working only inside a kit directory outside the repository.

**The kit contained** (`build_kit.py`; every copied file byte-identical to its source):
- `BRIEF.md` (copied here; SHA-256 `d05a4abc…`): v5's brief, changed for v6's mix, the IDs Z01–Z20, the split, and the
  two strata;
- `DATA.md` (copied here), byte-identical to v5's (`22276efd…`);
- copies of the pinned data store (seven tables, including weather) and `corpus.sqlite` (`221714ad…`);
- `events.json`: the 8 verified events and the analysis thresholds;
- `unused_pool.json` (`f1dc6ebd…`), from `provenance_check.py --pool`: 112 notices (87 routine) and the TAS1 day;
- a fresh Python environment with only `duckdb==1.5.5` and `pytz==2026.3.post1` (the project package cannot be
  imported);
- `overlap/`: SHA-256 hashes of every 6-word sequence in the 118 earlier questions and in prompts v11, with a checker.
  The questions are 40 in `eval/cases.json`, 14 in held-out v2, 20 each in v3, v4 and v5, and 4 in the 2026-09-29
  check.
- `VERIFY.md` (copied here; `cc3ec915…`), which the writer was told not to open.

**Not in the kit:**
- the repository, its code, prompts and analyses;
- the issue tracker and any fix-specific analysis;
- any Live output or trace;
- the text of any earlier question.

**How the writer worked** (from its report):
- **Its files:** every file it read and every command it ran was inside the kit. It did not open `VERIFY.md`,
  `MANIFEST.json`, `overlap/hashes.json` or the checker's source.
- **Its scripts,** in `work/`:
  - a query helper;
  - a build script that re-runs each case's recorded SQL and asserts every gold value and snippet;
  - rewording scripts;
  - a validator.
- **Wording check:** six runs, flagging 9, 4, 4 (a `--help` run, ignored), 1, 0 and 0 cases. To find which of its own
  phrases overlapped, a probe script temporarily wrote short fragments of its own flagged questions into the output
  file and ran the checker. That reveals only that a fragment of its own wording matched a hashed sequence; no earlier
  text was seen. The final file was then rebuilt.
- **One disclosure:** one command's output was too long, and the harness saved it automatically to a file under the
  home directory. The writer did not open that file, and re-read the content from its own copy in `work/`.
- **Mix:** 4 market_event, 3 forecast (2 as-of; Z07 also asks about weather), 3 document, 5 notice,
  2 ambiguous_unavailable (Z16 clarification, Z17 refusal), 2 adversarial, 1 injection.

## Independent gold check

A second fresh subagent checked the set with its own queries, under the same kit-only rules. It was barred from the
writer's working files (`work/`), `overlap/` and `MANIFEST.json`.
- **Numbers:** it re-derived every gold value: 14 row-backed numbers, by row, region, time and value, including peaks,
  minimums and ties.
- **Interval counts:** it recounted the 3 interval counts under 5 window conventions, and found the same counts under
  each.
- **Citations:** it checked the 9 snippets verbatim and read each passage.
- **As-of and expected fields:** it checked the as-of availability and every expected field against the brief.
- **Strata:** it checked the mix, the strata and pool membership.
- **The writer's flags:** it checked each one.
- **Result: 20/20 PASS**, with no revision. The verdicts and notes are in `VERIFICATION.json` (SHA-256 `223f1cf9…`),
  and it confirmed the case file's SHA-256 before and after.
- **Access:** every file it read was inside the kit. A directory listing showed the names of `work/`, `overlap/` and
  `MANIFEST.json`, which it did not open. Two long outputs were saved by the harness under the home directory; it did
  not open them, and re-read the content inside the kit.

## Blind compatibility check by the developer (counts and IDs only)

`scripts/blind_check_heldout.py` checks v5's mix by a constant. It was run unchanged, with that constant set to v6's
pre-registered mix from outside the script, so that nothing under `scripts/` changed since `6413076`:

```
python - <<'EOF'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("bc", "scripts/blind_check_heldout.py")
bc = importlib.util.module_from_spec(spec); spec.loader.exec_module(bc)
bc.MIX = {"market_event": 4, "forecast": 3, "document": 3, "notice": 5, "ambiguous_unavailable": 2, "adversarial": 2,
          "injection": 1}
sys.argv = ["blind_check_heldout.py", "eval/holdout_v6/cases.json", "--split", "holdout_v6", "--prior",
            "eval/cases.json", "eval/holdout_v2/cases.json", "eval/holdout_v3/cases.json", "eval/holdout_v4/cases.json",
            "eval/holdout_v5/cases.json", "eval/live_check_2026_09_29/cases.json", "--prompts", "src/nem_agent/prompts/v11"]
raise SystemExit(bc.main())
EOF
```

- **Mix:** as pre-registered (4/3/3/5/2/2/1), with IDs Z01–Z20 and split `holdout_v6`.
- **Gold numbers:** 14/14 row-backed numbers resolve in the repository's store with their values, plus 3 derived
  counts.
- **Gold citations:** 9/9 snippets are verbatim in the repository's index.
- **G = 18,** so the Q3 bar is 15. There are 2 as-of forecast cases (Z06, Z07).
- **Expected statuses:** 18 answered or answered with caveats, 1 needs clarification, 1 refused.
- **Requests:** every case builds a request.
- **Wording:** no 6-word overlap with the 118 earlier questions or prompts v11, and no exact duplicate.
- **`PROBLEMS: none`.**

## Provenance check by the developer (IDs only)

`python eval/holdout_v6/provenance_check.py --check eval/holdout_v6/cases.json`:
- **The search:** 770 files, at `6413076`.
- **The pool:** 112 notices (87 routine) and the region-day TAS1 2026-07-29.
- **The unused cases:** Z04, Z11, Z12, Z13, Z14 and Z15. Each gold document is a pool notice, and Z04's gold rows are
  on the pool day.
- **Routine price-review notices:** 1, within the limit of 1.
- **Files changed since `6413076`:** 17, all of them this protocol, `tests/eval/test_holdout_v6.py`,
  `docs/live-gates.md` or `docs/issue-tracker.md`.
- **`PROBLEMS: none`.**

**The developer did not read the questions, labels or gold values** before freezing, and will not before the runs.
- **What the developer saw:** the writer's and verifier's final reports, which give case IDs, categories, strata and
  short reasons; the counts above; and the cases' `group` fields (event IDs).
- **What the developer copied:** the case file and the verification, by `cp`, checked by SHA-256 only.
- **The developer's knowledge:** the reports named some topics without quoting a question or stating a gold value.
  - Z04 asks about the TAS1 day's maximums and total demand.
  - Z05 concerns the last run before a half-hour.
  - Z07 asks about weather.
  - Z12 is a market-wide reserve notice.
  - Z15 has a companion notice.
  - Z20's definition is in a passage next to the comparison with native demand.
  - The verifier's script names mentioned direction, intervention, reserve, Basslink and non-conformance notices, and
    InitialSupply passages.

## Points flagged for the human reviewer (by case ID)

- **Z01–Z03:** the interval counts are the same under every window convention. Their gold uses the window end as
  `valid_at_utc`, with no row.
- **Z04 (unused):** the TAS1 day has no high-price interval but has low-price intervals. Its gold values are the day's
  maximums, with no ties.
  - **The tool:** `find_market_events` may return no high-price event.
  - **The verifier's note:** "TOTALDEMAND" rather than "total demand" would remove any reading as operational demand.
- **Z05:** "the last run issued before the half-hour" picks the same run whether read as before its start or its end.
- **Z07:** an as-of forecast case that also asks about weather. It carries `no_retrospective_evidence`, and no weather
  row was public by the cutoff.
- **Z11, Z12, Z14 (unused):** other notices on the same topics exist, and the question's date or time picks out one.
  Z12 has no `findings_region` (a market-wide reserve notice).
- **Z15 (unused, the routine notice):** a companion notice for the same interval is also in the pool. It opens the
  review but does not give the outcome, so it cannot answer the question.
- **Z18, Z19 (adversarial):** they carry gold numbers (the peak price, and demand in Z19), and `must_not_contain` is
  the brief's list.
- **Z20 (injection):** its `must_not_contain` lists injection phrases. The cited passage gives the definition; the
  explicit comparison with native demand is in the adjacent passage of the same document.

## Overlap with earlier sets and development

- **Familiar (14):**
  - **Events:** the 8 familiar event-based cases (market_event, forecast, adversarial) take one case each on the 8
    pinned events, every one used by earlier sets and by development.
  - **Documents:** the 3 document cases use definition and procedure documents, all used before.
  - **No material:** the clarification, refusal and injection cases.
- **Unused (6):** material not previously used in evaluation or fix development, by the search above. It is **not**
  wholly unseen:
  - corpus-wide automatic checks in development ran over every notice;
  - the material shares the snapshot, sources and document templates of the used material.
- **Not comparable by category:** the unused stratum is five notice questions and one market_event question; the
  familiar stratum has no notice question.
- **No overlap in the questions:** they are new, written blind, with no 6-word overlap with any earlier question or
  prompts v11.
- **What this means:**
  - **A PASS would support:** "the frozen code answers new questions about this pinned data acceptably".
  - **The unused stratum's own figures** describe new material of known kinds. They do not show generalisation to new
    events, periods or kinds of document.

## Run A and run C sets

- **Run A, `DEVCHECK.json`:** Y02, Y05, Y06, Y07, Y14, Y17, Y18 and Y20 from `eval/holdout_v5/cases.json`,
  unchanged. They are v5's failures, development data since v5's FAIL, and the cases the fixes I-8 to I-14 were built
  from.
- **Run C, `REGRESSION.json`:** byte-identical to v5's. It holds H01–H14 (former held-out v2) and ADV02, ADV04,
  DOC04 and EV09 (`eval/cases.json`), all development data.
  - **What it measures:** it gates only H1–H5.
  - **Earlier result:** in v5's regression run it completed with no H1–H5 violation, on the code before the fixes.

## Changes after the writer started

- **The rule and rubric:** unchanged since `6fb0151`, which predates the writer.
- **Written after the writer started:**
  - the runner, the per-case process, the scorer and the offline tests;
  - `FREEZE.json` and this file;
  - the `DATA.md` copy.

  They concern only how the runs are recorded and measured. No bar, threshold, cap, stratum rule or case changed.
- **The blind check:** run with v6's mix set from outside the script (above), rather than by editing the script.
