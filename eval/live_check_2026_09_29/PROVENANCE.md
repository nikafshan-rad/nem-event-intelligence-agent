# Fresh cases F01–F04: provenance

- **File:** `cases.json`, 4 cases (F01, F02 document; F03 notice; F04 adversarial), written on 2026-09-29. It was
  frozen with `PROTOCOL.md` before any paid call.
- **Protocol:** held-out v4's, at small scale. See `eval/holdout_v4/PROVENANCE.md`.

## Writer

A fresh subagent with no conversation history, working only inside a kit directory outside the repository.

**The kit contained:**
- `BRIEF.md` (copied here): v4's brief with the size and mix changed to 2 document, 1 notice and 1 adversarial case,
  and "do not ask about operational demand" added so the set stays separate from W20;
- `DATA.md`, identical to v4's;
- copies of the pinned data store (six tables) and `corpus.sqlite`, byte-identical to the repository's;
- `events.json`, the 8 verified events and their thresholds;
- a fresh Python environment with only `duckdb` and `pytz` (the project package cannot be imported);
- `overlap/`: SHA-256 hashes of every 6-word sequence in the 94 earlier questions (`eval/cases.json` and held-out v2,
  v3 and v4) and in prompts v11, with a checker.

**Not in the kit:** the repository, its code, prompts, analyses and Live outputs, and the text of earlier questions.

**How the writer worked:**
- It listed every file it read and every command it ran, all inside the kit. It did not open the hash file.
- One large query output was saved by the harness to a file outside the kit; the writer did not open it.
- Its first wording check flagged F03 (1 sequence) and F04 (3 sequences). It reworded both, keeping region, date,
  measure and gold, until the check printed none.

## Independent gold check

A second fresh subagent, under the same kit-only rules and barred from `overlap/`, re-derived every gold item with its
own queries.
- **Result: 4/4 PASS** (`VERIFICATION.json`).
- **Numbers:** F04's three row-backed numbers were confirmed by `row_id`, region, time and value. Its derived interval
  count gives the same result under five window-boundary conventions.
- **Citations:** the three snippets are verbatim, each in the passage that answers its question. F01 and F02 cite
  different procedures.
- **Reviewer note (F03):** a notice issued on 1 August says another SA line was also out on that date. An answer that
  also mentions it should not be penalised.

## Blind compatibility check by the developer (counts and IDs only)

```
python scripts/blind_check_heldout.py eval/live_check_2026_09_29/cases.json --split fresh_2026_09_29 \
  --prior eval/cases.json eval/holdout_v2/cases.json eval/holdout_v3/cases.json eval/holdout_v4/cases.json \
  --prompts src/nem_agent/prompts/v11
```

- **Clean:**
  - 3/3 row-backed gold numbers resolve in the repository's store, plus 1 derived count;
  - 3/3 snippets are verbatim in the repository's index;
  - every case builds a request;
  - no 6-word overlap with the 94 earlier questions or the prompts, and no duplicates.
- **Expected mix line:** the script's only "problem" is a mix mismatch. It is expected: the script hard-codes v4's
  20-case mix. The code was not changed.
