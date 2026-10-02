# Review records: targeted Live check of I-15, I-16 and I-17 (records only)

The runs are in `../LC-i15-17-dev/` (D1) and `../LC-i15-17-fresh/` (D2), with their run logs, records, standard
output and traces. This folder holds the review. No answer was regenerated at any point. The frozen criteria
(`eval/livecheck_i15_17/PASS_RULE.md`) were applied unchanged.

## Files, in the order they were made

| File | What it is | SHA-256 |
| --- | --- | --- |
| `SHEET.json` | The review sheet, made by `score.py --sheet` from the saved records: shown answers, gold and automatic fields. It carries no question text | `c68145c3…` |
| `REVIEW_developer_original.json` | The developer's review (the developer implemented the fixes and had the questions), made before any reviewer result was seen | `e4de2b1e…` |
| `REVIEW_BRIEF.md` | The independent reviewer's brief | |
| `REVIEW_independent_original.json` | The independent reviewer's **original** review. The reviewer worked only inside a kit (brief, pass rule, sheet, gold, store copies), and the kit **did not contain the question texts**, so the reviewer inferred each question from the gold and checks | `74f9f3db…` |
| `DECISION_original.json` | `score.py --review` on the two original reviews: **FAIL** | `92320a3d…` |
| `QUESTIONS.json` | The exact frozen questions and request-level fields of the 18 cases, copied verbatim from `eval/holdout_v6/cases.json` and `eval/livecheck_i15_17/cases.json`. Each equals the question and request stored in its run record | `dd137c2a…` |
| `RECHECK_BRIEF.md` | The recheck brief given to the same independent reviewer with `QUESTIONS.json` | |
| `REVIEW_independent_corrected.json` | The independent reviewer's recheck of the same answers with the exact questions | `3182f5a6…` |
| `REVISIONS_independent.json` | Every case, and each changed judgement with its reason | `9d25102f…` |
| `DECISION_final.json` | `score.py --review` on the developer's review and the corrected independent review, taking the stricter reading wherever they differ: **FAIL** | `a99e554e…` |

The original reviews and decision are kept unchanged, and are read-only on disk.

## The one revised judgement

**K10, H4: 0 → 1** (`REVISIONS_independent.json`).
- **What the question asks:** when dispatch total demand "hit its highest point" across the event window.
- **What the answer gives:** its headline, "reached 7711.58 MW at 18:00 AEST 28 Jul", is thus given as the highest
  point.
- **The window's maximum:** 7867.57 MW at 22:10Z (`DISPATCHIS_202607290810_0000000529811184:L95`).
- **Why it changed:** without the question, "reached" had not been read as a superlative.
- **What did not change:** no outcome, and no other count.

The verdict, FAIL, is unchanged.

## Process notes

- **A session restart** during the first independent review cleared the developer's scratch working files, including
  the sheet, the developer review and the review kit. The runs, records and traces in the repository were not
  affected.
  - **The sheet** was regenerated deterministically from the saved records.
  - **The developer review** was re-entered unchanged from the developer's recorded judgements.
  - **The independent review:** a fresh independent reviewer was started; the interrupted first reviewer had produced
    no output.
  - `REVIEW_independent_original.json` is that fresh reviewer's original review.
- **The developer review was not revised after the recheck:**
  - The developer had the questions from the start.
  - The independent reviewer found two numbers the developer had missed: K09's "day minimum", and K01's second flow
    direction.
  - Under the frozen rule, the stricter reading of the two reviews decides.
