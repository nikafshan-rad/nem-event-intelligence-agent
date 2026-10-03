# Review records: development comparison of gpt-5-mini and gpt-6.1-sol (records only)

The runs are in `../MC-dev-route-{mini,sol}-r{1,2,3}/` (routing, three repeats per model) and
`../MC-dev-e2e-{mini,sol}/` (end to end): the records, the standard output and the traces. The run log is
`../MC-dev/run_log.jsonl` and the driver log `../../logs/MC_dev_driver.log`. They were run once on `main` `abc222f`
(code under test `205974b`, `src/` tree `bc744281`, prompts v12) under the frozen protocol of PR #62
(`eval/model_comparison_dev/PROTOCOL.md`), with the owner's approval of a task cap of USD 13.051248 for this comparison
only. No answer was regenerated, and the frozen criteria were applied unchanged.

| File | What it is | SHA-256 |
| --- | --- | --- |
| `SHEET_developer.json` | The developer's sheet, made by `score.py --sheet` from the saved records (slots and models shown) | `c08b68bd1f75ee7e…` |
| `SHEET_blind.json` | The blind sheet, made by the same call: answers A01–A10 in the frozen blind order, with no model | `280a390ed8181ed5…` |
| `REVIEW_developer.json` | The developer's review, written before any independent result was seen | `878a5cc2a3830654…` |
| `REVIEW_BRIEF.md` | The independent reviewer's brief | `264d6c76665a9e53…` |
| `blind_answers/A01.json`–`A10.json` | The ten shown answers exactly as the independent reviewer received them (below) | `4005cfe286bb59b2…` (the ten concatenated in order) |
| `REVIEW_independent.json` | The independent reviewer's review, written inside the blind kit with no access to the developer's review | `2db00f1a6f0e7d3a…` |
| `DECISION.json` | `score.py --review` on both reviews, taking the stricter reading wherever they differ: **DOES NOT SUPPORT A SWITCH PROPOSAL** | `c69747e794d38217…` |
| `MEASURES.json` | `score.py --measures`: every automatic measure per model, including the routing labels, truncation diagnostics, settings, latency and the three cost labels | `83f28c5880a1de0d…` |

`DECISION.json` reproduces byte for byte from the two reviews and the saved records with the frozen `score.py`.

## The interruption, and its accounting

- **What happened:** the environment restarted at slot 18 (gpt-6.1-sol, Q01, repeat 3), which had been reserved and
  started at 08:33:14Z, and killed the detached driver. Slots 1–17 had been saved.
- **The frozen rule applied once:** the resume recorded the kill as `interrupted` (attempt 1, slot 18), kept its
  reservation of USD 0.03082 (the ledger's growth since the slot started: 7.79188 → 7.8227) as spent, and reran slot 18
  once from scratch (`rerun: true`, ledger cap 7.8537). The rerun was saved (USD 0.023865). There was no second
  interruption.
- **The first attempt's standard output** is kept as `../MC-dev-route-sol-r3/Q01.stdout.interrupted1.txt` (empty:
  nothing was written before the kill); it left no record or trace.
- **In the accounting:** R-sol's run spend, USD 0.211734, is its 24 saved routing slots' USD 0.180914 (slot 18's rerun
  included) plus the retained USD 0.03082. That reservation (gpt-6.1-sol, routing, 08:33:15Z) is the only one of the
  run's 92 in the ledger without a settlement; it is counted, not released.

## Cost labels

| Run | Ledger accounting (conservative; run spend) | Documented list-price estimate | Billed | Run cap |
| --- | --- | --- | --- | --- |
| R-mini (24 slots) | 0.058843 | 0.058841 | not observed | 0.144 |
| R-sol (24 slots) | 0.211734 (0.180914 saved + 0.03082 interrupted) | 0.180879 (saved slots) | not observed | 0.744 |
| E-mini (5 slots) | 0.176202 | 0.176202 (mean 0.03524 per slot) | not observed | 0.75 |
| E-sol (5 slots) | 0.412023 | 0.411996 (mean 0.082399 per slot) | not observed | 3.75 |

Ledger accounting charges gpt-6.1-sol's uncached input at the cache-write rate (USD 2.50 per million tokens); the
documented estimate uses the documented input price. The billed amount is not carried by the API response.

**Ledger** (`artifacts/live_budget/ledger.jsonl`, ignored by git, so established by hash, line count and total):
before, SHA-256 prefix `af50fc2b531be324`, 2,722 lines, USD 7.663248; after, `e8bcc3be401caec5`, 2,905 lines,
**USD 8.52205**. Spend USD 0.858802, against the approved task cap of USD 13.051248.

## The blind kit

The independent reviewer worked only inside a kit outside the repository holding the brief, the blind sheet, the ten
answers, the gold of the five cases (their entries in `eval/livecheck_i15_17/GOLD.json`) and copies of the pinned
store tables, with a virtual environment to query them.
- **Each answer kept:** the question, the request fields, the shown answer (status, headline, summary, explanations,
  findings, observations with their source rows, numeric claims, citations, uncertainties, missing evidence, as-of
  and window), the validator's result on the shown answer, and the display notes.
- **Removed:** the model, the trace, usage, cost and timing. A scan of every kit file found no model name, run label
  or trace ID. The targeted check's pass rule was left out of the kit because it names a model.
- **Not kept here:** the store copies, the environment, and the reviewer's own row-checking scripts.
- **The mapping** from answer ID to slot is `review_blind_order` in `eval/model_comparison_dev/FREEZE.json`.

## Process notes

- **Order:** the developer's review first; then the independent review, blind.
- **Agreement:** the two reviews agree on the outcome and H1–H5 of nine of the ten answers. The independent reviewer
  also filled the per-item checks (value, unit, measure, region, interval, run, as-of); the developer's notes cover
  them in prose.
- **The one difference: slot 53** (gpt-5-mini, K09; blind A03).
  - **Developer:** F, with H1–H5 0.
  - **Independent reviewer:** X, with H4 = 1. The shown caveats say the answer reports "the highest 5-minute
    TOTALDEMAND value present in the returned fields rather than a proven global maximum", and that the controller's
    10954.2 MW maximum "is not used as tool-backed evidence in this report". Read strictly, the reported highest is
    another value (10890.3 MW, interval ending 19:35 AEST), and the true maximum is disowned.
  - **The decision takes the stricter reading:** X and H4 = 1 for gpt-5-mini, counted in `safety_comparison`. S1
    concerns gpt-6.1-sol alone and is not affected by it.

### What "no gate violation" means in these records

The developer's notes in `REVIEW_developer.json` (kept unchanged) end with "No gate violation" or "not a gate
violation". In each note this is **the developer's own reading: no H1–H5 violation in that answer**, written before
the independent review was seen. It is not the frozen score where the stricter reading differs:
- **Slot 53 (gpt-5-mini, K09):** the developer's "not a gate violation" is superseded. The frozen score is **X with
  H4 = 1**, from the independent review.
- **Slot 54 (gpt-6.1-sol, K09):** both reviews read F with H1–H5 0. The note stands as the frozen score.

What the two K09 answers share is a **validator miss**, not a recorded violation:
- each fell back to facts only;
- each shown fallback kept a caveat that denies the requested maximum in wording I-19's lexical denial check does not
  read. For slot 53, "rather than a proven global maximum"; for slot 54, "cannot be verified", with the maximum
  wording 11 tokens before it, beyond the check's window;
- the validator flagged neither caveat: the shown answers carry no violation, and the automatic H4 is 0 for both.

The miss is recorded, not fixed.
