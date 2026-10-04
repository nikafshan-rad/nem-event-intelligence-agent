# Provenance of the cases and gold (preparation record; no paid call)

## Order of work (2026-10-04, UTC)
1. **The protocol was pre-registered first.** `PROTOCOL.md`, with the owner's decisions, classes, criteria and caps,
   was committed and pushed as `78e6f47` at 09:35:33Z, before any fresh question was written or any gold drafted.
2. **The writer's kit was built outside the repository** (`build_kit.py writer`, 09:39:00Z). Its `MANIFEST.json` has
   SHA-256 `81a602b9…5430d`. It holds:
   - `WRITER_BRIEF.md`, `CAPABILITIES.md` and `GOLD_FORMAT.md`, each byte-identical to the copies here;
   - the data facts: the eight events and the data period;
   - a Python environment with the standard library only;
   - the overlap checker: SHA-256 hashes of every 6-word sequence in 245 earlier questions (every `question` in
     `eval/` and `artifacts/live/`), in the prompts v16 files, and in D28's and D29's test files and
     `docs/decisions.md`. No earlier text is in the kit.
3. **The writer, step 1.** A fresh agent, working in its kit only, wrote N01–N07 with its reading of each
   (`out/fresh.json`, 09:43:18Z).
   - The overlap checker's final output: `cases with overlap: none`.
   - Its output is copied here unchanged as `WRITER_OUTPUT.json`, SHA-256 `913b0883…80672`.
4. **The familiar step was added to the writer's kit only then** (`build_kit.py familiar`, 09:45:48Z):
   `WRITER_BRIEF_FAMILIAR.md` and `familiar/questions.json`. `FAMILIAR_MANIFEST.json` (SHA-256 `edf7a963…54a25`)
   records `out/fresh.json`'s hash at that moment, which is unchanged since.
5. **The writer, step 2.** The same agent wrote its reading of D01–D10 (`out/familiar.json`, 09:49:13Z).
   - It is copied here unchanged as `WRITER_FAMILIAR.json`, SHA-256 `f18aa4ca…1a776`.
   - `out/fresh.json` was unchanged (the agent hashed it before and after).
6. **Gold was built by `gold.py`** from the writer's two outputs: `cases.json` (SHA-256 `69c2b3ec…edafe9`) and
   `GOLD.json`.
   - **The mechanical checks pass:** fields, anchors, the half-hour grid, half-hour counts, local-time conversions,
     and each case's outcomes within its set.
   - **`gold.py --cross-check`:** the gold agrees with every item of the frozen verified sources. Those are K14's and
     K06's run rules, targets and issue time; Y07's, H06's and Z07's cutoffs and targets; FC02's cutoff and peak target;
     and F07's maximum and cutoff.
7. **The reviewer's kit was built separately** (`build_kit.py reviewer`, 09:50:51Z). Its `MANIFEST.json` has SHA-256
   `97eea26e…3fb3b1`. It holds:
   - `REVIEW_BRIEF.md`, `CAPABILITIES.md` and `GOLD_FORMAT.md`, byte-identical to the copies here;
   - the same data facts and environment;
   - `questions.json`: the 17 questions with their request fields only. There is no gold, no intended reading and no
     set.
8. **The reviewer, blind.** A second fresh agent, working in its kit only, gave its own reading of all 17 questions,
   with every bound computed by its own code (`out/review.json`, 09:54:45Z).
   - It is copied here as `REVIEW.json`, SHA-256 `f4c44616…ef054f`.
   - **`gold.py --compare REVIEW.json`:** the reviewer and the gold agree on every gated item of D01–D07, D09, D10 and
     N01–N07. That covers outcome, region, domain, operation, scope bounds and half-hour count, run, cutoff, maximum,
     unsupported parts, tool eligibility and intents, with no anchor of one reading excluded by the other.
   - **D08 differs only in its primary reading** (see "Disagreements").
9. **The reviewer, D08 follow-up.** This came after its blind reading was fixed. The reviewer was told the owner had
   pre-registered two acceptable outcomes for D08, and was asked to read D08 as an operational demand forecast
   request; it was given none of the gold's values.
   - Its record is `REVIEW_D08.json` (09:57:36Z, SHA-256 `c4e8c04a…3ae2`).
   - **`gold.py --compare-alternative REVIEW_D08.json`:** the gold agrees with every item checked. The operation is a
     forecast value; the target is the SA1 31 July event's peak half-hour, (2026-07-30T16:30Z, 17:00Z]; the run is
     as_of_availability; the cutoff is 2026-07-30T14:35Z; the tools are eligible; there are no unsupported parts.
   - The reviewer judges the target unique once `CAPABILITIES.md` is applied: the only "peak half-hour" it defines is
     a price event's, and one SA1 event falls on that date.

## The agents
- **The writer and the reviewer** were fresh agents of the same kind. Each was told to work only in its kit outside
  the repository, to open, list, search and run nothing else, and not to use the web.
- **Each reports** every file it opened and every command it ran, and confirms it stayed in its kit. Their reports
  are `WRITER_REPORT.md` and `REVIEW_REPORT.md`.
- **The report files:** the harness did not let either agent write a report file. Each gave its report in its reply,
  and the reports are copied here unchanged under a short heading.
- **Context the environment added:** each agent disclosed that its session started with context the environment adds
  to every agent session. That context was the developer's memory index (titles), a git-status snapshot with
  repository file names and recent commit titles, and the account's e-mail address. Each says it opened none of it
  and used none of it.
