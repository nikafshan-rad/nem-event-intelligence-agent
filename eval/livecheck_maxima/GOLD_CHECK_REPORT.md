# Gold check report

Independent reading and computation of the 12 questions in `questions.json`, following `GOLD_CHECK_BRIEF.md`.
The result is in `out/gold_check.json`. I recorded each reading in `work/readings.py` before running any computation.

## Summary

| Case | Measure | Region | Window kind | window_utc (start, end] | as_of_utc | Outcome | Value (MW) | Interval end(s) UTC (local) | Held / in window | Excluded rows | Runner-up |
|---|---|---|---|---|---|---|---|---|---|---|---|
| D01 | total demand | NSW1 | day | 2026-07-28T14:00Z, 2026-07-29T14:00Z | - | established | 10954.2 | 2026-07-29T09:05Z (19:05 AEST) | 288/288 | 0 | 10928.72 @ 08:55Z |
| D02 | operational demand | QLD1 | day | 2026-07-28T14:00Z, 2026-07-29T14:00Z | - | established | 7548.0 | 2026-07-29T08:30Z (18:30 AEST) | 48/48 | 0 | 7547.0 @ 09:00Z |
| D03 | total demand | TAS1 | day | 2026-07-28T14:00Z, 2026-07-29T14:00Z | - | established | 1367.32 | 2026-07-28T21:55Z (07:55 AEST, 29 Jul) | 288/288 | 0 | 1362.37 @ 2026-07-29T09:00Z |
| D04 | total demand | TAS1 | day | 2026-07-28T14:00Z, 2026-07-29T14:00Z | 2026-07-29T05:00Z | not_established | 1367.32 (highest held, not a maximum) | 2026-07-28T21:55Z (07:55 AEST, 29 Jul) | 170/288 | 118 | 1362.25 @ 2026-07-28T22:00Z |
| F01 | total demand | QLD1 | day | 2026-07-28T14:00Z, 2026-07-29T14:00Z | - | established | 7568.22 | 2026-07-29T08:20Z (18:20 AEST) | 288/288 | 0 | 7555.57 @ 08:50Z |
| F02 | total demand | SA1 | day | 2026-07-28T14:30Z, 2026-07-29T14:30Z | - | established | 2162.0 | 2026-07-29T09:15Z (18:45 ACST) | 288/288 | 0 | 2158.82 @ 09:10Z |
| F03 | operational demand | NSW1 | day | 2026-07-28T14:00Z, 2026-07-29T14:00Z | - | established | 11079.0 | 2026-07-29T09:00Z (19:00 AEST) | 48/48 | 0 | 11034.0 @ 09:30Z |
| F04 | operational demand | TAS1 | day (25 h, DST ends) | 2026-04-04T13:00Z, 2026-04-05T14:00Z | - | established | 1158.0 | 2026-04-05T09:00Z (19:00 AEST) | 50/50 | 0 | 1152.0 @ 08:30Z |
| F05 | operational demand | NSW1 | explicit | 2026-04-04T03:00Z, 2026-04-04T10:00Z | - | established | 7958.0 | 2026-04-04T08:30Z (19:30 AEDT) | 14/14 | 0 | 7905.0 @ 08:00Z |
| F06 | total demand | VIC1 | event VIC1-20260820T0910-hi | 2026-08-19T11:00Z, 2026-08-20T11:30Z | - | established | 7361.73 | 2026-08-20T08:35Z (18:35 AEST) | 294/294 | 0 | 7353.08 @ 08:45Z |
| F07 | operational demand | QLD1 | day | 2025-10-04T14:00Z, 2025-10-05T14:00Z | 2025-10-05T02:00Z | not_established | 5693.0 (highest held, not a maximum) | 2025-10-04T14:30Z (00:30 AEST, 5 Oct) | 8/48 | 40 | 5578.0 @ 15:00Z |
| F08 | null (unspecified "demand") | TAS1 | event TAS1-20260731T0730-hi | 2026-07-30T09:30Z, 2026-07-31T09:30Z | - | clarification | - | - | - | - | - |

Every top value is held by exactly one interval (no exact ties at the top or at the runner-up). The `source_row_ids`
are in `out/gold_check.json`. For operational demand, every chosen row is the `updated` revision: wherever both
revisions exist, `updated` has the later `available_at_utc`. No `initial` and `updated` rows share an
`available_at_utc` anywhere in the table, so the "prefer `updated` on a tie" rule never applied.

## Ambiguous or out-of-scope questions

