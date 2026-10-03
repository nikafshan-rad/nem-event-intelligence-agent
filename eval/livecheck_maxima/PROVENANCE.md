# Provenance of the cases and gold (preparation record; no paid call)

## Order of work (2026-10-03, UTC)
1. **The protocol was pre-registered first.** `PROTOCOL.md`, with the owner's three clarifications, the criteria, the
   strata and the caps, was committed and pushed as `fbcd4e8` at 14:36:10Z, before any fresh question was written.
2. **The writer's kit was built outside the repository** (`build_kit.py writer`), with its `MANIFEST.json` SHA-256
   `5e49e2efecd6042320abf9bb486877b8b73459a572ce0bf07baadfca0a74a952`. It holds:
   - `BRIEF.md` (SHA-256 `9dde2c01…`) and a generated `DATA.md`;
   - the three store tables;
   - the 8 events, and `windows.json` (fully held windows, computed from the store);
   - the development-material list;
   - a Python environment with only `duckdb` and `pytz`;
   - SHA-256 hashes of every 6-word sequence in 237 earlier evaluation questions and the 3 prompt files of v12, with no
     text.
3. **The writer**, a fresh agent working in the kit only, wrote F01–F08 (`out/cases_maxima.json`, 14:44:24Z). It is
   copied here unchanged as `WRITER_OUTPUT.json`, SHA-256
   `d4442ff7f763f1e1e12fcd04f8949afa54a022be7ef898d4a48089779d763e7c`. Its report is `WRITER_REPORT.md`.
4. **The developer's scope review:** every question meets its stratum and the brief's data rules. **None was
   rejected, and none was reworded.**
5. **`cases.json` was assembled** (`build_kit.py cases`):
   - the reused cases are copied unchanged but for their case ID;
   - D04 adds the cutoff to Z04;
   - the fresh cases are as written.
6. **Gold was computed** by `gold.py`, written by the developer without reference to the application's code. The
   result is `GOLD.json`. D01–D03 agree with the frozen gold of K09, K11 and Z04.
7. **The checker's kit was built separately** (`build_kit.py checker`), with its `MANIFEST.json` SHA-256
   `4455bb4bfc44002fdf6ac5b71759f8ad691cef0c96511a1d9304cd19e493d5e1`. It holds:
   - `GOLD_CHECK_BRIEF.md` (SHA-256 `4c81f50e…`), `DATA.md`, the same tables and data facts, and the same environment;
   - `questions.json`: the 12 questions of D01–D04 and F01–F08, with their request fields only. No intended reading
     and no gold.
8. **The independent gold check:** a second fresh agent, working in its kit only, read each question itself and
   computed each result with its own code. It used two implementations, a script and a pure-SQL re-implementation,
   which agree.
   - Its output is copied here as `GOLD_CHECK.json` (SHA-256
     `6bf7c16e8f2ed6bc88e78d7ea7dbe7491f898a5ba77275a01265880e1646ff7c`), with its report as
     `GOLD_CHECK_REPORT.md`.
   - **`gold.py --compare GOLD_CHECK.json`: "GOLD.json and the independent check agree exactly."** That covers every
     reading (measure, region, window kind and bounds, event, cutoff, expected outcome) and every result field
     (status, value, unit, interval ends, source rows, counts, excluded rows and runner-up).
   - No question went back to the writer.
9. **One correction before the freeze, caught by a test.**
   - **The fault:** the first assembly of `cases.json` overwrote Z04's own `group` field ("TAS1-2026-07-29") with this
     check's group, so D03 was not an unchanged copy.
   - **The fix:** this check's field is now `check_group`, and the test that reused cases are unchanged passes.
   - **No effect on the questions or gold:** the checker's kit was built from the first assembly (`cases.json`
     SHA-256 `b46d7918…`), but its 12 questions and request fields are identical to the current `cases.json`'s, which
     a check confirmed, and `GOLD.json` was recomputed and agrees exactly.

10. **`build_kit.py` was edited after both kits were built:**
    - the `cases` mode (step 5) was added;
    - the field rename (step 9);
    - two type-safety edits to its row counts.

    Regenerating `windows.json` and `DATA.md` with the current code gives files byte-identical to both kits' copies.

## The writer
- **What it read:** only inside its kit. That is `BRIEF.md`, `DATA.md`, `data/events.json`, `data/windows.json` and
  `data/development_material.json`, plus `opdemand_actual` and `regionsum_5min` by duckdb, queried for timing,
  revision and interval counts only, and its own `work/` scripts.
