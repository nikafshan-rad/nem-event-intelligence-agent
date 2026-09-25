# What a fresh setup does after NEMWeb's rolling folder drops files

NEMWeb serves recent files from `Reports/Current` for a limited time (about 60 days observed: 25 Jul – 23 Sep 2026)
and later bundles most of them into `Reports/Archive`. **AEMO market notices are never archived there.** The notices
selected for the July events will leave `Current` around the end of September 2026. After that, no fresh setup
can download them again.

This page describes that situation from an **executed simulation**, not a forecast. It covers what degrades, what
keeps working, and how to reproduce the check.

## Which pinned sources depend on `Reports/Current`

| Source (from `data/source_selection.json`) | Files | After roll-off |
| --- | --- | --- |
| AEMO market notices (`MARKET_NOTICE`) | 198 | **Lost to fresh setups.** Not archived by AEMO; nothing to recover. |
| August next-day actual demand (`opdem_actual_daily_20260805`, `_0806`, `_0819`, `_0820`) | 4 | Recovered automatically once AEMO publishes the August monthly archive (see below). Until then: missing; initial real-time actuals are used instead. |
| Public_Prices daily files (`PUBLIC_PRICES`) | 60 | Used only by the G0 probe's event scan; **not** needed by `make data`, `make index`, the app or the evaluation. |
| Everything else (DispatchIS, SCADA, forecasts, real-time actuals, MMSDM, AEMO PDFs, MMS Data Model pages, NASA POWER) | 45 | Unaffected (archives ~13 months; documents and API). |

## Observed behaviour (simulation, 2026-09-23)

Command: `make rolloff-sim` (i.e. `python scripts/simulate_rolloff.py --home /tmp/nem_rolloff_home --out
artifacts/rolloff_simulation.json`). It sets `NEM_AGENT_SIMULATE_ROLLED_OFF=1`, so **every** NEMWeb `Reports/Current`
URL answers a simulated 404. This is harsher than reality, where the Current files leave gradually. It copies no
Current file into the isolated home. Results are in `artifacts/rolloff_simulation.json`.

| Step | Exit | What it reported |
| --- | --- | --- |
| `build-data` | 0 | `[data] ROLLED OFF opdem_actual_daily_2026080x/081x/0820 … (SIMULATED)`; `failed_sources=0 rolled_off_sources=4`; warning pointing here. `opdemand_actual` has 2,925 rows instead of 3,410 (the 485 updated next-day rows for 5, 6, 19 and 20 Aug are absent). `data_version=62fa768cd357380c` (a different snapshot, recorded in every report). |
| `data-check` | 0 | `DATA-CHECK: PASS`; `no_failed_sources: true`; the 4 files are listed under `rolled_off_sources`. |
| `build-index` | 0 | `chunks=398 docs=9 … rolled_off=198` and a warning: all 198 market notices unavailable. `corpus_version=4b2b1371d045896f` (definitions 144, procedures 254). |
| Primary SA1 investigation | 0 | Still `answered` and validated: same headline ($4,981.00/MWh), same prices, demand and forecast errors. `published_findings` drops from 2 to **0**, and `missing_evidence` states: *"22 of 22 AEMO market notices selected for this event's window are not in the local corpus: they have rolled off NEMWeb's rolling 'Current' folder and AEMO does not archive notices, so any statement they contained is unavailable on this machine."* |
| Notice question (DOC07: "What did AEMO's market notice say about the City West transformer in SA1 on 2026-07-30?") | 0 | **`abstained`**: "The question asks what an AEMO market notice said, but no market notice matching the region and date is in the local corpus, so it cannot be quoted." (It never quotes an unrelated document instead.) |
| `eval` | 0 | All gate checks true. Held-out: status 20/21, gold numbers 13/13, forecast gold 5/5, gold citation **2/3** with **1 case counted `corpus_unavailable`** (DOC07, scored correct only because it abstained), as-of leakage 0. |
| Retrieval evaluation | – | 6 of 21 labelled items and 4 of 15 queries are `unavailable_in_corpus` and are reported separately; on the remaining items Recall@5 = 12/15, Hit@5 = 11/11. |
| `pytest` (full suite) | 0 | **133 passed, 2 skipped.** The skips are the notice-specific retrieval tests, which skip with the reason "not in corpus: NEMWeb Current notices have rolling retention". |

