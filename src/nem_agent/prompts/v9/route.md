Classify the analyst's question into exactly one intent and extract parameters. Output JSON only.

Intents:
- market_event_review: what happened around a high- or low-price interval in a region on a date.
- forecast_review: what AEMO's issued operational-demand forecasts said and how they compared with actual demand.
- source_explanation: what a term, definition, procedure or AEMO notice says.

Regions: NSW1, QLD1, SA1, TAS1, VIC1 (map state names, e.g. "South Australia" -> SA1). Anything outside the NEM
(e.g. Western Australia/WEM) is out of scope. Trading, bidding, asset control or predicting future prices is out of
scope. `event_date` is the calendar date in the region's local time (YYYY-MM-DD) or null. `as_of_utc` is an
ISO-8601 UTC timestamp only if the question asks what was known at a specific time; otherwise null.
How to choose the intent:
- A question about what a term, field, table, procedure or document means or says is source_explanation, even
  when it names a data table or a region (e.g. "What does AVAILABLEGENERATION mean in the region summary?").
- A question about what issued forecasts said, or what was known at a time ("as of", "known at"), is
  forecast_review, even when it also mentions an event, a price spike or weather.
- A question about what happened to prices, or why prices moved, is market_event_review.
- A question about what AEMO market notices said, or "according to the notice", is source_explanation, even when it
  mentions a price event, a forecast or reserves.
- A forecast named by its issue time ("the forecast issued at <time>") is not an as-of question: leave as_of_utc
  null unless the question asks what was known "as of" a time.

Clarification (set needs_clarification and clarification_reason; otherwise both false/null):
- several_regions or several_dates: the question names more than one region or more than one event date.
- missing_region_or_date: a market_event_review or forecast_review question has no region or no date.
  source_explanation questions never need a region or a date.
- unclear_question: the question cannot be matched to any intent.
