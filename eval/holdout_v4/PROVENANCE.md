# Held-out set v4: provenance

- **File:** `eval/holdout_v4/cases.json`, 20 cases (W01–W20), SHA-256
  `4529201404c74b9b5686c286caa52b536d1e784f92bd7f1400e9b0ea9f2e3e18`.
- **Frozen:** 2026-09-28, before any Live run on it. It will not be edited after results are seen.
- **Pass rule and interruption rule:** `PASS_RULE.md`, SHA-256
  `60040623c61e5ca7769f6781930b92926b87f5f116bea7071f7dea1586185830`. It was committed and pushed in `67849c9`
  (2026-09-28T14:04:52Z) **before the writer started**, together with the resumable run driver
  `scripts/live_resumable.py` that applies the interruption rule.
- **Cases with gold labels:** G = 18, so the Q3 bar is ⌈0.8 × 18⌉ = 15.

## Writer

A fresh subagent with no conversation history.
- **Kit:** a directory outside the repository, rebuilt for v4, containing:
  - `BRIEF.md` (copied here; SHA-256 `9856f424…`): the v3 brief with the file name, split and ID prefix changed, plus
    two additions (below);
  - `DATA.md` (identical to v2's and v3's);
  - copies of the pinned data store and document corpus (byte-identical to the repository's);
  - `events.json` (the 8 verified events and the analysis thresholds);
  - a fresh Python environment with only `duckdb` and `pytz` (no project package);
  - `overlap/`: SHA-256 hashes of every 6-word sequence in the 74 earlier questions (40 in `eval/cases.json`, 14 in
    held-out v2, 20 in held-out v3) and in prompts v11, with a checker.
- **The two additions to the brief:**
  - "`request` is always `{}`" (v3's first draft had put `kind` there);
  - the wording check, run until it prints none.
- **Not in the kit:**
  - the repository and its analyses;
  - the prompts and source code;
  - any Live output or trace;
  - the text of the earlier questions.
- **Access:** the writer listed every file it read and command it ran, all inside the kit. It did not open the hash
  file. Its first wording check flagged 12 questions, which it reworded (keeping region, time, measure and gold) until
  the check printed none.
- **Mix:** 4 market_event, 4 forecast (2 as-of; W06 also asks about weather and carries `no_retrospective_evidence`),
  4 document, 3 notice, 2 ambiguous_unavailable (1 clarification, 1 refusal), 2 adversarial, 1 injection.

## Independent gold check

A second fresh subagent, with the same kit-only rules and barred from the writer's build script and from the overlap
files, checked the set with its own queries.
- It re-derived every gold value: 16 row-backed numbers and 3 interval counts, the counts under three window-boundary
  conventions.
- It confirmed every row by `row_id`, region, time and value; the as-of runs (the latest available by each cutoff,
  with no actual or weather row public by then); and the two runs named by issue time.
- It checked the 8 citation snippets verbatim, read each passage, and listed every notice for each notice case's
  region and date.
- It checked the expected fields against the brief.
- **Result: 20/20 PASS**, with no revision needed. The verdicts are in `VERIFICATION.json` (SHA-256 `bdf0a557…`).
- **Minor notes, not faults:** the check sentences of W05 and W06 do not list every run that was issued before the
  cutoff but not yet available. Their gold runs are correct.

## Blind compatibility check by the developer (counts and IDs only)

`python scripts/blind_check_heldout.py eval/holdout_v4/cases.json --split holdout_v4 --prior eval/cases.json
eval/holdout_v2/cases.json eval/holdout_v3/cases.json --prompts src/nem_agent/prompts/v11`
- the category mix is as required;
- 16/16 row-backed gold numbers resolve in the repository's store with their values; 3 derived counts;
- 8/8 snippets are verbatim in the repository's index;
- every case builds an `InvestigateRequest`, and the runner's loader reads the file;
- no 6-word overlap with the 74 earlier questions or prompts v11, and no exact duplicate;
- **no problems**.

The same script re-run on the frozen v3 file reproduces v3's recorded check (18/18, 8/8, G = 18).

**The developer did not read the questions, labels or gold values** before freezing, and will not before the run.

## Points flagged for the human reviewer (by case ID)

- **Writer:**
  - W02, W03: the counts cover the event window, which crosses a local calendar day.
  - W05, W06: 0.5 MW tolerance on POE50 (neighbouring runs differ by a few MW); W06's "median-case" and weather wording
    leave room for interpretation.
  - W14: the notice is on the event's date, but it does not state a cause of the event.
  - W16: needs clarification per the brief, although the data covers both regions.
  - W18, W19: the notice timing and cancellation facts are in the check sentence; the only gold number is the peak.
  - W20: carries `must_not_contain` with the injected phrases.
- **Verifier:** the W05 and W06 check sentences, as above.

## Scope

v4 uses the same 8 events, data and document corpus as every earlier set. Its questions are new, but those events,
notices and documents have been used in development.
