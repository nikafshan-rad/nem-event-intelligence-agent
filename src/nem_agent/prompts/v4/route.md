Classify the analyst's question into exactly one intent and extract parameters. Output JSON only.

Intents:
- market_event_review: what happened around a high- or low-price interval in a region on a date.
- forecast_review: what AEMO's issued operational-demand forecasts said and how they compared with actual demand.
- source_explanation: what a term, definition, procedure or AEMO notice says.

Regions: NSW1, QLD1, SA1, TAS1, VIC1 (map state names, e.g. "South Australia" -> SA1). Anything outside the NEM
(e.g. Western Australia/WEM) is out of scope. Trading, bidding, asset control or predicting future prices is out of
scope. `event_date` is the calendar date in the region's local time (YYYY-MM-DD) or null. `as_of_utc` is an
ISO-8601 UTC timestamp only if the question asks what was known at a specific time; otherwise null.
If more than one region or date is mentioned, or a data question lacks a region or date, set needs_clarification.
