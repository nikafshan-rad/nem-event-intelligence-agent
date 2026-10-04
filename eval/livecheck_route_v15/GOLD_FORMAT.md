# The reading of one question (JSON)

Give one record per question, in this form. Use `null` where a field does not apply. Every time is ISO 8601 UTC
ending in `Z` (for example `2026-07-30T16:30:00Z`). Compute every conversion from local time with code, and keep
the code in `work/`.

```json
{
  "config": "N04",
  "question": "the question, exactly",
  "request": {},
  "region": "TAS1",
  "outcome": "resolved",
  "acceptable_outcomes": ["resolved"],
  "intents": ["forecast_review"],
  "domain": "operational_demand",
  "operation": "forecast_value",
  "scope": {"kinds": ["whole_local_day"], "start_utc": "...", "end_utc": "...",
            "start_local": "...", "end_local": "...", "half_hours": 48},
  "run": {"rule": "none", "half_hour_end_utc": null, "issued_at_utc": null},
  "cutoff_utc": null,
  "maximum": null,
  "request_anchors": ["operational demand forecast"],
  "excluded_anchors": ["the weather forecast"],
  "unsupported_parts": [],
  "demand_forecast_tools": "eligible",
  "notes": "how you read the question, and anything a careful analyst might read differently"
}
```

## Fields
- **`region`:** the NEM region the question is about, or `null` if none is named.
- **`outcome`:** what the assistant should do. One of:
  - `resolved`;
  - `clarify_unsupported`;
  - `clarify_which_forecast`;
  - `clarify_mixed`;
  - `refusal`;
  - `event_review_unsupported`;
  - `event_review_unclear`.

  The meanings are in `CAPABILITIES.md`. A `resolved` outcome means the assistant proceeds with a fully pinned-down
  request: an operational demand forecast request, or a demand-maximum request.
- **`acceptable_outcomes`:** every outcome you would accept for this question, `outcome` first.
- **`intents`:** for a resolved outcome, the investigations that could serve it: `forecast_review`,
  `market_event_review`, or both. Otherwise `[]`.
- **`domain`:** what the forecast asked about is of:
  - `operational_demand`, `weather`, `price` or `other`;
  - `unclear`: its kind is not shown;
  - `none`: no forecast is asked about.
- **For a resolved operational demand forecast request** (otherwise `null`):
  - **`operation`:** `forecast_value`, `single_interval_comparison` or `window_comparison`.
  - **`scope`:**
    - `kinds`: one or more of `half_hour`, `event_peak_half_hour`, `whole_local_day`, `event`, `explicit`. List more
      than one only if they describe exactly the same half-hours, and you judge either label correct.
    - `start_utc` and `end_utc`: the bounds.
    - `start_local` and `end_local`: the same bounds in the region's local time, with offset.
    - `half_hours`: the number of half-hours.
  - **`run`:**
    - `rule`: `none`, `last_issued_before`, `issued_at` or `as_of_availability`;
    - for `last_issued_before` and `issued_at`: `half_hour_end_utc`, the end of the target half-hour;
    - for `issued_at`: `issued_at_utc`.
- **`cutoff_utc`:** the as-of cutoff, if the question or its request fields give one; else `null`.
- **`maximum`:** for a demand-maximum request, `{"measure": "operational_demand" | "dispatch_total_demand",
  "window_kind": "whole_local_day" | "event" | "explicit", "start_utc": ..., "end_utc": ...}`; else `null`.
- **`request_anchors`:** one to three short phrases copied exactly from the question, each lying inside the words
  that ask for the supported request (the demand forecast request, or the maximum). Any reasonable reading of
  "where the request is" would include them. Use `[]` when nothing is resolved.
- **`excluded_anchors`:** short phrases copied exactly from the question that must not be read as part of the
  supported request: quoted background, a declined request, the other request of a mixed question. Otherwise `[]`.
- **`unsupported_parts`:** each forecast of another kind that the question explicitly asks for **in addition to** a
  resolved request: `{"kind": "weather" | "price" | "other", "anchor": "a short phrase copied exactly from it"}`.
  Otherwise `[]`. A question asking only for another kind of forecast has `[]` here; its domain says so.
- **`demand_forecast_tools`:** `eligible`, `not_used` or `not_restricted` (see `CAPABILITIES.md`).
- **`notes`:** your reasoning, in a few sentences.
