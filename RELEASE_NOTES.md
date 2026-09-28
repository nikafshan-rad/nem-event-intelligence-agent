# Release notes

## v1.0 (2026-09-28)

The first release of the NEM Event Intelligence Agent: a read-only research assistant for Australia's National
Electricity Market. It answers questions about price events, demand forecasts and AEMO documents from real public
AEMO data, with every number traced to a source row and every quote checked against its source.

**Live (LLM) mode is experimental in this release.** Replay mode is the verified baseline.

### What is included

- **Data:**
  - real public AEMO data for five regions (late July – August 2026) and public AEMO documents and market notices,
    with per-row provenance;
  - an **approved-bytes store**, so builds restore exactly the publisher files a reviewer approved (SHA-256 verified)
    without contacting AEMO or NASA;
  - `data_version` `8c14c217f5570d32`, `corpus_version` `221b6ea0f21e006d`.
- **Tools and retrieval:** 8 typed, bounded, read-only tools with as-of rules; hybrid document retrieval (FTS5 +
  embeddings) with eligibility filters and injection handling.
- **Two controllers:**
  - **Replay:** scripted, no language model;
  - **Live:** gpt-5-mini through the OpenAI Responses API, with strict schemas, one bounded repair and a facts-only
    fallback.
- **Validation and budget:** independent validators (numbers, quotes, times and time zones, units, as-of, metric
  compatibility, causal language, injection, notice timing); a task-wide budget ledger that fails closed.
- **Evaluation:** a 40-case Replay evaluation with two baselines; three independent Live held-out sets (v2, v3, v4)
  with frozen pass rules; a safety suite of 24 adversarial fixtures.
- **Interfaces:** a FastAPI service and a Streamlit app that labels every answer Live or Replay.

### Verification status

- **CI:** passed on `main` `ab08fe6` (lint, type check, real-data build from the approved-bytes store, tests, Replay
  evaluation, safety suite; Python 3.12 and 3.14).
- **Offline:** 305 tests pass; the Replay evaluation and the safety suite (24/24) pass.
- **Live, held-out v4:** 20 cases written and gold-checked by independent agents, frozen with the pass rule before
  any paid call, run once.

| Criterion (bar) | Result |
| --- | --- |
| Safety: writes, forbidden calls, causal claims, as-of leaks, injection (0) | all 0 |
| Numbers presented as facts traced to evidence (100%) | 100% |
| Expected status (≥ 16/20) | 18/20 |
| Correct intent and required tools (≥ 18/20) | 20/20 |
| Gold labels hit by the model's own answer (≥ 15/18) | 15/18 (met exactly) |
| Relevant, judged by hand (≥ 16/20) | 17/20, counting two answers with gaps (strictly, 15/20) |
| Regression run with no safety violation (required by the rule) | **not run: unverified** |

**The full L3 rule is therefore unverified.** Live met v4's own criteria narrowly, and earlier held-out sets v2 and
v3 failed.

Incomplete or unusable v4 answers:
- **W10, W14: facts-only fallbacks.** The document statements cited citation IDs that did not exist.
- **W20: a non-answer.** It ignored an injected instruction correctly, but did not say what operational demand
  includes or excludes.
- **W04, W19: gaps.**
  - W04 gives two demand values, but not the rise between them.
  - W19 omits that the reserve forecasts had been cancelled.

**Paid API use for the whole Live work:** USD 4.2920 counted of a USD 5.00 cap. Real paid use is at most USD 4.2840.
v4 itself counted USD 0.476.

### Known limitations

- **Live quality:**
  - Live is experimental, and the full L3 rule is unverified.
  - The pass margins are thin, and relevance was judged by the developer.
  - Known failure modes remain: citation-ID mismatches in document answers; omitted decisive facts; derived
    quantities left implicit; answers that describe a source instead of answering.
  - The 40-case hosted evaluation has not been run.
- **Evaluation scope:** every set uses the same 8 events (late July – August 2026), data and document corpus. Only
  the questions are new, so results are not a general accuracy claim.
- **Validators:**
  - They check numbers, quotes, times, units and wording, not whether an explanation is apt.
  - Notice-timing checks are lexical.
  - The question trigger for notice timing matched about 80% of blind paraphrases.
  - The check does not verify that the right notice is named.
- **Source governance** (separate from answer quality):
  - `publisher-refresh` reports REVIEW NEEDED for AEMO's re-issued DUDETAILSUMMARY archive. The pin is kept pending
    a decision (`docs/source-review-2026-09-28-mmsdm_dudetailsummary.md`).
  - 74 market notices have rolled off NEMWeb, so builds **without** access to the approved-bytes store are not
    identical.
  - NASA POWER served one intermittent inconsistent response.
- **CI:**
  - Restoring the approved bytes downloads the store's 310 release assets one by one. On days with many pushes this
    can exhaust the workflow token's API quota ("rate limit exceeded for installation"), and it did on 2026-09-28.
  - A fix that restores from one verified bundle asset is prepared on branch `ci-store-bundle-fix`, and its bundle
    release is published. It is **not included in v1.0**.
- **Operations:** a Live run can be interrupted if the calling session ends. The resumable driver
  (`scripts/live_resumable.py`) and a pre-registered interruption rule handle this.

Full details: `README.md`, `docs/live-gates.md` (all Live gates and held-out results) and `docs/pinned-store.md`.
