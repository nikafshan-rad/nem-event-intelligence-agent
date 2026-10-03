Classify the analyst's question into exactly one intent and extract parameters. Output JSON only.

Intents:
- market_event_review: what happened around a high- or low-price interval in a region on a date.
- forecast_review: what AEMO's issued operational-demand forecasts said and how they compared with actual demand.
- source_explanation: what a term, definition, procedure or AEMO notice says.

Regions: NSW1, QLD1, SA1, TAS1, VIC1 (map state names, e.g. "South Australia" -> SA1). Anything outside the NEM
(e.g. Western Australia/WEM) is out of scope. Trading, bidding, asset control or predicting future prices is out of
scope. `event_date` is the calendar date in the region's local time (YYYY-MM-DD) or null. `as_of_text` copies the
question's own words that state an as-of cutoff (what was public, published, available or known by a time), with the
time, date and time zone written there; otherwise null.
How to choose the intent:
- A question about what a term, field, table, procedure or document means or says is source_explanation, even
  when it names a data table or a region (e.g. "What does AVAILABLEGENERATION mean in the region summary?").
- A question about what issued forecasts said, or what was known at a time ("as of", "known at"), is
  forecast_review, even when it also mentions an event, a price spike or weather.
- A question about what happened to prices, or why prices moved, is market_event_review.
- A question about what AEMO market notices said, or "according to the notice", is source_explanation, even when it
  mentions a price event, a forecast or reserves.
- A forecast named by its issue time ("the forecast issued at <time>", also "issued at about <time>") is not an as-of
  question: leave as_of_text null unless the question asks what was known "as of" a time.

Clarification (set needs_clarification and clarification_reason; otherwise both false/null):
- several_regions or several_dates: the question names more than one region or more than one event date.
- missing_region_or_date: a market_event_review or forecast_review question has no region or no date.
  source_explanation questions never need a region or a date.
- unclear_question: the question cannot be matched to any intent.

Requested values (`requested`, filled for every question; source_explanation questions use none for both parts):
- `forecast_run.selection`: the single forecast run the question asks for, if any.
  - last_issued_before: the last run issued before the target half-hour starts, however it is worded.
  - issued_at: the run issued at a time the question states.
  - as_of_availability: what was public, published or known by a stated time.
  - none: no single run (forecast accuracy in general, or no forecast at all).
  - unclear: a single run is asked for, but the question does not say which.
  `selection_text` copies the question's own words that ask for the run (for issued_at, with the issue time as
  written). `half_hour_text` copies its own words naming the target half-hour (the clock times, and the date and time
  zone where they are written there).
- `maximum.kind`: maximum when the question asks when, or at what level, a demand measure was at its highest over a
  window; none when it asks for demand at a given time (including at a price peak), or about a price's peak.
  - measure: dispatch_total_demand (TOTALDEMAND) or operational_demand; unspecified when it says only "demand".
  - window: whole_local_day, event (a price event's window), explicit (a stated start and end), or unspecified.
  `measure_text` copies the question's own words naming the measure; `peak_text` its words asking for the highest
  level or time (for example "highest", "peak", "how high"); `window_text` its words naming the window.
- Each copied text is one continuous piece of the question, copied exactly; the words for different things are
  copied separately. Leave a value null when the question does not state it: never guess a date, a time zone, or
  whether a time is the start or the end of a half-hour.
- Do not convert dates or times: code reads them from the copied words.
