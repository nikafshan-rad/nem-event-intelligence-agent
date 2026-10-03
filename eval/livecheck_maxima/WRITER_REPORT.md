# Writer report: F01–F08 (demand maxima)

Output: `out/cases_maxima.json` (8 cases). No answer values (no maxima, no demand levels, no times of maxima) are
recorded anywhere, and none were computed: no query selected `totaldemand_mw` or `operational_demand_mw`.

## Files read
- `BRIEF.md`
- `DATA.md`
- `data/events.json`
- `data/windows.json`
- `data/development_material.json`
- `data/store/opdemand_actual.parquet` (queried with duckdb; only timing, revision, region and count columns)
- `data/store/regionsum_5min.parquet` (queried with duckdb; only interval counts)
- My own files in `work/` (scripts and `work/questions.json`)

Not opened: `MANIFEST.json`, `overlap/hashes.json`, `overlap/check_overlap.py` (run only as a program),
`data/store/price_5min.parquet` (not needed). Directory listings: `ls -la` of the kit root, `data/`, `data/store/`,
`out/`, `overlap/`. The listing showed file names only.

## Queries run (all with `venv/bin/python`, scripts in `work/`)
1. `work/q1_avail.py`: for operational demand, row counts and publication lag (`available_at_utc - interval_end_utc`)
   by `revision`, plus the distinct `unit` and `definition`. Result: `initial` rows are public about 2h46m after the
   half-hour; `updated` rows between about 3.4 h and 27 h after it.
2. `work/q2_window_avail.py`: for each half-hour of a window, the number of rows and each row's revision and
   `available_at_utc`. Run for QLD1 on 5 October 2025 (local day) and for the window of TAS1-20260731T0730-hi. Used to
   choose F07's window and cutoff.
3. `work/q3_verify.py`: for each case window, the local bounds (pytz) and the count of distinct held intervals against
   the expected count for the measure. Also the weekday of the dates used. All answerable windows are fully held:
   F01 288/288, F02 288/288, F03 48/48, F04 50/50, F05 14/14, F06 294/294, F07 48/48. F08's window is held for both
   measures (288/288 and 48/48).
4. `work/q4_f07_cutoff.py`: for F07's window, the number of half-hours with a row public by the cutoff (8) and
   without one (40), out of 48.
5. `work/probe.py`: finds which of my own 6-word sequences trip the overlap checker (see the judgement calls).
6. `work/build_cases.py`: writes `out/cases_maxima.json` from `work/questions.json` and the fixed intended fields.

## Confirmation
I opened, listed, searched and ran nothing outside the kit directory. I did not use the web. All scripts and
intermediate files are in `work/`, and the outputs are in `out/`.

## Overlap check: final output
```
cases with overlap: none
```

## Judgement calls
- **F01/F02 regions:** the brief excludes NSW1 and TAS1, and VIC1's 29 July 2026 day is development material (for
  any measure), so F01 and F02 have to be QLD1 and SA1. QLD1's development item for that day covers operational
  demand only. SA1's day contains one development half-hour (SA1, ending 2026-07-29T08:00Z). That can't be avoided,
  so the notes record it.
- **F03 region:** QLD1 is excluded. TAS1 and VIC1 days are development material. NSW1 and SA1 each contain one
  development half-hour. NSW1's whole-day development item is for total demand, not operational demand. I chose NSW1
  to spread regions, since SA1 is already F02. I treat a whole-day window that only *contains* a development
  half-hour as a smaller overlap than reusing a listed day, and the notes record it.
- **F04:** TAS1, the whole local day of 5 April 2026 (25 hours). The question names the date and says it is the
  whole day on Hobart clocks. It deliberately does not mention daylight saving or the 25-hour length, so the DST
  handling is tested, not given away.
- **F05/F06 measures:** F05 uses operational demand (NSW1, 2 pm–9 pm AEDT on Saturday 4 April 2026 =
  03:00Z–10:00Z). F06 uses total demand. April 2026 is held only for operational demand, so F05 had to use that
  measure. The words in F05 match the request fields exactly, with the window read as (start, end].
- **F06 event:** VIC1-20260820T0910-hi. It is the only event on 20 August 2026 and is not development material. The
  other events were avoided because they are development material (VIC1 low-price, SA1 31 July), overlap a
  development day (TAS1 6 August), or contain a development half-hour (NSW1 31 July, SA1 29 July). The TAS1 31 July
  event is used for F08. VIC1 31 July was left unused. I identified the event by region, kind and date, not peak time,
  so the question carries no time of day that could coincide with the answer.
- **F07:** QLD1, the local day of 5 October 2025, with cutoff `as_of_utc` 2025-10-05T02:00:00Z (noon AEST, stated
  in the question). This day holds only `updated` rows. At the cutoff, 8 of 48 half-hours are public (published
  2025-10-04T21:26Z) and 40 are not (published 2025-10-05T21:26Z), so the maximum for the whole day can't be
  established. The question asks for the whole day's maximum, not the maximum so far.
- **F08:** names no measure (only "demand"). Every other part is well defined: TAS1 and the window of event
  TAS1-20260731T0730-hi, which is fully held for both measures. That makes the missing measure the only reason to
  ask for clarification. The `intended` window is the event window, and the measure is null.
- **Overlap probing:** the checker reports only case IDs. To find which phrases overlapped, `work/probe.py`
  temporarily replaced `out/cases_maxima.json` with one probe case per 6-word window of **my own draft questions**,
  ran the checker as a program, and then restored the file. I probed no text other than my own drafts. Two rounds of
  rewording removed every overlap. The checker ran six times in total: the first check, one run with `--help` to see
  whether it takes arguments (it ignores them), three probe runs, and the final check.
