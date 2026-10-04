# Provenance of the gold

How the comparison's gold was written, reviewed, reconciled and built, in order (PROTOCOL.md, "The gold"). Times are
UTC. Both agents were fresh agents with no access to this repository. Each worked only in a kit outside it, built by
`build_kit.py`, and reported every file it opened and every command it ran (`WRITER_REPORT.md`, `REVIEW_REPORT.md`).
The developer wrote no held-out question and no held-out gold item, and settled no disagreement.

## 1. The protocol, before any held-out question
- **Commit `3252ff5`** (2026-10-04T22:38:08Z), pushed: `PROTOCOL.md`, `CAPABILITIES.md`, `GOLD_FORMAT.md`,
  `WRITER_BRIEF.md`, `REVIEW_BRIEF.md` and `RECONCILE_BRIEF.md`. None of these files has changed since.

| File | SHA-256 |
| --- | --- |
| `PROTOCOL.md` | `49392940ed7e9424d60302380d0729114b1e20f7b5590704672db6d3474e1257` |
| `CAPABILITIES.md` | `94213aca068a279c17b4d3297cb7fe03996647a49b096c4802a34901096f27e7` |
| `GOLD_FORMAT.md` | `ab4012c8d1c5d995b9cb8abdb15ec18912b06f258e574621b2bb3cf9e179ade6` |
| `WRITER_BRIEF.md` | `5ea6f5b1281aa4b67eeae396903408d0c727085ea890b72cad1216192e8f2582` |
| `REVIEW_BRIEF.md` | `223c449fcb2d766940eb7969005db47325d120a47ed62e29b278d9ccfd912772` |
| `RECONCILE_BRIEF.md` | `f390d24a099d6595e2ed60c9e9e6471bba27f35f8a0ecf1838d6838049a13479` |

## 2. The writer
- **The kit** was built at 2026-10-04T22:40:32Z (`build_kit.py writer`). It held the brief, the capabilities, the
  format, the data facts and the overlap checker.
  - The checker holds the hashes of 48,918 six-word sequences, from 254 earlier questions, the 6 prompt files of
    prompts v16 and v17, and 5 other texts (the D31 and forecast tests and `docs/decisions.md`). No earlier text was
    in the kit.
  - `MANIFEST.json`: `e8b514627e447b81ba93b90c47997ab1daa021b150a552cc899a291f14adc025`. `overlap/hashes.json`:
    `287c9e32fc4a32c280552739583f104e94552e75103ab2313d3cfb4bb28538c4`.
- **The output:** the writer wrote 46 records, H01–H40 and C01–C06, and the overlap checker's final run printed
  `cases with overlap: none`. The first draft flagged 39 questions, which the writer reworded.
- **The kit's own files were unchanged at the end:** every file in the manifest matched its hash.
- **The file:** `out/heldout.json` (`7975d7bd39986d2901bcf655aba0fe621213277dc70a9b9fb1a37ee19a8eb954`, CRLF line
  endings) is `WRITER_OUTPUT.json` (`0fa3fc888f4594b38f48b3f79d3e6e73f3dce9c1fa8490f729f2f20b2885c5d8`), with CRLF
  converted to LF and nothing else changed.
- **The mechanical checks** (`gold.py check`) found no problem: the format, the IDs, the family quotas (31 answerable)
  and the times on the grid and their local offsets.
- **The writer's report** notes that one oversized command output was saved by its tool outside the kit and was never
  opened.

