# Provenance of the routing-extraction check's cases and gold (preparation record; no paid call)

## Order of work

1. **The pass rule** (`PASS_RULE.md`) was committed and pushed as `8f0bfae` (2026-10-03T02:57:00Z), **before any fresh
   question was written**.
2. **The briefs, the kit builder and the development routing gold** (`BRIEF.md`, `VERIFY.md`, `build_kit.py`,
   `DEV_GOLD.json`) were committed and pushed as `5438653` (02:59:18Z), before the writer started.
   - **`DEV_GOLD.json`** is the developer's derivation of each development question's expected resolution from the
     targeted check's frozen, independently verified gold (`eval/livecheck_i15_17/GOLD.json` and `DEVCHECK.json`).
   - **The brief describes scenarios, not wording.** Two example phrasings were removed from it before the writer
     started, because they echo wording the resolution's cues were tuned on.
3. **The writer's kit was built outside the repository** (`build_kit.py writer`). It holds:
   - the brief and the data dictionary;
   - copies of the pinned store tables and the 8 events;
   - a Python environment with only `duckdb==1.5.5` and `pytz==2026.3.post1`;
   - SHA-256 hashes of every 6-word sequence in the 213 earlier evaluation questions (including the I-18 paraphrase
     matrix and the targeted check) and in prompts v11 and v12.

   It holds no development question, no code and no earlier question text. Its `MANIFEST.json` SHA-256 is
   `ef147c49b52fde9fe22bb4ae01aab4ececd2900e29b89371907a546cf436b7f9`.
4. **The writer** wrote Q01–Q24. It was a fresh agent with no conversation history, working only in the kit.
   - **Committed as written,** before verification: `78b7512` (03:08:35Z).
   - **`cases.json` SHA-256:** `ea09ac11f4494a4143feb1f7630d07dbd55f734788ae6e7927e4f686c0e54b1e`.
5. **The verifier** checked every fresh case and every development gold with its own queries, from parameters it derived
   from each question (`VERIFY.md`). It was a second fresh agent, working in its own kit (`build_kit.py verifier`), with
   no access to the writer's working files. Its kit adds the development questions and `DEV_GOLD.json`; its
   `MANIFEST.json` SHA-256 is `ee84b5a4227ba0048ad7ccd41ef187d689d6c0ddf5d63e6d62f7584184d93c1a`.
   - **Round 1** (`VERIFICATION.round1.json`): fresh 24 of 24 PASS. Development 17 of 18 PASS; **K15 REVISE**: its
     region was null although the question names South Australia.
   - **The revision:** K15's region was set to SA1 in `DEV_GOLD.json`, and its basis now says that region is scored
     only if the case proceeds as a data question (`3e62acc`). This is the developer's own derivation, so the developer
     corrected it, given only the verifier's reason. No fresh case was edited.
   - **Round 2** (`VERIFICATION.json`, SHA-256 `b754a24ca38dbfa84cb18a28454730573d562c125a5e0def112a7def3184d8de`):
     **PASS**, fresh 24 of 24 and development 18 of 18. The verifier confirmed, by rebuilding the earlier file byte
     for byte, that only K15's region and basis changed. It records `cases.json`
     `ea09ac11f4494a4143feb1f7630d07dbd55f734788ae6e7927e4f686c0e54b1e` and `DEV_GOLD.json`
     `27ecb592aeaba930c5cbe3534bd8e978a1574d0d13d51eb4f800fb2b16431a3f`.
6. **The developer's checks,** independent of both agents. They re-read the store for every bound fresh case:
   - **Last-issued-before cases** (Q01–Q06): the gold run is the last issued before the half-hour starts, and it
     forecasts the half-hour.
   - **Issued-at cases** (Q07, Q08): exactly one run is issued within 10 minutes of the stated time, and it forecasts
     the half-hour.
   - **Q05's request cutoff:** the run was available at 2026-08-19T15:18:04Z, before the cutoff of 20:00Z.
   - **Every maximum window is fully held:**

     | Case | Intervals held |
     |---|---|
     | Q09 | 48 of 48 |
     | Q10 | 288 of 288 |
     | Q11 | 48 of 48 |
     | Q12 | 294 of 294 |
     | Q13 | 49 of 49 |
     | Q14 | 120 of 120 |
     | Q15 | 14 of 14 |
     | Q16 | 144 of 144 |

     The event windows (Q12, Q13) equal `events.json`'s exactly.
   - **Every case's request builds,** and all 42 routing questions run through `run_route.route_case` offline (a
     SYNTHETIC transport, no model fields) without error.

