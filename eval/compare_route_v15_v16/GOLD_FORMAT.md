# The reading of one question (JSON)

Give one record per question, in this form. Use `null` or `[]` where a field does not apply. Every time is ISO 8601
UTC ending in `Z` (for example `2026-07-30T16:30:00Z`). Compute every conversion from local time with code, and keep
the code in `work/`. Every phrase you copy from the question must be copied exactly, character for character.

```json
{
  "config": "H07",
  "question": "the question, exactly",
  "request": {},
  "region": "VIC1",
  "local_dates": ["2026-08-17"],
  "answerable": true,
  "outcome": "resolved",
  "acceptable_outcomes": ["resolved"],
  "intents": ["forecast_review"],
  "cutoff_utc": null,
  "mentions": [
    {"stance": "declined", "kind": "forecast_value", "subject": "weather", "primary": false,
     "anchors": ["the weather forecast"]},
    {"stance": "asked", "kind": "forecast_value", "subject": "operational_demand", "primary": true,
     "anchors": ["AEMO's operational demand forecast values"]}
  ],
  "reader": {
    "subject_key_words": ["operational demand"],
    "scope_kinds": ["half_hour"],
    "scope_key_words": ["18:30", "AEST", "17 August 2026"],
    "run_rule": "none",
    "run_key_words": [],
    "cutoff_key_words": [],
    "maximum": null
  },
  "resolution": {
    "operation": "forecast_value",
    "scope": {"kinds": ["half_hour"], "start_utc": "2026-08-17T08:00:00Z", "end_utc": "2026-08-17T08:30:00Z",
              "start_local": "2026-08-17T18:00:00+10:00", "end_local": "2026-08-17T18:30:00+10:00", "half_hours": 1},
    "run": {"rule": "none", "half_hour_end_utc": null, "issued_at_utc": null},
    "maximum": null,
    "not_answered": []
  },
  "demand_forecast_tools": "eligible",
  "unsupported_time": null,
  "notes": "how you read the question, and anything a careful analyst might read differently"
}
```

## Fields
- **`region`:** the NEM region the question is about (a request field `region` decides it), or `null` if none.
- **`local_dates`:** every local calendar date (YYYY-MM-DD, region time) a careful reader could give as the date the
  question is about; `[]` if it names none.
- **`answerable`:** `true` only when a correct assistant resolves exactly one supported request with every detail
  pinned down (`CAPABILITIES.md`). Otherwise `false`.
- **`outcome`** and **`acceptable_outcomes`:** from `resolved`, `clarify`, `refusal`,
  `event_review_without_demand_forecast` (`CAPABILITIES.md`, "How a question should be handled"). List every outcome
  you would accept, `outcome` first. An answerable question's only acceptable outcome is `resolved`.
- **`intents`:** for a resolved question, every investigation that could serve it: `forecast_review`,
  `market_event_review`, or both. Otherwise `[]`.
- **`cutoff_utc`:** the as-of cutoff a correct assistant applies: the request field `as_of_utc` when given, else the
  question's own cutoff when it can be pinned down; else `null`. A cutoff that belongs only to a declined or background
  mention is not applied.
- **`mentions`:** every forecast or demand-peak the question mentions, in order:
  - **`stance`:** `asked` (the question asks for it), `declined` (the question says it does not want it), or
    `background` (mentioned as context, quoted or not, and not asked for);
  - **`kind`:** `forecast_value`, `single_interval_comparison`, `window_comparison`, `demand_maximum`, or `unclear`;
  - **`subject`:** what it is a forecast or peak of: `operational_demand`, `dispatch_total_demand`,
    `demand_unspecified`, `weather`, `price`, `other`, or `unclear` (not shown);
  - **`primary`:** `true` for the one asked supported request of an answerable question; else `false`;
  - **`anchors`:** one to three short phrases copied exactly from the question, each inside this mention's own words,
    which any reasonable reading of "where this mention is" would include.
- **`reader`:** what a careful reader extracts for the primary request (else `null`), judged against the question's
  meaning, not against any program. The reader sees the question only, never a request field.
  - **`subject_key_words`:** tokens a reader's words for the subject must contain (for example `operational demand`,
    `POE50`, `TOTALDEMAND`);
  - **`scope_kinds`**, **`scope_key_words`:** the kinds of half-hour or period a reader could correctly name, and the
    tokens (times, dates, zones, event names) a reader's words for it must contain. Fill these in even where you know
    of no program that could convert the words;
  - **`run_rule`**, **`run_key_words`:** `none`, `last_issued_before`, `issued_at` or `as_of_availability`, and the
    tokens that fix which run;
  - **`cutoff_key_words`:** the tokens pinning the question's own as-of cutoff; `[]` if it states none;
  - **`maximum`:** for a demand maximum, `{"measure": "operational_demand" | "dispatch_total_demand", "window":
    "whole_local_day" | "event" | "explicit", "measure_key_words": [...], "window_key_words": [...]}`; else `null`.
- **`resolution`:** when `resolved` is acceptable, exactly what a correct assistant binds (else `null`):
  - **`operation`:** `forecast_value`, `single_interval_comparison` or `window_comparison` for a forecast request;
    `null` for a maximum;
  - **`scope`:** for a forecast request: `kinds` (one or more of `half_hour`, `event_peak_half_hour`,
    `whole_local_day`, `event`, `explicit`, listing more than one only if they are exactly the same half-hours),
    `start_utc`, `end_utc`, `start_local`, `end_local` (with offset), `half_hours`; `null` for a maximum;
  - **`run`:** `rule` as above; `half_hour_end_utc` for `last_issued_before` and `issued_at` (the end of the target
    half-hour); `issued_at_utc` for `issued_at`;
  - **`maximum`:** for a maximum, `{"measure": ..., "window_kind": "whole_local_day" | "event" | "explicit",
    "start_utc": ..., "end_utc": ...}`; else `null`. A request window field is the window (`explicit`);
  - **`not_answered`:** the kinds (`weather`, `price`, `other`) of other forecasts the question also asks for, which
    a correct answer names as not answered; else `[]`.
- **`demand_forecast_tools`:** `eligible`, `not_used` or `not_restricted` (`CAPABILITIES.md`).
- **`unsupported_time`:** for a question whose only obstacle is a time the assistant cannot pin down
  (`CAPABILITIES.md`), one of `noon`, `midday`, `part_of_day`, `over_24_hours`, `start_or_end_unknown`,
  `no_time_zone`; else `null`.
- **`notes`:** your reasoning, in a few sentences, including any reading a careful analyst might take instead.
