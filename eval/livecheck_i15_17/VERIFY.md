# Brief: independently verify 15 evaluation cases for a targeted check

Another agent has written 15 evaluation cases for a research assistant about Australia's National Electricity Market,
following `BRIEF.md` in this kit. Your job is to check every case **with your own queries**, independently of how the
writer derived it. Work **only inside this kit directory**. The rules for doing so are at the end.

## What to read

- `BRIEF.md`: what the cases must contain. Read it first: its scenarios and conventions define a correct case.
- `DATA.md` and `data/`: the data, the events (`events.json`), the development material list
  (`development_material.json`) and the document passages.
- `out/cases_livecheck.json`: the cases to check.

## What to check, for each case

1. **Gold numbers:** re-derive every gold value with your own SQL on `data/` (use `venv/bin/python` with `duckdb`, or
   `sqlite3`).
   - Confirm that `source_row_id` is the right row: region, measure, interval end, and for operational demand the
     right revision.
   - Confirm that the value matches within its tolerance, and the unit.
   - Confirm that UTC and local times stated in the question name the intervals the gold uses, under the brief's
     conventions (interval end, AEST/ACST/market time).
2. **Value and time (K01–K04):**
   - K01 and K02 each ask for values at two or more different intervals.
   - **K03:** the trap the case relies on really exists in the data (an equal value at another nearby interval, or a
     local clock time that is another interval's UTC clock time).
   - **K04:** every gold row was public by the cutoff (`available_at_utc` ≤ cutoff), with the revision public by then
     for operational demand.
3. **Forecast run (K05–K08):**
   - **K05 and K06:**
     - the half-hour is unambiguous from the question;
     - `gold_run` is the run with the greatest `issued_at_utc` earlier than that half-hour's start, among runs
       forecasting it;
     - its values are right, and the actual is the latest revision.
   - **K07:**
     - the request's `as_of_utc` is later than the gold run's issue time and earlier than its `available_at_utc`;
     - `must_not_substitute` is the latest earlier run that was public by the cutoff;
     - the question does not mention the cutoff;
     - "unavailable" is the only correct outcome.
   - **K08:** the question genuinely does not identify the half-hour. Could a careful analyst tell which one is meant?
     If so, it is REVISE.
4. **Demand maximum (K09–K12):**
   - **K09 and K11:**
     - the day is fully held (288 five-minute intervals, or 48 half-hours, in the local day);
     - the gold is the maximum over exactly that local day, with ties and the next-highest correct;
     - the measures are right: dispatch total demand for K09, operational demand at its latest revision for K11;
     - the regions are not TAS1 or VIC1, and differ from each other.
   - **K10:**
     - the event is a listed one;
     - the gold is the maximum over its window, (start, end];
     - that maximum differs from `day_max_for_comparison`, the maximum over a fully held local day the window
       overlaps (recompute it).
   - **K12:** the question genuinely leaves open which measure or which window. Could a careful analyst tell which
     peak is meant? If so, it is REVISE.
5. **Regression controls (K13–K15):**
   - **K13:** the value is total demand at the event's peak-price interval, not a maximum.
   - **K14:** the stated issue time is a real run's `issued_at_utc`, and the run forecasts that half-hour.
   - **K15:** the snippet is copied verbatim (at least 20 characters) from a passage of the cited document, and that
     passage answers the question.
6. **Expected fields:**
   - `area`, `expected_outcome`, `intent`, `answerable`, `status_in`, `required_tools`, `as_of_utc`, `window_utc` and
     `check`, against the brief;
   - IDs K01–K15 in order, split `livecheck_i15_17`;
   - `request` `{}` except K07.
7. **Expected outcome from the data, not from the assistant:**
   - **`supplied`:** every gold item is in the data and the question pins it down.
   - **`unavailable`:** the requested item exists but was not public by the cutoff.
   - **`clarification`:** the question is genuinely ambiguous.
8. **Development material:** whether any gold row falls in `development_material.json`. Note it; it is allowed when
   the writer says why.
9. **The writer's flags:** check each case the writer asked you to look at.

## Output

Write `out/VERIFICATION.json`:

```json
{"verified_by": "independent verifier (agent)", "generated_at": "<UTC>", "file_sha256": "<SHA-256 of the cases file>",
 "result": "PASS|REVISE", "cases": [{"case_id": "K01", "verdict": "PASS|REVISE", "checks": "<what you checked>",
 "recomputed": "<the values, rows and times you derived>", "development_overlap": "<none, or which>",
 "note": "<anything a reviewer should know, or why it must be revised>"}]}
```

`result` is `PASS` only if every case passes. A case that is wrong in any respect is `REVISE`, with the reason. Do not
edit the cases file yourself.

## Independence rules (important)

- Read and run only what is inside this kit directory (`BRIEF.md`, `VERIFY.md`, `DATA.md`, `data/`, `venv/`, `out/`).
  Do **not** open `work/` (the writer's working files), `overlap/` or `MANIFEST.json`. You may create a directory
  `verify/` for your own scripts.
- Do **not** open, list or search anything else on this machine, in particular anything under `/workspaces`, `/tmp`
  outside this kit, or your home directory. Do not use the web.
- In your final message, list every file path you read and every command you ran, and give each case's ID, category
  and verdict, with a short reason for any REVISE. Do not quote any question or gold value in that message.