- **The isolation is by instruction:** the agents had tools that could read files, and their own reports are the
  record of what they read.

## Disagreements and findings for the owner (none resolved by the developer)
- **D08 (FC02).** Both independent agents judge that, under `CAPABILITIES.md`, the demand reading should not be
  acceptable: "the latest issued forecast" does not show what is forecast. Both would accept
  `clarify_which_forecast`, and also `event_review_unclear`.
  - The owner pre-registered clarify_which_forecast and the demand reading. The gold keeps exactly those two.
  - The demand reading's fields are independently verified (step 9).
  - Whether to keep the demand reading, or to add `event_review_unclear`, is the owner's decision. Changing either
    would mean rebuilding the gold and the freeze.
- **N04 and N07: known before the run** (`PROTOCOL.md`, "Known before the run"). With correct readings, the merged
  code fails N04 and cannot supply N07, so the check cannot PASS as frozen. These are outcomes of the code, found by
  the developer's offline dry run after the gold was built. The questions are not changed.
- **D05, the weakest supply case.** Both agents read "the 23:00 to 23:30 UTC half-hour" as 2026-08-19, from the
  question's only date. Both note that a stricter reader might ask for the date.
- **D05, D06 and D07, event peaks.** Their half-hours coincide with event peak half-hours. Both agents label them
  `half_hour` only, because the questions name them by clock time, and the gold does the same.

## The developer's offline checks
- **Careful readings of every configuration,** through the real per-call runner and the fake transport. They are
  SYNTHETIC decisions, written as a careful reader following prompts v16 would answer
  (`tests/eval/test_livecheck_route_v15.py`).
  - Each makes exactly one routing call, with no dispatcher, tool or synthesis.
  - Each leaves a complete record.
  - Each is classed as its gold says, except N04 (a violation) and N07 (an unnecessary clarification), both known
    before the run.
- **Reservations:** each configuration's actual routing request was measured, with no call and no ledger write. Every
  one is within USD 0.006 (`FREEZE.json`).
- **Real files:** no real ledger, frozen material or application code was changed.

## Changes after the pre-registration commit (before any run; no rule changed)
- **`PROTOCOL.md`:** the section "Known before the run" was added.
- **`REVIEW_BRIEF.md`:** before the reviewer's kit was built, a general instruction was added. When a resolved reading
  is among the outcomes the reviewer would accept, it fills in that reading's fields. It names no case.
- **`gold.py`:** the gold records each case's resolved reading explicitly (`resolved_reading`), derived mechanically
  from the fields the writer filled. D08's own domain reading is `unclear`, and its pre-registered demand reading is
  `operational_demand_forecast`, so the scorer reads the demand alternative from the fields and not from that label.

## Amendment 1 (before any run; `AMENDMENT_1.md`)
The owner instructed it on 2026-10-04, after the first freeze (`6077d46`) and before any paid call. `PROTOCOL.md` and
`GOLD.json` are unchanged.

1. **The extraction step was added to both kits** (`build_kit.py extraction`, 10:29:42Z). Each kit gained
   `EXTRACTION_FORMAT.md` and `extraction/questions.json`, the same 17 questions with request fields.
   - Each `EXTRACTION_MANIFEST.json` records the hashes of that agent's earlier outputs at that moment.
   - The writer's manifest is `7260de42…` and the reviewer's is `d9452bbf…`.
2. **Both agents, independently and in their own kits** (outputs 10:33:43Z):
   - **Task A:** D08's final reading, after the owner withdrew the earlier instruction accepting the demand reading.
     Both give `clarify_which_forecast` and also accept `event_review_unclear`. Both reject `resolved`,
     `clarify_unsupported`, `event_review_unsupported`, `refusal` and `clarify_mixed`, with reasons. Their records
     are `D08_WRITER.json` (`3876c9f4…`) and `D08_REVIEWER.json` (`5266e5dc…`).
   - **Task B:** an extraction record for each question, per `EXTRACTION_FORMAT.md`. These are
     `EXTRACTION_WRITER.json` (`bb7aa522…`) and `EXTRACTION_REVIEWER.json` (`1af290fb…`).
   - Each agent's earlier outputs are unchanged by hash. Each reports every file and command, and says it stayed in
     its kit. Their reports are appended to `WRITER_REPORT.md` and `REVIEW_REPORT.md`.
3. **`amend.py`** built `GOLD_AMENDED.json` (`8ac78ab6…`) and `EXTRACTION_GOLD.json` (`500225c9…`).
   - The two authors agree on every label, local date, key word, cutoff and anchor of all 17 questions, and the
     extraction gold agrees with the amended gold.
   - Their intent sets differ for seven send-back questions, so intent is recorded there, not assessed
     (`AMENDMENT_1.md`, "Layer 1").
4. **Before the rules were fixed,** the developer reviewed the combined extraction gold. Three of the scorer's rules
   were set so as not to attribute errors to the model that neither author identifies:
   - intent is assessed only where the authors' intent sets agree;
   - a null run rule (no single demand run applies) is not assessed;
   - the forecast-clause item does not apply to D10, which asks no forecast.

   This was before any paid result existed. With them, SYNTHETIC careful readings of every configuration score as
   expected:
   - **correct end to end:** 14 configurations;
   - **N04:** a correct reading mis-resolved by code (a resolver defect);
   - **N07:** a correct reading rejected by code;
   - **D08:** a demand reading is an incorrect reading accepted by code.
5. **The re-freeze** uses the first freeze's order seed, so the call order is unchanged.
