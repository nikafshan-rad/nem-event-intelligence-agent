# What a careful reader extracts from one question (JSON)

The assistant's first step is a reader that sees **only the question**, never any request field. It writes down what
the question asks, using the question's own words. Code then works out every time from those words.

This record says what a careful reader's extraction would contain. Each item is judged against the question's
meaning and `CAPABILITIES.md`, not against any program.

- **Words** are copied exactly from the question.
- **Key words** are the short tokens (times, dates, time zones, names) inside a reader's words that pin the item down.
  A reader's words for the item must contain every key word.
- Use `null` or `[]` where an item does not apply.

```json
{
  "config": "N07",
  "intents": ["forecast_review"],
  "region": "QLD1",
  "local_dates": ["2026-08-04"],
  "domain": "operational_demand",
  "operation": "window_comparison",
  "scope_kinds": ["explicit"],
  "scope_words": "between 06:00 and noon AEST on 4 August 2026",
  "scope_key_words": ["06:00", "noon", "AEST", "4 August 2026"],
  "run_rule": "none",
  "run_words": null,
  "run_key_words": [],
  "half_hour_words": null,
  "half_hour_key_words": [],
  "cutoff_words": null,
  "cutoff_key_words": [],
  "maximum": null,
  "request_anchors": ["AEMO's operational demand forecast for Queensland"],
  "excluded_anchors": ["the Bureau was calling for a cold, drizzly morning across Brisbane"],
  "unsupported_anchors": [],
  "notes": "why"
}
```

## Items
- **`intents`:** every investigation a careful reader could route the question to while handling it correctly:
  `forecast_review`, `market_event_review`, `source_explanation`.
- **`region`:** the NEM region the question is about, or `null`.
- **`local_dates`:** every local calendar date (YYYY-MM-DD, in the region's time zone) a careful reader could give as
  the date the question is about. Use `[]` if the question names none.
- **`domain`:** what the forecast asked about is of:
  - `operational_demand`, `weather`, `price` or `other`;
  - `unclear`: its kind is not shown;
  - `none`: no forecast is asked about.
- **For an operational demand forecast request whose details the question states:**
  - **`operation`:** `forecast_value`, `single_interval_comparison` or `window_comparison` (else `null`).
  - **`scope_kinds`:** one or more of `half_hour`, `event_peak_half_hour`, `whole_local_day`, `event`, `explicit`.
  - **`scope_words`:** the words naming the half-hour or period.
  - **`scope_key_words`:** the tokens in them that fix its bounds.

  Fill these in even where you know of no program that could convert the words. A reader can extract words that code
  later cannot use. For any other question, use `null` and `[]`.
- **The run:**
  - **`run_rule`:** `none`, `last_issued_before`, `issued_at` or `as_of_availability`.
  - **`run_words` / `run_key_words`:** the words asking for the single run, and the tokens that fix which run.
  - **`half_hour_words` / `half_hour_key_words`:** the words naming the half-hour the run is chosen for, and their
    tokens. Use `null` and `[]` when the question does not name one separately.
- **`cutoff_words` / `cutoff_key_words`:** the words of an as-of cutoff in the question (what was public by a time),
  and the tokens that pin the time. Use `null` and `[]` if the question states no cutoff. The reader never sees a
  request field.
- **`maximum`:** for a demand-maximum request:

  ```json
  {"measure": "operational_demand" | "dispatch_total_demand",
   "window": "whole_local_day" | "event" | "explicit",
   "measure_key_words": [], "window_key_words": []}
  ```

  Else `null`. A temperature's highest value is not a demand maximum.
- **`request_anchors`:** one to three short phrases copied exactly from the question, each inside the words that ask
  for the forecast or maximum actually requested. This applies to any requested forecast, including a forecast of
  another kind when that is all the question asks for.
- **`excluded_anchors`:** phrases a careful reader must not read as the request: quoted background, a declined
  request, the other request of a mixed question.
- **`unsupported_anchors`:** for each forecast of another kind that the question asks for **in addition to** an
  operational demand forecast request, a short phrase from it. Otherwise `[]`.
- **`notes`:** your reasoning, in a few sentences.
