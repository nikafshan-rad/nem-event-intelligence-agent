# Release notes

## v2.0.0 (2026-10-04)

The second release records what the system does today, and what the evidence shows, as of `main` `0f02799`
(pull requests #8–#78 since v1.0). It adds typed, code-computed answers for demand maxima and forecast
comparisons, keeps them apart from the language model's interpretation, and resolves what a question asks for into a
request contract before any tool runs.

> **Live (LLM) mode remains experimental.** This release does not certify Live reliability. It is not an L3 result,
> it is not production-ready, and it is not evidence of generalisation. Replay, which uses no language model, is the
> verified baseline. Every historical PASS and FAIL, frozen protocol, gold file and record is unchanged.

### What is new since v1.0

- **Verified demand maxima (D24, D25, D26).**
  - **What is computed:** a requested maximum of dispatch total demand (5-minute) or operational demand
    (half-hourly), over a whole local day, a price event's window or a stated window. Code computes it from the
    pinned data.
  - **Admission:** the result is admitted only after the runtime verifier re-derives it from the store. It is then
    rendered deterministically in the report's `answer`, in both Live and Replay.
  - **Under a cutoff:** a maximum that cannot be established is stated as "not established", together with the
    highest value held.
  - **Read back from JSON:** a result is not trusted until `results.verify_loaded` has re-derived it.
- **Typed forecast comparisons (D27, D28).**
  - **The computed answer:** a forecast review's requested comparison is either `forecast_point` (one half-hour's
    forecast and actual pair) or `forecast_aggregate` (MAE and mean error over the pairs it lists).
  - **Statuses:** `established`, `partial` or `unavailable`. In the rendered answer, a result the verifier did not
    admit is `not_verified` and shows no value.
  - **Resolved before any tool:** the operation (a forecast value, one half-hour compared, or a period compared) and
    the exact half-hour or period.
  - **No defaults:** a whole local day is used exactly. Windows over the forecast tools' 24 hours, and periods that
    cannot be read, are sent back for clarification rather than replaced.
- **Computed answers kept apart from the interpretation (D25).**
  - **Report format "2":** `answer` holds the computed answer rendered by code, and `summary` holds only the
    interpretation (the model's lines in Live, the scripted lines in Replay).
  - **New validators on the interpretation:**
    - a stated time must match the time of the evidence it cites (I-15);
    - a requested forecast run must not be replaced by another (I-16);
    - requested maxima and requested results must not be replaced or contradicted (I-17, I-19);
    - aggregate coverage must not be overstated (I-20).
  - **Fallbacks:** a facts-only fallback keeps a verified requested maximum and withholds the model's notes (I-21).
- **Current routing contract: route contract v15, prompts v16 (D26, D28, D29).**
  - **One routing call:** gpt-5-mini, strict JSON schema, at most 2,000 output tokens. It returns the intent, region,
    date and cutoff words, and `requested`:
    - the forecast run;
    - the demand maximum;
    - the forecast request: operation, scope, domain, the requested clause, and any unsupported part.

    Each item comes with the question's own words.
  - **Code converts every time** from those words and resolves each request with its provenance. A request that is
    unresolved or in conflict is sent back before any tool runs.
  - **Only a resolved operational-demand request** enters the demand-forecast workflow (D29). A weather, price or
    other forecast is named as not answered, and the demand-forecast tools are blocked for it.
  - **Incomplete or invalid routing responses** are rejected (I-14) and never reach a tool.
- **Also new:**
  - plain display text (I-4);
  - evidence-backed exclusions shown apart from hypotheses (I-7c);
  - routing and answer fixes I-8 to I-13;
  - bounded diagnostics of hosted-model calls (D23);
  - restore of the approved bytes from one bundle asset, which fixes the CI quota limitation listed for v1.0.

### Evidence, kept apart

#### Offline verification (no language model)

These are the repository's existing offline checks, re-run on the release code in a fresh checkout (details under
"Release checks" below). Re-running them uses no language model and makes no paid call. It is not a new evaluation:
no case, gold, threshold or protocol was added or changed.
- **Tests:** 2,245 pass. 3 are skipped, because the traces they read are git-ignored and absent from a fresh
  checkout.
