# v2.0.0 release checks (offline; no language model)

These are the repository's existing offline checks, re-run on the v2.0.0 release code before the documentation
commits.
- **Not a new evaluation:** no case, gold, threshold or protocol was added or changed. The Replay evaluation
  (`make eval`) is the existing 40-case offline evaluation, re-run.
- **Not a Live run:** no language model was called, and no paid call was made.
- **Code:** commit `5199800` (`src/` tree `6c26d0e0ce143ac2b44d4aa21856da08e7d6dc4d`). It is `main` `0f02799` plus
  the version string only. The release candidate has the same `src/` tree; it adds documentation and this folder.
- **Environment:**
  - a fresh git worktree, with a new virtual environment from `requirements.lock`, Python 3.14.2;
  - `OPENAI_API_KEY` unset, and a scratch budget ledger;
  - no paid call. The real ledger was not touched.
- **Sequence:** CI's (`.github/workflows/ci.yml`), plus the demo, the retrieval evaluation, the API smoke test and a
  Streamlit startup check.
- **Candidate checks:** the release pull request reports the same checks on its exact head commit, with CI on Python
  3.12 and 3.14.

| Step | Command | Result |
| --- | --- | --- |
| Install | `make setup SYSTEM_PY=python3` | pass; `nem_agent 2.0.0`, package metadata `2.0.0` |
| Lint | `make lint` | pass |
| Type check | `make typecheck` | pass |
| Approved-bytes index | `make store-verify` | PASS: 310 objects (307 current, 3 superseded, 0 unavailable) |
| Restore | `make restore-pinned` | PASS: 307 restored, 0 rejected |
| Data | `make data`, `make data-check` | PASS; `data_version` `8c14c217f5570d32` |
| Document index | `make index` | pass; `corpus_version` `221b6ea0f21e006d` |
| No publisher contacted | `python -m nem_agent.cli publisher-downloads --expect-none` | none |
| Tests | `make test` | 2,245 passed, 3 skipped (the traces they read are git-ignored, so absent from a fresh checkout), 1 third-party deprecation warning |
| Replay evaluation | `make eval` | PASS: every gate passes. Figures in `eval/report.md` |
| Retrieval evaluation | `make retrieval-eval` | Recall@5 16/21, Hit@5 15/15, MRR@5 0.830: identical to the committed file |
| Safety suite | `make safety` | PASS: 24/24 detected, 0 critical violations remaining, 0 unauthorized writes, 1 valid approval write; identical to the committed summary |
| Demo | `make demo` | pass; the README's quoted sample output matches |
| API smoke test | `make smoke` | PASS: `/health` status ok, `"version": "2.0.0"`; Replay investigation answered and validated; evidence row checksum matches; 422 for bad input; 400 for Live without a key |
| App startup | `streamlit run app/streamlit_app.py` (headless) | `/_stcore/health` ok; `GET /` 200 |

## The Replay evaluation against its frozen gold

`eval/offline.json` and `eval/report.md` are the outputs of `make eval` on the release code. Every gate passes.
Against the frozen gold, these figures differ from the committed `artifacts/eval/report.md` of 2026-09-28. D28 and
D29 record the changes, and the gold is unchanged.

| Measure | 2026-09-28 | v2.0.0 | Why |
| --- | --- | --- | --- |
| Forecast gold, test | 5/5 | 1/5 | the whole local day is compared, while the gold encodes an earlier 12-hour slice (D28) |
| Forecast gold, dev | 5/5 | 0/5 | the same |
| Status, test | 20/21 | 18/21 | FC02 (unnamed forecast, D29) and AMB06 (24.5-hour window, D28) are sent back |
| Scripted router, test | 19/20, macro-F1 0.92 | 17/20, macro-F1 0.82 | a clarification counts as a routing miss |

## Committed artifacts that regenerate differently

These files were made with earlier code (2026-09-25 to 2026-09-28), and regenerating them on the release code
changes them:
- `artifacts/eval/offline.json` and `artifacts/eval/report.md`;
- `artifacts/replay_case.json`, `artifacts/replay_definition_case.json` and `artifacts/replay_forecast_case.json`;
- `artifacts/api_smoke_transcript.json`.

**How they differ:**
- **`replay_case.json` and `replay_definition_case.json`:** the outcome is the same. They differ in new report
  fields, validation checks, evidence IDs, timings and version stamps.
- **`replay_forecast_case.json`:** the outcome changed, as D28 specifies. "for SA1 on 2026-07-31" is now compared
  over the whole local day: 38 half-hours with published actuals, MAE 89 MW, mean error −1 MW. Before, it was a
  12-hour slice: 24 half-hours, MAE 33 MW, mean error +5 MW. The record is now a format-2 report with a computed
  answer.
- **The smoke transcript:** it differs in the version, the code stamp, trace IDs and evidence IDs.

The README quotes the event review (`replay_case.json`), whose figures are unchanged, including its forecast review
over the 24 half-hours around the event peak.

They are kept as committed, and nothing in them is a historical verdict. `artifacts/eval/retrieval_eval.json` and
`artifacts/g5_safety_summary.json` regenerate identically.
