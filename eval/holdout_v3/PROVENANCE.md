# Held-out set v3: provenance

- **File:** `eval/holdout_v3/cases.json`, 20 cases, SHA-256
  `81337e55e3e139396c57f81dbd889154f4edb624a2c644187c16b9e142ebee07`.
- **Frozen:** 2026-09-28, before any Live run on it. It will not be edited after results are seen.
- **Pass rule:** `PASS_RULE.md`, SHA-256 `ef2c9968183dd27daa3c79919677f4f63c420dfa7fe86b085553a120badeca00`.
  It was written while the writer was still working, before the developer had seen any case.
- **Cases with gold labels:** G = 18, so the Q3 bar is ⌈0.8 × 18⌉ = 15.

## Writer

A fresh subagent with no conversation history.
- **Kit:** a directory outside the repository containing:
  - `BRIEF.md` (copied here; SHA-256 `41bb1b18…`): the v2 brief with only the case count, mix, file name, split and
    ID prefix changed;
  - `DATA.md` (copied here; identical to v2's);
  - copies of the pinned data store and the document corpus (each file's hash equal to the repository's);
  - the 8 verified events and the analysis threshold;
  - its own Python environment.
- **Not in the kit:**
  - the repository and its failure analyses;
  - the prompts and source code;
  - any Live output or trace;
  - the 54 earlier questions (the 40 in `eval/cases.json` and the 14 in held-out v2);
  - the v2 writer's output;
  - the notice-trigger paraphrase sets.
- **Access:** it was told not to access anything outside the kit. It listed every file it read and every command it
  ran, and all were inside the kit.
- **Mix:** 4 market_event, 4 forecast (2 as-of), 4 document, 3 notice, 2 ambiguous_unavailable (1 clarification,
  1 refusal), 2 adversarial, 1 injection. Case IDs V01–V20.

## Independent gold check

A second fresh subagent, with the same kit-only rules and barred from the writer's working files, checked the set.
- It re-derived every gold value with its own queries: 18 row-backed numbers and 5 interval counts.
- It checked every citation snippet verbatim against its passage (8), and that the passage answers the question.
- For the as-of cases, it checked the rows were the latest public ones at the cutoff.
- It checked every expected field against the brief.
- **Result: 20/20 PASS.** The verdicts are in `VERIFICATION.json`.

## Blind compatibility check by the developer (counts and IDs only)

- **Mix and gold:** the category mix is as required. 18/18 row-backed gold numbers resolve in the repository's own
  store, and 8/8 snippets are verbatim in its index.
- **Loading:** every case builds an `InvestigateRequest`, and the runner's loader reads the file.
- **First draft, two problems:**
  - V20 carried `kind` in `request` as well as `expected`. The runner builds the request from `request`, so the case
    would have crashed.
  - V01, V02, V03, V05, V06, V08 and V18 each shared a 6-word sequence with one of the 54 earlier questions. None
    shared one with the prompts, and none was an exact duplicate.
- **Revision:** both problems were sent back to the writer, identified by case ID only.
  - The writer received a checker holding only SHA-256 hashes of the earlier 6-word sequences, so it never saw the
    earlier questions.
  - It reworded those 7 questions and removed `request.kind`.
  - A mechanical diff confirmed that nothing else changed: no gold value, expected field or other case.
  - The verifier re-checked the 8 changed cases: PASS, so **20/20** overall.
  - The final file has no 6-word overlap with the earlier questions or the prompts.
- **The developer did not read the questions, labels or gold values** before freezing, and will not before the run.

## Points flagged for the human reviewer (by case ID)

- **Writer:**
  - V01, V02, V03, V04, V18: the interval-count golds set `valid_at_utc` to the window end (the scorer does not use
    it for counts).
  - V01: a gold price row is marked NOT FIRM.
  - V07, V08: a forecast run is named by an approximate issue time (a few seconds off).
  - V16, V17: `group` holds 'documents' or the one event mentioned.
- **Verifier:**
  - V02: the question's calendar day starts before the data does (the count is the same either way).
  - V13: the notice's incident time is before the grouped event's window (metadata only).

## Scope

v3 uses the same 8 events, data and document corpus as every earlier set. Its questions are new, but the underlying
events, notices and documents are ones the system has been developed on.