In short, **numbers, charts, forecasts, definitions and validation keep working. Event-specific AEMO statements
disappear.** The system says so explicitly; it neither fails silently nor fills the gap.

## Automatic recovery from NEMWeb Archive

When a pinned Current URL answers 404, `make data` and `make verify` call `nem_agent.recover`. It lists the NEMWeb
Archive folder for that dataset, looks for a member with the **same file name** inside the bundles whose start
date could cover it, and accepts the member only if its bytes hash to the **SHA-256 recorded by the probe**.

- Verified on a real file that has already left Current: `PUBLIC_ACTUAL_OPERATIONAL_DEMAND_DAILY_20260710_*.zip`
  was recovered byte-identical from `Archive/Operational_Demand/ACTUAL_DAILY/PUBLIC_ACTUAL_OPERATIONAL_DEMAND_DAILY_20260701.zip`
  (`tests/data/test_recover.py`).
- The four August next-day files will therefore come back automatically once AEMO publishes the August monthly
  archive (`…_DAILY_20260801.zip`; July's appeared by the end of August). Until then they are reported as rolled off.
- Market notices have no archive, so recovery cannot help them.

## Other places a copy may survive

- **The machine that ran setup before roll-off** keeps verified copies in `data/raw/` (git-ignored). A later fetch
  failure falls back to them and labels the source `cache_fallback`, with its original retrieval time.
- **GitHub Actions** caches `data/raw` under the hash of `data/source_selection.json` and reuses it only for that
  exact pin set; there is no prefix fallback to older caches (D20). A run for a new pin set downloads what is
  available that day and reports rolled-off notices as missing. GitHub evicts caches unused for 7 days, so this
  is a convenience, not an archive.
- **Committing the notice texts** (198 files, ≈ 0.3 MB) would make them permanent in the repository. That was not done because
  AEMO's copyright-permissions page refused scripted access, so the redistribution terms could not be checked
  ([`docs/decisions.md` D2](decisions.md)). If you confirm the terms in a browser, the files are in
  `data/raw/MARKET_NOTICE/` on a machine that fetched them in time.

## Publisher revisions (a different failure from roll-off)

A file can also stay online but **change**. When a publisher replaces content at a pinned URL, the SHA-256 check
fails, and `make data`/`make index` report the source as failed. This is intended: numbers and quotes must come from
the exact bytes that were reviewed. Observed on 2026-09-25 (CI run 36107168395 on `main`, no cache):

| Source | Change | Effect before the re-pin |
| --- | --- | --- |
| `aemo_so_op_3705` | AEMO SO_OP_3705 Version 97 → **98** (effective 23 September 2026), same URL | `build-index` exit 1 (failed source); index lost the procedure's chunks |
| `nasa_power_tas1_20260805_20260806`, `nasa_power_vic1_20260819_20260820` | NASA POWER provisional GEOS-IT → final **MERRA-2** meteorology | reported as failed; weather for those two events missing |

The fix is a reviewed re-pin (`scripts/repin_source.py`, docs/decisions.md D20). The old pin stays in the
entry's `superseded` history and in `data/SOURCES.md`. The same run also showed real roll-off: **12** market
notices had left NEMWeb Current and were reported as missing evidence without failing the build, as described above.

## How to check a real fresh setup

```bash
make setup && make data && make index      # warnings name any rolled-off sources; exit codes stay 0
make data-check                            # rolled-off sources listed separately from failures
make verify                                # G0 re-check: 404s from Current are warnings, recovered files are verified
make eval                                  # corpus_unavailable cases are counted, not passed
```
