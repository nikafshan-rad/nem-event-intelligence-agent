# Provenance of the targeted Live check's cases (preparation record; no paid call)

## Order of work

1. **The pass rule and the development cases** (`PASS_RULE.md`, `DEVCHECK.json`) were committed and pushed as `bd5a47c`
   (2026-10-02T14:21:25Z), **before any question was written**.
2. **The kit was built outside the repository** (`build_kit.py`). It holds:
   - the briefs and the data dictionary;
   - copies of the pinned store and corpus, the 8 events, and the development-material list;
   - a Python environment with only `duckdb==1.5.5` and `pytz==2026.3.post1`;
   - SHA-256 hashes of every 6-word sequence in the 138 earlier evaluation questions and prompts v11.

   Kit `MANIFEST.json` SHA-256: `29c7555d63cdb3baa81595b4afad01dfef5089cb7e01f7482a335b37e220fd2a`.
3. **The writer** (a fresh agent, no conversation history, kit only) wrote K01–K15 to the brief (`BRIEF.md`).
4. **The verifier** (a second fresh agent, kit only, barred from the writer's working files) checked every case with its
   own queries (`VERIFY.md`). The result was **PASS, 15 of 15, with no revision**.
5. **The cases and the verification were copied into this directory with `cp`:**
   - `cases.json`, SHA-256 `9f0da7bf3f4fa6b79abf258604611bec61ce173e48dd209cf0b99d51a8e04ed9`, the same hash the verifier
     recorded before and after its checks;
   - `VERIFICATION.json`, SHA-256 `baad49e073bdf8b12049ab84d4acfc6e7036761246c9d96b5b7c9b5969df565a`.
6. **The developer's checks** (`labels.py`, and a check script):
   - `GOLD.json` re-reads every gold row from the pinned store. Every value, interval and table matches; the derived
     count in Z03 has no row by design.
   - **K07's runs against its cutoff:**
     - the run asked for was issued 2026-08-06T06:56:59Z, before the half-hour's 07:00Z start, and became available at
       09:48:05Z, after the 09:00Z cutoff;
     - the run that must not be substituted was issued 05:56:58Z and became available at 08:48:18Z, so it was public
       by the cutoff;
     - the actual for that half-hour was not public by then either.
   - **The maxima were recomputed over their windows**, each fully held:
     - K09: NSW1, 288 intervals;
     - K10: VIC1's event window, 294 intervals;
     - K11: QLD1, 48 half-hours. Its two revisions are equal.
   - **Every case's request builds** without error.

## The writer

- **Read only inside the kit:** `BRIEF.md`, `DATA.md`, `data/events.json`, `data/development_material.json`, the store
  files (by duckdb), `corpus.sqlite` (by sqlite3), and its own `work/` scripts and output. It did not open `VERIFY.md`,
  `MANIFEST.json` or `overlap/hashes.json`. It opened, listed and searched nothing outside the kit, and did not use the
  web.
- **Disclosed:**
  - **How it removed overlap with earlier wording.** The checker names only the flagged case. To find which 6-word
    windows matched, the writer temporarily wrote single-window probe questions into its output file and ran the
    checker, then restored the file. It never opened the hashes.

    This inferred, by probing, which short word sequences occur in earlier questions or prompts. It learned no
    question text. The final check prints `cases with overlap: none`.
  - **One oversized query output** was saved automatically by the tool layer under the agent's home directory. The
    writer did not open it, and re-ran a narrower query instead.
  - **K10 uses development material,** the VIC1 low-price event and VIC1's 29 July. This is the only way to meet its
    scenario: 29 July 2026 is the only fully held day, and the only other event overlapping it (SA1) has a window
    maximum equal to the day's. The verifier confirmed this independently.
  - **K08 and K12 have no gold,** but one of their candidate readings is development material.

## The verifier

- **Read:** `VERIFY.md`, `BRIEF.md`, `DATA.md`, `data/development_material.json`, `data/events.json` and
  `out/cases_livecheck.json`, and queried the store and corpus with its own scripts in `verify/`. It did not open
  `work/`, `overlap/` or `MANIFEST.json`, opened nothing outside the kit, and did not use the web.
- **Result:** PASS, 15 of 15. Its notes on the cases the writer flagged (K04, K07, K08, K10, K11, K12) are in
  `VERIFICATION.json`.

## Overlap with development material (`LABELS.json`)

- **D1 (Z03, Z05, Z04):** development cases by definition.
- **D2:** only K10 overlaps, with the VIC1 event window 2026-07-27T23:00Z to 2026-07-28T23:30Z and VIC1's local
  29 July. It is reported in its own table.
- **Every other D2 case:** none.
- **All cases are on familiar, pinned data.** None is unseen-event evidence.

## Deviation from the v6 process

In v6 the developer stayed blind to questions and gold until after the runs. Here, at the owner's request, the frozen
scope, gold evidence and overlap labels are published for review before any run. The code under test is frozen, so
seeing them cannot change it. The developer did not write, edit or choose any case.
