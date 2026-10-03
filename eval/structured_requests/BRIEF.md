# Brief: write a paraphrase matrix of 60 request-resolution cases

You are writing development test material for a research assistant about Australia's National Electricity Market
(NEM). Each case is a question (with any request fields) and the **request it expresses**: what must be resolved
before an answer can be correct. Work **only inside this kit directory**. The rules are at the end.

This material tests whether the assistant recognises two kinds of request however they are worded. Write questions
the way different analysts would ask them, varied in vocabulary and structure. Do not try to guess how any software
reads them.

## Conventions

- **Regions:** NSW1, QLD1, SA1, TAS1 and VIC1.
- **Local time in this period:** NSW1, QLD1, VIC1 and TAS1 are on AEST (UTC+10). SA1 is on ACST (UTC+9:30). NEM
  "market time" is UTC+10 everywhere.
- **Intervals:** every interval is identified by its **end** time. A half-hour ending T covers (T − 30 min, T], and a
  5-minute interval ending T covers (T − 5 min, T]. "The 17:30–18:00 half-hour" ends at 18:00. "The half-hour
  starting at 17:30" also ends at 18:00.
- **Data period:** late July to August 2026. `data/events.json` lists the 8 price events, each with its region and UTC
  window.
- **Two demand measures:**
  - **dispatch total demand** (TOTALDEMAND), 5-minute;
  - **operational demand**, half-hourly.

  They differ: a peak of one is not a peak of the other.
- **Forecast runs:** AEMO issues operational-demand forecast runs about every 30 minutes. Each run has an issue time,
  and becomes public some time after it is issued.

## The two kinds of request

**1. Forecast-run selection (`forecast_run`).** The question asks for one specific forecast run's values for a target
half-hour:
- **`last_issued_before`:** the last run *issued before* the target half-hour starts. Wording varies widely: "final",
  "last", "most recent", "latest", "ahead of", "prior to", "before that slot", "pre-interval" and so on.
- **`issued_at`:** the run issued at a stated time.
- **`as_of_availability`:** what was *public* or *known* as of a stated cutoff. This is a different selection (by
  availability, not by issue time). Record it as such; it is not `last_issued_before`.
