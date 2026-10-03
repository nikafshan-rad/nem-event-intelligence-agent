# Writer's brief: eight questions about demand maxima

You are writing eight questions, F01–F08, for a one-off check of an assistant that answers analysts' questions about
the Australian National Electricity Market (NEM). Its answers are computed from a pinned copy of public AEMO data, the
same data that is in this kit. The questions test whether it finds **the highest value of a demand measure over a
window**, and when that happened.

Work only inside this kit. Do not open, list or search anything outside it, and do not use the web. You have no
access to the assistant's code, prompts, tests or earlier questions, and you do not need them. When you finish,
report every file you read and every query you ran (see "Report").

## What is in the kit
- `DATA.md`: the columns of the three tables in `data/store/`.
- `data/store/regionsum_5min.parquet`: 5-minute dispatch data; **`totaldemand_mw`** is dispatch total demand
  (AEMO's TOTALDEMAND).
- `data/store/opdemand_actual.parquet`: half-hourly **operational demand**, `operational_demand_mw`.
  - A half-hour can have two rows: `revision` `initial` (published soon after the half-hour) and `updated` (published
    the next morning).
  - `available_at_utc` is when a row was public.
- `data/store/price_5min.parquet`: 5-minute dispatch prices (`rrp`), for describing events.
- `data/events.json`: the 8 market events the data was selected for, with each event's window.
- `data/windows.json`: which windows are **fully held** for each measure, and other data facts. This is computed from
  the store.
- `data/development_material.json`: regions, days and windows used in developing the assistant. Avoid them unless a
  stratum cannot be met otherwise; if you use one, say why.
- `venv/`: Python with only `duckdb` and `pytz` (`venv/bin/python`).
- `overlap/check_overlap.py`: checks your questions against hashed 6-word sequences of earlier questions and the
  assistant's instructions. No earlier text is in the kit.
- `out/`: for your output.

**Conventions:**
- Times in the store are UTC.
- A row's interval is identified by its **end** (`interval_end_utc`).
- A window (start, end] holds the intervals with start < interval end <= end.
- A **local day** runs from local midnight to the next local midnight in the region's time zone (see
  `data/windows.json`). It is 24 hours, except on daylight-saving change days.

## The eight questions

| ID | Measure | Window | Cutoff | Must be |
|---|---|---|---|---|
| F01 | dispatch total demand | the whole local day of 29 July 2026; a region other than NSW1 and TAS1 | none | answerable, maximum established |
| F02 | dispatch total demand | the whole local day of 29 July 2026; another region other than NSW1, TAS1 and F01's | none | answerable, maximum established |
| F03 | operational demand | the whole local day of 29 July 2026; a region other than QLD1 | none | answerable, maximum established |
| F04 | operational demand | the whole local day of 5 April 2026, in a region with daylight saving (its day is 25 hours) | none | answerable, maximum established |
| F05 | either measure (F05 and F06 must use different measures) | an **explicit window** given in the request fields `window_start_utc` and `window_end_utc` | none | answerable, maximum established |
| F06 | the other measure | the **full window of one listed event** | none | answerable, maximum established |
| F07 | operational demand | a fully held local day or a listed event's window | the request field `as_of_utc`, **inside** the window | answerable, but no maximum can be established as of the cutoff |
| F08 | — | — | — | must be sent back for clarification |

**Every answerable question (F01–F07):**
- **What it asks:** exactly one maximum, the highest level of one measure in one region over one window, and when
  it happened. It asks for nothing else.
- **The measure:** named unambiguously as an analyst would: dispatch total demand (TOTALDEMAND) or operational demand.
  Never just "demand".
- **The region and window:** both named so that there is exactly one reading. For a whole local day, give the date and
  make clear it is the whole day in local time. Do not narrow it to part of the day.
- **The data:** the window must be fully held for the measure (`data/windows.json`). F07's cutoff is the exception.
- **No answers:** it contains no answer, and no number the answer would give.

**Each stratum:**
- **F05:** the request carries `window_start_utc` and `window_end_utc`.
  - The bounds are ISO 8601 UTC, ending in `Z`, on the measure's interval boundaries: 5 minutes for total demand,
    half-hours for operational demand.
  - The window is at most 48 hours, fully held for the measure, and not exactly a whole local day or a listed event's
    window.
  - The question may describe the window in words, for example in local time. If it does, the words must match the
    fields exactly.
- **F06:** the question identifies exactly one event of `data/events.json`, as an analyst would: its region, its kind
  (high or low price), and its date or peak time. It asks about the event's whole window.
- **F07:**
  - the request carries `as_of_utc`, ISO 8601 UTC, strictly inside the window;
  - at least one half-hour of the window has a row public by the cutoff, and at least one does not;
  - the question asks for the maximum over the whole window, as F01–F06 do. It may mention the cutoff, or leave it to
    the request field.
- **F08:** a question about a demand peak in a named region that a careful assistant must ask about before answering.
  Either it names no measure (only "demand", "load" or similar), or it gives no window at all. It must be otherwise
  in scope: a NEM region, and data of the kind in the kit.

**Request fields:** use only those named above. F05 has `window_start_utc` and `window_end_utc`. F07 has `as_of_utc`.
Every other question has an empty request, `{}`.

**Wording:**
- Write each question as an analyst would ask it, in your own words, with varied phrasing across the eight.
- Each question is one or two sentences.
- Run `venv/bin/python overlap/check_overlap.py` until it prints `cases with overlap: none`.

## Output: `out/cases_maxima.json`

```json
{"cases": [
  {"case_id": "F01", "stratum": "F01",
   "question": "...",
   "request": {},
   "intended": {"measure": "total demand", "region": "QLD1", "window_kind": "day",
                "window_utc": ["2026-07-28T14:00:00Z", "2026-07-29T14:00:00Z"],
                "window_local": ["2026-07-29T00:00:00+10:00", "2026-07-30T00:00:00+10:00"],
                "event_id": null, "as_of_utc": null, "expected_outcome": "established"},
   "notes": "why this region and window; development material used, if any, and why"}
]}
```

**The `intended` fields:**
- `measure`: `"total demand"` or `"operational demand"`; null for F08 if it names none.
- `region`: one of NSW1, QLD1, SA1, TAS1, VIC1.
- `window_kind`: `"day"`, `"explicit"` or `"event"`; null for F08 if it gives no window.
- `window_utc`: the (start, end] bounds.
- `window_local`: the same bounds in local time, with their offsets.
- `event_id`: for F06, and for F07 if it uses an event window.
- `as_of_utc`: F07's cutoff.
- `expected_outcome`: `"established"` (F01–F06), `"not_established"` (F07) or `"clarification"` (F08).

Record no answer values.

## Report
When done, write `out/WRITER_REPORT.md` with:
- every file you read;
- the queries you ran, summarised;
- confirmation that you opened, listed and searched nothing outside the kit, and used no web access;
- the overlap check's final output;
- any judgement calls.