## 3. Checks added while the gold was being made
The developer added two mechanical checks to `gold.py`, each prompted by a defect found in the developer's own
development gold (section 6). The writer's records meet both, as first written, and the development gold meets both.
- **No two mentions may share their words** (each mention's anchors lie inside its own words, `GOLD_FORMAT.md`). The
  comparison of two records relies on this. Added while the writer was working.
- **Demand-forecast tools are `eligible` only for a resolved forecast request** (the converse of an existing check;
  `CAPABILITIES.md`, "Tool eligibility"). Added after the writer's output was in.

## 4. The reviewer
- **The kit** was built at 2026-10-04T23:03:41Z (`build_kit.py reviewer`).
  - It held all 69 questions with their request fields, under neutral IDs R01–R69 in an order shuffled once (seed
    `20261005`), with no gold, family or set.
  - The mapping was written to `REVIEW_IDS.json` here (`e33fdcae8beefafff33d30a1097b164d6afc960c44292ad7111809b15a1c0f91`),
    never to the kit. `MANIFEST.json`: `a4fe46334e915e418cf97ec906145238c6dc3aeae830f95fe8d99dde02ec0252`.
- **The output:** the reviewer wrote 69 records, every question and request field copied exactly. The kit's own files
  were unchanged at the end.
- **The file:** `out/review.json` is `REVIEW.json`, byte for byte
  (`d4521e8a31407cac299e27db59cdcc1bfa347de84692aaa516394bc175b49382`).
- **Two format notes, recorded, not sent back:** R04 (H10) and R33 (H09) accept `resolved` without giving intents,
  and give the tools as `not_used` (the reviewer's chosen outcome is `clarify`). The comparison flags both questions in
  any case (section 5).
- **One command outside the kit, in step 2:** the reviewer reported that a `git hash-object` it ran on its own output
  may have made git search the parent directories for a repository. None of the kit's parent directories holds one
  (checked: git reports none), so nothing outside the kit was read.

## 5. The comparison and the reconciliation
- **`gold.py compare`:** 5 of the 46 held-out questions disagreed on a gated item; none of the 23 development
  questions did.
  - **C02, H13, H24:** the same asked mention, anchored on words that do not overlap.
  - **H09, H10:** the reviewer also accepted `resolved`, where the writer accepted `clarify` and
    `event_review_without_demand_forecast` only. The reviewer's own chosen outcome was also `clarify`.
- **Step 1, to the writer** (the pre-registered text, the gated items and the reviewer's record, for each question):
  - **C02, H13, H24:** revised. Only the asked mention's anchors were extended, to the reviewer's words.
  - **H09, H10:** kept, each with one paragraph (`RECONCILED.json`).
  - **The file:** `out/reconcile_step1.json` (`43d0bd7d9604d86f1e7c79f3805d78e529f803a8b2d5d1b98b31d59a2642eb5e`),
    checked here: `mentions` is the only changed field.
- **Step 2, to the reviewer** (the pre-registered text and the writer's final record, for each question): the
  reviewer accepted all five. It judged its own extra `resolved` in H09 and H10 an added leniency, not a defect in the
  writer's record.
  - **The file:** `out/reconcile_step2.json`
    (`9420ab493f742427c2d2e71cfca415eb350faf62e65a235079e6774471dd8de8`).
- **No replacement round was needed, and no question was dropped.**
- **How the texts were passed:** the pre-registered texts went unchanged, with `{config}` given in each agent's own
  numbering, with the other numbering beside it. Each message also asked for the decisions in a named output file.
- **`RECONCILED.json`** records both steps and the five final records, which replace both readings in the build.

## 6. The development gold
- **Derived by `gold.py`** from frozen, verified sources, read only:
  - the v15 check's amended and extraction gold;
  - the maxima check's gold;
  - the saved end-to-end records.
- **Their hashes** are in `GOLD.json` (`sources_sha256`).
- **Two defects** in the developer's own derivation were found by the new checks and tests, and fixed before the
  freeze:
  - **V15-N07 listed its asked demand request twice**: the v15 gold already holds it, and the derivation added it
    again;
  - **V15-N07 kept v15's `eligible` tool label** after this protocol's capabilities made it `clarify` only (its period
    ends at "noon"). A forecast request that is not resolved is "any other question that asks for a forecast":
    `not_used`.
- **The reviewer's blind reading agreed** with the development gold on every gated item, after both fixes.

## 7. The build
`gold.py build` (with `RECONCILED.json`) wrote `GOLD.json` and `cases.json`:
- **69 configurations:**
  - 40 held-out questions;
  - 6 controls;
  - 23 development configurations.
- **31 answerable held-out questions**, the protocol's number: 93 availability slots per arm.
- **161 slots per arm**, 322 in all.

`freeze.py` then froze the code, the arms, the reservations, the order, the run cap, the denominators and the SHA-256
of every frozen file, this one included (`FREEZE.json`).