- **Replay evaluation:** its gates pass. The figures against its frozen gold have changed since the README's
  2026-09-28 figures, by design, as D28 and D29 recorded:

  | | 2026-09-28 | Now |
  | --- | --- | --- |
  | Forecast gold, test | 5/5 | 1/5 |
  | Forecast gold, dev | 5/5 | 0/5 |
  | Status matches, test | 20/21 | 18/21 |
  | Scripted router | 19/20 | 17/20 |

  - **Why forecast gold fell:** forecast reviews now compare the whole local day that the question names, while the
    gold encodes an earlier 12-hour slice (D28).
  - **Why status fell:** FC02 and AMB06 are now sent back (D28, D29).
  - **Unchanged:** numeric traceability and citation validity stay at 100%.

  This release corrects the stale README figures. The frozen gold is unchanged.
- **Retrieval evaluation:** unchanged (Recall@5 16/21).
- **Safety suite:** 24/24 detected.
- **API smoke test and app startup check:** pass.
- **Lint and type checks:** clean.
- **Data:** the data store and document index rebuild from the approved-bytes store without contacting a
  publisher.

Offline checks measure tools, retrieval, validators, request resolution and templates. They are never evidence of
Live quality.

#### Demonstrated Live outcomes (gpt-5-mini; small samples, each run once; counts, not rates)

