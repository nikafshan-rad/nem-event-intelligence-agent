# Brief: independently verify a held-out evaluation set (20 cases)

Another agent has written 20 evaluation cases for a research assistant about Australia's National Electricity Market,
following `BRIEF.md` in this kit. Your job is to check every case **with your own queries**, independently of how the
writer derived it. Work **only inside this kit directory**. The rules for doing so are at the end.

## What to read

- `BRIEF.md`: what the cases must contain (read it first; the rules there define a correct case).
- `DATA.md` and `data/`: the data and document passages.
- `out/cases_holdout_v6.json`: the cases to check.

## What to check, for each case

1. **Gold numbers:** re-derive every gold value with your own SQL on `data/` (use `venv/bin/python` with `duckdb`, or
   `sqlite3`). For a row-backed number, confirm that `source_row_id` is the right row (region, time, measure; the
   window's peak or minimum where the question asks for one; the latest revision for actual demand unless the question
   is "as of"; the designated or as-of forecast run) and that the value matches within its tolerance. For a derived
   count (`intervals_meeting_threshold`), recount it, and note whether a different window convention would change it.
2. **Citations:** confirm the snippet is copied verbatim from a passage of the cited document (at least 20 characters),
   and read the passage: it must answer the question.
3. **As-of cases:** confirm the cutoff, and that the gold values were public by it (`available_at_utc` ≤ cutoff; the
   latest run available as of T is the run with the greatest `issued_at_utc` among rows public by T).
4. **Expected fields:** `intent`, `answerable`, `status_in`, `required_tools`, `must_not_contain`, `findings_region`,
   `kind`, `no_retrospective_evidence` and `check`, against the brief.
5. **Mix and IDs:** exactly the brief's category mix, IDs Z01–Z20, split `holdout_v6`, `request` `{}`.
6. **Strata:** exactly 6 cases are `"unused"`: the 5 notice cases, each citing a notice listed in
   `data/unused_pool.json` (at most 1 with `"routine_price_review": true`), and 1 market_event or forecast case on
   TAS1, 29 July 2026 local time (2026-07-28T14:00:00Z to 2026-07-29T14:00:00Z), all of whose gold rows are from that
   day. Every other case is `"familiar"`, and its event-based material is a listed event.
7. **Answerability:** the question is answerable from the data as the brief intends (or deliberately not, for the
   clarification and refusal cases), and is unambiguous enough that the gold labels are the only reasonable answer.
8. **The writer's flags:** check each case the writer asked you to look at.

## Output

Write `out/VERIFICATION.json`:

```json
{"verified_by": "independent verifier (agent)", "generated_at": "<UTC>", "file_sha256": "<SHA-256 of the cases file>",
 "result": "PASS|REVISE", "cases": [{"case_id": "Z01", "verdict": "PASS|REVISE", "checks": "<what you checked>",
 "note": "<anything a reviewer should know, or why it must be revised>"}]}
```

`result` is `PASS` only if every case passes. A case that is wrong in any respect is `REVISE`, with the reason. Do not
edit the cases file yourself.

## Independence rules (important)

- Read and run only what is inside this kit directory (`BRIEF.md`, `VERIFY.md`, `DATA.md`, `data/`, `venv/`, `out/`).
  Do **not** open `work/` (the writer's working files), `overlap/` or `MANIFEST.json`. You may create a directory
  `verify/` for your own scripts.
- Do **not** open, list or search anything else on this machine, in particular anything under `/workspaces`, `/tmp`
  outside this kit, or your home directory. Do not use the web.
- In your final message, list every file path you read and every command you ran, and give each case's ID, category,
  stratum and verdict, with a short reason for any REVISE. Do not quote any question or gold value in that message.