7. **An amendment before any run** (2026-10-03, no result seen; at the owner's request).
   - **The gap:** a forecast run's issue time was compared within 60 seconds, but the scorer did not establish
     which stored run that time identifies.
   - **The change** (`PASS_RULE.md`, "Correct binding", and `score.py`, `run_identity`): a bound run is correct only
     if the stored run its fields identify, by the controller's own lookups, is the gold run itself. A different run
     fails, even within 60 seconds. The 60 seconds only absorbs a time stated to the minute.
   - **Corroboration:** every forecast-run gold identifies exactly one stored run, which is:
     - the run the writer recorded (Q01–Q08);
     - the run in the targeted check's frozen gold (K05, K06, K07, K14, Z05);
     - at the issue time the verifier recomputed (all 13).
   - **What the change could affect:** in the pinned data, no two runs of one region are issued within 10 minutes of
     each other (the closest are 1,792 seconds apart), so it changes no possible label. It makes the guarantee hold
     by construction.
   - The protocol was re-frozen.

## The writer

- **Read only inside the kit:**
  - `BRIEF.md`, `DATA.md` and `data/events.json`;
  - the store tables, through duckdb;
  - its own `work/` scripts and output.

  It did not open `MANIFEST.json` or `overlap/hashes.json`, or the checker's source. It opened, listed and searched
  nothing outside the kit, and did not use the web.
- **Disclosed:**
  - **How it removed overlap with earlier wording.** The checker names only the flagged case. To find which 6-word
    windows matched, the writer temporarily wrote probe questions into its output file and ran the checker, then
    restored the file. It never opened the hashes. This inferred which short word sequences occur in earlier
    questions or prompts; it learned no question text. The final check prints `cases with overlap: none`.
  - **All three whole-day cases use 29 July 2026,** the only local day fully held for both demand measures (in AEST and
    ACST). They use SA1 and VIC1, because the brief listed NSW1, QLD1 and TAS1 on 29 July as material used elsewhere.

## The verifier

- **Read only inside its kit:**
  - `VERIFY.md`, `BRIEF.md` and `DATA.md`;
  - `data/events.json`, `dev/questions.json`, `dev/DEV_GOLD.json` and `out/cases.json`;
  - the store tables, through its own scripts in `verify/`.

  It opened nothing outside the kit, and did not use the web.
- **Disclosed:** its first command printed `MANIFEST.json` together with `VERIFY.md`, before it had read the rule
  against opening it. The manifest holds only file hashes, and the verifier made no use of it.

## Overlap with development material

- **R-dev and E-dev:** development cases by definition (the resolution was tuned on them).
- **R-fresh:**
  - **Different questions:** the fresh cases were written without access to any earlier question, and their wording
    overlaps none (the hashed 6-word check).
  - **Familiar data:** they use the same pinned data, so they are not unseen-event evidence.
  - **Windows used before:** some fresh windows contain or equal material used before.
    - **Q12:** VIC1's 20-August high-price event window. It is K13's event, and earlier development material.
    - **Q13:** SA1's 31-July event window, listed as development material in the targeted check.
    - **Q10 and Q11:** SA1's local 29 July. It contains the half-hour ending 2026-07-29T08:00Z, listed there too.

## Deviation from the v6 process

As in the targeted check, at the owner's request, the frozen scope, cases, gold and verification are published for
review before any run. The code under test is frozen (`f2455ca`), so seeing them cannot change it. The developer did
not write, edit or choose any fresh case.
