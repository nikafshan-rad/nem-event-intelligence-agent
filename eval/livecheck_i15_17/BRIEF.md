# Brief: write 15 evaluation cases for a targeted check

You are writing new evaluation cases for a research assistant. Its answers will be checked by people against your gold
evidence. Work **only inside this kit directory**. The rules for doing so are at the end.

## What the assistant does

It answers one question at a time about Australia's National Electricity Market (NEM). It uses public AEMO data for
five regions (NSW1, QLD1, SA1, TAS1, VIC1) over late July – August 2026, plus public AEMO documents. It is read-only:
it never trades, bids or controls anything. Every question is handled as one of three intents.

| Intent | What the question asks | Tools the assistant is designed to call |
| --- | --- | --- |
| `market_event_review` | what happened around a high- or low-price interval in one region on one date, including prices and demand at given times | `find_market_events`, `get_price_timeline`, `get_actual_demand`, `retrieve_public_evidence` |
| `forecast_review` | what AEMO's issued operational-demand forecasts (POE10/50/90) said, and how they compared with actual operational demand | `get_forecast_runs`, `get_actual_demand`, `compare_forecast_actual`, `retrieve_public_evidence` |
| `source_explanation` | what a term, field, procedure, AEMO document or AEMO market notice says | `retrieve_public_evidence` |

When a question is ambiguous, the assistant should ask for clarification rather than guess. When something asked for
cannot be supplied from the data, it should say so rather than give something else in its place.

Its data is in `data/` and described in `DATA.md`:
- 5-minute dispatch prices (`price_5min`);
- 5-minute region summaries (`regionsum_5min`, including dispatch total demand, `totaldemand_mw`);
- half-hourly actual operational demand (`opdemand_actual`, with revisions);
- half-hourly issued forecast runs (`opdemand_forecast`, POE10/50/90);
- unit SCADA;
- document passages (`corpus.sqlite`).

`data/events.json` lists the 8 verified price events, each with a region, a UTC window and a project analysis
threshold.

**Conventions you need:**
- **Interval times:** every interval is identified by its end time. A 5-minute interval ending T covers (T − 5 min,
  T], and a half-hour ending T covers (T − 30 min, T].
- **Local time:** NSW1, QLD1, VIC1 and TAS1 are on AEST (UTC+10) in this period, and SA1 is on ACST (UTC+9:30). NEM
  "market time" is UTC+10 for every region.
- **Two different demand measures:**
  - **Dispatch total demand** (`regionsum_5min.totaldemand_mw`) is a 5-minute dispatch quantity.
  - **Operational demand** (`opdemand_actual.operational_demand_mw`) is half-hourly. It has revisions: use the latest
    one unless a question asks "as of" a time.
- **Forecast runs** (`opdemand_forecast`):
  - each run has a `run_id`, an `issued_at_utc`, a `published_at_utc` and an `available_at_utc`;
  - a run forecasts many half-hours (`target_end_utc`);
  - the last run issued before a half-hour is the run with the greatest `issued_at_utc` earlier than that half-hour's
    start, among runs that forecast it;
  - a row is public at a cutoff if its `available_at_utc` ≤ the cutoff.
- **Full coverage:** only some days are fully held, so check coverage before asking about a whole day. A whole local
  day of 5-minute data has 288 intervals, and of half-hours 48. In this data only 29 July 2026 (local time) is fully
  held, for every region.

## What to write: exactly 15 cases, K01–K15, in this order

Write each question the way an analyst would ask it, in your own words, varied from case to case. Each must be
answerable as described (or deliberately not, for the three controls). The scenarios below say **what** each question
asks for, not how to phrase it.

**Value and time (K01–K04; area `value_time`; expected outcome `supplied`):**
- **K01, K02:** each asks for values of one or more measures at **two or more different intervals** in one question:
  for example a price and a demand figure at two given times, or one measure at several times.
  - Give the times as an analyst would: mix UTC and local or market time, and refer to an interval by its end or its
    start as is natural.
  - Every requested value is a gold number.
