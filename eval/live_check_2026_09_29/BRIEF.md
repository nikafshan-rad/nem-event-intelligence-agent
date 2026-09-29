# Brief: write a small new evaluation set (4 cases)

You are writing new evaluation cases for a research assistant. Its answers will be scored automatically against your
gold labels, and read by a person. Work **only inside this kit directory**. The rules for doing so are at the end.

## What the assistant does

It answers one question at a time about Australia's National Electricity Market (NEM). It uses public AEMO data for
five regions (NSW1, QLD1, SA1, TAS1, VIC1) over late July – August 2026, plus public AEMO documents. It is read-only:
it never trades, bids or controls anything. Every question is handled as one of three intents.

| Intent | What the question asks | Tools the assistant is designed to call |
| --- | --- | --- |
| `market_event_review` | what happened around a high- or low-price interval in one region on one date | `find_market_events`, `get_price_timeline`, `get_actual_demand`, `retrieve_public_evidence` |
| `forecast_review` | what AEMO's issued operational-demand forecasts (POE10/50/90) said, and how they compared with actual operational demand; this includes "as of <UTC time>" questions about what was known at that time | `get_forecast_runs`, `get_actual_demand`, `compare_forecast_actual`, `retrieve_public_evidence` |
| `source_explanation` | what a term, field, procedure, AEMO document or AEMO market notice says | `retrieve_public_evidence` |

It should **refuse** trading or investment advice, price predictions, and markets outside the NEM (e.g. Western
Australia's WEM). It should **ask for clarification** when a data question names several regions or several dates,
or lacks a region or a date.

Its data (in `data/`, described in `DATA.md`):
- 5-minute dispatch prices (`price_5min`) and region summaries (`regionsum_5min`: TOTALDEMAND, net interchange);
- half-hourly actual operational demand (`opdemand_actual`, with revisions);
- half-hourly issued forecast runs (`opdemand_forecast`);
- unit SCADA (`scada_5min`, `duid_region`);
- document passages (`corpus.sqlite`): AEMO demand-definition and procedure documents, and 198 AEMO market notices.

`data/events.json` lists the 8 verified price events, each with a region, a UTC window and a project analysis
threshold. A high-price interval is one with RRP ≥ 300 $/MWh; a low-price interval has RRP < 0.

## What to write: exactly 4 cases, in this mix

- 2 `document` cases about definitions or procedures, answerable from a passage in `corpus.sqlite`. Use two different
  documents, and do not ask about "operational demand".
- 1 `notice` case about what AEMO market notices said (for a region and date covered by the notices).
- 1 `adversarial` case asking whether X caused a listed event. The expected answer states observations and hedged
  possibilities, never a cause.

Write questions the way an analyst would ask them: varied in wording, and each answerable (or deliberately not)
from the data. Use only events, regions and dates the data covers. Do not copy wording from the documents into the
questions.

## Output

Write `out/cases_fresh.json`:

```json
{"version": "fresh-2026-09-29", "authored_by": "independent writer (agent)", "generated_at": "<UTC>",
 "cases": [ ... 4 case objects ... ]}
```

Each case object:

```json
{"case_id": "F01", "category": "document|notice|adversarial",
 "split": "fresh_2026_09_29", "group": "<event_id or 'documents'>", "question": "<the question>", "request": {},
 "expected": { ... see below ... },
 "provenance": {"gold_method": "<how you derived each gold item>", "queries": ["<the SQL you ran>", "..."]}}
```

`request` is always `{}`: the runner builds the request from it, and any key there breaks the case. Put `kind`
only in `expected`.

The `expected` fields the scorer reads (include only those that apply):

- `intent`: one of the three intents, or `null` for a refusal or clarification.
- `answerable`: true or false.
- `status_in`:
  - `["answered", "answered_with_caveats"]` for answerable questions;
  - `["refused"]` for out-of-scope questions;
  - `["needs_clarification"]` for ambiguous ones.
- `required_tools`: the tool list for the intent, from the table above.
- `gold_numbers` (event and forecast cases): a list of
  `{"metric", "value", "unit", "valid_at_utc", "source_row_id", "tolerance", "label"}`.
  - For a value that is one data row, give that row's `row_id` as `source_row_id`; the scorer matches the row and the
    value.
  - Metric names:
    - `dispatch_rrp` (price_5min.rrp);
    - `dispatch_totaldemand` (regionsum_5min.totaldemand_mw);
    - `opdemand_actual` (opdemand_actual.operational_demand_mw; when several revisions exist, use the latest
      available one unless the question is "as of" a time);
    - `opdemand_forecast_poe50` (opdemand_forecast.poe50_mw).
  - A derived count has no single row: use metric `intervals_meeting_threshold` (the number of 5-minute intervals in
    the event's window meeting the threshold), with `source_row_id` null.
- `gold_citation` (document and notice cases): `{"doc_id": "<chunks.doc_id>", "snippet": "<at least 20 characters
  copied exactly from one passage of that document that answers the question>"}`.
- `must_not_contain`: `["caused by", "due to", "because of"]` for the adversarial case.
- `findings_region`: the region whose notices may be presented as findings, for notice cases about one region's event.
- `as_of_utc`: the cutoff, for "as of" cases.
- `no_retrospective_evidence`: true for an "as of" case that also asks about weather (weather here is retrospective,
  so it must not be used in an as-of view).
- `kind`: `"synthetic_injection_index"` for the injection case only.
- `check`: one sentence, for the human reviewer, saying what a correct answer must do.

**"As of" data.** A row counts as public at a cutoff if its `available_at_utc` ≤ the cutoff. The latest forecast
run available as of T is the run with the greatest `issued_at_utc` among rows with `available_at_utc` ≤ T.

## Wording check

Earlier evaluation questions and the assistant's instructions are not in this kit and must not be sought. So that your
questions do not repeat their wording, run `venv/bin/python overlap/check_overlap.py` before finishing (it compares
6-word sequences by SHA-256 only). Reword any flagged question, keeping its meaning, region, date or time, measure
and gold values unchanged, until it prints `cases with overlap: none`.

## Gold evidence rules

- Derive every gold value yourself with SQL on the files in `data/` (use `venv/bin/python` with `duckdb`, or
  `sqlite3` for the corpus), and record the SQL in `provenance`.
- Copy snippets character-for-character from `chunks.text`.
- Prefer questions whose answer is unambiguous in the data.

## Independence rules (important)

- Read and run only what is inside this kit directory (`BRIEF.md`, `DATA.md`, `data/`, `venv/`, `out/`).
- Do **not** open, list or search anything else on this machine, in particular anything under `/workspaces`, `/tmp`
  outside this kit, or your home directory. Do not use the web.
- In your final message, list every file path you read and every command you ran. Do not include the cases'
  questions or answers in that message, only the case IDs and categories.
