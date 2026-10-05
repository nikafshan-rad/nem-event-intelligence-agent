# v2.1.0 release checks (offline; no language model)

These are the repository's existing offline checks, re-run on the v2.1.0 release code before the documentation
commit.
- **Not a new evaluation:** no case, gold, threshold or protocol was added or changed. The Replay evaluation (`make
  eval`) is the existing 40-case offline evaluation, re-run.
- **Not a Live run:** no language model was called, and no paid call was made.
- **Code:** commit `86f6573` (`src/` tree `b331810fc21657e82347694cc3b4bc34bbf78993`). It is `main` `6badc0c` plus
  the version string only. The release candidate has the same `src/` tree; it adds documentation and this folder.
- **Environment:**
  - a fresh git worktree, with a new virtual environment from `requirements.lock`;
  - Python 3.12.3, on Ubuntu 24.04 under WSL;
  - `OPENAI_API_KEY` unset;
  - a scratch budget ledger, still empty after the checks (no call was reserved).
- **Left untouched:** the owner's running demo app, its key, its ledger and its cap. The Streamlit check used another
  port.
- **Sequence:** CI's (`.github/workflows/ci.yml`), plus the demo, the retrieval evaluation, the API smoke test and a
  Streamlit startup check.
- **Candidate checks:** the release pull request reports the same checks on its exact head commit, with CI on Python
  3.12 and 3.14.

| Step | Command | Result |
| --- | --- | --- |
| Install | `make setup SYSTEM_PY=python3` | pass; `nem_agent 2.1.0`, package metadata `2.1.0` |
| Lint | `make lint` | pass |
| Type check | `make typecheck` | pass (75 source files) |
| Approved-bytes index | `make store-verify` | PASS: 310 objects (307 current, 3 superseded, 0 unavailable) |
| Restore | `make restore-pinned` | PASS: 307 restored, 0 rejected |
| Data | `make data`, `make data-check` | PASS; `data_version` `8c14c217f5570d32`, as in v2.0.0 |
| Document index | `make index` | pass; `corpus_version` `221b6ea0f21e006d`, as in v2.0.0 |
| No publisher contacted | `python -m nem_agent.cli publisher-downloads --expect-none` | none |
| Tests | `make test` | 2,491 passed, 3 skipped (below), 1 third-party deprecation warning |
| Replay evaluation | `make eval` | PASS: every gate passes. No non-volatile difference from v2.0.0's output. Figures in `eval/report.md` |
| Retrieval evaluation | `make retrieval-eval` | Recall@5 16/21, Hit@5 15/15, MRR@5 0.830: every metric as in v2.0.0. One ranked passage differs (below) |
| Safety suite | `make safety` | PASS: 24/24 detected, 0 critical violations remaining, 0 unauthorized writes, 1 valid approval write; identical to the committed summary |
| Demo | `make demo` | pass |
| API smoke test | `make smoke` | PASS: `/health` status ok, `"version": "2.1.0"`; Replay investigation answered and validated; evidence row checksum matches; 422 for bad input; 400 for Live without a key |
| App startup | `streamlit run app/streamlit_app.py` (headless) | `/_stcore/health` ok; `GET /` 200 |

## Skipped and not run

- **3 tests skipped:** `tests/eval/test_live_check_dev2.py:448`, "the 2026-09-29 traces are in the git-ignored trace
  store only". A fresh checkout does not have them. The same 3 tests were skipped at v2.0.0.
- **No release check was skipped.**
- **Not run, because they are not offline release checks:**
  - `make eval-live` and `make live-smoke`: they need an API key and are paid;
  - `make probe`, `make verify` and `make refresh-check`: they contact the publishers;
  - `make rolloff-sim` and `make ml`: optional experiments.

## The Replay evaluation

- **The output:** `eval/offline.json` and `eval/report.md` are what `make eval` wrote on the release code. Every gate
  passes.
- **Against v2.0.0's output** (`artifacts/release/v2.0.0/eval/offline.json`), only volatile fields differ: the code
  stamp, the generation time, latencies and trace IDs. Every outcome and figure is the same.
- **The figures:**
  - status matches: 18/21 (test);
  - forecast gold: 1/5 (test) and 0/5 (dev);
  - scripted router: 17/20, macro-F1 0.82;
  - numeric traceability and citation validity: 100%.

  D28 and D29 record why they differ from the committed 2026-09-28 report, and the gold is unchanged.

## Committed artifacts that regenerate differently

Every file below is kept as committed, and nothing in them is a historical verdict.
- **Changed by earlier code, as at v2.0.0** (`artifacts/release/v2.0.0/CHECKS.md` explains how):
  - `artifacts/eval/offline.json` and `artifacts/eval/report.md`;
  - `artifacts/replay_case.json`, `artifacts/replay_definition_case.json` and `artifacts/replay_forecast_case.json`;
  - `artifacts/api_smoke_transcript.json`.
- **`artifacts/eval/retrieval_eval.json`: one ranked passage differs.**
  - **The difference:** for R05 ("What is TOTALDEMAND in DISPATCHREGIONSUM?"), the fifth result is
    `aemo_demand_terms#p27c61` instead of `mms_dm_elec22#DISPATCHREGIONSUM#3`. Every metric is unchanged, R05's
    included (1 of its 2 labelled items found; first at rank 2).
  - **Why it is environmental:**
    - No retrieval code, dependency or corpus changed since v2.0.0.
    - The fresh index has the same embeddings checksum as an index built earlier on this machine.
    - v2.0.0's own code, run here on the same index, gives the same fifth result.
    - v2.0.0's checks, on Python 3.14.2, reproduced the committed file.

    The difference is therefore consistent with the environment (Python 3.12.3 here). It was not traced further.
- **`artifacts/g5_safety_summary.json`:** regenerates identically.

## The smoke test's code stamp

The smoke test ran after the evaluation and the demo had rewritten the committed artifacts above. `/health`
therefore reported `"code": "86f6573-dirty"`. No source file had changed: the worktree's status listed only those
artifacts.