- **K03:** a question where getting the time right matters because of the data. The value asked about is equal to the
  same measure's value at another interval nearby, or the question's local clock time coincides with a different
  interval's UTC clock time in the data. Gold is the value at the interval actually asked about.
- **K04:** a question asking, **as of** a stated UTC cutoff (ISO-8601, in the question's own words), for values at
  given intervals that were public by then. The gold rows' `available_at_utc` must be ≤ the cutoff. For operational
  demand, use the revision public by then.

**Forecast run (K05–K08; area `forecast_run`):**
- **K05, K06 (expected `supplied`):** each asks what the **last forecast run issued before** a stated half-hour
  forecast for it (POE50, or POE10/50/90), and how that compared with actual operational demand for that half-hour.
  - The question must identify the half-hour unambiguously, as an analyst would (its date, its clock time and zone),
    and need not say how the run is to be looked up.
  - **Gold:** that run's identity (`run_id`, `issued_at_utc`, `available_at_utc`) and values, and the actual (latest
    revision).
  - Use different regions or half-hours from each other.
- **K07 (expected `unavailable`):** the same kind of question as K05, about another half-hour, sent with an **as-of
  cutoff in the request**: `"request": {"as_of_utc": "<ISO-8601 UTC>"}`. Do not mention the cutoff in the question.
  - **The cutoff:** later than that run's issue time, but **earlier than its `available_at_utc`**, so the run asked for
    was not yet public.
  - **An earlier run was public:** at least one earlier run for that half-hour was public by the cutoff, so the
    assistant could wrongly substitute it.
  - **A correct answer** says that the run asked for cannot be supplied as of the cutoff, and gives no other run's
    values in its place.
  - **Gold:** the run asked for, with its times, the cutoff, and the latest run that *was* public by the cutoff (the
    one that must not be substituted).
- **K08 (expected `clarification`):** asks about the last run issued before a half-hour, but the question genuinely
  does not identify which half-hour: a careful analyst could not tell which one is meant. A correct answer asks for
  the missing detail and gives no run's values.

**Demand maximum (K09–K12; area `demand_max`):**
- **K09 (expected `supplied`):** asks when **dispatch total demand** peaked over a whole local day that is fully held,
  and at what level. Use 29 July 2026 in a region other than TAS1 and VIC1.
  - **Gold:** the maximum row; any tied rows; the next-highest value and its interval.
- **K10 (expected `supplied`):** asks when **dispatch total demand** peaked **during one of the listed events** (its
  window in `events.json`), and at what level. Choose an event whose window maximum **differs from** the maximum over
  a full local day the event's window overlaps.
  - **Gold:** the maximum row within the event window, (start, end], and that differing day's maximum, for comparison.
