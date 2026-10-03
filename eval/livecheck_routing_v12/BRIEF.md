# Brief: write 24 fresh questions, each with the request it expresses

You are writing test material for a research assistant about Australia's National Electricity Market (NEM). Each case
is an analyst's question (with any request fields) and the **request it expresses**: what must be pinned down before
an answer can be correct. Work **only inside this kit directory**. The rules are at the end.

Write the questions the way different analysts would ask them, varied in vocabulary and structure. Do not try to guess
how any software reads them.

## Conventions

- **Regions:** NSW1, QLD1, SA1, TAS1 and VIC1.
- **Local time in this period:** NSW1, QLD1, VIC1 and TAS1 are on AEST (UTC+10). SA1 is on ACST (UTC+9:30). NEM
  "market time" is UTC+10 everywhere.
- **Intervals:** every interval is identified by its **end** time. A half-hour ending T covers (T − 30 min, T], and a
  5-minute interval ending T covers (T − 5 min, T]. "The 17:30–18:00 half-hour" ends at 18:00; so does "the half-hour
  starting at 17:30".
- **Data period:** late July to August 2026. `DATA.md` describes the tables; `data/events.json` lists the 8 price
  events, each with its region and UTC window.
- **Two demand measures,** which differ (a peak of one is not a peak of the other):
  - **dispatch total demand** (TOTALDEMAND), 5-minute, in `regionsum_5min`;
  - **operational demand**, half-hourly, in `opdemand_actual`.
- **Forecast runs:** AEMO issues operational-demand forecast runs about every 30 minutes (`opdemand_forecast`). Each
  run has an issue time, and becomes public some time after it is issued (`published_at_utc`, `available_at_utc`).

## The requests

**1. Forecast-run selection.** The question asks for one specific forecast run's values for a target half-hour:
- **`last_issued_before`:** the last run *issued before* the target half-hour starts;
- **`issued_at`:** the run issued at a stated time.

It is **pinned down** when the target half-hour's date (with the year), time, time zone, and whether that time is the
half-hour's start or end are all clear, together with the region and the selection rule.

**2. Demand maximum.** The question asks when, and at what level, a demand measure reached its maximum over a window:
- **the window, one of:** `whole_local_day` (a whole local calendar day), `event` (a listed event's window, exactly as
  in `events.json`), or `explicit` (a start and an end the question or request states);
- **pinned down** when the measure, the region and the window are all clear.

**Not a request:** demand *at* the price peak or in a named interval; the peak *price*; forecast accuracy in general;
what forecast was *public* or *known* by a cutoff (that selects by availability, not by issue time).

## What to write: exactly 24 cases, Q01–Q24 in this order

| IDs | Kind | Expected outcome | What to vary |
|---|---|---|---|
| Q01–Q08 | Forecast run, pinned down | `bound` | At least 5 `last_issued_before` and at least 2 `issued_at`. Name the half-hour in varied ways: am/pm and 24-hour ranges, the half-hour's start in some and its end in others, an ISO time, a city's local time, AEST/ACST, market time. At least one question refers back to the half-hour it has already named, instead of repeating it. At most one case may give an as-of cutoff in its request field `as_of_utc`, set after that run became public. |
| Q09–Q16 | Demand maximum, pinned down | `bound` | At least 3 `whole_local_day`, at least 2 `event` and at least 2 `explicit`. At least 3 for each measure. Vary the words for "maximum" as different analysts would, and put the measure before them in some questions and after them in others. |
| Q17–Q18 | Forecast run, genuinely ambiguous | `clarify` | Q17: a half-hour without its date, or without its time zone. Q18: a single clock time that could be the half-hour's start or its end. |
| Q19–Q20 | Demand maximum, genuinely ambiguous | `clarify` | Q19: a demand peak that does not say which measure. Q20: a window that is not pinned down (for example "in the evening"). |
| Q21–Q24 | No request | `no_request`, Q23 `as_of_availability` | Q21: demand at an event's price peak. Q22: the peak price, and demand in that same interval. Q23: what forecast was public, or known, at a stated cutoff. Q24: how accurate forecasts were over a day. |