- **What it did not read:** it did not open `MANIFEST.json`, `overlap/hashes.json` or the checker script, and did
  not query any demand value. It opened, listed and searched nothing outside the kit, and did not use the web.
- **What it disclosed:**
  - **How it removed overlap with earlier wording.** The overlap checker names only the flagged case. To find which of
    its own 6-word sequences matched, the writer temporarily wrote probe cases made of its own drafts into its output
    file, ran the checker, and restored the file. It never opened the hashes. The final check prints
    `cases with overlap: none`.
  - **Development material.**
    - F01 and F02 had to be QLD1 and SA1, since NSW1 and TAS1 are excluded and VIC1's 29 July is development
      material.
    - SA1's day and NSW1's day (F03) each contain one development half-hour. No other region was free of overlap.
  - **F04 does not mention daylight saving,** so handling the 25-hour day is tested rather than given away.

## The gold checker
- **What it read:** only inside its kit. That is `GOLD_CHECK_BRIEF.md`, `DATA.md`, `questions.json`,
  `data/events.json` and `data/windows.json`, plus the three tables by duckdb (prices only for the information-only
  price part of D03 and D04), and its own `work/` scripts.
- **What it did not read:** it did not open `MANIFEST.json`. It opened, listed and searched nothing outside the kit,
  and did not use the web.
- **Its findings,** all consistent with `GOLD.json`:
  - **D04:** 10 total-demand rows were published before the cutoff but became available after it. Requiring both
    timestamps holds 170 intervals; publication alone would hold 180.
  - **F07:** October 2025 holds only the next-day revision, so 8 of 48 half-hours are public by the cutoff.
  - **D03 and D04:** the price part is out of scope for the demand gold. The price figures agree with
    `GOLD.json`'s `price_reference`.
- **Context its environment added:** its session started with context the environment adds to every agent session: a
  git-status snapshot listing repository file names, and the developer's memory index (titles). It opened none of
  those files and used none of it. The writer's sessions had the same environment; its report does not mention it.

## The developer's offline checks
- **Gold:**
  - `gold.py` reproduces `GOLD.json`;
  - D01–D03 agree with the reused cases' frozen gold;
  - no window in the sample has a tie.
- **Replay dry run (no model):** all 16 cases through the new exporter.
  - **The cases that bind a maximum match gold exactly.** D03, and D04 not established with 170 of 288 held and 118
    rows excluded.
  - **Replay's rule-based router sends most fresh phrasings back.** That is a known limitation of Replay, not of the
    Live path under test; Live routing is done by the model.
- **Fake-transport dry run (no network, scratch ledger):** saved gpt-5-mini development-comparison records of K09,
  K11, K05 and K07 were replayed as D01, D02, R01 and R03 through the new exporter.
  - Format 2 with `answer` for D01 and D02, whose admitted results match gold exactly. D01's replayed draft falls back,
    and the fallback is labelled.
  - Format 1 for the controls.
  - Every export round-trips, re-verifies against the pinned store, and matches its trace.

## Data facts that bear on the results
- **Revisions in the sample:**
  - every operational-demand row gold takes is the `updated` revision;
  - October 2025 and April 2026 hold no `initial` revision.

  So no case in the sample has a cutoff that falls between a half-hour's `initial` and `updated` revisions. Gold's
  rule for that case (the latest eligible revision, never a later one) is tested offline on SYNTHETIC rows.
- **The excluded-count wording** (PROTOCOL.md, "Known before the run"): every case in the sample has one row per
  interval in its window, so the excluded rows equal the intervals with no eligible row. In D04 (total demand) that is
  118 and 118. In F07 (one revision per half-hour) it is 40 and 40. The `AS_OF_CUTOFF` sentence's count is therefore
  correct in this sample, and the wording defect is not exercised by it.

## Changes to PROTOCOL.md after its pre-registration commit (before any run; no rule changed)
- **"What is frozen":** the file list adds `WRITER_OUTPUT.json`, `WRITER_REPORT.md` and `GOLD_CHECK_REPORT.md`, the
  agents' outputs kept for provenance.
- **"Limitations":** a factual note that the sample has no cutoff between two revisions.
- **"Known before the run":** a factual note that the excluded-count wording is not exercised by this sample.
