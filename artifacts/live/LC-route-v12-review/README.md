# Review records: Live check of the v12 routing extraction (records only)

The runs are in `../LC-route-v12-dev/` (R-dev), `../LC-route-v12-fresh/` (R-fresh) and `../LC-route-v12-e2e/` (E-dev):
the run logs, the records, the standard output and the traces. They were run once each on `main` `baf94fa` (code under
test `f2455ca`, src tree `b367b911`, prompts v12, `gpt-5-mini`) under the frozen protocol of PR #57. No answer was
regenerated, and the frozen criteria (`eval/livecheck_routing_v12/PASS_RULE.md`) were applied unchanged.

| File | What it is | SHA-256 |
| --- | --- | --- |
| `SHEET.json` | The review sheet made by `score.py --sheet` from the saved records | `a7de30b1e8dff1d8…` |
| `REVIEW_developer.json` | The developer's review, written before any independent result was seen | `971b1475174bfad9…` |
| `REVIEW_BRIEF.md` | The independent reviewer's brief | `531213b0a021287a…` |
| `QUESTIONS.json` | The exact frozen questions and request fields of all 47 cases, each equal to its run record's question, and given to the reviewer from the start | `ab40d561eeb08578…` |
| `REVIEW_independent.json` | The independent reviewer's review. It was written inside a kit (the brief, both pass rules, the questions, the gold, the records and traces, and store copies), with no access to the developer's review | `f70567ab80f026dc…` |
| `DECISION.json` | `score.py --review` on both reviews, taking the stricter reading wherever they differ: **FAIL** | `1ee60785cbb8aa4a…` |

## Process notes

- **Routing labels:** they are mechanical. Both reviewers confirmed all 42, with no disagreement.
- **End-to-end:** the reviewers differed on one reading, K05's H4. The developer read 0; the independent reviewer read 1,
  because the MAE described "for the 24-hour target window" covers one half-hour of a 12-hour tool window. The stricter
  reading (1) applies.
- **A disclosure by the independent reviewer:** the tool layer saved one oversized shell output outside its kit. The
  reviewer did not open that copy, and extracted what it needed with a script instead.