**Use the data.**
- **Forecast runs:**
  - for every `bound` run case, check that a run exists that forecasts the target half-hour under the rule;
  - for `last_issued_before`, record the run issued last before the half-hour starts;
  - for `issued_at`, state a time that names exactly one run (you may give it to the minute, if no other run is
    within 10 minutes).
- **Maxima:** for every `bound` maximum case, check that the data holds every interval of the window for that measure,
  and record the maximum's value and interval.
- **Events:** for an `event` window, use a listed event's region and window exactly.
- **Prefer other material:** where you can, prefer half-hours, days and windows other than these (used elsewhere):
  - QLD1, 6 August 2026 around 17:00–18:00 local;
  - SA1, the morning of 20 August 2026;
  - NSW1, 6 August 2026 around 17:00 local, and 29 July 2026;
  - VIC1's low-price event (28 July 2026);
  - QLD1, 29 July 2026;
  - TAS1, 29–31 July and 6 August 2026;
  - NSW1, the half-hours ending 2026-07-28T21:30Z and 2026-07-30T21:30Z.

## Output

Write `out/cases.json`:

```json
{"version": "livecheck-routing-v12-fresh-1", "authored_by": "independent writer (agent)", "generated_at": "<UTC>",
 "cases": [ ... 24 case objects ... ]}
```

Each case:

```json
{"case_id": "Q01", "kind": "forecast_run|demand_max|forecast_run_clarify|demand_max_clarify|control",
 "question": "<the question>",
 "request": {},
 "expected": {
   "outcome": "bound|clarify|no_request|as_of_availability",
   "region": "NSW1|QLD1|SA1|TAS1|VIC1|null",
   "forecast_run": {"selection": "last_issued_before|issued_at", "target_half_hour_end_utc": "<ISO Z>",
                    "issued_at_utc": "<ISO Z or null>"},
   "maximum": {"measure": "dispatch_total_demand|operational_demand", "window_kind": "whole_local_day|event|explicit",
               "window_utc": ["<ISO Z start>", "<ISO Z end>"]},
   "as_of_utc": "<ISO Z or null>",
   "missing": ["date", "time_zone", "half_hour", "start_or_end", "measure", "window"],
   "grounding": "<the question's exact words (or the request field) that establish each field>",
   "data_check": "<what you found in the data: the run (its ID and issue time), or the maximum (value, interval) and the window's coverage>",
   "note": "<anything a reviewer should know>"}}
```

- **Fields to include:**
  - `forecast_run` only for a bound run case;
  - `maximum` only for a bound maximum case;
  - `missing` only for `clarify`;
  - `as_of_utc` always: the request's cutoff, or the question's own cutoff (Q23), else null.
- **`request`:** `{}`, except the one case that may use `as_of_utc`.
- **Times:** convert every time to UTC yourself, carefully.

## Wording check

Earlier evaluation questions and the assistant's instructions are not in this kit and must not be sought. Run
`venv/bin/python overlap/check_overlap.py` before finishing (it compares 6-word sequences by SHA-256 only), and reword
any flagged question, keeping its meaning, until it prints `cases with overlap: none`.

## Independence rules (important)

- Read and run only what is inside this kit directory (`BRIEF.md`, `DATA.md`, `data/`, `venv/`, `out/`, and
  `overlap/check_overlap.py` by running it; do not open `overlap/hashes.json` or `MANIFEST.json`). You may create
  `work/` for your own scripts.
- Do **not** open, list or search anything else on this machine, in particular anything under `/workspaces`, `/tmp`
  outside this kit, or your home directory. Do not use the web.
- In your final message, list every file you read and every command you ran, and the counts per kind, outcome,
  selection rule, window kind and measure. Do not include questions or expected values in that message.
