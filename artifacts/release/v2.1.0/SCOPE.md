# v2.1.0 release scope (recorded before any change)

The owner approved this scope on 2026-10-05: one bounded release-preparation pull request for v2.1.0, to be published
as a **GitHub prerelease**, not a production release. It is committed before any other change in the pull request.

## Base

- **Code:** `main` `6badc0c`, the merge of PR #88. v2.0.0 was tagged on `82c6ac7`.
- **Included:** the pull requests merged since v2.0.0:

  | PR | Decision | Change |
  | --- | --- | --- |
  | #80 | D31, Amendment 1 | Request plan: route contract v16, prompts v17, a deterministic compiler. Opt-in and off by default. |
  | #82 | D32 | Experimental confirmed-request workflow in the app: preview, clarification one question at a time, confirmation, computed answer. Opt-in. |
  | #83 | D32 | Execution restricted to the tool of the confirmed maximum or forecast comparison; status derived from the verified result. |
  | #84 | D32 | Current clarification requirements in the preview; historical interpretation notes moved to diagnostics. |
  | #86 | D32 | Headlines derived from the verified result for confirmed comparisons and maxima. |
  | #87 | D33 | Routing reasoning effort, configurable for routing calls only, unset by default; a progress message while routing runs. |
  | #88 | D34 | Live budget stops and missing model answers labelled truthfully. |

- **Excluded and kept paused:**
  - **PR #81:** the comparative routing-only evaluation of route contracts v15 and v16, frozen and not run;
  - **PR #89:** D35, an opt-in early transition to synthesis.

## Changes in this pull request

1. **Package version:** `2.1.0` in `pyproject.toml` and `src/nem_agent/__init__.py`. `GET /health` reports it.
2. **Release notes:** a v2.1.0 section in `RELEASE_NOTES.md` covering:
   - what changed since v2.0.0;
   - the limitations;
   - compatibility;
   - installation and demo instructions.

   Also a status line in the README and a status note in `docs/live-gates.md`.
3. **Release-check record:**
   - `artifacts/release/v2.1.0/CHECKS.md`;
   - the Replay evaluation output in `artifacts/release/v2.1.0/eval/`;
   - this file.

## Unchanged

- **The application:** behaviour, default settings, prompts, models, caps and supported features. The experimental
  modes stay off by default.
- **Frozen and historical material:** every frozen file, gold file, protocol, historical record and verdict.
- **Tags:** `v1.0`, `v2.0.0`, `pinned-bytes-2026-09-27` and `pinned-bytes-bundle-2026-09-28`.
- **The owner's running demo app:** its key, its ledger and its USD 0.50 cap.

## Verification plan

These are the repository's existing offline checks, re-run. They are not a new evaluation and not a Live run.
- **Environment:**
  - a fresh git worktree;
  - a new virtual environment from `requirements.lock`;
  - `OPENAI_API_KEY` unset;
  - a scratch budget ledger.
- **Checks:**
  - install (`make setup`) and the version;
  - lint and the type check;
  - the approved-bytes index;
  - the restore of the pinned bytes;
  - the data build and data check;
  - the document index;
  - the publisher-download check;
  - the full test suite;
  - the Replay evaluation, the retrieval evaluation and the safety suite;
  - the demo;
  - the API smoke test (`/health` must report `2.1.0`);
  - the Streamlit startup.
- **Reporting:** every skipped check or test is reported with its reason.
- **CI:** it must pass on the exact final head of the pull request.

## Not committed

- **No secrets, local configuration or demo-ledger contents.**
- **The historical task-wide ledger** is described as previously recorded: USD 9.336937, 3,226 lines, SHA-256 prefix
  `f303c2bc70aadd8f`. It is not available on the machine preparing this release, so it is not re-verified, and no
  replacement is created.

## Publication plan (for later approval; not done in this pull request)

1. Tag `v2.1.0` on the eventual merge commit, after checking that its tree equals the reviewed head and that `main` CI
   passes.
2. Publish it as a GitHub **prerelease**.
3. Keep `v1.0` marked Latest, and leave `v2.0.0` unchanged.

**Not done in this pull request:** no paid call, new evaluation, unrelated fix, app restart, merge, tag or
publication.
