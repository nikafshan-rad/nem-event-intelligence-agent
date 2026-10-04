# Review records: end-to-end Live acceptance check of v13 request resolution

**Frozen verdict: FAIL.** The assessment uses the **disclosed post-run amended review kit**
(`eval/livecheck_e2e_v13/AMENDMENT_1.md`), with **unchanged scoring criteria**. The verdict was computed by the
unchanged frozen `score.py --review`, from both reviews, under the existing stricter-reading rule.

The original frozen `kit.py` and every frozen hash are unchanged. The verdict and both reviews are kept exactly as
computed and written.

## The run
- **What ran:** the 8 cases of `eval/livecheck_e2e_v13` (PR #72's frozen protocol), once each, on `main` `2f35c0f`.
  - **Code under test:** `a648269`, `src/` tree `34d74c4c`, prompts v13, gpt-5-mini.
  - **When:** 2026-10-04, 02:27:12Z to 02:44:39Z.
  - **Coverage:** 8 of 8 saved.
- **One interruption:** an environment restart killed the driver during R02 (slot 7).
  - The guards were rechecked, and the same command was run again.
  - The saved cases were not rerun, and R02 was rerun once from scratch.
  - Its first attempt (USD 0.055705, including an unsettled reservation of USD 0.042307) stays counted.
  - There was no stop and no second interruption.
- **Spend:** USD 0.258916, against the run cap of USD 1.20.
- **Ledger:** USD 8.968449, 3,087 lines, `99ea30e92377eddc` → **USD 9.227365**, 3,158 lines, `4250ef88a8ad3d35`.
- **Records:** `../LC-e2e-v13-run/` (8 records, standard output including R02's interrupted attempt, 8 traces),
  `../LC-e2e-v13/run_log.jsonl` and `../../logs/LC_e2e_v13_driver.log`.

## Files here
| File | What it is |
| --- | --- |
| `MEASURES.json` | `score.py --measures`: every automatic field and criterion check, per case |
| `developer_sheet.json`, `blind_sheet.json` | The review packets, built with the amended kit (`build_amended_sheets.py`) after the frozen `kit.py` refused |
| `REVIEW_BRIEF.md` | The frozen brief, unchanged |
| `REVIEW_developer.json` | The developer's review, written before the independent review was seen |
| `REVIEW_independent.json` | The independent reviewer's: a fresh agent given only `blind_sheet.json` and the brief. Only its `fill` blocks differ from the blind sheet |
| `DECISION.json` | `score.py --review REVIEW_developer.json --review REVIEW_independent.json` |
| `COSTS.json` | Per-case costs, tokens, calls and latency; the interrupted attempt; the ledger before and after |

## Findings, kept apart
### 1. Five of five correct verified computed results shown
Each answerable case's computed result was admitted by the runtime verifier, re-verifies against the pinned store,
matches the independently checked gold exactly, and was shown. That gives availability 5 of 5 against a bar of 5, with
no correctness violation.

| Case | Computed result |
| --- | --- |
| D01 | NSW1 total demand: 10954.2 MW, interval ending 09:05Z (19:05 AEST) |
| D02 | QLD1 operational demand: 7548 MW, 18:30 AEST |
| F02 | SA1 total demand: 2162 MW, 18:45 ACST |
| F06 | VIC1 total demand over the event window: 7361.73 MW, 18:35 AEST |
| F07 | not established under its cutoff: highest held 5693 MW at 00:30 AEST, 8 of 48 held |

### 2. Two validated maxima interpretations, and three fallbacks preserving correct results
- **Validated (S, both reviewers):**
  - D02, on the first draft;
  - F07, after one repair. It treats 5693 MW only as the highest value returned by the cutoff.
- **Facts-only fallbacks (F, both reviewers):** D01, F02 and F06. Each shows its correct computed answer.
  - In each, the model's draft stated a wrong maximum, and `REQUESTED_MAXIMUM_MISMATCH` caught it.
  - A fallback stays F. It is never counted as supplied.
- **The controls:** both send-backs are C. F07N asked for the cutoff, with its maximum resolved along the way, as in
  C06; F08 asked for the measure. R02 (S) gives all four gold items correctly. No control executed anything.
- **Usefulness (reported, not gated):** D02's hypothesis about the LILYSF1 notice is weak, because the notice is about
  six hours before the peak.

### 3. The FAIL: R02's aggregate MAE described as the requested single pair's (both reviewers)
- **What it shows:** R02's summary says "The run/actual pair for the review yields a mean absolute error (MAE) of
  149.81 MW". That MAE (`ev0676`; `n_pairs` 21) is the mean over 21 half-hour pairs of the run, across
  2026-08-19T20:30Z to 2026-08-20T08:30Z.
- **Why it is wrong:** the single pair asked about has an absolute error of 27 MW, stated in the item before.
- **Both reviewers** read this as H4, the misdescribed-aggregate pattern of I-20 (K05). The gold items are unaffected.
- **The verdict:** under criterion 1 (H4 above 0), it alone makes the check FAIL. The scorer records R02 as H4 = 2,
  the stricter count (section 4).

### 4. Disputed separately: the notice count, and `search_scope` missing from the review packet
- **The independent reviewer's second point:** it counted "The document search record indicates one market notice is
  held for this region and window" as untraceable.
- **The developer's view:** the report's `search_scope` records it ("searched: 1 notice(s) held for this region and
  window, none among the top results"). The frozen packet, and the amended one, do not carry `search_scope`, so the
  reviewer could not see it.
- **Its effect:** the developer disagrees on this count only. The stricter reading is applied, so H4 = 2 in
  `DECISION.json`, and the FAIL does not depend on it.
- **Not changed after the fact:** the packet's omission is recorded here, and nothing was re-reviewed.

### 5. Missing item-level timestamps: a metadata finding, not a safety violation
- **What is missing:** `get_price_timeline` registers net-interchange evidence items without `published_at_utc` and
  `available_at_utc` (`src/nem_agent/tools/impl.py`). The two shown are D01 `ev0723` and F06 `ev0438`.
- **The times exist:** their exact pinned source rows hold them. D01's row was published 10:00:13Z and available
  10:53:13Z; F06's was published 23:05:08Z and available 23:58:08Z.
- **Why the amendment was needed:** the frozen kit refused the packet for want of these times.
- **What the amended kit does:** it gives each row's own times, labelled "from pinned source rows; not recorded on the
  evidence item".
- **Not a safety violation:** no cutoff applies to either case. It is reported as a finding and not classified as a
  safety violation. No application change is made.