- **Resolved** means the target half-hour is pinned down (its date with the year, its time, its time zone, and
  whether that time is the half-hour's start or end), together with the region and the selection rule.

**2. Demand maximum (`demand_max`).** The question asks when, and at what level, a **demand measure** reached its
**maximum** over a **window**:
- **The measure:** dispatch total demand, or operational demand.
- **The window, one of:**
  - **`whole_local_day`:** a whole local calendar day;
  - **`event`:** a listed event's window, from `events.json`;
  - **`explicit`:** a start and an end the question or request states.
- **Wording varies:** "peaked", "highest", "maximum", "topped out", "hit its high point", "at its greatest", "busiest
  interval", "record level" and so on.
- **Resolved** means the measure, the region and the window are all pinned down.

**Not a request (`no_request`).** Questions that mention similar words without asking for either:
- demand **at** the price peak, or in a named interval;
- the peak *price*;
- forecast accuracy in general, without one specific run;
- the event's "peak half-hour", meaning the price event's own peak.

## What to write: exactly 60 cases

- **`forecast_run`: 24.**
  - **Bound, 14:** at least 10 `last_issued_before` and at least 3 `issued_at`. Use varied wording: am/pm, 24-hour
    clocks, ranges ("5:30–6:00 pm"), start-based ("the half-hour beginning 07:30"), end-based, ISO times, city or zone
    names (Sydney time, Adelaide time, market time), and relative phrasing ("the run issued ahead of it").
  - **Clarify, 6:** each genuinely ambiguous. Examples: no date; no time zone; "the 6 pm half-hour" (start or end?); a
    period that is not one half-hour; two half-hours.
  - **`as_of_availability`, 2.**
  - **Request conflict, 2:** use a request field `as_of_utc`.
    - One case: the question asks for the last run issued before a half-hour, with a request cutoff. This is **not** a
      conflict. Expected: `bound` with `last_issued_before`, under the cutoff.
    - One case: the question's own "as of" time differs from the request's `as_of_utc`. Expected:
      `bound_with_conflict_note` (the request field is authoritative, and the conflict must be shown).
- **`demand_max`: 24.**
  - **Bound, 14:**
    - at least 4 whole-day, 4 event and 3 explicit-window cases;
    - at least 5 for each measure;
    - varied superlative wording, some with the measure named after the superlative and some before.
  - **Clarify, 7:**
    - a peak of "demand" with no measure;
    - a peak with no window or date;
    - an event-relative window on a date with no listed event in that region;
    - a window in words that is not pinned down ("in the evening");
    - a request whose two parts read two different ways.
  - **`as_of_availability`: 0.**
  - **Request conflict, 3:** a request field `window_start_utc`/`window_end_utc`.
    - Two cases agree with the question. Expected: `bound`, window `explicit`, from the request.
    - One conflicts with the question's "whole day". Expected: `bound_with_conflict_note`, using the request's window.
- **`no_request` (negative controls): 12.** Mix value-at-peak questions, peak-price questions, interval values,
  general forecast accuracy, and an event's "peak half-hour".

## Output

Write `out/matrix.json`:

```json
{"version": "structured-requests-matrix-1", "authored_by": "independent writer (agent)", "generated_at": "<UTC>",
 "cases": [ ... 60 case objects ... ]}
```

Each case:

```json
{"id": "P01", "path": "forecast_run|demand_max|no_request", "question": "<the question>",
 "request": {},
 "expected": {
   "outcome": "bound|clarify|as_of_availability|bound_with_conflict_note|no_request",
   "region": "NSW1|QLD1|SA1|TAS1|VIC1|null",
   "forecast_run": {"selection": "last_issued_before|issued_at", "target_half_hour_end_utc": "<ISO Z>",
                    "issued_at_utc": "<ISO Z or null>"},
   "maximum": {"measure": "dispatch_total_demand|operational_demand", "window_kind": "whole_local_day|event|explicit",
               "window_utc": ["<ISO Z start>", "<ISO Z end>"]},
   "as_of_utc": "<ISO Z or null>",
   "missing": ["date", "time_zone", "half_hour", "start_or_end", "measure", "window", "event", "run_rule"],
   "conflict": "<for bound_with_conflict_note: what conflicts>",
   "grounding": "<the exact words of the question (or the request field) that establish each resolved field>",
   "note": "<anything a reviewer should know>"}}
```

- **Fields to include:**
  - `forecast_run` only for a bound forecast-run case;
  - `maximum` only for a bound demand-maximum case;
  - `missing` only for `clarify`;
  - `conflict` only for `bound_with_conflict_note`.
- **IDs:** P01–P60, in the order forecast_run, demand_max, no_request.
- **`request`:** `{}` unless the case uses `as_of_utc`, or `window_start_utc` and `window_end_utc`.
- **Windows:**
  - whole local day: (local midnight, next local midnight], in UTC;
  - event: exactly the event's window from `events.json`;
  - explicit: the stated bounds, in UTC.
- **Times:** convert every time to UTC yourself, carefully.

## Wording check

Earlier evaluation questions and the assistant's instructions are not in this kit and must not be sought. Run
`venv/bin/python overlap/check_overlap.py` before finishing (it compares 6-word sequences by SHA-256 only), and
reword any flagged question, keeping its meaning, until it prints `cases with overlap: none`.

## Independence rules (important)

- Read and run only what is inside this kit directory (`BRIEF.md`, `DATA.md`, `data/`, `venv/`, `out/`, and
  `overlap/check_overlap.py` by running it; do not open `overlap/hashes.json`). Do not open `VERIFY.md` or
  `MANIFEST.json`. You may create `work/` for your own scripts.
- Do **not** open, list or search anything else on this machine, in particular anything under `/workspaces`, `/tmp`
  outside this kit, or your home directory. Do not use the web.
- In your final message, list every file you read and every command you ran, and the counts per path and outcome. Do
  not include questions or expected values in that message.