- **F08 (send back for clarification).** "how far did demand climb" does not say which measure: dispatch total demand
  (TOTALDEMAND) or operational demand. The window itself is clear: the only TAS1 event dated 31 Jul 2026 is
  TAS1-20260731T0730-hi. I recorded `measure: null` and `expected_outcome: "clarification"`, with `result: null`.
- **D03 and D04 (partly out of scope).** Each is a compound question. It asks for the day's highest 5-minute dispatch
  price (`rrp`) as well as the TAS1 total demand peak. Price is not a demand measure, so that part is out of scope for
  this demand-maxima check. The gold covers only the TAS1 total demand part, which names its measure and has a clear
  whole-day window. For information only, the price part:
  - D03: 126.45599 $/MWh at 2026-07-29T10:05:00Z (20:05 Hobart), 288/288 intervals.
  - D04, under the cutoff: 47.23225 $/MWh at 2026-07-28T21:30:00Z, 170/288 intervals, so not established.
- **D04, cutoff sensitivity (not an ambiguity, but a trap).** The cutoff 2026-07-29T05:00Z (15:00 Hobart) falls
  inside the day. 10 rows (interval ends 04:15Z to 05:00Z) were published before the cutoff but became available
  after it. Because both timestamps must be at or before the cutoff, they are excluded:
  - With both timestamps checked, 170 intervals are held.
  - Checking `published_at_utc` alone would hold 180.
  - The highest held value equals D03's full-day maximum, but it is not established as a maximum.
  - The runner-up differs from D03's.
- **F07, partial hold.** The kit has no `initial` revision for October 2025, only `updated` rows from two AEMO daily
  files:
  - Half-hours ending 14:30Z to 18:00Z on 4 Oct are available from 2025-10-04T21:26:01Z, before the cutoff.
  - The other 40 half-hours are available only from 2025-10-05T21:26:01Z, after the cutoff.
  - So 8 of 48 are held, and 5693.0 MW (the half-hour ending 00:30 Brisbane) is the highest held value, not the day's
    maximum.
- **No ambiguity found in the rest.**
  - Weekday names match the dates: 29 Jul 2026 is a Wednesday, 4 Apr 2026 a Saturday, 5 Apr 2026 a Sunday, and
    5 Oct 2025 a Sunday.
  - F05's text (14:00 to 21:00 AEDT) agrees with its explicit request fields.
  - F07's "noon Brisbane" agrees with its `as_of_utc`.
  - F04 is the 25-hour day on which daylight saving ends; its window is DST-aware (50 half-hours).

## Files read

All paths are relative to the kit directory.
- `GOLD_CHECK_BRIEF.md`
- `DATA.md`
- `questions.json`
- `data/events.json`
- `data/windows.json`
- `data/store/regionsum_5min.parquet` and `data/store/opdemand_actual.parquet`, queried with duckdb.
- `data/store/price_5min.parquet`, queried with duckdb, only for the information-only price part of D03/D04.
- My own files in `work/` and `out/`.

Directory listings: the kit root, `data/`, `data/store/`, `out/`, `venv/`, `venv/bin/` and `work/`. The root listing
shows a file named `MANIFEST.json`. I did not open it.

## Scripts (in `work/`)

- `readings.py`: my reading of each question, written before computing. It derives local-day UTC bounds with pytz
  from the region's IANA zone, event windows from `data/events.json`, and explicit windows from the request.
- `explore.py`: data sanity checks: row counts, duplicates, nulls, revisions, and timestamp order.
- `compute.py`: the main computation, which writes `out/gold_check.json`. It also writes `work/diagnostics.json`, and
  its printed output is in `work/compute_output.txt`.
- `check_cutoffs.py`: row-level checks of the two cutoff cases, D04 and F07.
- `crosscheck_sql.py`: an independent pure-SQL reimplementation that compares every result field (0 mismatches). It
  also checks revision ties and computes the information-only price part of D03/D04.
- `local_times.py`: converts the top and runner-up interval ends to local time for this report.

All scripts were run with `venv/bin/python` (duckdb 1.5.5, pytz 2026.3.post1).

## Confirmation

I opened, listed and searched nothing outside the kit directory, and I used no web access.

Running `venv/bin/python` loads the interpreter and the packages it was built with. I did not open or list any of
those files myself.

My session began with some context injected automatically by the environment, which I did not ask for: a git-status
snapshot that lists repository file names, and a memory index. I opened none of the files it names, and nothing in it
was used in this check.