| Check (date) | Code | What ran | Verdict, as recorded | Key counts |
| --- | --- | --- | --- | --- |
| Live check (2026-09-29) | `bab1c3d` | W20 and 4 fresh questions | not an L3 result | no fallback; 1 of 4 fresh answers complete |
| Held-out v5 (2026-10-02) | `e5bb00e` | 20 independent cases | **L3 FAIL** | gold labels 13/18 (bar 15); relevance 13/20 (bar 16) |
| Held-out v6, runs A–C (2026-10-02) | `6413076` | 20 independent cases | **L3 FAIL** | gold labels 11/18; relevance 14/20; an H4 value/time mismatch (Z03) |
| Targeted I-15–I-17 (2026-10-02) | `cf9558e` | 18 cases | **FAIL** | 4 incorrect targeted answers (X); wrong numbers stated as fact (H4) in 5 answers |
| v12 routing extraction (2026-10-03) | `f2455ca` | 42 routing, 5 end to end | **FAIL** | 0 wrong bindings; 4 of 42 cut off; K09 X; K05 H4 |
| gpt-5-mini against gpt-6.1-sol (2026-10-03) | `205974b` | development cases | **does not support a switch** | gpt-6.1-sol: 11 correct bindings against 15; 6 of 43 calls cut off against 1 of 48 |
| Demand-maxima acceptance (2026-10-03) | `761290d` | 16 cases | **FAIL** (the independent reviewer's R03 and R04 readings, disputed, as recorded) | all 6 rendered results exactly right; result availability 6/11 (bar 8) |
| v13 routing only (2026-10-04) | `a648269` | 32 routing calls | **PASS** on what it accepts only: routing, on a development sample | 23/23 exact resolutions; controls 9/9; no call cut off |
| v13 end to end (2026-10-04) | `a648269` | 8 cases | **FAIL** | 5/5 correct verified results shown; R02 H4 (an MAE over 21 pairs given for one requested pair) |
| v15 routing diagnostic (2026-10-04) | `d38eb4d` | 34 routing calls | **FAIL** (combined, as frozen) | supply 3/20; containment 12/12; model readings 23 correct, 5 incorrect, 6 none |

- **L3 status:**
  - held-out v4 met its own criteria on v1.0 code, but its full L3 rule is unverified;
  - v2, v3, v5 and v6 failed;
  - no L3 evaluation has run on code after `6413076`.
- **This release's code** differs from `d38eb4d` only in its version string. Its one Live check is the v15 routing
  diagnostic, which covers routing only. No end-to-end Live run has used route contract v15 and prompts v16.

#### Not verified

- **Live answer quality** on this release's code, end to end.
- **L3** on any code after `6413076`.
- **The 40-case hosted evaluation:** never run.
- **Real-model request extraction** beyond the samples above, and generalisation to other events, dates, data or
  wordings.
- **Any model other than the snapshot that served the recorded Live runs.**
  - **The IDs:** the code requests the alias `gpt-5-mini`. Every saved Live record that captured the model the API
    reported shows the snapshot `gpt-5-mini-2025-08-07`, including all 34 calls of the v15 diagnostic. Older records
    store only the requested alias.
  - **The notice:** OpenAI's deprecations page
    (<https://developers.openai.com/api/docs/deprecations#2026-06-11-gpt-5-and-o3-model-deprecations>, read
    2026-10-04), in its entry "2026-06-11: GPT-5 and o3 model deprecations", says it notified "developers using older
    GPT-5 and o3 model snapshots of their deprecation and removal from the API on December 11, 2026". Its table lists
    `gpt-5-mini-2025-08-07` with shutdown date Dec 11, 2026 and recommended replacement `gpt-5.6-terra`.
  - **What the notice does not cover:** it names the dated snapshot only, not the alias `gpt-5-mini`, and does not
    say what the alias will serve after that date.
  - **Consequence:** Live behaviour on any other model or snapshot is unverified.

### Known limitations

1. **Correct readings rejected or mis-resolved by the resolver:**
   - **v15 diagnostic:** 10 of the model's 23 correct readings were lost in total.
     - **Rejected, 9.** They were sent back: contained, but the question was not answered.
       - 8 by D29's clause-containment rule (D01 ×2, D02 ×2, D03 ×2, D07, N07).
       - 1 because "noon" was not read (N07).
     - **Mis-resolved, 1.** N04 noted a declined weather forecast as unanswered, which is a scored violation.
   - **Earlier checks:**
     - vocabulary gaps ("daily high", "midday", an event named by its ID);
     - span rules (a missing peak word; the several-dates rule);
     - in the maxima check, two completed readings (D01, F06) were rejected by the controller's check of the
       reading, and one (F07) was asked which window was meant.
2. **Ambiguous forecast readings accepted in Live:**
   - **D08:** in the v15 diagnostic, "the latest issued forecast" was bound as an operational-demand forecast, with
     the demand-forecast tools eligible.
   - **Unnamed forecasts:** all three completed readings of the unnamed-forecast questions read operational demand.
     N03's two were contained only incidentally, by clause containment.
   - **Undetectable by D29's checks:** a forecast whose kind is not named, read by the model as demand
     (`test_misreadings_the_checks_cannot_detect`).
   - **Replay** sends such questions back.
3. **Routing truncation** (routing is capped at 2,000 output tokens, mostly reasoning tokens):
   - **Calls cut off:** 4 of 42 (v12), 0 of 32 (v13), 6 of 34 (v15). Under v15 the median routing output was 1,560
     tokens.
   - **Effect:** a cut-off response is rejected and the question is sent back. This fails closed, but costs supply.
   - **D06:** in v15 call D06, parser-derived binding metadata remained in a sent-back record. It was scored as a
     wrong binding, though nothing ran.
   - **OpenAI's guide** suggests reserving at least 25,000 tokens for reasoning models when starting out. The cap has
     not been changed or re-measured.
4. **Interpretation errors:**
   - **In answers** (the model's text about results code computed correctly):
     - R02 (v13 end to end): an MAE over 21 pairs presented for the single requested pair (H4);
     - K09 (v12): a headline contradicting the controller's correct maximum (X);
     - K05 (v12): an MAE window misdescribed (H4);
     - Z03 (v6): a value stated for another half-hour (H4);
     - fallback caveats denying a maximum, in wording outside the lexical checks (model comparison).
   - **In routing** (v15): among 28 completed readings, errors were in the domain (3), the date (2) and the run (2).
   - **The validators that check interpretation are lexical,** so wording outside their patterns passes.
5. **Fallback frequency.** A facts-only fallback shows validated tool facts and a verified computed result, without
   the model's interpretation. The table counts different sets, so the total is not a rate:

   | Check | Cases | Facts-only fallbacks |
   | --- | --- | --- |
   | Held-out v4 (v1.0 code) | 20 | 2 (W10, W14) |
   | Held-out v5 | 20 | 1 (Y02) |
   | Held-out v6, run B | 20 | 2 (Z02, Z09) |
   | Targeted I-15–I-17 | 18 | 1 (Z05) |
   | v12 end to end | 5 | 0 |
   | Model comparison, gpt-5-mini | 5 | 2 (K07, K09) |
   | Demand-maxima acceptance | 16 | 2 (D03, D04; each kept the correct computed result) |
   | v13 end to end | 8 | 3 (D01, F02, F06; each kept the correct computed result) |
   | **Total** | **112** | **13** |

6. **Carried over from v1.0:**
   - the evaluation-scope, validator and source-governance limitations still apply;
   - the DUDETAILSUMMARY re-pin decision is still pending;
   - market notices keep leaving NEMWeb, so builds without the approved-bytes store are not identical;
   - the CI restore-quota limitation is fixed.

### Compatibility and migration

- **Package and API:**
  - The package version is now `2.0.0`, up from `0.1.0`, which v1.0 had left unchanged. `GET /health` returns
    `"version": "2.0.0"`.
  - The endpoints, the `InvestigateRequest` fields and the `POST /investigate` envelope (`report`, `trace_id`,
    `latency_ms`, `usage`, `tool_calls`) are unchanged.
  - `GET /schema/report` returns the extended report schema.
- **Report (`InvestigationReport`):**
  - **`schema_version`:**
    - `"2"` when the report carries a computed answer: `answer` holds the rendered results, and `summary` is the
      interpretation only;
    - `"1"` otherwise, where `summary` holds everything shown, as before;
    - a record with no `schema_version` reads as `"1"`.

    `nem_agent.report.summary_v1(report)` reads either format as format 1.
  - **New fields:** `answer`, `results` and `ruled_out_explanations`; `validation` gains keys. A reader that rejects
    unknown fields (for example the v1.0 model with `extra="forbid"`) rejects v2.0.0 reports.
  - **`forecast_comparison`** is filled only from the controller's verified aggregate, never from the model's choice.
  - **Displayed text:** tool names, internal fields and evidence-ID markers are rewritten into plain words outside
    quotations. Each changed line keeps its original in `validation.display_rewrites`.
- **Result schemas:**
  - Dispatch on each result's `schema_version`: `analytical_result/1` (a demand maximum) or `forecast_result/1` (a
    forecast comparison).
  - A reader that assumes every result is a demand maximum rejects forecast results.
  - Results read back from JSON carry the producing server's verification statement. Re-verify them against the
    pinned store (`nem_agent.results.verify_loaded`) before relying on them.
- **Routing decisions, traces and saved records:**
  - Traces carry route contract v15 decisions, and `versions.prompt` is `prompts/v16`; prompts v1–v15 are kept.
  - Decisions recorded under contracts v12–v14 are read through adapters. A field missing from an older decision
    means "not reported", never "no requirement".
  - Saved records under `artifacts/` still validate.
- **New clarification reasons:**
  - **The texts:** forecast operation, scope, kind, unsupported kind and window-limit clarifications.
  - **Readers** should use `status` (`needs_clarification`), not match on reason text.
  - **Questions:** a forecast question must say what is forecast. Replay sends back an unnamed forecast with
    "Which forecast is the question about?".

### Installation, startup and smoke checks

From a clean checkout of the tag (Linux or Codespaces, Python 3.12 or later; no API key needed, and no paid call is
made):

```bash
make setup                 # .venv with pinned dependencies; prints "nem_agent 2.0.0 python <version>"
make store-verify          # the approved-bytes index covers every pin (no network)
make restore-pinned        # repository collaborators: approved publisher bytes, SHA-256 verified (needs GH_TOKEN)
make data && make index    # data store and document index
.venv/bin/python -m nem_agent.cli publisher-downloads --expect-none   # the pinned build contacted no publisher
make lint typecheck test   # 2,245 tests pass; 3 skip without the git-ignored traces
make eval && make safety   # Replay evaluation and SYNTHETIC safety suite
make smoke                 # API: /health ("version": "2.0.0", status ok), a validated Replay investigation,
                           # a 422 for bad input, and a 400 for live without a key
make app                   # Streamlit on port 8501; make api: FastAPI on port 8000 (docs at /docs)
```

Expected: `data_version` `8c14c217f5570d32` and `corpus_version` `221b6ea0f21e006d`, the same as v1.0.
- **Without the store,** builds download from AEMO and NASA and verify every file. They are not identical, because
  notices have rolled off NEMWeb.
- **Live** needs `OPENAI_API_KEY` and is paid. See the README.

### Release checks on the candidate commit

- **What they are:** the repository's existing offline checks, re-run. They follow CI's sequence in a fresh git
  worktree, with no API key, a scratch budget ledger and a new virtual environment.
- **What they are not:**
  - a new evaluation: no case, gold, threshold or protocol was added or changed;
  - a Live run: no language model was called and no paid call was made. The Replay evaluation (`make eval`) is the
    existing 40-case offline evaluation, re-run.
- **The record:** `artifacts/release/v2.0.0/CHECKS.md`.
- **Steps:** install, version, lint, type check, store index, restore, data build and check, document index, the
  publisher-download check, tests, the Replay evaluation, the retrieval evaluation, the safety suite, the demo, the
  API smoke test, and the Streamlit startup.
- **Result:** every step passed on the release code (commit `5199800`, Python 3.14.2). That commit's `src/` tree is
  the release candidate's; the candidate adds documentation and this evidence only.
- **Candidate checks:** the release pull request reports the same checks on its exact head commit, with CI on
  Python 3.12 and 3.14.
- **Regenerated artifacts:** these committed Replay artifacts were made with earlier code (2026-09-25 to
  2026-09-28), and regenerating them changes them:
  - `artifacts/eval/offline.json` and `artifacts/eval/report.md`;
  - `artifacts/replay_*.json`;
  - `artifacts/api_smoke_transcript.json`.

  How they differ:
  - **The event-review and definition demo records:** the outcome is unchanged, and the README's quoted sample
    output still matches.
  - **The forecast demo record:** it changed as D28 specifies. It now compares the whole local day, with 38 pairs
    and an MAE of 89 MW, instead of a 12-hour slice with 24 pairs and an MAE of 33 MW.
  - **The evaluation:** it differs in the figures above.

  All of them are kept as committed. The current Replay evaluation and the details are in
  `artifacts/release/v2.0.0/`.

### Next version (direction only; not in this release)

D31 (`docs/decisions.md`) records the direction for the next version: a one-call typed request plan and a
deterministic compiler.
- **The model:** reads each forecast mention's stance (asked, declined or background), its kind (or not stated),
  its operation and its scope.
- **Code:**
  - keeps admission, provenance, plan consistency and a stated-basis policy;
  - keeps time conversion, limits, permissions, computation, verification and rendering;
  - drops the lexical and quote-boundary checks from Live interpretation, for the new contract only.
- **Not done here:** nothing is implemented, and no evaluation is prepared. D30, a narrower change to the resolver,
  is paused.

### Paid API use to date

The task-wide ledger counts **USD 9.336937** over all Live work. Interrupted calls are counted at their worst case,
and the billed amount is not observed. This release made no paid call, ran no Live check, and created no new
evaluation.

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

- **CI:** passed on `main` `c5faf6c` (lint, type check, real-data build from the approved-bytes store, tests, Replay
  evaluation, safety suite; Python 3.12 and 3.14). The release-notes change after it touches documentation only.
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