- **K11 (expected `supplied`):** asks when **operational demand** peaked over a whole local day that is fully held
  (29 July 2026, a region other than TAS1 and VIC1, and different from K09's), and at what level.
  - **Gold:** the maximum half-hour (latest revision), with ties and the next-highest.
- **K12 (expected `clarification`):** asks for a demand peak but genuinely leaves open either **which demand measure**
  or **over what window**, so that a careful analyst could not tell which peak is meant. A correct answer asks.

**Regression controls (K13–K15; area `control`; expected outcome `supplied`):**
- **K13:** about one listed event: its peak price, and dispatch total demand **in that peak interval** (the value at
  the price peak, not a maximum).
- **K14:** what the forecast run **issued at a stated exact time** (ISO-8601 UTC, a real `issued_at_utc`) forecast for
  one stated half-hour, against the actual.
- **K15:** a question about a definition, procedure or market notice, answerable from one passage in `corpus.sqlite`.

**Development material.** Prefer material outside `data/development_material.json`, which lists regions and intervals
used in developing the assistant. If a scenario cannot be met otherwise, you may use it; say so in that case's
`provenance.note`.

## Output

Write `out/cases_livecheck.json`:

```json
{"version": "livecheck-i15-17", "authored_by": "independent writer (agent)", "generated_at": "<UTC>",
 "cases": [ ... 15 case objects ... ]}
```

Each case object:

```json
{"case_id": "K01", "category": "value_time|forecast_run|demand_max|control", "split": "livecheck_i15_17",
 "question": "<the question>", "request": {},
 "expected": { ... see below ... },
 "provenance": {"gold_method": "<how you derived each gold item>", "queries": ["<the SQL you ran>", "..."], "note": ""}}
```

`request` is `{}` except for K07 (`{"as_of_utc": "..."}`).

The `expected` fields (include those that apply):
- `area`: `value_time`, `forecast_run`, `demand_max` or `control`.
- `expected_outcome`: `supplied`, `unavailable` or `clarification`.
- `intent`: one of the three intents. Give it for the clarification cases too: the intent the question is about.
- `answerable`: true, except K08 and K12.
- `status_in`:
  - `["answered", "answered_with_caveats"]` for `supplied` and `unavailable`;
  - `["needs_clarification"]` for `clarification`.
- `required_tools`: the tool list for the intent, from the table above.
- `gold_numbers`: a list of `{"metric", "value", "unit", "valid_at_utc", "source_row_id", "tolerance", "label"}`, one
  per value a correct answer must state. Use the data row's `row_id` as `source_row_id`.
  - **Metric names:** `dispatch_rrp`, `dispatch_totaldemand`, `opdemand_actual`, `opdemand_forecast_poe10`,
    `opdemand_forecast_poe50`, `opdemand_forecast_poe90`.
- `gold_run` (forecast cases): `{"run_id", "issued_at_utc", "published_at_utc", "available_at_utc", "target_end_utc"}`.
  For K07, also `"must_not_substitute": {"run_id", "issued_at_utc", "available_at_utc"}`.
- `as_of_utc`: the cutoff, for K04 (in the question) and K07 (in the request).
- `window_utc` (K09–K11): `[start, end]` of the window the maximum is over. Add `ties` (rows) and `next_highest`
  (row, value). For K10, also `day_max_for_comparison` (row, value, local day).
- `gold_citation` (K15): `{"doc_id": "<chunks.doc_id>", "snippet": "<at least 20 characters copied exactly from one
  passage of that document that answers the question>"}`.
- `check`: one sentence for the human reviewer: what a correct answer must do, and what it must not do.

## Wording check

Earlier evaluation questions and the assistant's instructions are not in this kit and must not be sought. So that your
questions do not repeat their wording, run `venv/bin/python overlap/check_overlap.py` before finishing (it compares
6-word sequences by SHA-256 only). Reword any flagged question, keeping its meaning and gold unchanged, until it prints
`cases with overlap: none`.

## Gold evidence rules

- Derive every gold value yourself with SQL on the files in `data/` (use `venv/bin/python` with `duckdb`, or
  `sqlite3` for the corpus), and record the SQL in `provenance`.
- Copy snippets character-for-character from `chunks.text`.
- Prefer questions whose answer is unambiguous in the data, except the two clarification cases, which must be
  genuinely ambiguous.

## Independence rules (important)

- Read and run only what is inside this kit directory (`BRIEF.md`, `DATA.md`, `data/`, `venv/`, `out/`, and
  `overlap/check_overlap.py` by running it; do not open `overlap/hashes.json`). Do not open `VERIFY.md` or
  `MANIFEST.json`. You may create a working directory `work/` for your own scripts.
- Do **not** open, list or search anything else on this machine, in particular anything under `/workspaces`, `/tmp`
  outside this kit, or your home directory. Do not use the web.
- In your final message, list every file path you read and every command you ran. Do not include the cases' questions
  or answers in that message, only the case IDs and categories, and any case you want the verifier to look at closely,
  with a short reason that does not quote the question or a gold value.
