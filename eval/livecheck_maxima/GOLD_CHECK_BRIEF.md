# Gold checker's brief: read each question, then compute its result with your own code

You are checking the expected answers of a one-off check of an assistant that answers analysts' questions about the
Australian National Electricity Market (NEM), from a pinned copy of public AEMO data (the data in this kit). Each
question asks for the highest value of a demand measure over a window, or must be sent back.

You are given only the questions and their request fields. Someone else has written down how each question should be
read, and someone else has computed the answers. You are given neither. You must read each question yourself, and
compute each result with **your own code**, from the rules below.

Work only inside this kit. Do not open, list or search anything outside it, and do not use the web.

## What is in the kit
- `questions.json`: the 12 questions, each with its `case_id`, `question` and `request` (the request fields the
  assistant receives with the question).
- `DATA.md`: the columns of the three tables in `data/store/`.
- `data/store/regionsum_5min.parquet` (5-minute; `totaldemand_mw` is dispatch total demand, TOTALDEMAND),
  `data/store/opdemand_actual.parquet` (half-hourly operational demand, `operational_demand_mw`) and
  `data/store/price_5min.parquet`.
- `data/events.json`: the 8 market events, each with its window.
- `data/windows.json`: data facts: time zones, fully held windows, daylight saving.
- `venv/`: Python with only `duckdb` and `pytz`.
- `out/`: for your output.

## Step 1: your reading of each question
For each question, record:
- `measure`: `"total demand"` (dispatch TOTALDEMAND) or `"operational demand"`, or null if it names none.
- `region`: NSW1, QLD1, SA1, TAS1 or VIC1.
- `window_kind`:
  - `"explicit"` if the request gives `window_start_utc` and `window_end_utc`;
  - `"event"` if it asks about a listed event's window;
  - `"day"` if it asks about a whole local day;
  - null if it gives no window.
- `window_utc`: the (start, end] bounds in UTC.
  - **A whole local day** runs from local midnight to the next local midnight in the region's IANA time zone
    (`data/windows.json`), so it is aware of daylight saving.
  - **An event window** is the event's `window_start_utc` and `window_end_utc`.
  - **An explicit window** is the request's fields.
- `event_id`: the event, if any.
- `as_of_utc`: the request's `as_of_utc`, or null.
- `expected_outcome`:
  - `"clarification"` if the question names no measure or gives no window;
  - otherwise `"established"` or `"not_established"`, as your computation in step 2 finds.

If a question can be read in more than one way, say so in `notes`, and give the reading you think an analyst means.

## Step 2: the result of each answerable question
The rules:
- **Rows:**
  - total demand: `regionsum_5min` rows of the region;
  - operational demand: `opdemand_actual` rows of the region.

  Use only rows whose `interval_end_utc` is in the window: start < interval end <= end.
- **Eligibility under a cutoff:** if `as_of_utc` is set, a row is eligible only if both its `published_at_utc` and
  its `available_at_utc` are at or before the cutoff. With no cutoff, every row is eligible.
- **One value per interval:**
  - total demand has one row per interval;
  - operational demand can have two rows per half-hour (`initial`, `updated`). Take, among that half-hour's
    **eligible** rows only, the one with the greatest `available_at_utc`, preferring `updated` on a tie. Never take a
    row that is not eligible.
- **Counts:**
  - `intervals_in_window`: the window's length divided by 5 minutes (total demand) or 30 minutes (operational demand);
  - `intervals_held`: intervals with an eligible value;
  - `complete`: true when `intervals_held` equals `intervals_in_window`;
  - `excluded_rows_by_as_of`: the rows in the window, of any revision, that are not eligible;
  - `intervals_without_eligible_row`.
- **Status:**
  - `"established"` if complete;
  - `"not_established"` if not complete but some interval is held;
  - `"unavailable"` if none is.
- **The value:**
  - established: the maximum;
  - not established: the highest value held, which is not a maximum.

  Then record every interval whose value equals it exactly (`interval_ends_utc`, sorted) and those rows' `row_id`s
  (`source_row_ids`, in the same order).
- **The runner-up:** the highest value strictly below it, and its interval end(s).

## Output: `out/gold_check.json`

```json
{"cases": [
  {"case_id": "F01",
   "reading": {"measure": "total demand", "region": "QLD1", "window_kind": "day",
               "window_utc": ["2026-07-28T14:00:00Z", "2026-07-29T14:00:00Z"], "event_id": null,
               "as_of_utc": null, "expected_outcome": "established"},
   "result": {"status": "established", "value": 0.0, "unit": "MW",
              "interval_ends_utc": ["..."], "source_row_ids": ["..."],
              "intervals_in_window": 288, "intervals_held": 288, "complete": true,
              "excluded_rows_by_as_of": 0, "intervals_without_eligible_row": 0,
              "runner_up": {"value": 0.0, "interval_ends_utc": ["..."]}},
   "notes": ""}
]}
```

**Format:**
- **Times:** `YYYY-MM-DDTHH:MM:SSZ`.
- **Values:** exactly as stored.
- **A question to send back:** `"result": null`.

Keep your scripts in `work/`.

## Report
When done, write `out/CHECK_REPORT.md` with:
- every file you read;
- your scripts;
- confirmation that you opened, listed and searched nothing outside the kit, and used no web access;
- every question you found ambiguous or out of scope, with why.
